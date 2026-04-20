"""
Views for lagersystemet.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, F, Q
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse

from .models import (
    Product, Category, StockLevel, StockTransaction,
    ReceivingOrder, ReceivingOrderLine, ShrinkageEntry,
    StockCount, StockCountLine, Event, BetalaSyncLog,
    PurchaseOrder, PurchaseOrderLine, Supplier
)
from .forms import (
    ProductFilterForm, StockTransactionForm, ReceivingOrderForm,
    ReceivingOrderLineFormSet, get_receiving_line_formset, ShrinkageEntryForm, 
    StockCountForm, StockCountLineForm, EventSelectForm, PurchaseOrderForm, 
    PurchaseOrderLineFormSet, get_purchase_order_line_formset, 
    ReceiveFromPurchaseOrderForm, ProductEditForm
)
from betala_sync.client import BetalaClientSync, BetalaAPIError
from django.conf import settings as django_settings


# =============================================================================
# HJELPEFUNKSJONER
# =============================================================================

def get_active_event(request):
    """Hent aktivt event fra session eller første tilgjengelige."""
    event_id = request.session.get('active_event_id')
    if event_id:
        try:
            return Event.objects.get(pk=event_id, is_active=True)
        except Event.DoesNotExist:
            pass
    
    # Finn første aktive event
    event = Event.objects.filter(is_active=True).first()
    if event:
        request.session['active_event_id'] = event.id
    return event


def get_active_organization_id(request):
    """Hent aktiv organisasjon-ID fra session."""
    org_id = request.session.get('betala_selected_org_id')
    if org_id:
        return int(org_id)
    
    # Fallback: hent fra aktivt event
    event = get_active_event(request)
    if event and event.betala_organization_id:
        return event.betala_organization_id
    
    return None


# =============================================================================
# DASHBOARD
# =============================================================================

@login_required
def dashboard(request):
    """Hovedoversikt/dashboard."""
    event = get_active_event(request)
    org_id = get_active_organization_id(request)
    
    # Event-valg - filtrert på valgt organisasjon
    if request.method == 'POST':
        form = EventSelectForm(request.POST, organization_id=org_id)
        if form.is_valid():
            request.session['active_event_id'] = form.cleaned_data['event'].id
            return redirect('inventory:dashboard')
    else:
        form = EventSelectForm(initial={'event': event}, organization_id=org_id)
    
    # Statistikk - filtrer på organisasjon
    products_qs = Product.objects.filter(is_active=True)
    if org_id:
        products_qs = products_qs.filter(betala_organization_id=org_id)
    products_count = products_qs.count()
    
    # Lagerbeholdning for aktivt event
    stock_stats = {}
    low_stock_count = 0
    recent_transactions = []
    
    if event:
        stock_levels = StockLevel.objects.filter(event=event).select_related('product')
        total_items = stock_levels.aggregate(total=Sum('quantity'))['total'] or 0
        
        low_stock_count = sum(1 for sl in stock_levels if sl.is_low_stock)
        
        stock_stats = {
            'total_items': total_items,
            'unique_products': stock_levels.count(),
            'low_stock': low_stock_count,
        }
        
        recent_transactions = StockTransaction.objects.filter(
            event=event
        ).select_related('product', 'created_by').order_by('-transaction_date')[:10]
    
    # Siste synkronisering
    last_sync = BetalaSyncLog.objects.filter(
        status=BetalaSyncLog.Status.SUCCESS
    ).first()
    
    context = {
        'event': event,
        'event_form': form,
        'products_count': products_count,
        'stock_stats': stock_stats,
        'low_stock_count': low_stock_count,
        'recent_transactions': recent_transactions,
        'last_sync': last_sync,
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required
def toggle_auto_sync(request):
    """Slå automatisk synkronisering av/på for et event."""
    if request.method == 'POST':
        event_id = request.POST.get('event_id')
        event = get_object_or_404(Event, pk=event_id)
        
        # Toggle basert på checkbox
        event.auto_sync_enabled = 'auto_sync_enabled' in request.POST
        event.save(update_fields=['auto_sync_enabled'])
        
        if event.auto_sync_enabled:
            messages.success(request, f'Automatisk synkronisering aktivert for {event.name}')
        else:
            messages.info(request, f'Automatisk synkronisering deaktivert for {event.name}')
    
    return redirect('inventory:dashboard')


# =============================================================================
# PRODUKTER
# =============================================================================

@login_required
def product_list(request):
    """Liste over alle produkter for valgt organisasjon."""
    categories = Category.objects.filter(is_active=True)
    form = ProductFilterForm(request.GET, categories=categories)
    
    # Hent aktiv organisasjon
    org_id = get_active_organization_id(request)
    org_name = request.session.get('betala_selected_org_name', '')
    
    # Synkroniser produkter fra Betala ved sidelasting
    sync_message = None
    if org_id:
        try:
            from betala_sync.services import SyncService
            service = SyncService(user=request.user, organization_id=str(org_id))
            created, updated, failed = service.sync_products()
            if created or updated:
                sync_message = f'Synkronisert: {created} nye, {updated} oppdatert'
        except Exception as e:
            sync_message = f'Kunne ikke synkronisere: {e}'
    
    # Filtrer produkter basert på organisasjon
    products = Product.objects.filter(is_active=True).select_related('category', 'supplier')
    if org_id:
        products = products.filter(betala_organization_id=org_id)
    
    if form.is_valid():
        if form.cleaned_data.get('search'):
            search = form.cleaned_data['search']
            products = products.filter(
                Q(name__icontains=search) |
                Q(sku__icontains=search) |
                Q(barcode__icontains=search)
            )
        if form.cleaned_data.get('category'):
            products = products.filter(category_id=form.cleaned_data['category'])
        if form.cleaned_data.get('show_inactive'):
            base_qs = Product.objects.all().select_related('category', 'supplier')
            if org_id:
                base_qs = base_qs.filter(betala_organization_id=org_id)
            products = base_qs
    
    # Paginering
    paginator = Paginator(products, 50)
    page = request.GET.get('page', 1)
    products = paginator.get_page(page)
    
    context = {
        'products': products,
        'form': form,
        'categories': categories,
        'organization_name': org_name,
        'sync_message': sync_message,
    }
    return render(request, 'inventory/product_list.html', context)


@login_required
def product_detail(request, betala_id):
    """Produktdetaljer med transaksjonshistorikk."""
    product = get_object_or_404(Product, betala_product_id=betala_id)
    event = get_active_event(request)
    
    # Lagernivå
    stock_level = None
    if event:
        stock_level = StockLevel.objects.filter(
            product=product, event=event
        ).first()
    
    # Transaksjonshistorikk
    transactions = product.transactions.select_related(
        'event', 'created_by'
    ).order_by('-transaction_date')[:20]
    
    # Pakke-innhold
    bundle_items = None
    if product.betala_is_bundles:
        bundle_items = product.get_bundle_items_display()
    
    # Hvilke pakker inneholder dette produktet
    containing_bundles = None
    if not product.betala_is_bundles:
        containing_bundles = product.get_containing_bundles()
    
    context = {
        'product': product,
        'stock_level': stock_level,
        'transactions': transactions,
        'event': event,
        'bundle_items': bundle_items,
        'containing_bundles': containing_bundles,
    }
    return render(request, 'inventory/product_detail.html', context)


@login_required
def product_edit(request, betala_id):
    """Rediger produkt og synkroniser til Betala."""
    product = get_object_or_404(Product, betala_product_id=betala_id)
    
    if request.method == 'POST':
        form = ProductEditForm(request.POST, instance=product)
        if form.is_valid():
            # Lagre gammel ID før vi synkroniserer
            old_product_id = product.betala_product_id
            
            # Lagre lokalt først (uten å oppdatere pakker ennå)
            product = form.save(commit=False)
            
            # Håndter enhetskonvertering-felter fra sidepanel (ikke i crispy form)
            base_unit_type = request.POST.get('base_unit_type')
            use_unit_conversion = request.POST.get('use_unit_conversion') == 'on'
            
            if base_unit_type in ['ml', 'cl', 'stk']:
                product.base_unit_type = base_unit_type
            product.use_unit_conversion = use_unit_conversion
            
            product.save()
            
            # Synkroniser til Betala hvis produktet har Betala ID
            if product.betala_product_id:
                # Bruk organization_id fra produkt, eller fallback til settings
                org_id = product.betala_organization_id or int(django_settings.BETALA_ORGANIZATION_ID)
                
                try:
                    payload = product.to_betala_payload()
                    # Sørg for at organization_id er med i payload
                    payload['organization_id'] = org_id
                    
                    # Prøv opptil 3 ganger ved feil
                    max_retries = 3
                    last_error = None
                    
                    for attempt in range(max_retries):
                        try:
                            with BetalaClientSync() as client:
                                response = client.update_product(
                                    product_id=product.betala_product_id,
                                    data=payload,
                                    org_id=org_id
                                )
                                break  # Suksess, avslutt løkken
                        except BetalaAPIError as e:
                            last_error = e
                            if e.status_code == 409:  # Conflict - prøv igjen
                                import time
                                time.sleep(0.5)  # Vent litt før retry
                                continue
                            raise  # Andre feil - ikke retry
                    else:
                        # Alle forsøk feilet
                        raise last_error
                    
                    # Betala gir produktet ny ID ved hver endring - oppdater lokalt
                    new_product_id = response.get('product_id')
                    if new_product_id and new_product_id != product.betala_product_id:
                        # Lagre gammel ID i previous_ids
                        if product.betala_previous_ids is None:
                            product.betala_previous_ids = []
                        if product.betala_product_id not in product.betala_previous_ids:
                            product.betala_previous_ids.append(product.betala_product_id)
                        
                        product.betala_product_id = new_product_id
                        product.save(update_fields=['betala_product_id', 'betala_previous_ids', 'updated_at'])
                    
                    # Oppdater pakker som inneholder dette produktet
                    # (med gammel ID, ny ID, og synkroniser til Betala)
                    if not product.betala_is_bundles:
                        updated_bundles = product.update_bundles_containing_this(
                            old_product_id=old_product_id,
                            sync_to_betala=True
                        )
                        if updated_bundles:
                            bundle_names = ', '.join([b.name for b in updated_bundles])
                            messages.info(request, f'Oppdaterte {len(updated_bundles)} pakke(r): {bundle_names}')
                        
                    messages.success(
                        request, 
                        f'Produkt "{product.name}" lagret og synkronisert til Betala!'
                    )
                except BetalaAPIError as e:
                    error_detail = e.message
                    if e.response_data and 'errors' in e.response_data:
                        error_detail = ', '.join(e.response_data['errors'])
                    messages.warning(
                        request,
                        f'Produkt lagret lokalt, men synkronisering til Betala feilet: {error_detail}'
                    )
                    # Oppdater pakker lokalt selv om Betala-synk feilet
                    if not product.betala_is_bundles:
                        product.update_bundles_containing_this(old_product_id=old_product_id)
                except Exception as e:
                    messages.warning(
                        request,
                        f'Produkt lagret lokalt, men synkronisering til Betala feilet: {str(e)}'
                    )
                    # Oppdater pakker lokalt selv om Betala-synk feilet
                    if not product.betala_is_bundles:
                        product.update_bundles_containing_this(old_product_id=old_product_id)
            else:
                messages.success(
                    request, 
                    f'Produkt "{product.name}" lagret (ikke koblet til Betala)'
                )
                # Oppdater pakker lokalt
                if not product.betala_is_bundles:
                    product.update_bundles_containing_this()
            
            return redirect('inventory:product_detail', betala_id=product.betala_product_id)
    else:
        form = ProductEditForm(instance=product)
    
    context = {
        'form': form,
        'product': product,
    }
    return render(request, 'inventory/product_edit.html', context)


@login_required
def bundle_edit(request, betala_id):
    """Rediger pakke-innhold."""
    from .forms import BundleContentsForm, AddBundleItemForm
    
    bundle = get_object_or_404(Product, betala_product_id=betala_id, betala_is_bundles=True)
    
    # Hent organisasjon fra pakken eller aktivt event
    organization_id = bundle.betala_organization_id
    if not organization_id:
        event = get_active_event(request)
        if event:
            organization_id = event.betala_organization_id
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_item':
            # Legg til nytt produkt i pakken
            add_form = AddBundleItemForm(request.POST, organization_id=organization_id)
            if add_form.is_valid():
                product = add_form.cleaned_data['product']
                quantity = add_form.cleaned_data['quantity']
                
                # Legg til i bundle_product_ids
                contents = bundle.get_bundle_contents()
                product_id = product.betala_product_id
                
                if product_id in contents:
                    contents[product_id] += quantity
                else:
                    contents[product_id] = quantity
                
                bundle.set_bundle_contents(contents)
                bundle.save()
                
                messages.success(request, f'La til {quantity}x {product.name} i pakken')
                return redirect('inventory:bundle_edit', betala_id=betala_id)
        
        elif action == 'update_quantities':
            # Oppdater antall for alle produkter
            contents = {}
            for key, value in request.POST.items():
                if key.startswith('qty_'):
                    product_id = int(key.replace('qty_', ''))
                    quantity = int(value) if value else 0
                    if quantity > 0:
                        contents[product_id] = quantity
            
            bundle.set_bundle_contents(contents)
            bundle.save()
            
            # Synk til Betala og oppdater med ny ID
            new_betala_id = bundle.betala_product_id
            try:
                from betala_sync.client import BetalaClientSync, BetalaAPIError
                from django.conf import settings as django_settings
                
                org_id = bundle.betala_organization_id or int(django_settings.BETALA_ORGANIZATION_ID)
                payload = bundle.to_betala_payload()
                payload['organization_id'] = org_id
                
                with BetalaClientSync() as client:
                    response_data = client.update_product(
                        product_id=bundle.betala_product_id,
                        data=payload,
                        org_id=org_id
                    )
                
                # Oppdater produktet med data fra Betala (inkl. ny ID)
                if response_data:
                    old_id = bundle.betala_product_id
                    new_id = response_data.get('product_id')
                    
                    if new_id and new_id != old_id:
                        # Lagre gammel ID for sporing
                        if old_id not in (bundle.betala_previous_ids or []):
                            bundle.betala_previous_ids = (bundle.betala_previous_ids or []) + [old_id]
                        bundle.betala_product_id = new_id
                        new_betala_id = new_id
                    
                    # Oppdater andre felter fra respons
                    if 'bundles_product_ids' in response_data:
                        bundle.betala_bundle_product_ids = response_data['bundles_product_ids']
                    if 'price' in response_data:
                        bundle.price_ore = response_data['price']
                    if 'vat' in response_data:
                        bundle.vat_ore = response_data['vat']
                    
                    bundle.save()
                
                messages.success(request, f'Pakke "{bundle.name}" oppdatert og synkronisert til Betala!')
            except BetalaAPIError as e:
                error_detail = ''
                if e.response_data:
                    error_detail = f': {e.response_data}'
                messages.warning(request, f'Pakke lagret lokalt, men Betala-synk feilet: {e.message}{error_detail}')
            except Exception as e:
                messages.warning(request, f'Pakke lagret lokalt, men Betala-synk feilet: {e}')
            
            return redirect('inventory:product_detail', betala_id=new_betala_id)
        
        elif action == 'remove_item':
            # Fjern et produkt fra pakken
            product_id = int(request.POST.get('product_id'))
            contents = bundle.get_bundle_contents()
            
            if product_id in contents:
                del contents[product_id]
                bundle.set_bundle_contents(contents)
                bundle.save()
                messages.success(request, 'Produkt fjernet fra pakken')
            
            return redirect('inventory:bundle_edit', betala_id=betala_id)
    
    # Hent pakke-innhold for visning
    bundle_items = []
    for product_id, quantity in bundle.get_bundle_contents().items():
        product = Product.objects.filter(betala_product_id=product_id).first()
        if product:
            bundle_items.append({
                'product': product,
                'product_id': product_id,
                'quantity': quantity,
                'line_total': (product.price_with_vat_ore or 0) * quantity,
            })
    
    # Beregn totalpris
    total_price = sum(item['line_total'] for item in bundle_items)
    
    add_form = AddBundleItemForm(organization_id=organization_id)
    
    context = {
        'bundle': bundle,
        'bundle_items': bundle_items,
        'total_price': total_price,
        'add_form': add_form,
    }
    return render(request, 'inventory/bundle_edit.html', context)


@login_required
def product_units(request, betala_id):
    """Administrer enheter for et produkt."""
    from .models import UnitOfMeasure
    from .forms import UnitOfMeasureForm
    
    product = get_object_or_404(Product, betala_product_id=betala_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_unit':
            # Legg til ny enhet
            name = request.POST.get('name', '').strip()
            short_name = request.POST.get('short_name', '').strip()
            conversion_factor = request.POST.get('conversion_factor')
            is_purchase_unit = request.POST.get('is_purchase_unit') == 'on'
            is_sale_unit = request.POST.get('is_sale_unit') == 'on'
            is_count_unit = request.POST.get('is_count_unit') == 'on'
            
            if name and conversion_factor:
                try:
                    factor = int(conversion_factor)
                    if factor >= 1:
                        UnitOfMeasure.objects.create(
                            product=product,
                            name=name,
                            short_name=short_name or name[:10],
                            conversion_factor=factor,
                            is_purchase_unit=is_purchase_unit,
                            is_sale_unit=is_sale_unit,
                            is_count_unit=is_count_unit,
                        )
                        messages.success(request, f'Enhet "{name}" opprettet')
                except ValueError:
                    messages.error(request, 'Ugyldig konverteringsfaktor')
                except Exception as e:
                    messages.error(request, f'Kunne ikke opprette enhet: {e}')
            else:
                messages.error(request, 'Navn og konverteringsfaktor er påkrevd')
        
        elif action == 'delete_unit':
            unit_id = request.POST.get('unit_id')
            try:
                unit = UnitOfMeasure.objects.get(id=unit_id, product=product)
                unit_name = unit.name
                unit.delete()
                messages.success(request, f'Enhet "{unit_name}" slettet')
            except UnitOfMeasure.DoesNotExist:
                messages.error(request, 'Enheten finnes ikke')
        
        elif action == 'update_unit':
            unit_id = request.POST.get('unit_id')
            try:
                unit = UnitOfMeasure.objects.get(id=unit_id, product=product)
                unit.name = request.POST.get(f'name_{unit_id}', unit.name)
                unit.short_name = request.POST.get(f'short_name_{unit_id}', unit.short_name)
                unit.conversion_factor = int(request.POST.get(f'factor_{unit_id}', unit.conversion_factor))
                unit.is_purchase_unit = request.POST.get(f'purchase_{unit_id}') == 'on'
                unit.is_sale_unit = request.POST.get(f'sale_{unit_id}') == 'on'
                unit.is_count_unit = request.POST.get(f'count_{unit_id}') == 'on'
                unit.save()
                messages.success(request, f'Enhet "{unit.name}" oppdatert')
            except (UnitOfMeasure.DoesNotExist, ValueError) as e:
                messages.error(request, f'Kunne ikke oppdatere enhet: {e}')
        
        elif action == 'create_defaults':
            # Opprett standardenheter basert på base_unit_type
            from .unit_conversion import create_default_units_for_liquid, create_default_units_for_bottles
            
            try:
                if product.base_unit_type in ('ml', 'cl'):
                    # Sjekk om det er øl (artikkelgruppe 04007) eller vin (04008)
                    if product.betala_article_group_id == '04008':  # Vin
                        units = create_default_units_for_bottles(product)
                    else:  # Øl eller annen væske
                        units = create_default_units_for_liquid(product)
                    
                    if units:
                        messages.success(request, f'Opprettet {len(units)} standardenheter')
                    else:
                        messages.info(request, 'Standardenheter finnes allerede')
                else:
                    messages.warning(request, 'Standardenheter kun tilgjengelig for væsker (ml/cl)')
            except Exception as e:
                messages.error(request, f'Kunne ikke opprette standardenheter: {e}')
        
        return redirect('inventory:product_units', betala_id=betala_id)
    
    units = product.units.all().order_by('sort_order', '-conversion_factor')
    
    context = {
        'product': product,
        'units': units,
    }
    return render(request, 'inventory/product_units.html', context)


# =============================================================================
# LAGERBEHOLDNING
# =============================================================================

@login_required
def stock_level_list(request):
    """Oversikt over lagerbeholdning."""
    event = get_active_event(request)
    
    if not event:
        messages.warning(request, 'Velg et event for å se lagerbeholdning')
        return redirect('inventory:dashboard')
    
    stock_levels = StockLevel.objects.filter(
        event=event
    ).select_related('product', 'product__category').order_by(
        'product__category__sort_order', 'product__name'
    )
    
    # Gruppert etter kategori
    by_category = {}
    for sl in stock_levels:
        cat_name = sl.product.category.name if sl.product.category else 'Uten kategori'
        if cat_name not in by_category:
            by_category[cat_name] = []
        by_category[cat_name].append(sl)
    
    context = {
        'event': event,
        'stock_levels': stock_levels,
        'by_category': by_category,
    }
    return render(request, 'inventory/stock_level_list.html', context)


@login_required
def low_stock_alert(request):
    """Produkter med lav beholdning."""
    event = get_active_event(request)
    
    if not event:
        messages.warning(request, 'Velg et event for å se lav beholdning')
        return redirect('inventory:dashboard')
    
    # Finn produkter under minimumsnivå
    low_stock = StockLevel.objects.filter(
        event=event
    ).select_related('product', 'product__supplier').annotate(
        min_level=F('product__min_stock_level'),
        shortage=F('product__min_stock_level') - F('quantity')
    ).filter(quantity__lte=F('min_level')).order_by('-shortage')
    
    context = {
        'event': event,
        'low_stock': low_stock,
    }
    return render(request, 'inventory/low_stock_alert.html', context)


# =============================================================================
# VAREMOTTAK
# =============================================================================

@login_required
def receiving_list(request):
    """Liste over varemottak."""
    event = get_active_event(request)
    
    orders = ReceivingOrder.objects.select_related(
        'event', 'supplier', 'received_by'
    ).order_by('-received_date')
    
    if event:
        orders = orders.filter(event=event)
    
    paginator = Paginator(orders, 20)
    page = request.GET.get('page', 1)
    orders = paginator.get_page(page)
    
    context = {
        'orders': orders,
        'event': event,
    }
    return render(request, 'inventory/receiving_list.html', context)


@login_required
def receiving_create(request):
    """Opprett nytt varemottak."""
    event = get_active_event(request)
    org_id = get_active_organization_id(request)
    
    if request.method == 'POST':
        form = ReceivingOrderForm(request.POST, organization_id=org_id)
        formset = get_receiving_line_formset(organization_id=org_id, data=request.POST)
        
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                order = form.save(commit=False)
                order.received_by = request.user
                order.status = ReceivingOrder.Status.RECEIVED
                order.save()
                
                formset.instance = order
                lines = formset.save()
                
                # Opprett lagertransaksjoner og oppdater innkjøpspris
                for line in lines:
                    if line.quantity_received > 0:
                        stock_tx = StockTransaction.objects.create(
                            product=line.product,
                            event=order.event,
                            transaction_type=StockTransaction.TransactionType.RECEIVING,
                            quantity=line.quantity_received,
                            unit_cost_ore=line.unit_cost_ore,
                            supplier=order.supplier,
                            delivery_note=order.delivery_note,
                            reference=f"Mottak #{order.pk}",
                            created_by=request.user
                        )
                        line.stock_transaction = stock_tx
                        line.save()
                        
                        # Oppdater innkjøpspris (eks mva) på produktet
                        if line.unit_cost_ore:
                            line.product.purchase_price_ore = line.unit_cost_ore
                            line.product.save(update_fields=['purchase_price_ore', 'updated_at'])
                
                messages.success(request, f'Varemottak #{order.pk} er registrert')
                return redirect('inventory:receiving_detail', pk=order.pk)
    else:
        form = ReceivingOrderForm(initial={'event': event}, organization_id=org_id)
        formset = get_receiving_line_formset(organization_id=org_id)
    
    context = {
        'form': form,
        'formset': formset,
        'event': event,
    }
    return render(request, 'inventory/receiving_form.html', context)


@login_required
def receiving_detail(request, pk):
    """Detaljer for varemottak."""
    order = get_object_or_404(ReceivingOrder, pk=pk)
    lines = order.lines.select_related('product')
    
    context = {
        'order': order,
        'lines': lines,
    }
    return render(request, 'inventory/receiving_detail.html', context)


# =============================================================================
# SVINN
# =============================================================================

@login_required
def shrinkage_list(request):
    """Liste over registrert svinn."""
    event = get_active_event(request)
    org_id = get_active_organization_id(request)
    
    entries = ShrinkageEntry.objects.select_related(
        'product', 'event', 'registered_by'
    ).order_by('-registered_date')
    
    # Filtrer på event eller organisasjon
    if event:
        entries = entries.filter(event=event)
    elif org_id:
        entries = entries.filter(event__betala_organization_id=org_id)
    
    # Statistikk
    stats = entries.aggregate(
        total_count=Count('id'),
        total_quantity=Sum('quantity')
    )
    
    paginator = Paginator(entries, 30)
    page = request.GET.get('page', 1)
    entries = paginator.get_page(page)
    
    context = {
        'entries': entries,
        'stats': stats,
        'event': event,
    }
    return render(request, 'inventory/shrinkage_list.html', context)


@login_required
def shrinkage_create(request):
    """Registrer nytt svinn."""
    event = get_active_event(request)
    org_id = get_active_organization_id(request)
    
    if request.method == 'POST':
        form = ShrinkageEntryForm(request.POST, organization_id=org_id)
        
        if form.is_valid():
            with transaction.atomic():
                entry = form.save(commit=False)
                entry.registered_by = request.user
                # Lås inn estimert tap ved registrering
                entry.recorded_loss_ore = entry.calculate_loss_ore()
                entry.save()
                
                # Opprett lagertransaksjon (negativ)
                tx_type = StockTransaction.TransactionType.SHRINKAGE
                if entry.reason in ['STAFF', 'TASTING']:
                    tx_type = StockTransaction.TransactionType.STAFF_CONSUMPTION
                elif entry.reason == 'BREAKAGE':
                    tx_type = StockTransaction.TransactionType.WASTE
                
                stock_tx = StockTransaction.objects.create(
                    product=entry.product,
                    event=entry.event,
                    transaction_type=tx_type,
                    quantity=-entry.quantity,
                    location=entry.location,
                    notes=f"{entry.get_reason_display()}: {entry.notes}",
                    created_by=request.user
                )
                entry.stock_transaction = stock_tx
                entry.save()
                
                messages.warning(
                    request,
                    f'Svinn registrert: {entry.quantity} x {entry.product.name}'
                )
                return redirect('inventory:shrinkage_list')
    else:
        form = ShrinkageEntryForm(initial={'event': event}, organization_id=org_id)
    
    context = {
        'form': form,
        'event': event,
    }
    return render(request, 'inventory/shrinkage_form.html', context)


# =============================================================================
# VARETELLING
# =============================================================================

@login_required
def stock_count_list(request):
    """Liste over varetelinger (kun hovedtellinger)."""
    event = get_active_event(request)
    
    # Vis kun hovedtellinger (ikke deltellinger)
    counts = StockCount.objects.filter(
        parent_count__isnull=True
    ).select_related(
        'event', 'started_by', 'completed_by'
    ).prefetch_related('partial_counts').order_by('-started_at')
    
    if event:
        counts = counts.filter(event=event)
    
    context = {
        'counts': counts,
        'event': event,
    }
    return render(request, 'inventory/stock_count_list.html', context)


@login_required
def stock_count_create(request):
    """Start ny varetelling."""
    event = get_active_event(request)
    org_id = get_active_organization_id(request)
    
    if request.method == 'POST':
        form = StockCountForm(request.POST, organization_id=org_id)
        
        if form.is_valid():
            count = form.save(commit=False)
            count.started_by = request.user
            count.save()
            
            # Hent alle produkter for organisasjonen (ikke pakker)
            products = Product.objects.filter(is_active=True).exclude(betala_is_bundles=True)
            if count.event and count.event.betala_organization_id:
                products = products.filter(betala_organization_id=count.event.betala_organization_id)
            
            # Hent eksisterende lagernivåer for eventet
            stock_levels = {
                sl.product_id: sl.quantity 
                for sl in StockLevel.objects.filter(event=count.event)
            }
            
            # Opprett linjer for alle produkter
            lines_created = 0
            for product in products:
                expected_qty = stock_levels.get(product.id, 0)
                StockCountLine.objects.create(
                    stock_count=count,
                    product=product,
                    expected_quantity=expected_qty
                )
                lines_created += 1
            
            messages.success(
                request,
                f'Varetelling startet med {lines_created} produkter'
            )
            return redirect('inventory:stock_count_detail', pk=count.pk)
    else:
        form = StockCountForm(initial={'event': event}, organization_id=org_id)
    
    context = {
        'form': form,
        'event': event,
    }
    return render(request, 'inventory/stock_count_form.html', context)


@login_required
def stock_count_detail(request, pk):
    """Utfør varetelling."""
    count = get_object_or_404(StockCount, pk=pk)
    lines = count.lines.select_related('product', 'product__category', 'unit').order_by(
        'product__category__sort_order', 'product__name'
    )
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'save_counts':
            # Lagre telletall
            for line in lines:
                counted = request.POST.get(f'counted_{line.pk}')
                unit_id = request.POST.get(f'unit_{line.pk}')
                
                if counted:
                    counted_value = float(counted.replace(',', '.'))
                    
                    # Hent enhet og konverter til base-enhet
                    unit = None
                    if unit_id:
                        try:
                            from inventory.models import UnitOfMeasure
                            unit = UnitOfMeasure.objects.get(pk=unit_id, product=line.product)
                            # Konverter til base-enhet
                            counted_value = int(counted_value * unit.conversion_factor)
                        except UnitOfMeasure.DoesNotExist:
                            counted_value = int(counted_value)
                    else:
                        counted_value = int(counted_value)
                    
                    line.counted_quantity = counted_value
                    line.unit = unit
                    line.counted_by = request.user
                    line.counted_at = timezone.now()
                    line.save()
            
            messages.success(request, 'Telletall lagret')
        
        elif action == 'share':
            # Del telling - lagre og marker som tilgjengelig for import
            # Lagre telletall først
            for line in lines:
                counted = request.POST.get(f'counted_{line.pk}')
                unit_id = request.POST.get(f'unit_{line.pk}')
                
                if counted:
                    counted_value = float(counted.replace(',', '.'))
                    
                    # Hent enhet og konverter til base-enhet
                    unit = None
                    if unit_id:
                        try:
                            from inventory.models import UnitOfMeasure
                            unit = UnitOfMeasure.objects.get(pk=unit_id, product=line.product)
                            counted_value = int(counted_value * unit.conversion_factor)
                        except UnitOfMeasure.DoesNotExist:
                            counted_value = int(counted_value)
                    else:
                        counted_value = int(counted_value)
                    
                    line.counted_quantity = counted_value
                    line.unit = unit
                    line.counted_by = request.user
                    line.counted_at = timezone.now()
                    line.save()
            
            count.status = StockCount.Status.COMPLETED
            count.completed_at = timezone.now()
            count.completed_by = request.user
            count.save()
            
            messages.success(request, f'Telling "{count.name}" lagret og delt! Kan nå importeres til en hovedtelling.')
            return redirect('inventory:stock_count_list')
        
        elif action == 'finalize':
            # For deltelling som allerede er importert - ikke tillat
            if count.is_partial and count.is_imported:
                messages.error(request, 'Denne tellingen er allerede importert')
                return redirect('inventory:stock_count_detail', pk=count.parent_count.pk)
            
            # For deltelling - marker som fullført (ikke opprett justeringer)
            if count.is_partial:
                count.status = StockCount.Status.COMPLETED
                count.completed_at = timezone.now()
                count.completed_by = request.user
                count.save()
                messages.success(request, f'Deltelling "{count.name}" fullført og klar for import')
                return redirect('inventory:stock_count_detail', pk=count.parent_count.pk)
            
            # For hovedtelling - fullfør telling og opprett justeringer
            with transaction.atomic():
                for line in lines:
                    if line.counted_quantity is not None and line.variance != 0:
                        stock_tx = StockTransaction.objects.create(
                            product=line.product,
                            event=count.event,
                            transaction_type=StockTransaction.TransactionType.COUNT,
                            quantity=line.variance,
                            reference=f"Varetelling #{count.pk}",
                            notes=f"Forventet: {line.expected_quantity}, Talt: {line.counted_quantity}",
                            created_by=request.user
                        )
                        line.stock_transaction = stock_tx
                        line.save()
                
                count.status = StockCount.Status.COMPLETED
                count.completed_at = timezone.now()
                count.completed_by = request.user
                count.save()
            
            messages.success(request, 'Varetelling fullført og lagerbeholdning oppdatert')
            return redirect('inventory:stock_count_list')
    
    # Statistikk
    counted = lines.filter(counted_quantity__isnull=False).count()
    total = lines.count()
    
    # Prefetch telleenheter for alle produkter
    from django.db.models import Prefetch
    from inventory.models import UnitOfMeasure
    lines = lines.prefetch_related(
        Prefetch(
            'product__units',
            queryset=UnitOfMeasure.objects.filter(is_count_unit=True).order_by('-conversion_factor'),
            to_attr='count_units_list'
        )
    )
    
    # Hent importerte deltellinger for denne tellingen
    imported_partials = []
    if not count.is_partial:
        imported_partials = count.partial_counts.select_related(
            'started_by', 'completed_by'
        ).order_by('-started_at')
    
    # Hent tilgjengelige tellinger som kan importeres (fullførte uten parent, samme event)
    available_for_import = []
    if not count.is_partial and count.status == StockCount.Status.IN_PROGRESS:
        available_for_import = StockCount.objects.filter(
            event=count.event,
            status=StockCount.Status.COMPLETED,
            parent_count__isnull=True
        ).exclude(pk=count.pk).select_related('started_by', 'completed_by').order_by('-completed_at')
    
    context = {
        'count': count,
        'lines': lines,
        'counted': counted,
        'total': total,
        'progress': (counted / total * 100) if total > 0 else 0,
        'partial_counts': imported_partials,
        'available_for_import': available_for_import,
    }
    return render(request, 'inventory/stock_count_detail.html', context)


@login_required
def stock_count_delete(request, pk):
    """Slett en varetelling."""
    count = get_object_or_404(StockCount, pk=pk)
    
    # Kan ikke slette importerte tellinger
    if count.is_imported:
        messages.error(request, 'Kan ikke slette importert telling')
        return redirect('inventory:stock_count_list')
    
    # Kan ikke slette fullførte hovedtellinger (har oppdatert lager)
    if count.status == StockCount.Status.COMPLETED and count.lines.filter(stock_transaction__isnull=False).exists():
        messages.error(request, 'Kan ikke slette fullført telling som har oppdatert lagerbeholdning')
        return redirect('inventory:stock_count_list')
    
    if request.method == 'POST':
        name = count.name
        count.delete()
        messages.success(request, f'Telling "{name}" slettet')
    
    return redirect('inventory:stock_count_list')


@login_required
def import_partial_counts(request, pk):
    """Importer valgte tellinger til hovedtelling."""
    main_count = get_object_or_404(StockCount, pk=pk)
    
    if main_count.is_partial:
        messages.error(request, 'Kan kun importere til hovedtelling')
        return redirect('inventory:stock_count_detail', pk=pk)
    
    if main_count.status != StockCount.Status.IN_PROGRESS:
        messages.error(request, 'Hovedtellingen er ikke aktiv')
        return redirect('inventory:stock_count_detail', pk=pk)
    
    if request.method == 'POST':
        # Hent valgte tellinger fra form
        selected_ids = request.POST.getlist('import_counts')
        
        if not selected_ids:
            messages.warning(request, 'Ingen tellinger valgt for import')
            return redirect('inventory:stock_count_detail', pk=pk)
        
        # Hent tellinger som kan importeres (fullført, uten parent, samme event)
        partials_to_import = StockCount.objects.filter(
            pk__in=selected_ids,
            event=main_count.event,
            status=StockCount.Status.COMPLETED,
            parent_count__isnull=True
        ).exclude(pk=main_count.pk)
        
        if not partials_to_import.exists():
            messages.warning(request, 'Ingen gyldige tellinger å importere')
            return redirect('inventory:stock_count_detail', pk=pk)
        
        with transaction.atomic():
            # For hver hovedlinje, summer antall fra alle deltellinger
            main_lines = {line.product_id: line for line in main_count.lines.all()}
            
            for partial in partials_to_import:
                for partial_line in partial.lines.filter(counted_quantity__isnull=False):
                    if partial_line.product_id in main_lines:
                        main_line = main_lines[partial_line.product_id]
                        if main_line.counted_quantity is None:
                            main_line.counted_quantity = 0
                        main_line.counted_quantity += partial_line.counted_quantity
                        main_line.counted_by = request.user
                        main_line.counted_at = timezone.now()
                        main_line.save()
                
                # Koble deltelling til hovedtelling og marker som importert
                partial.parent_count = main_count
                partial.status = StockCount.Status.IMPORTED
                partial.save()
        
        messages.success(request, f'{partials_to_import.count()} telling(er) importert til hovedtellingen')
    
    return redirect('inventory:stock_count_detail', pk=pk)


@login_required
def stock_count_mobile(request, pk):
    """Mobilvennlig varetelling med strekkodeskanning."""
    count = get_object_or_404(StockCount, pk=pk)
    
    if count.status != StockCount.Status.IN_PROGRESS:
        messages.error(request, 'Denne tellingen er ikke aktiv')
        return redirect('inventory:stock_count_detail', pk=pk)
    
    org_id = get_active_organization_id(request)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'count_product':
            # Registrer telling for et produkt (via strekkode eller manuelt valg)
            product_id = request.POST.get('product_id')
            counted_quantity = request.POST.get('counted_quantity')
            unit_id = request.POST.get('unit_id')
            mode = request.POST.get('mode', 'add')  # 'add' eller 'replace'
            
            if product_id and counted_quantity:
                try:
                    product = Product.objects.get(pk=product_id)
                    
                    # Konverter til base-enhet hvis enhet er valgt
                    counted_value = float(counted_quantity.replace(',', '.'))
                    unit = None
                    if unit_id:
                        try:
                            unit = UnitOfMeasure.objects.get(pk=unit_id, product=product)
                            counted_value = int(counted_value * unit.conversion_factor)
                        except UnitOfMeasure.DoesNotExist:
                            counted_value = int(counted_value)
                    else:
                        counted_value = int(counted_value)
                    
                    # Finn eller opprett linje i tellingen
                    line, created = count.lines.get_or_create(
                        product=product,
                        defaults={
                            'expected_quantity': StockLevel.objects.filter(
                                product=product, event=count.event
                            ).aggregate(total=Sum('quantity'))['total'] or 0
                        }
                    )
                    
                    # Legg til eller erstatt
                    if mode == 'add' and not created and line.counted_quantity is not None:
                        line.counted_quantity += counted_value
                    else:
                        line.counted_quantity = counted_value
                    
                    line.unit = unit
                    line.counted_by = request.user
                    line.counted_at = timezone.now()
                    line.save()
                    
                    # Formater visning av registrert antall
                    display_quantity = counted_quantity
                    if unit:
                        display_quantity = f"{counted_quantity} {unit.name}"
                    
                    return JsonResponse({
                        'success': True,
                        'product_name': product.name,
                        'counted': display_quantity,
                        'new_total': line.counted_quantity,
                        'is_new_product': created,
                        'message': f'{product.name}: {display_quantity} {"lagt til" if mode == "add" else "registrert"} (totalt: {line.counted_quantity})'
                    })
                except Product.DoesNotExist:
                    return JsonResponse({'success': False, 'error': 'Produktet finnes ikke'})
                except Exception as e:
                    return JsonResponse({'success': False, 'error': str(e)})
        
        elif action == 'delete_line':
            # Slett en tellelinje
            product_id = request.POST.get('product_id')
            if product_id:
                try:
                    line = count.lines.get(product_id=product_id)
                    product_name = line.product.name
                    line.delete()
                    return JsonResponse({
                        'success': True,
                        'message': f'{product_name} slettet fra tellingen'
                    })
                except count.lines.model.DoesNotExist:
                    return JsonResponse({'success': False, 'error': 'Fant ikke linjen'})
                except Exception as e:
                    return JsonResponse({'success': False, 'error': str(e)})
        
        elif action == 'lookup_barcode':
            # Søk etter produkt via strekkode
            barcode = request.POST.get('barcode', '').strip()
            
            if not barcode:
                return JsonResponse({'success': False, 'error': 'Ingen strekkode oppgitt'})
            
            # Søk i organisasjonens produkter
            products = Product.objects.filter(
                barcode=barcode,
                is_active=True
            )
            if org_id:
                products = products.filter(betala_organization_id=org_id)
            
            product = products.first()
            
            if product:
                # Sjekk om produktet allerede er talt
                existing_line = count.lines.filter(product=product).first()
                existing_count = existing_line.counted_quantity if existing_line else None
                
                # Hent telleenheter for produktet
                count_units = []
                if product.use_unit_conversion:
                    for unit in product.units.filter(is_count_unit=True).order_by('-conversion_factor'):
                        count_units.append({
                            'id': unit.pk,
                            'name': unit.name,
                            'conversion_factor': unit.conversion_factor
                        })
                
                return JsonResponse({
                    'success': True,
                    'product': {
                        'id': product.pk,
                        'name': product.name,
                        'sku': product.sku,
                        'barcode': product.barcode,
                        'category': product.category.name if product.category else None,
                        'existing_count': existing_count,
                        'use_unit_conversion': product.use_unit_conversion,
                        'base_unit_type': product.base_unit_type,
                        'count_units': count_units
                    }
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': f'Fant ikke produkt med strekkode: {barcode}'
                })
    
    # Hent statistikk
    lines = count.lines.select_related('product', 'product__category')
    counted = lines.filter(counted_quantity__isnull=False).count()
    total = lines.count()
    
    # Hent siste talte produkter
    recent_counts = lines.filter(
        counted_quantity__isnull=False
    ).order_by('-counted_at')[:5]
    
    context = {
        'count': count,
        'counted': counted,
        'total': total,
        'progress': (counted / total * 100) if total > 0 else 0,
        'recent_counts': recent_counts,
    }
    return render(request, 'inventory/stock_count_mobile.html', context)


# =============================================================================
# TRANSAKSJONER
# =============================================================================

@login_required
def transaction_list(request):
    """Liste over alle lagertransaksjoner."""
    event = get_active_event(request)
    
    transactions = StockTransaction.objects.select_related(
        'product', 'event', 'created_by', 'supplier'
    ).order_by('-transaction_date')
    
    if event:
        transactions = transactions.filter(event=event)
    
    # Filter
    tx_type = request.GET.get('type')
    search = request.GET.get('search', '').strip()
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if tx_type:
        transactions = transactions.filter(transaction_type=tx_type)
    
    if search:
        transactions = transactions.filter(
            Q(product__name__icontains=search) |
            Q(reference__icontains=search)
        )
    
    if from_date:
        transactions = transactions.filter(transaction_date__date__gte=from_date)
    if to_date:
        transactions = transactions.filter(transaction_date__date__lte=to_date)
    
    # Gruppering av salg fra Betala
    view_mode = request.GET.get('view', 'grouped')  # 'grouped' eller 'flat'
    
    if view_mode == 'grouped':
        # Grupper salg etter betala_sequence_number
        from itertools import groupby
        from collections import defaultdict
        
        all_transactions = list(transactions[:500])  # Begrens for ytelse
        
        grouped_sales = defaultdict(list)
        other_transactions = []
        
        for tx in all_transactions:
            if tx.transaction_type == 'SALE' and tx.betala_sequence_number:
                grouped_sales[tx.betala_sequence_number].append(tx)
            else:
                other_transactions.append(tx)
        
        # Konverter til liste med gruppeinformasjon
        sale_groups = []
        for seq_num, txs in sorted(grouped_sales.items(), key=lambda x: x[1][0].transaction_date, reverse=True):
            sale_groups.append({
                'sequence_number': seq_num,
                'transactions': txs,
                'total_items': sum(abs(t.quantity) for t in txs),
                'product_count': len(txs),
                'transaction_date': txs[0].transaction_date,
            })
        
        context = {
            'sale_groups': sale_groups,
            'other_transactions': other_transactions,
            'event': event,
            'transaction_types': StockTransaction.TransactionType.choices,
            'selected_type': tx_type,
            'view_mode': view_mode,
        }
    else:
        # Flat visning (som før)
        paginator = Paginator(transactions, 50)
        page = request.GET.get('page', 1)
        transactions = paginator.get_page(page)
        
        context = {
            'transactions': transactions,
            'event': event,
            'transaction_types': StockTransaction.TransactionType.choices,
            'selected_type': tx_type,
            'view_mode': view_mode,
        }
    
    return render(request, 'inventory/transaction_list.html', context)


# =============================================================================
# LEVERANDØRER
# =============================================================================

@login_required
def supplier_list(request):
    """Liste over alle leverandører."""
    suppliers = Supplier.objects.filter(is_active=True).annotate(
        products_count=Count('products')
    ).order_by('name')
    
    context = {
        'suppliers': suppliers,
    }
    return render(request, 'inventory/supplier_list.html', context)


@login_required
def supplier_create(request):
    """Opprett ny leverandør."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        contact_person = request.POST.get('contact_person', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        if name:
            supplier = Supplier.objects.create(
                name=name,
                contact_person=contact_person,
                email=email,
                phone=phone
            )
            messages.success(request, f'Leverandør "{supplier.name}" opprettet')
            return redirect('inventory:supplier_list')
        else:
            messages.error(request, 'Navn er påkrevd')
    
    return render(request, 'inventory/supplier_form.html', {'supplier': None})


@login_required
def supplier_edit(request, pk):
    """Rediger leverandør."""
    supplier = get_object_or_404(Supplier, pk=pk)
    
    if request.method == 'POST':
        supplier.name = request.POST.get('name', '').strip()
        supplier.contact_person = request.POST.get('contact_person', '').strip()
        supplier.email = request.POST.get('email', '').strip()
        supplier.phone = request.POST.get('phone', '').strip()
        supplier.address = request.POST.get('address', '').strip()
        supplier.notes = request.POST.get('notes', '').strip()
        
        if supplier.name:
            supplier.save()
            messages.success(request, f'Leverandør "{supplier.name}" oppdatert')
            return redirect('inventory:supplier_list')
        else:
            messages.error(request, 'Navn er påkrevd')
    
    return render(request, 'inventory/supplier_form.html', {'supplier': supplier})


# =============================================================================
# EVENTS
# =============================================================================

@login_required
def event_list(request):
    """Liste over alle events."""
    events = Event.objects.annotate(
        products_count=Count('stock_levels__product', distinct=True),
        transactions_count=Count('transactions')
    ).order_by('-start_date')
    
    context = {
        'events': events,
    }
    return render(request, 'inventory/event_list.html', context)


@login_required
def event_detail(request, pk):
    """Event detaljer og statistikk."""
    event = get_object_or_404(Event, pk=pk)
    
    # Statistikk
    stock_stats = StockLevel.objects.filter(event=event).aggregate(
        total_items=Sum('quantity'),
        product_count=Count('id')
    )
    
    transaction_stats = StockTransaction.objects.filter(event=event).values(
        'transaction_type'
    ).annotate(count=Count('id'), total_qty=Sum('quantity'))
    
    context = {
        'event': event,
        'stock_stats': stock_stats,
        'transaction_stats': transaction_stats,
    }
    return render(request, 'inventory/event_detail.html', context)


# =============================================================================
# INNKJØPSORDRE
# =============================================================================

@login_required
def purchase_order_list(request):
    """Liste over innkjøpsordrer."""
    event = get_active_event(request)
    
    orders = PurchaseOrder.objects.select_related(
        'event', 'supplier', 'created_by'
    ).order_by('-created_at')
    
    if event:
        orders = orders.filter(event=event)
    
    # Filter på status
    status = request.GET.get('status')
    if status:
        orders = orders.filter(status=status)
    
    paginator = Paginator(orders, 20)
    page = request.GET.get('page', 1)
    orders = paginator.get_page(page)
    
    context = {
        'orders': orders,
        'event': event,
        'status_choices': PurchaseOrder.Status.choices,
        'selected_status': status,
    }
    return render(request, 'inventory/purchase_order_list.html', context)


@login_required
def purchase_order_create(request):
    """Opprett ny innkjøpsordre."""
    event = get_active_event(request)
    org_id = get_active_organization_id(request)
    
    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, organization_id=org_id)
        formset = get_purchase_order_line_formset(organization_id=org_id, data=request.POST)
        
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                order = form.save(commit=False)
                order.created_by = request.user
                order.save()
                
                formset.instance = order
                formset.save()
                
                messages.success(request, f'Innkjøpsordre {order.order_number} er opprettet')
                return redirect('inventory:purchase_order_detail', pk=order.pk)
    else:
        form = PurchaseOrderForm(initial={'event': event}, organization_id=org_id)
        formset = get_purchase_order_line_formset(organization_id=org_id)
    
    context = {
        'form': form,
        'formset': formset,
        'event': event,
    }
    return render(request, 'inventory/purchase_order_form.html', context)


@login_required
def purchase_order_detail(request, pk):
    """Detaljer for innkjøpsordre."""
    order = get_object_or_404(PurchaseOrder, pk=pk)
    lines = order.lines.select_related('product')
    
    # Hent relaterte varemottak
    receiving_orders = order.receiving_orders.all()
    
    context = {
        'order': order,
        'lines': lines,
        'receiving_orders': receiving_orders,
    }
    return render(request, 'inventory/purchase_order_detail.html', context)


@login_required
def purchase_order_edit(request, pk):
    """Rediger innkjøpsordre."""
    order = get_object_or_404(PurchaseOrder, pk=pk)
    org_id = get_active_organization_id(request)
    
    # Kan ikke redigere fullførte eller kansellerte ordre
    if order.status in [PurchaseOrder.Status.FULLY_RECEIVED, PurchaseOrder.Status.CANCELLED]:
        messages.error(request, 'Kan ikke redigere denne ordren')
        return redirect('inventory:purchase_order_detail', pk=pk)
    
    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, instance=order, organization_id=org_id)
        formset = get_purchase_order_line_formset(organization_id=org_id, data=request.POST, instance=order)
        
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
                
                messages.success(request, f'Innkjøpsordre {order.order_number} er oppdatert')
                return redirect('inventory:purchase_order_detail', pk=order.pk)
    else:
        form = PurchaseOrderForm(instance=order, organization_id=org_id)
        formset = get_purchase_order_line_formset(organization_id=org_id, instance=order)
    
    context = {
        'form': form,
        'formset': formset,
        'order': order,
    }
    return render(request, 'inventory/purchase_order_form.html', context)


@login_required
def purchase_order_mark_ordered(request, pk):
    """Merk innkjøpsordre som bestilt."""
    order = get_object_or_404(PurchaseOrder, pk=pk)
    
    if order.status == PurchaseOrder.Status.DRAFT:
        order.status = PurchaseOrder.Status.ORDERED
        order.order_date = timezone.now().date()
        order.save()
        messages.success(request, f'Innkjøpsordre {order.order_number} er merket som bestilt')
    
    return redirect('inventory:purchase_order_detail', pk=pk)


@login_required
def purchase_order_cancel(request, pk):
    """Kanseller innkjøpsordre."""
    order = get_object_or_404(PurchaseOrder, pk=pk)
    
    if order.status not in [PurchaseOrder.Status.FULLY_RECEIVED, PurchaseOrder.Status.CANCELLED]:
        order.status = PurchaseOrder.Status.CANCELLED
        order.save()
        messages.warning(request, f'Innkjøpsordre {order.order_number} er kansellert')
    
    return redirect('inventory:purchase_order_detail', pk=pk)


@login_required
def purchase_order_close(request, pk):
    """Lukk innkjøpsordre - merk som fullført selv om ikke alt er mottatt."""
    order = get_object_or_404(PurchaseOrder, pk=pk)
    
    if order.status == PurchaseOrder.Status.PARTIALLY_RECEIVED:
        # Beregn gjenstående før vi justerer
        remaining = order.total_ordered - order.total_received
        
        # Juster bestilt antall ned til mottatt antall på hver linje
        for line in order.lines.all():
            if line.quantity_received < line.quantity_ordered:
                line.quantity_ordered = line.quantity_received
                line.save()
        
        order.status = PurchaseOrder.Status.FULLY_RECEIVED
        order.save()
        
        messages.success(
            request, 
            f'Innkjøpsordre {order.order_number} er avsluttet. '
            f'{remaining} gjenstående enheter er fjernet fra bestillingen.'
        )
    
    return redirect('inventory:purchase_order_detail', pk=pk)


@login_required
def purchase_order_receive(request, pk):
    """Motta varer fra innkjøpsordre (delmottak støttet)."""
    order = get_object_or_404(PurchaseOrder, pk=pk)
    
    # Kan ikke motta fra kansellerte eller fullstendig mottatte ordre
    if order.status in [PurchaseOrder.Status.CANCELLED, PurchaseOrder.Status.FULLY_RECEIVED]:
        messages.error(request, 'Kan ikke motta fra denne ordren')
        return redirect('inventory:purchase_order_detail', pk=pk)
    
    lines = order.lines.select_related('product')
    
    if request.method == 'POST':
        form = ReceiveFromPurchaseOrderForm(request.POST)
        
        if form.is_valid():
            with transaction.atomic():
                # Opprett varemottak
                receiving_order = ReceivingOrder.objects.create(
                    event=order.event,
                    supplier=order.supplier,
                    purchase_order=order,
                    order_number=order.order_number,
                    delivery_note=form.cleaned_data.get('delivery_note', ''),
                    received_date=form.cleaned_data['received_date'],
                    received_by=request.user,
                    status=ReceivingOrder.Status.RECEIVED,
                    notes=form.cleaned_data.get('notes', '')
                )
                
                items_received = 0
                
                # Behandle hver linje
                for line in lines:
                    qty_field = f'qty_{line.pk}'
                    batch_field = f'batch_{line.pk}'
                    expiry_field = f'expiry_{line.pk}'
                    
                    qty_received = request.POST.get(qty_field, '')
                    if qty_received and int(qty_received) > 0:
                        qty_received = int(qty_received)
                        
                        # Opprett varemottakslinje
                        receiving_line = ReceivingOrderLine.objects.create(
                            receiving_order=receiving_order,
                            product=line.product,
                            purchase_order_line=line,
                            quantity_expected=line.remaining_quantity,
                            quantity_received=qty_received,
                            unit_cost_ore=line.unit_cost_ore,
                            batch_number=request.POST.get(batch_field, ''),
                            expiry_date=request.POST.get(expiry_field) or None
                        )
                        
                        # Opprett lagertransaksjon
                        stock_tx = StockTransaction.objects.create(
                            product=line.product,
                            event=order.event,
                            transaction_type=StockTransaction.TransactionType.RECEIVING,
                            quantity=qty_received,
                            unit_cost_ore=line.unit_cost_ore,
                            supplier=order.supplier,
                            delivery_note=receiving_order.delivery_note,
                            reference=f"PO-{order.order_number} / Mottak #{receiving_order.pk}",
                            created_by=request.user
                        )
                        receiving_line.stock_transaction = stock_tx
                        receiving_line.save()
                        
                        # Oppdater mottatt antall på innkjøpsordrelinjen
                        line.quantity_received += qty_received
                        line.save()
                        
                        items_received += qty_received
                
                # Oppdater status på innkjøpsordren
                order.update_status()
                
                if items_received > 0:
                    messages.success(
                        request, 
                        f'Mottatt {items_received} enheter. Varemottak #{receiving_order.pk} opprettet.'
                    )
                else:
                    # Slett tom varemottak
                    receiving_order.delete()
                    messages.warning(request, 'Ingen varer ble mottatt')
                
                return redirect('inventory:purchase_order_detail', pk=pk)
    else:
        form = ReceiveFromPurchaseOrderForm()
    
    context = {
        'order': order,
        'lines': lines,
        'form': form,
    }
    return render(request, 'inventory/purchase_order_receive.html', context)
