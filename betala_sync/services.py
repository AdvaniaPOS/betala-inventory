"""
Synkroniseringstjenester for Betala.

Synkroniserer produkter, kategorier og salg fra Betala POS til lagersystemet.
"""

import logging
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional, Tuple, Dict
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User

from inventory.models import (
    Product, Category, Event, StockTransaction, StockLevel, 
    BetalaSyncLog, BetalaTransactionSync
)
from .client import BetalaClientSync, BetalaAPIError, BetalaConfig

logger = logging.getLogger(__name__)


class SyncService:
    """
    Tjeneste for synkronisering av data fra Betala.
    """
    
    def __init__(self, user: User = None, organization_id: str = None):
        self.user = user
        self.organization_id = organization_id
        self.client = None
    
    def _get_client(self) -> BetalaClientSync:
        """Hent eller opprett API-klient."""
        if self.client is None:
            from django.conf import settings
            
            # Bruk spesifisert org_id eller fall tilbake til settings
            org_id = self.organization_id or settings.BETALA_ORGANIZATION_ID
            
            config = BetalaConfig(
                base_url=settings.BETALA_API_URL,
                api_key=settings.BETALA_API_KEY,
                organization_id=org_id,
            )
            self.client = BetalaClientSync(config=config)
        return self.client
    
    def _create_sync_log(
        self,
        sync_type: str,
        status: str = BetalaSyncLog.Status.STARTED
    ) -> BetalaSyncLog:
        """Opprett ny synkroniseringslogg."""
        return BetalaSyncLog.objects.create(
            sync_type=sync_type,
            status=status,
            triggered_by=self.user
        )
    
    def _finish_sync_log(
        self,
        log: BetalaSyncLog,
        status: str,
        processed: int = 0,
        created: int = 0,
        updated: int = 0,
        failed: int = 0,
        error: str = ''
    ):
        """Avslutt synkroniseringslogg."""
        log.status = status
        log.completed_at = timezone.now()
        log.items_processed = processed
        log.items_created = created
        log.items_updated = updated
        log.items_failed = failed
        log.error_message = error
        log.save()
    
    # =========================================================================
    # KATEGORISYNC
    # =========================================================================
    
    def sync_categories(self) -> Tuple[int, int, int]:
        """
        Synkroniser kategorier fra Betala.
        
        Returns:
            Tuple med (opprettet, oppdatert, feilet)
        """
        log = self._create_sync_log(BetalaSyncLog.SyncType.CATEGORIES)
        created = updated = failed = 0
        
        try:
            with self._get_client() as client:
                categories = client.get_categories()
            
            for cat_data in categories:
                try:
                    category, was_created = Category.objects.update_or_create(
                        betala_category_id=cat_data['category_id'],
                        defaults={
                            'name': cat_data.get('name', 'Ukjent'),
                            'color': cat_data.get('color', ''),
                            'sort_order': cat_data.get('sort_order', 0),
                            'is_active': not cat_data.get('is_archived', False),
                        }
                    )
                    if was_created:
                        created += 1
                    else:
                        updated += 1
                except Exception as e:
                    logger.error(f"Feil ved synk av kategori {cat_data}: {e}")
                    failed += 1
            
            self._finish_sync_log(
                log,
                BetalaSyncLog.Status.SUCCESS,
                processed=len(categories),
                created=created,
                updated=updated,
                failed=failed
            )
            
        except BetalaAPIError as e:
            self._finish_sync_log(
                log,
                BetalaSyncLog.Status.FAILED,
                error=str(e)
            )
            raise
        
        return created, updated, failed
    
    # =========================================================================
    # PRODUKTSYNC
    # =========================================================================
    
    def sync_products(self, include_archived: bool = False) -> Tuple[int, int, int]:
        """
        Synkroniser produkter fra Betala.
        
        Returns:
            Tuple med (opprettet, oppdatert, feilet)
        """
        log = self._create_sync_log(BetalaSyncLog.SyncType.PRODUCTS)
        created = updated = failed = 0
        
        try:
            with self._get_client() as client:
                products = client.get_products(include_archived=include_archived)
            
            for prod_data in products:
                try:
                    # Unikt per org + product_id
                    org_id = prod_data.get('organization_id')
                    product_id = prod_data.get('product_id')
                    
                    product, was_created = Product.objects.update_or_create(
                        betala_organization_id=org_id,
                        betala_product_id=product_id,
                        defaults={
                            'name': prod_data.get('name', 'Ukjent'),
                            'description': prod_data.get('description', ''),
                            # Kategori er bare en tekst fra Betala, ikke eget objekt
                            'category_name': prod_data.get('category', ''),
                            'price_ore': prod_data.get('price'),
                            'vat_ore': prod_data.get('vat'),
                            'vat_factor': prod_data.get('vat_factor', 2500),
                            'is_active': not prod_data.get('is_archived', False),
                            'betala_article_group_id': prod_data.get('article_group_id', '04999'),
                            'betala_tag': prod_data.get('tag', 0),
                            'betala_open_price': prod_data.get('open_price', False),
                            'betala_is_bundles': prod_data.get('is_bundles', False),
                            'betala_bundle_product_ids': prod_data.get('bundles_product_ids', []),
                            # Pakker skal ikke telles i lager - kun innholdet
                            'track_inventory': False if prod_data.get('is_bundles', False) else True,
                            'betala_is_bar_printing': prod_data.get('is_bar_printing', False),
                            'betala_is_kitchen_printing': prod_data.get('is_kitchen_printing', False),
                            'betala_general_ledger_account': prod_data.get('general_ledger_account'),
                        }
                    )
                    if was_created:
                        created += 1
                        logger.info(f"Opprettet produkt: {product.name}")
                    else:
                        updated += 1
                        
                except Exception as e:
                    logger.error(f"Feil ved synk av produkt {prod_data}: {e}")
                    failed += 1
            
            # Koble pakke-produkter etter at alle produkter er synkronisert
            bundles = Product.objects.filter(
                betala_is_bundles=True
            ).exclude(betala_bundle_product_ids=[])
            
            for bundle in bundles:
                bundle.bundle_products.clear()
                for bundle_product_id in bundle.betala_bundle_product_ids:
                    bundled_product = Product.objects.filter(
                        betala_product_id=bundle_product_id
                    ).first()
                    if bundled_product:
                        bundle.bundle_products.add(bundled_product)
                        logger.debug(
                            f"Koblet {bundled_product.name} til pakke {bundle.name}"
                        )
                    else:
                        logger.warning(
                            f"Pakkeprodukt {bundle_product_id} ikke funnet "
                            f"for pakke {bundle.name}"
                        )
            
            self._finish_sync_log(
                log,
                BetalaSyncLog.Status.SUCCESS,
                processed=len(products),
                created=created,
                updated=updated,
                failed=failed
            )
            
        except BetalaAPIError as e:
            self._finish_sync_log(
                log,
                BetalaSyncLog.Status.FAILED,
                error=str(e)
            )
            raise
        
        return created, updated, failed
    
    # =========================================================================
    # SALGSSYNC
    # =========================================================================
    
    def sync_sales(
        self,
        event: Event,
        start_date: date = None,
        end_date: date = None
    ) -> Tuple[int, int]:
        """
        Synkroniser salg fra Betala og oppdater lagerbeholdning.
        
        Bruker /transactions-endepunktet som returnerer:
        - transaction: {sequence_number, finalized, is_void, ...}
        - products: [liste over solgte produkter - ett element per enhet]
        
        Args:
            event: Event å synkronisere for
            start_date: Fra dato (default: event start eller siste sync)
            end_date: Til dato (default: i dag)
        
        Returns:
            Tuple med (antall transaksjoner, antall produktlinjer)
        """
        if not event.betala_sales_point_group_id:
            raise ValueError("Event mangler betala_sales_point_group_id")
        
        log = self._create_sync_log(BetalaSyncLog.SyncType.SALES)
        
        # Bestem datoområde
        if start_date is None:
            # Bruk siste sync-tid eller event startdato
            if event.last_sales_sync:
                start_date = event.last_sales_sync.date()
            else:
                start_date = event.start_date
        
        if end_date is None:
            end_date = timezone.now().date()
        
        transactions_synced = 0
        lines_synced = 0
        skipped_void = 0
        
        try:
            with self._get_client() as client:
                # Hent alle transaksjoner for perioden
                transactions = client.get_transactions(
                    sales_point_group_id=int(event.betala_sales_point_group_id),
                    from_date=start_date,
                    to_date=end_date,
                    limit=50000  # Høy limit for å få alle
                )
            
            logger.info(f"Hentet {len(transactions)} transaksjoner fra Betala")
            
            with transaction.atomic():
                for tx_data in transactions:
                    tx_info = tx_data.get('transaction', {})
                    sequence_number = tx_info.get('sequence_number')
                    
                    if not sequence_number:
                        logger.warning(f"Transaksjon mangler sequence_number, hopper over")
                        continue
                    
                    # Sjekk om transaksjonen allerede er synkronisert
                    if BetalaTransactionSync.objects.filter(
                        event=event,
                        sequence_number=sequence_number
                    ).exists():
                        continue
                    
                    # Parse tidsstempel
                    finalized_str = tx_info.get('finalized', '')
                    try:
                        finalized_at = datetime.fromisoformat(
                            finalized_str.replace('Z', '+00:00')
                        )
                    except (ValueError, AttributeError):
                        finalized_at = timezone.now()
                    
                    is_void = tx_info.get('is_void', False)
                    products = tx_data.get('products', [])
                    
                    # Tell produkter (hver forekomst i listen er 1 stk)
                    product_counts: Dict[int, int] = Counter()
                    total_amount = 0
                    
                    for prod in products:
                        product_id = prod.get('product_id')
                        if product_id:
                            product_counts[product_id] += 1
                            # Beregn beløp (price + vat)
                            price = prod.get('price', 0) or 0
                            vat = prod.get('vat', 0) or 0
                            total_amount += price + vat
                    
                    # Lagre transaksjonssync-record
                    sync_record = BetalaTransactionSync.objects.create(
                        event=event,
                        sequence_number=sequence_number,
                        finalized_at=finalized_at,
                        is_void=is_void,
                        total_items=len(products),
                        total_amount_ore=total_amount
                    )
                    
                    # Ikke oppdater lager for annullerte transaksjoner
                    if is_void:
                        skipped_void += 1
                        transactions_synced += 1
                        continue
                    
                    # Oppdater lagerbeholdning for hver unike produkt
                    for product_id, quantity in product_counts.items():
                        product = Product.objects.filter(
                            betala_product_id=product_id
                        ).first()
                        
                        if not product:
                            # Prøv å matche på tidligere IDer
                            product = Product.objects.filter(
                                betala_previous_ids__contains=product_id
                            ).first()
                        
                        if not product:
                            logger.warning(
                                f"Produkt {product_id} ikke funnet, "
                                f"hopper over i trans #{sequence_number}"
                            )
                            continue
                        
                        # Hvis produktet er en pakke, trekk fra innholdet i stedet
                        if product.betala_is_bundles:
                            bundle_contents = product.get_bundle_contents()
                            if bundle_contents:
                                for bundle_product_id, bundle_qty in bundle_contents.items():
                                    bundle_product = Product.objects.filter(
                                        betala_product_id=bundle_product_id
                                    ).first()
                                    
                                    if not bundle_product:
                                        logger.warning(
                                            f"Pakkeprodukt {bundle_product_id} ikke funnet "
                                            f"for pakke {product.name}"
                                        )
                                        continue
                                    
                                    if not bundle_product.track_inventory:
                                        continue
                                    
                                    # quantity = antall pakker solgt * antall av dette produktet i pakken
                                    total_qty = quantity * bundle_qty
                                    
                                    StockTransaction.objects.create(
                                        product=bundle_product,
                                        event=event,
                                        transaction_type=StockTransaction.TransactionType.SALE,
                                        quantity=-total_qty,
                                        reference=f"Betala trans #{sequence_number} (pakke: {product.name})",
                                        betala_sequence_number=sequence_number,
                                        transaction_date=finalized_at,
                                        created_by=self.user
                                    )
                                    lines_synced += 1
                                continue  # Ikke tell pakken selv
                        
                        if not product.track_inventory:
                            continue
                        
                        # Opprett lagertransaksjon (negativ = ut av lager)
                        StockTransaction.objects.create(
                            product=product,
                            event=event,
                            transaction_type=StockTransaction.TransactionType.SALE,
                            quantity=-quantity,
                            reference=f"Betala trans #{sequence_number}",
                            betala_sequence_number=sequence_number,
                            transaction_date=finalized_at,
                            created_by=self.user
                        )
                        lines_synced += 1
                    
                    transactions_synced += 1
                
                # Oppdater siste sync-tidspunkt
                event.last_sales_sync = timezone.now()
                event.save(update_fields=['last_sales_sync', 'updated_at'])
            
            self._finish_sync_log(
                log,
                BetalaSyncLog.Status.SUCCESS,
                processed=len(transactions),
                created=lines_synced
            )
            
            logger.info(
                f"Synkronisert {transactions_synced} transaksjoner, "
                f"{lines_synced} lagerlinjer, {skipped_void} annullert"
            )
            
        except BetalaAPIError as e:
            self._finish_sync_log(
                log,
                BetalaSyncLog.Status.FAILED,
                error=str(e)
            )
            raise
        except Exception as e:
            logger.exception(f"Feil i sync_sales: {e}")
            self._finish_sync_log(
                log,
                BetalaSyncLog.Status.FAILED,
                error=str(e)
            )
            raise
        
        return transactions_synced, lines_synced
    
    # =========================================================================
    # FULL SYNC
    # =========================================================================
    
    def full_sync(self, event: Event = None) -> dict:
        """
        Kjør full synkronisering av alt fra Betala.
        
        Returns:
            Dict med synkroniseringsresultater
        """
        results = {
            'categories': {'created': 0, 'updated': 0, 'failed': 0},
            'products': {'created': 0, 'updated': 0, 'failed': 0},
            'sales': {'purchases': 0, 'lines': 0},
        }
        
        # Synk kategorier
        cat_created, cat_updated, cat_failed = self.sync_categories()
        results['categories'] = {
            'created': cat_created,
            'updated': cat_updated,
            'failed': cat_failed
        }
        
        # Synk produkter
        prod_created, prod_updated, prod_failed = self.sync_products()
        results['products'] = {
            'created': prod_created,
            'updated': prod_updated,
            'failed': prod_failed
        }
        
        # Synk salg hvis event er spesifisert
        if event and event.betala_sales_point_group_id:
            purchases, lines = self.sync_sales(event)
            results['sales'] = {
                'purchases': purchases,
                'lines': lines
            }
        
        return results
