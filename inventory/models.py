"""
Databasemodeller for Betala Inventory.

Disse modellene håndterer lagerstyring med synkronisering mot Betala POS.
"""

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal


class TimeStampedModel(models.Model):
    """Abstrakt basemodell med timestamp-felter."""
    created_at = models.DateTimeField('Opprettet', auto_now_add=True)
    updated_at = models.DateTimeField('Sist oppdatert', auto_now=True)

    class Meta:
        abstract = True


# =============================================================================
# GRUNNDATA
# =============================================================================

class Supplier(TimeStampedModel):
    """Leverandører av varer."""
    name = models.CharField('Navn', max_length=200)
    contact_person = models.CharField('Kontaktperson', max_length=200, blank=True)
    email = models.EmailField('E-post', blank=True)
    phone = models.CharField('Telefon', max_length=50, blank=True)
    address = models.TextField('Adresse', blank=True)
    notes = models.TextField('Notater', blank=True)
    is_active = models.BooleanField('Aktiv', default=True)

    class Meta:
        verbose_name = 'Leverandør'
        verbose_name_plural = 'Leverandører'
        ordering = ['name']

    def __str__(self):
        return self.name


class Event(TimeStampedModel):
    """Festival/event for å gruppere lageraktivitet."""
    name = models.CharField('Navn', max_length=200)
    start_date = models.DateField('Startdato')
    end_date = models.DateField('Sluttdato')
    location = models.CharField('Sted', max_length=300, blank=True)
    description = models.TextField('Beskrivelse', blank=True)
    is_active = models.BooleanField('Aktivt event', default=True)
    
    # Betala kobling
    betala_organization_id = models.BigIntegerField(
        'Betala Org ID', 
        null=True, 
        blank=True,
        help_text='Kobling til Betala organisasjon'
    )
    betala_sales_point_group_id = models.BigIntegerField(
        'Betala Salgspunktgruppe', 
        null=True, 
        blank=True
    )
    betala_api_key = models.CharField(
        'Betala API-nøkkel',
        max_length=500,
        blank=True,
        help_text='API-nøkkel for automatisk synkronisering (valgfritt)'
    )
    
    # Synkroniseringsstatus
    auto_sync_enabled = models.BooleanField(
        'Automatisk synkronisering',
        default=False,
        help_text='Aktiver for å synkronisere salg automatisk hvert 15. min'
    )
    last_sales_sync = models.DateTimeField(
        'Siste salgssynkronisering',
        null=True,
        blank=True,
        help_text='Når siste salgssync ble kjørt'
    )

    class Meta:
        verbose_name = 'Event'
        verbose_name_plural = 'Events'
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} ({self.start_date})"
    
    @property
    def is_ongoing(self):
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date


class Category(TimeStampedModel):
    """Produktkategorier - synkronisert fra Betala."""
    name = models.CharField('Navn', max_length=200)
    color = models.CharField('Farge', max_length=20, blank=True)
    sort_order = models.IntegerField('Sortering', default=0)
    is_active = models.BooleanField('Aktiv', default=True)
    
    # Betala kobling
    betala_category_id = models.IntegerField(
        'Betala Kategori ID',
        null=True,
        blank=True,
        unique=True,
        db_index=True
    )

    class Meta:
        verbose_name = 'Kategori'
        verbose_name_plural = 'Kategorier'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    """Produkter - synkronisert fra Betala med lagerinformasjon."""
    
    # Artikkelgrupper fra Betala (fast liste)
    ARTICLE_GROUPS = {
        '04001': 'Uttak av behandlingstjenester',
        '04002': 'Uttak av behandlingsvarer',
        '04003': 'Varesalg',
        '04004': 'Salg av behandlingstjenester',
        '04005': 'Salg av hårklipp',
        '04006': 'Mat',
        '04007': 'Øl',
        '04008': 'Vin',
        '04009': 'Brennevin',
        '04010': 'Rusbrus/Cider',
        '04011': 'Mineralvann (brus)',
        '04012': 'Annen drikke (te, kaffe etc)',
        '04013': 'Tobakk',
        '04014': 'Andre varer',
        '04015': 'Inngangspenger',
        '04016': 'Inngangspenger fri adgang (uten vederlag)',
        '04017': 'Garderobeavgift',
        '04018': 'Garderobeavgift fri garderobe (uten vederlag)',
        '04019': 'Helpensjon: Overnatting med frokost, lunsj og middag',
        '04020': 'Halvpensjon: Overnatting med frokost og middag',
        '04021': 'Overnatting med frokost',
        '04999': 'Øvrige',
    }
    
    # Grunnleggende info
    name = models.CharField('Navn', max_length=300)
    description = models.TextField('Beskrivelse', blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Kategori',
        related_name='products'
    )
    category_name = models.CharField(
        'Kategori (tekst)',
        max_length=100,
        blank=True,
        help_text='Kategorinavn fra Betala'
    )
    
    # Pris (i øre, som Betala)
    price_ore = models.IntegerField('Pris (øre)', null=True, blank=True)
    vat_ore = models.IntegerField('MVA (øre)', null=True, blank=True)
    vat_factor = models.IntegerField('MVA-sats %', default=25)
    
    # Lagerinformasjon
    sku = models.CharField('Varenummer', max_length=100, blank=True, db_index=True)
    barcode = models.CharField('Strekkode', max_length=100, blank=True, db_index=True)
    unit = models.CharField('Enhet', max_length=50, default='stk')
    min_stock_level = models.IntegerField('Min beholdning', default=0)
    
    # Enhetskonvertering - base unit for dette produktet
    class BaseUnitType(models.TextChoices):
        ML = 'ml', 'Milliliter'      # For væsker
        CL = 'cl', 'Centiliter'      # Alternativ for væsker
        STK = 'stk', 'Stykk'         # For faste varer
    
    base_unit_type = models.CharField(
        'Base-enhet',
        max_length=10,
        choices=BaseUnitType.choices,
        default=BaseUnitType.STK,
        help_text='Den minste enheten produktet lagres i (unngår avrundingsfeil)'
    )
    use_unit_conversion = models.BooleanField(
        'Bruk enhetskonvertering',
        default=False,
        help_text='Aktiver for produkter med flere enheter (f.eks. fatøl: Tank, Glass)'
    )
    
    # Leverandør
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Leverandør',
        related_name='products'
    )
    purchase_price_ore = models.IntegerField('Innkjøpspris (øre)', null=True, blank=True)
    
    # Status
    is_active = models.BooleanField('Aktiv', default=True)
    track_inventory = models.BooleanField('Følg lagerbeholdning', default=True)
    
    # Betala kobling
    betala_product_id = models.IntegerField(
        'Betala Produkt ID',
        null=True,
        blank=True,
        db_index=True
    )
    betala_previous_ids = models.JSONField(
        'Tidligere Betala IDer',
        default=list,
        blank=True,
        help_text='Liste over tidligere Betala produkt-IDer (for sporing ved ID-endringer)'
    )
    betala_article_group_id = models.CharField(
        'Betala Artikkelgruppe',
        max_length=20,
        blank=True,
        default='04999'
    )
    betala_organization_id = models.BigIntegerField(
        'Betala Org ID',
        null=True,
        blank=True,
        db_index=True
    )
    
    # Betala-spesifikke felter
    betala_tag = models.IntegerField('Tag (farge)', default=0)
    betala_open_price = models.BooleanField('Åpen pris', default=False)
    betala_is_bundles = models.BooleanField('Er pakke', default=False)
    betala_bundle_product_ids = models.JSONField(
        'Pakke-produkt IDer',
        default=list,
        blank=True,
        help_text='Liste over Betala produkt-IDer som inngår i pakken'
    )
    bundle_products = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='part_of_bundles',
        verbose_name='Produkter i pakken',
        help_text='Produkter som inngår i denne pakken'
    )
    betala_is_bar_printing = models.BooleanField('Bar-utskrift', default=False)
    betala_is_kitchen_printing = models.BooleanField('Kjøkken-utskrift', default=False)
    betala_general_ledger_account = models.IntegerField(
        'Hovedbokskonto',
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = 'Produkt'
        verbose_name_plural = 'Produkter'
        ordering = ['category__sort_order', 'name']
        # Produkter er unike per organisasjon
        constraints = [
            models.UniqueConstraint(
                fields=['betala_organization_id', 'betala_product_id'],
                name='unique_product_per_org',
                condition=models.Q(betala_product_id__isnull=False)
            )
        ]

    def __str__(self):
        return self.name
    
    @property
    def article_group_name(self):
        """Navn på artikkelgruppe basert på ID."""
        return self.ARTICLE_GROUPS.get(self.betala_article_group_id, 'Ukjent')
    
    @property
    def price_eks_mva_kr(self):
        """Pris eks. mva i kroner (price_ore fra Betala)."""
        if self.price_ore is not None:
            return Decimal(self.price_ore) / 100
        return None
    
    @property
    def vat_kr(self):
        """MVA-beløp i kroner."""
        if self.vat_ore is not None:
            return Decimal(self.vat_ore) / 100
        return None
    
    @property
    def price_kr(self):
        """Salgspris inkl. mva i kroner (price + vat)."""
        if self.price_ore is not None:
            price = self.price_ore
            vat = self.vat_ore or 0
            return Decimal(price + vat) / 100
        return None
    
    @property
    def purchase_price_kr(self):
        """Innkjøpspris i kroner."""
        if self.purchase_price_ore is not None:
            return Decimal(self.purchase_price_ore) / 100
        return None
    
    @property
    def vat_percent(self):
        """MVA-sats i prosent (Betala lagrer som 1500 for 15%)."""
        if self.vat_factor is not None:
            return Decimal(self.vat_factor) / 100
        return None
    
    @property
    def price_with_vat_ore(self):
        """Salgspris inkl. mva i øre (for Betala API)."""
        if self.price_ore is not None:
            return self.price_ore + (self.vat_ore or 0)
        return None
    
    def to_betala_payload(self):
        """
        Generer payload for oppdatering av produkt i Betala.
        
        Returns:
            dict: Payload for POST til /products/{id}/_edit
        
        Raises:
            ValueError: Hvis data er inkonsistent (open_price=False uten pris)
        """
        # Hvis åpen pris, sett price_with_vat til null
        if self.betala_open_price:
            price_with_vat = None
        else:
            # Betala krever pris når open_price er False
            if self.price_ore is None:
                raise ValueError(f'Produktet "{self.name}" har ikke pris, men "Åpen pris" er avslått. Sett en pris eller slå på "Åpen pris".')
            # Betala forventer price_with_vat (totalpris inkl. mva)
            price_with_vat = self.price_ore + (self.vat_ore or 0)
        
        return {
            'product_id': self.betala_product_id,
            'organization_id': self.betala_organization_id,
            'name': self.name,
            'description': self.description or '',
            'category': self.category_name or '',
            'article_group_id': self.betala_article_group_id or '04999',
            'vat_factor': self.vat_factor or 2500,
            'price_with_vat': price_with_vat,
            'open_price': self.betala_open_price,
            'tag': self.betala_tag or 0,
            'is_bundles': self.betala_is_bundles,
            'bundles_product_ids': self.betala_bundle_product_ids or [],
            'is_bar_printing': self.betala_is_bar_printing,
            'is_kitchen_printing': self.betala_is_kitchen_printing,
            'general_ledger_account': self.betala_general_ledger_account,
            'ticket': None,
        }
    
    def get_current_stock(self, event=None):
        """Hent nåværende lagerbeholdning."""
        qs = self.stock_levels.all()
        if event:
            qs = qs.filter(event=event)
        return qs.aggregate(total=models.Sum('quantity'))['total'] or 0
    
    # =========================================================================
    # ENHETSKONVERTERING (Unit of Measure)
    # =========================================================================
    
    def get_purchase_units(self):
        """Hent enheter som kan brukes ved innkjøp."""
        if not self.use_unit_conversion:
            return []
        return self.units.filter(is_active=True, is_purchase_unit=True)
    
    def get_sale_units(self):
        """Hent enheter som kan brukes ved salg."""
        if not self.use_unit_conversion:
            return []
        return self.units.filter(is_active=True, is_sale_unit=True)
    
    def get_count_units(self):
        """Hent enheter som kan brukes ved varetelling."""
        if not self.use_unit_conversion:
            return []
        return self.units.filter(is_active=True, is_count_unit=True)
    
    def get_all_active_units(self):
        """Hent alle aktive enheter for produktet."""
        if not self.use_unit_conversion:
            return []
        return self.units.filter(is_active=True).order_by('sort_order', '-conversion_factor')
    
    def convert_to_base_units(self, quantity: int, unit_id: int) -> int:
        """
        Konverter en mengde fra en spesifikk enhet til base-enheter.
        
        Args:
            quantity: Antall i den gitte enheten
            unit_id: ID til UnitOfMeasure
            
        Returns:
            Antall i base-enheter (heltall)
            
        Raises:
            ValueError: Hvis enheten ikke finnes eller ikke tilhører dette produktet
        """
        if not self.use_unit_conversion:
            # Ingen enhetskonvertering - returner som-er
            return quantity
        
        try:
            unit = self.units.get(id=unit_id, is_active=True)
            return unit.to_base_units(quantity)
        except Exception as e:
            raise ValueError(f"Ugyldig enhet (ID: {unit_id}) for produkt {self.name}") from e
    
    def format_stock_display(self, base_quantity: int = None, event=None) -> str:
        """
        Formater lagerbeholdning til menneskelig lesbar streng.
        
        Eksempel: 35500 ml -> "1 Tank 30L, 5 Liter, 500 ml"
        
        Args:
            base_quantity: Antall i base-enheter. Hvis None, hentes fra StockLevel.
            event: Filtrer på event (valgfritt)
            
        Returns:
            Formatert streng
        """
        if base_quantity is None:
            base_quantity = self.get_current_stock(event)
        
        if not self.use_unit_conversion:
            # Enkel visning uten konvertering
            return f"{base_quantity} {self.unit or self.base_unit_type}"
        
        # Hent enheter sortert fra størst til minst
        units = list(self.units.filter(is_active=True).order_by('-conversion_factor'))
        
        if not units:
            return f"{base_quantity} {self.base_unit_type}"
        
        parts = []
        remaining = base_quantity
        
        for unit in units:
            if unit.conversion_factor <= remaining:
                whole, remaining = unit.from_base_units(remaining)
                if whole > 0:
                    parts.append(f"{whole} {unit.short_name or unit.name}")
        
        # Legg til rest i base-enheter hvis det er noe igjen
        if remaining > 0:
            parts.append(f"{remaining} {self.base_unit_type}")
        
        if not parts:
            return f"0 {self.base_unit_type}"
        
        return ", ".join(parts)
    
    def validate_stock_for_transaction(self, quantity_base_units: int, event=None) -> tuple:
        """
        Valider at det er nok på lager for en transaksjon (uttak).
        
        Args:
            quantity_base_units: Antall base-enheter som skal tas ut (positivt tall)
            event: Event å sjekke mot
            
        Returns:
            tuple: (is_valid, current_stock, new_stock)
        """
        current = self.get_current_stock(event)
        new_stock = current - quantity_base_units
        
        return (new_stock >= 0, current, new_stock)
    
    def get_bundle_contents(self):
        """
        Hent pakke-innhold med antall fra betala_bundle_product_ids.
        Returnerer dict med {product_id: quantity}.
        """
        if not self.betala_is_bundles or not self.betala_bundle_product_ids:
            return {}
        
        from collections import Counter
        return dict(Counter(self.betala_bundle_product_ids))
    
    def get_bundle_items_display(self):
        """
        Hent pakke-innhold som liste med produkter og antall.
        Returnerer [(product, quantity), ...] for visning.
        """
        contents = self.get_bundle_contents()
        if not contents:
            return []
        
        items = []
        for product_id, quantity in contents.items():
            product = Product.objects.filter(betala_product_id=product_id).first()
            if product:
                items.append((product, quantity))
            else:
                # Ukjent produkt - vis ID
                items.append((None, quantity, product_id))
        return items
    
    def calculate_bundle_price(self):
        """
        Beregn pakkepris basert på innholdet.
        Returnerer (price_ore, vat_ore) tuple.
        """
        if not self.betala_is_bundles:
            return self.price_ore, self.vat_ore
        
        total_price = 0
        total_vat = 0
        
        for product_id, quantity in self.get_bundle_contents().items():
            product = Product.objects.filter(betala_product_id=product_id).first()
            if product:
                total_price += (product.price_ore or 0) * quantity
                total_vat += (product.vat_ore or 0) * quantity
        
        return total_price, total_vat
    
    def update_bundle_price(self, save=True):
        """
        Oppdater pakkepris basert på innholdet.
        Kalles automatisk når innholdets pris endres.
        """
        if not self.betala_is_bundles:
            return False
        
        new_price, new_vat = self.calculate_bundle_price()
        
        if self.price_ore != new_price or self.vat_ore != new_vat:
            self.price_ore = new_price
            self.vat_ore = new_vat
            if save:
                self.save(update_fields=['price_ore', 'vat_ore', 'updated_at'])
            return True
        return False
    
    def set_bundle_contents(self, contents_dict):
        """
        Sett pakke-innhold fra dict {product_id: quantity}.
        Oppdaterer betala_bundle_product_ids og prisen.
        """
        if not self.betala_is_bundles:
            return
        
        # Bygg liste med gjentatte IDer
        ids = []
        for product_id, quantity in contents_dict.items():
            ids.extend([product_id] * quantity)
        
        self.betala_bundle_product_ids = ids
        self.update_bundle_price(save=False)
    
    def update_bundles_containing_this(self, old_product_id=None, sync_to_betala=False):
        """
        Oppdater alle pakker som inneholder dette produktet.
        Kalles når prisen på dette produktet endres eller ID-en endres.
        
        Args:
            old_product_id: Gammel produkt-ID (hvis ID-en har blitt endret)
            sync_to_betala: Om pakkene skal synkroniseres til Betala
        """
        if not self.betala_product_id:
            return []
        
        # IDer vi skal lete etter: gammel ID + alle previous_ids
        search_ids = set()
        if old_product_id:
            search_ids.add(old_product_id)
        if self.betala_previous_ids:
            search_ids.update(self.betala_previous_ids)
        # Også søk etter nåværende ID (for prisoppdateringer)
        search_ids.add(self.betala_product_id)
        
        # Finn alle pakker som inneholder dette produktet
        bundles = Product.objects.filter(betala_is_bundles=True)
        
        updated_bundles = []
        for bundle in bundles:
            if not bundle.betala_bundle_product_ids:
                continue
            
            # Sjekk om noen av våre IDer finnes i pakken
            found_ids = search_ids.intersection(set(bundle.betala_bundle_product_ids))
            if found_ids:
                # Erstatt alle gamle IDer med nåværende ID
                bundle.betala_bundle_product_ids = [
                    self.betala_product_id if pid in search_ids else pid
                    for pid in bundle.betala_bundle_product_ids
                ]
                
                # Oppdater pris
                bundle.update_bundle_price(save=False)
                bundle.save()
                updated_bundles.append(bundle)
        
        # Synkroniser oppdaterte pakker til Betala
        if sync_to_betala and updated_bundles:
            from betala_sync.client import BetalaClientSync, BetalaAPIError
            from django.conf import settings as django_settings
            
            for bundle in updated_bundles:
                try:
                    org_id = bundle.betala_organization_id or int(django_settings.BETALA_ORGANIZATION_ID)
                    payload = bundle.to_betala_payload()
                    payload['organization_id'] = org_id
                    
                    with BetalaClientSync() as client:
                        response = client.update_product(
                            product_id=bundle.betala_product_id,
                            data=payload,
                            org_id=org_id
                        )
                    
                    # Oppdater pakken med ny ID fra Betala
                    if response:
                        new_id = response.get('product_id')
                        if new_id and new_id != bundle.betala_product_id:
                            old_bundle_id = bundle.betala_product_id
                            if old_bundle_id not in (bundle.betala_previous_ids or []):
                                bundle.betala_previous_ids = (bundle.betala_previous_ids or []) + [old_bundle_id]
                            bundle.betala_product_id = new_id
                            bundle.save(update_fields=['betala_product_id', 'betala_previous_ids', 'updated_at'])
                            
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Kunne ikke synkronisere pakke {bundle.name} til Betala: {e}")
        
        return updated_bundles
    
    def get_containing_bundles(self):
        """
        Hent alle pakker som inneholder dette produktet.
        Søker også etter tidligere IDer i previous_ids.
        
        Returns:
            QuerySet med pakker (Product-objekter)
        """
        if not self.betala_product_id:
            return Product.objects.none()
        
        # Alle IDer vi skal søke etter
        search_ids = {self.betala_product_id}
        if self.betala_previous_ids:
            search_ids.update(self.betala_previous_ids)
        
        # Finn pakker som inneholder noen av disse ID-ene
        bundles = []
        for bundle in Product.objects.filter(betala_is_bundles=True):
            if bundle.betala_bundle_product_ids:
                if search_ids.intersection(set(bundle.betala_bundle_product_ids)):
                    bundles.append(bundle.pk)
        
        return Product.objects.filter(pk__in=bundles)


# =============================================================================
# LAGERBEVEGELSER
# =============================================================================

class StockLevel(TimeStampedModel):
    """Lagernivå per produkt per event/lokasjon."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name='Produkt',
        related_name='stock_levels'
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        verbose_name='Event',
        related_name='stock_levels',
        null=True,
        blank=True
    )
    quantity = models.IntegerField('Antall', default=0)
    location = models.CharField('Lokasjon', max_length=200, blank=True)

    class Meta:
        verbose_name = 'Lagernivå'
        verbose_name_plural = 'Lagernivåer'
        unique_together = ['product', 'event', 'location']

    def __str__(self):
        return f"{self.product.name}: {self.quantity} {self.product.unit}"
    
    @property
    def is_low_stock(self):
        """Sjekk om beholdningen er under minimum."""
        return self.quantity <= self.product.min_stock_level


class StockTransaction(TimeStampedModel):
    """
    Alle lagerbevegelser.
    Positiv quantity = inn på lager, negativ = ut av lager.
    """
    
    class TransactionType(models.TextChoices):
        RECEIVING = 'RECEIVING', 'Varemottak'
        SALE = 'SALE', 'Salg (fra Betala)'
        SHRINKAGE = 'SHRINKAGE', 'Svinn'
        WASTE = 'WASTE', 'Kast/avfall'
        STAFF_CONSUMPTION = 'STAFF', 'Personalforbruk'
        TASTING = 'TASTING', 'Prøvesmaking'
        TRANSFER = 'TRANSFER', 'Overføring'
        ADJUSTMENT = 'ADJUSTMENT', 'Korrigering'
        RETURN = 'RETURN', 'Retur til leverandør'
        INITIAL = 'INITIAL', 'Åpningsbeholdning'
        COUNT = 'COUNT', 'Varetelling'
    
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name='Produkt',
        related_name='transactions'
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        verbose_name='Event',
        related_name='transactions',
        null=True,
        blank=True
    )
    
    transaction_type = models.CharField(
        'Type',
        max_length=20,
        choices=TransactionType.choices
    )
    quantity = models.IntegerField(
        'Antall',
        help_text='Positivt = inn, negativt = ut'
    )
    
    # Detaljer
    unit_cost_ore = models.IntegerField('Enhetskost (øre)', null=True, blank=True)
    reference = models.CharField('Referanse', max_length=200, blank=True)
    notes = models.TextField('Notater', blank=True)
    location = models.CharField('Lokasjon', max_length=200, blank=True)
    
    # Leverandørinfo (for varemottak)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Leverandør'
    )
    delivery_note = models.CharField('Følgeseddel', max_length=100, blank=True)
    
    # Betala kobling (for salg)
    betala_purchase_id = models.UUIDField(
        'Betala KjøpID',
        null=True,
        blank=True,
        db_index=True
    )
    betala_sequence_number = models.IntegerField(
        'Betala trans.nr',
        null=True,
        blank=True,
        db_index=True,
        help_text='Transaksjonsnummer fra Betala for gruppering av salg'
    )
    
    # Bruker
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Registrert av',
        related_name='stock_transactions'
    )
    transaction_date = models.DateTimeField(
        'Transaksjonsdato',
        default=timezone.now
    )

    class Meta:
        verbose_name = 'Lagertransaksjon'
        verbose_name_plural = 'Lagertransaksjoner'
        ordering = ['-transaction_date']

    def __str__(self):
        return f"{self.get_transaction_type_display()}: {self.product.name} ({self.quantity:+d})"
    
    @property
    def total_cost_ore(self):
        """Total kostnad i øre."""
        if self.unit_cost_ore:
            return self.unit_cost_ore * abs(self.quantity)
        return None
    
    def save(self, *args, **kwargs):
        """Oppdater lagernivå ved lagring."""
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new:
            # Oppdater eller opprett StockLevel
            # NB: Lokasjon brukes IKKE for å splitte lager - alt er på samme lager per event
            # Lokasjon lagres kun på transaksjonen for sporbarhet
            stock_level, created = StockLevel.objects.get_or_create(
                product=self.product,
                event=self.event,
                location='',  # Alt på samme lager
                defaults={'quantity': 0}
            )
            stock_level.quantity += self.quantity
            stock_level.save()


# =============================================================================
# VAREMOTTAK
# =============================================================================

class ReceivingOrder(TimeStampedModel):
    """Samler flere varemottak-linjer i én ordre."""
    
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Utkast'
        RECEIVED = 'RECEIVED', 'Mottatt'
        VERIFIED = 'VERIFIED', 'Kontrollert'
    
    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        verbose_name='Event',
        related_name='receiving_orders'
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        verbose_name='Leverandør',
        related_name='receiving_orders'
    )
    
    # Kobling til innkjøpsordre
    purchase_order = models.ForeignKey(
        'PurchaseOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Innkjøpsordre',
        related_name='receiving_orders',
        help_text='Koble til eksisterende innkjøpsordre for delmottak'
    )
    
    order_number = models.CharField('Ordrenummer', max_length=100, blank=True)
    delivery_note = models.CharField('Følgeseddel', max_length=100, blank=True)
    
    status = models.CharField(
        'Status',
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    
    received_date = models.DateField('Mottatt dato', default=timezone.now)
    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Mottatt av',
        related_name='received_orders'
    )
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Kontrollert av',
        related_name='verified_orders'
    )
    
    notes = models.TextField('Notater', blank=True)

    class Meta:
        verbose_name = 'Varemottak'
        verbose_name_plural = 'Varemottak'
        ordering = ['-received_date']

    def __str__(self):
        return f"Mottak {self.pk} - {self.supplier.name} ({self.received_date})"
    
    @property
    def total_items(self):
        return self.lines.count()
    
    @property
    def total_cost_ore(self):
        return self.lines.aggregate(
            total=models.Sum(models.F('quantity') * models.F('unit_cost_ore'))
        )['total'] or 0


class ReceivingOrderLine(TimeStampedModel):
    """Enkeltlinjer i et varemottak."""
    receiving_order = models.ForeignKey(
        ReceivingOrder,
        on_delete=models.CASCADE,
        verbose_name='Varemottak',
        related_name='lines'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name='Produkt'
    )
    
    # Enhet brukt ved mottak (for enhetskonvertering)
    unit = models.ForeignKey(
        'UnitOfMeasure',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Enhet',
        related_name='receiving_lines',
        help_text='Hvilken enhet ble brukt ved mottak (f.eks. Fat 300L)'
    )
    
    # Kobling til innkjøpsordrelinje (for delmottak)
    purchase_order_line = models.ForeignKey(
        'PurchaseOrderLine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Fra innkjøpsordrelinje',
        related_name='receiving_lines'
    )
    
    quantity_expected = models.IntegerField('Forventet antall', default=0)
    quantity_received = models.IntegerField('Mottatt antall')
    unit_cost_ore = models.IntegerField(
        'Enhetskost (øre)',
        validators=[MinValueValidator(0)]
    )
    
    batch_number = models.CharField('Batch/Lot', max_length=100, blank=True)
    expiry_date = models.DateField('Utløpsdato', null=True, blank=True)
    notes = models.TextField('Notater', blank=True)
    
    # Kobling til lagertransaksjon
    stock_transaction = models.OneToOneField(
        StockTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='receiving_line'
    )

    class Meta:
        verbose_name = 'Varemottakslinje'
        verbose_name_plural = 'Varemottakslinjer'

    def __str__(self):
        return f"{self.product.name}: {self.quantity_received}"
    
    @property
    def variance(self):
        """Avvik mellom forventet og mottatt."""
        if self.quantity_expected:
            return self.quantity_received - self.quantity_expected
        return 0


# =============================================================================
# INNKJØPSORDRE (BESTILLINGER)
# =============================================================================

class PurchaseOrder(TimeStampedModel):
    """Innkjøpsordre/bestilling fra leverandør."""
    
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Utkast'
        ORDERED = 'ORDERED', 'Bestilt'
        PARTIALLY_RECEIVED = 'PARTIAL', 'Delvis mottatt'
        FULLY_RECEIVED = 'RECEIVED', 'Fullstendig mottatt'
        CANCELLED = 'CANCELLED', 'Kansellert'
    
    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        verbose_name='Event',
        related_name='purchase_orders'
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        verbose_name='Leverandør',
        related_name='purchase_orders'
    )
    
    order_number = models.CharField(
        'Ordrenummer', 
        max_length=100, 
        unique=True,
        help_text='Internt ordrenummer'
    )
    supplier_reference = models.CharField(
        'Leverandørreferanse', 
        max_length=100, 
        blank=True,
        help_text='Ordrenummer fra leverandør'
    )
    
    status = models.CharField(
        'Status',
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    
    order_date = models.DateField('Bestillingsdato', null=True, blank=True)
    expected_delivery = models.DateField('Forventet levering', null=True, blank=True)
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Opprettet av',
        related_name='created_purchase_orders'
    )
    
    notes = models.TextField('Notater', blank=True)

    class Meta:
        verbose_name = 'Innkjøpsordre'
        verbose_name_plural = 'Innkjøpsordrer'
        ordering = ['-created_at']

    def __str__(self):
        return f"PO-{self.order_number} - {self.supplier.name}"
    
    @property
    def total_items(self):
        """Totalt antall linjer."""
        return self.lines.count()
    
    @property
    def total_ordered(self):
        """Totalt antall bestilte enheter."""
        return self.lines.aggregate(total=models.Sum('quantity_ordered'))['total'] or 0
    
    @property
    def total_received(self):
        """Totalt antall mottatte enheter."""
        return self.lines.aggregate(total=models.Sum('quantity_received'))['total'] or 0
    
    @property
    def total_cost_ore(self):
        """Total kostnad i øre."""
        return self.lines.aggregate(
            total=models.Sum(models.F('quantity_ordered') * models.F('unit_cost_ore'))
        )['total'] or 0
    
    @property
    def total_cost_kr(self):
        """Total kostnad i kroner."""
        return Decimal(self.total_cost_ore) / 100
    
    @property
    def receive_progress_percent(self):
        """Prosent mottatt."""
        if self.total_ordered > 0:
            return int((self.total_received / self.total_ordered) * 100)
        return 0
    
    def update_status(self):
        """Oppdater status basert på mottatt mengde."""
        if self.status == self.Status.CANCELLED:
            return
        
        total_ordered = self.total_ordered
        total_received = self.total_received
        
        if total_received == 0:
            if self.order_date:
                self.status = self.Status.ORDERED
            else:
                self.status = self.Status.DRAFT
        elif total_received >= total_ordered:
            self.status = self.Status.FULLY_RECEIVED
        else:
            self.status = self.Status.PARTIALLY_RECEIVED
        self.save()
    
    def save(self, *args, **kwargs):
        # Generer ordrenummer hvis ikke satt
        if not self.order_number:
            from django.utils import timezone
            import random
            today = timezone.now().strftime('%Y%m%d')
            self.order_number = f"{today}-{random.randint(1000, 9999)}"
        super().save(*args, **kwargs)


class PurchaseOrderLine(TimeStampedModel):
    """Enkeltlinje i en innkjøpsordre."""
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        verbose_name='Innkjøpsordre',
        related_name='lines'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name='Produkt'
    )
    
    quantity_ordered = models.PositiveIntegerField('Bestilt antall')
    quantity_received = models.PositiveIntegerField('Mottatt antall', default=0)
    unit_cost_ore = models.IntegerField(
        'Enhetskost (øre)',
        validators=[MinValueValidator(0)],
        help_text='Pris per enhet eks. mva i øre'
    )
    
    notes = models.TextField('Notater', blank=True)

    class Meta:
        verbose_name = 'Innkjøpsordrelinje'
        verbose_name_plural = 'Innkjøpsordrelinjer'

    def __str__(self):
        return f"{self.product.name}: {self.quantity_ordered}"
    
    @property
    def remaining_quantity(self):
        """Gjenstående antall å motta."""
        return max(0, self.quantity_ordered - self.quantity_received)
    
    @property
    def is_fully_received(self):
        """Er linjen fullstendig mottatt?"""
        return self.quantity_received >= self.quantity_ordered
    
    @property
    def line_total_ore(self):
        """Total kostnad for linjen i øre."""
        return self.quantity_ordered * self.unit_cost_ore
    
    @property
    def unit_cost_kr(self):
        """Enhetskost i kroner."""
        return Decimal(self.unit_cost_ore) / 100


# =============================================================================
# SVINN OG KORREKSJONER
# =============================================================================

class ShrinkageEntry(TimeStampedModel):
    """Dedikert modell for svinnregistrering med mer detaljer."""
    
    class ShrinkageReason(models.TextChoices):
        BREAKAGE = 'BREAKAGE', 'Knust/ødelagt'
        EXPIRED = 'EXPIRED', 'Utgått dato'
        THEFT = 'THEFT', 'Tyveri'
        SPILLAGE = 'SPILLAGE', 'Sølt'
        OVERPOURING = 'OVERPOUR', 'Overskjenking'
        STAFF = 'STAFF', 'Personalforbruk'
        TASTING = 'TASTING', 'Prøvesmaking'
        GIVEAWAY = 'GIVEAWAY', 'Gave/promo'
        UNKNOWN = 'UNKNOWN', 'Ukjent'
        OTHER = 'OTHER', 'Annet'
    
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name='Produkt',
        related_name='shrinkage_entries'
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        verbose_name='Event',
        related_name='shrinkage_entries'
    )
    
    quantity = models.PositiveIntegerField('Antall')
    reason = models.CharField(
        'Årsak',
        max_length=20,
        choices=ShrinkageReason.choices
    )
    location = models.CharField('Sted', max_length=200, blank=True)
    notes = models.TextField('Beskrivelse', blank=True)
    
    registered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='Registrert av'
    )
    registered_date = models.DateTimeField('Registrert', default=timezone.now)
    
    # Kobling til lagertransaksjon
    stock_transaction = models.OneToOneField(
        StockTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shrinkage_entry'
    )
    
    # Registrert tap - låst ved registrering
    recorded_loss_ore = models.IntegerField(
        'Registrert tap (øre)',
        null=True,
        blank=True,
        help_text='Estimert tap ved registreringstidspunkt'
    )

    class Meta:
        verbose_name = 'Svinn'
        verbose_name_plural = 'Svinn'
        ordering = ['-registered_date']

    def __str__(self):
        return f"{self.product.name}: {self.quantity} ({self.get_reason_display()})"
    
    @property
    def estimated_loss_ore(self):
        """Estimert tap i øre - bruker registrert verdi om den finnes."""
        if self.recorded_loss_ore is not None:
            return self.recorded_loss_ore
        # Fallback til beregnet verdi (for gamle entries)
        if self.product.price_ore:
            return self.product.price_ore * self.quantity
        return None
    
    def calculate_loss_ore(self):
        """Beregn tap basert på nåværende produktpris."""
        if self.product.price_ore:
            return self.product.price_ore * self.quantity
        return None


class StockCount(TimeStampedModel):
    """
    Varetelling for å justere lagerbeholdning.
    
    Kan være enten en hovedtelling eller en deltelling.
    Deltellinger kobles til en hovedtelling via parent_count.
    """
    
    class Status(models.TextChoices):
        IN_PROGRESS = 'IN_PROGRESS', 'Pågår'
        COMPLETED = 'COMPLETED', 'Fullført'
        CANCELLED = 'CANCELLED', 'Avbrutt'
        IMPORTED = 'IMPORTED', 'Importert'  # For deltellinger som er importert
    
    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        verbose_name='Event',
        related_name='stock_counts'
    )
    
    # For deltellinger - kobling til hovedtelling
    parent_count = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name='Hovedtelling',
        related_name='partial_counts'
    )
    
    name = models.CharField('Navn/beskrivelse', max_length=200)
    status = models.CharField(
        'Status',
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS
    )
    location = models.CharField('Lokasjon', max_length=200, blank=True)
    
    started_at = models.DateTimeField('Startet', default=timezone.now)
    completed_at = models.DateTimeField('Fullført', null=True, blank=True)
    
    started_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='Startet av',
        related_name='started_counts'
    )
    completed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Fullført av',
        related_name='completed_counts'
    )
    notes = models.TextField('Notater', blank=True)

    class Meta:
        verbose_name = 'Varetelling'
        verbose_name_plural = 'Varetelinger'
        ordering = ['-started_at']

    def __str__(self):
        prefix = "[Deltelling] " if self.is_partial else ""
        return f"{prefix}{self.name} ({self.started_at.date()})"
    
    @property
    def is_partial(self):
        """Er dette en deltelling?"""
        return self.parent_count_id is not None
    
    @property
    def is_imported(self):
        """Er deltelling importert til hovedtelling?"""
        return self.status == self.Status.IMPORTED
    
    @property
    def can_be_imported(self):
        """Kan deltelling importeres?"""
        return (
            self.is_partial and 
            self.status == self.Status.COMPLETED and 
            not self.is_imported
        )
    
    def get_available_partial_counts(self):
        """Hent deltellinger som kan importeres."""
        return self.partial_counts.filter(status=self.Status.COMPLETED)


class StockCountLine(TimeStampedModel):
    """Enkelttelling for et produkt."""
    stock_count = models.ForeignKey(
        StockCount,
        on_delete=models.CASCADE,
        verbose_name='Varetelling',
        related_name='lines'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name='Produkt'
    )
    
    expected_quantity = models.IntegerField('Forventet antall')
    counted_quantity = models.IntegerField('Talt antall', null=True, blank=True)
    
    # Enhet brukt ved telling
    unit = models.ForeignKey(
        'UnitOfMeasure',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Enhet',
        help_text='Enheten som ble brukt ved telling'
    )
    
    counted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Talt av'
    )
    counted_at = models.DateTimeField('Talt', null=True, blank=True)
    notes = models.TextField('Notater', blank=True)
    
    # Kobling til justeringstransaksjon
    stock_transaction = models.OneToOneField(
        StockTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='count_line'
    )

    class Meta:
        verbose_name = 'Tellelinje'
        verbose_name_plural = 'Tellelinjer'
        unique_together = ['stock_count', 'product']

    def __str__(self):
        variance = ''
        if self.counted_quantity is not None and self.expected_quantity:
            diff = self.counted_quantity - self.expected_quantity
            variance = f' (avvik: {diff:+d})'
        return f"{self.product.name}: {self.counted_quantity or '?'}{variance}"

    @property
    def variance(self):
        """Avvik mellom forventet og talt."""
        if self.counted_quantity is not None:
            return self.counted_quantity - self.expected_quantity
        return None

    def get_expected_in_units(self):
        """Returner forventet antall formatert i enheter."""
        if not self.product.use_unit_conversion:
            return str(self.expected_quantity)
        
        # Hent telleenheter for produktet
        count_units = self.product.units.filter(is_count_unit=True).order_by('-conversion_factor')
        if not count_units.exists():
            return str(self.expected_quantity)
        
        remaining = self.expected_quantity
        parts = []
        
        for unit in count_units:
            if remaining >= unit.conversion_factor:
                count = remaining // unit.conversion_factor
                remaining = remaining % unit.conversion_factor
                parts.append(f"{count} {unit.name}")
        
        # Legg til rest i base-enhet
        if remaining > 0:
            base_abbrev = getattr(self.product, 'base_unit_type', 'stk')
            parts.append(f"{remaining} {base_abbrev}")
        
        return ' + '.join(parts) if parts else str(self.expected_quantity)

    def get_counted_in_unit(self):
        """Returner talt antall i den valgte enheten."""
        if self.counted_quantity is None:
            return None
        if self.unit and self.unit.conversion_factor > 0:
            return self.counted_quantity / self.unit.conversion_factor
        return self.counted_quantity


# =============================================================================
# BETALA TRANSAKSJONSSYNKRONISERING
# =============================================================================

class BetalaTransactionSync(TimeStampedModel):
    """
    Sporer hvilke Betala-transaksjoner som er synkronisert til lagersystemet.
    
    Brukes for å unngå duplikater når vi henter salgsdata fra Betala.
    Unik kombinasjon av (event/sales_point_group, sequence_number) identifiserer
    en transaksjon.
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        verbose_name='Event',
        related_name='synced_transactions'
    )
    sequence_number = models.IntegerField(
        'Sekvensnummer',
        db_index=True,
        help_text='Betala transaksjon sekvensnummer (unik per sales_point_group)'
    )
    finalized_at = models.DateTimeField(
        'Avsluttet',
        help_text='Når transaksjonen ble avsluttet i Betala'
    )
    is_void = models.BooleanField(
        'Annullert',
        default=False,
        help_text='Om transaksjonen er annullert/refundert'
    )
    
    # Salgsdetaljer (aggregert)
    total_items = models.IntegerField(
        'Antall varer',
        default=0,
        help_text='Totalt antall produkter solgt i denne transaksjonen'
    )
    total_amount_ore = models.IntegerField(
        'Totalbeløp (øre)',
        default=0
    )
    
    # Metadata
    synced_at = models.DateTimeField(
        'Synkronisert',
        auto_now_add=True
    )

    class Meta:
        verbose_name = 'Betala transaksjon'
        verbose_name_plural = 'Betala transaksjoner'
        ordering = ['-finalized_at']
        # Unik kombinasjon - en transaksjon kan bare synkes én gang
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'sequence_number'],
                name='unique_transaction_per_event'
            )
        ]

    def __str__(self):
        status = '(ANNULLERT) ' if self.is_void else ''
        return f"{status}Trans #{self.sequence_number}: {self.total_items} varer @ {self.finalized_at.strftime('%d.%m.%Y %H:%M')}"


# =============================================================================
# BETALA SYNKRONISERING
# =============================================================================

class BetalaSyncLog(TimeStampedModel):
    """Logger synkronisering med Betala API."""
    
    class SyncType(models.TextChoices):
        PRODUCTS = 'PRODUCTS', 'Produkter'
        CATEGORIES = 'CATEGORIES', 'Kategorier'
        SALES = 'SALES', 'Salg'
        FULL = 'FULL', 'Full sync'
    
    class Status(models.TextChoices):
        STARTED = 'STARTED', 'Startet'
        SUCCESS = 'SUCCESS', 'Vellykket'
        PARTIAL = 'PARTIAL', 'Delvis vellykket'
        FAILED = 'FAILED', 'Feilet'
    
    sync_type = models.CharField(
        'Type',
        max_length=20,
        choices=SyncType.choices
    )
    status = models.CharField(
        'Status',
        max_length=20,
        choices=Status.choices,
        default=Status.STARTED
    )
    
    started_at = models.DateTimeField('Startet', default=timezone.now)
    completed_at = models.DateTimeField('Fullført', null=True, blank=True)
    
    items_processed = models.IntegerField('Behandlet', default=0)
    items_created = models.IntegerField('Opprettet', default=0)
    items_updated = models.IntegerField('Oppdatert', default=0)
    items_failed = models.IntegerField('Feilet', default=0)
    
    error_message = models.TextField('Feilmelding', blank=True)
    details = models.JSONField('Detaljer', default=dict, blank=True)
    
    triggered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Startet av'
    )

    class Meta:
        verbose_name = 'Synkroniseringslogg'
        verbose_name_plural = 'Synkroniseringslogger'
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.get_sync_type_display()} - {self.started_at}"


# =============================================================================
# TILGANGSKONTROLL
# =============================================================================

class AllowedOrganization(TimeStampedModel):
    """
    Organisasjoner som har tilgang til systemet.
    Kun organisasjoner som er registrert her vil vises for brukere.
    """
    # Betala organisasjons-ID (numerisk)
    betala_org_id = models.CharField(
        'Betala Org ID',
        max_length=100,
        unique=True,
        help_text='Organisasjonens ID i Betala (f.eks. 12345)'
    )
    
    # Organisasjonsnavn (for visning i admin)
    name = models.CharField(
        'Organisasjonsnavn',
        max_length=200,
        help_text='Navn på organisasjonen (for referanse)'
    )
    
    # Identifier (alternativ identifikator fra Betala)
    identifier = models.CharField(
        'Identifier',
        max_length=100,
        blank=True,
        help_text='Organisasjonens identifier i Betala (valgfritt)'
    )
    
    # Aktiv/inaktiv
    is_active = models.BooleanField(
        'Aktiv',
        default=True,
        help_text='Deaktiver for å fjerne tilgang midlertidig'
    )
    
    # Notater
    notes = models.TextField(
        'Notater',
        blank=True,
        help_text='Interne notater om organisasjonen'
    )

    class Meta:
        verbose_name = 'Godkjent organisasjon'
        verbose_name_plural = 'Godkjente organisasjoner'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.betala_org_id})"


# =============================================================================
# ENHETSKONVERTERING (UNIT OF MEASURE)
# =============================================================================

class UnitOfMeasure(TimeStampedModel):
    """
    Enheter for et produkt med konverteringsfaktor.
    
    Alle mengder lagres internt i produktets base_unit (ml, cl, stk).
    Denne modellen definerer "menneskelige" enheter som Tank, Flaske, Glass etc.
    
    Eksempel for fatøl:
        - Base unit: ml
        - Tank 30L: conversion_factor = 30000 (30L * 1000ml)
        - Dunk 3L: conversion_factor = 3000
        - Glass 0.4L: conversion_factor = 400
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name='Produkt',
        related_name='units'
    )
    
    name = models.CharField(
        'Enhetsnavn',
        max_length=100,
        help_text='F.eks. "Tank 30L", "Flaske 0.33L", "Glass 0.4L"'
    )
    short_name = models.CharField(
        'Kortform',
        max_length=20,
        blank=True,
        help_text='F.eks. "Tank", "Fl", "Glass"'
    )
    
    conversion_factor = models.PositiveIntegerField(
        'Konverteringsfaktor',
        validators=[MinValueValidator(1)],
        help_text='Antall base-enheter (ml eller stk) denne enheten tilsvarer'
    )
    
    # Bruksområder - hvilke operasjoner kan denne enheten brukes til?
    is_purchase_unit = models.BooleanField(
        'Innkjøpsenhet',
        default=False,
        help_text='Kan brukes ved innkjøp/varemottak'
    )
    is_sale_unit = models.BooleanField(
        'Salgsenhet',
        default=False,
        help_text='Brukes for salg fra Betala'
    )
    is_count_unit = models.BooleanField(
        'Telleenhet',
        default=True,
        help_text='Kan brukes ved varetelling'
    )
    
    # Sortering
    sort_order = models.IntegerField(
        'Sortering',
        default=0,
        help_text='Lavere tall = vises først (brukes for format_stock_display)'
    )
    
    # Aktiv
    is_active = models.BooleanField('Aktiv', default=True)

    class Meta:
        verbose_name = 'Enhet'
        verbose_name_plural = 'Enheter'
        ordering = ['product', 'sort_order', '-conversion_factor']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'name'],
                name='unique_unit_name_per_product'
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.conversion_factor} {self.product.base_unit_type})"
    
    def to_base_units(self, quantity: int) -> int:
        """Konverter en mengde i denne enheten til base-enheter."""
        return quantity * self.conversion_factor
    
    def from_base_units(self, base_quantity: int) -> tuple:
        """
        Konverter base-enheter til denne enheten.
        
        Returns:
            tuple: (whole_units, remainder_in_base_units)
        """
        whole_units = base_quantity // self.conversion_factor
        remainder = base_quantity % self.conversion_factor
        return whole_units, remainder
