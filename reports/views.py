"""
Rapportviews for lagersystemet.
"""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum, Count, F, Q
from django.utils import timezone

from inventory.models import (
    Product, Category, StockLevel, StockTransaction,
    ShrinkageEntry, Event, BetalaTransactionSync
)
from inventory.views import get_active_event, get_active_organization_id
from .generators import InventoryExcelGenerator, TransactionExcelGenerator


def get_org_context(request):
    """Hent organisasjonskontekst for rapporter."""
    org_id = get_active_organization_id(request)
    org_name = request.session.get('betala_selected_org_name', '')
    event = get_active_event(request)
    return org_id, org_name, event


@login_required
def report_index(request):
    """Rapportoversikt."""
    org_id, org_name, event = get_org_context(request)
    
    context = {
        'event': event,
        'organization_name': org_name,
    }
    return render(request, 'reports/index.html', context)


@login_required
def daily_report(request):
    """Daglig rapport med alle aktiviteter."""
    org_id, org_name, event = get_org_context(request)
    report_date = request.GET.get('date')
    
    if report_date:
        try:
            report_date = date.fromisoformat(report_date)
        except ValueError:
            report_date = date.today()
    else:
        report_date = date.today()
    
    # Transaksjoner for dagen
    start = timezone.make_aware(
        timezone.datetime.combine(report_date, timezone.datetime.min.time())
    )
    end = start + timedelta(days=1)
    
    transactions = StockTransaction.objects.filter(
        transaction_date__gte=start,
        transaction_date__lt=end
    )
    if event:
        transactions = transactions.filter(event=event)
    transactions = transactions.select_related('product', 'created_by')
    
    # Statistikk per type
    by_type = transactions.values('transaction_type').annotate(
        count=Count('id'),
        total_qty=Sum('quantity')
    )
    
    # Top produkter solgt
    sales = transactions.filter(
        transaction_type=StockTransaction.TransactionType.SALE
    ).values('product__name').annotate(
        total_sold=Sum('quantity')
    ).order_by('total_sold')[:10]
    
    # Svinn
    shrinkage = transactions.filter(
        transaction_type__in=[
            StockTransaction.TransactionType.SHRINKAGE,
            StockTransaction.TransactionType.WASTE,
            StockTransaction.TransactionType.STAFF_CONSUMPTION
        ]
    )
    
    # Varemottak
    receiving = transactions.filter(
        transaction_type=StockTransaction.TransactionType.RECEIVING
    )
    
    # Betala-transaksjoner for dagen
    betala_transactions = []
    if event:
        betala_transactions = BetalaTransactionSync.objects.filter(
            event=event,
            finalized_at__gte=start,
            finalized_at__lt=end
        ).order_by('-finalized_at')
    
    context = {
        'event': event,
        'organization_name': org_name,
        'report_date': report_date,
        'transactions': transactions,
        'by_type': by_type,
        'top_sales': sales,
        'shrinkage': shrinkage,
        'receiving': receiving,
        'total_transactions': transactions.count(),
        'betala_transactions': betala_transactions,
    }
    return render(request, 'reports/daily_report.html', context)


@login_required
def shrinkage_report(request):
    """Svinnrapport."""
    org_id, org_name, event = get_org_context(request)
    
    # Tidsperiode
    days = int(request.GET.get('days', 7))
    start_date = date.today() - timedelta(days=days)
    
    entries = ShrinkageEntry.objects.filter(
        registered_date__gte=start_date
    )
    # Filtrer på event eller organisasjon
    if event:
        entries = entries.filter(event=event)
    elif org_id:
        entries = entries.filter(event__betala_organization_id=org_id)
    entries = entries.select_related('product', 'registered_by')
    
    # Aggregert per årsak - konverter koder til lesbare navn
    reason_choices = dict(ShrinkageEntry.ShrinkageReason.choices)
    by_reason_raw = entries.values('reason').annotate(
        count=Count('id'),
        total_qty=Sum('quantity')
    ).order_by('-total_qty')
    
    by_reason = []
    for item in by_reason_raw:
        by_reason.append({
            'reason': reason_choices.get(item['reason'], item['reason']),
            'count': item['count'],
            'total_qty': item['total_qty']
        })
    
    # Aggregert per produkt
    by_product = entries.values('product__name').annotate(
        count=Count('id'),
        total_qty=Sum('quantity')
    ).order_by('-total_qty')[:20]
    
    # Total verdi (estimert)
    total_value = 0
    for entry in entries:
        if entry.estimated_loss_ore:
            total_value += entry.estimated_loss_ore
    
    context = {
        'event': event,
        'organization_name': org_name,
        'entries': entries,
        'by_reason': by_reason,
        'by_product': by_product,
        'total_entries': entries.count(),
        'total_quantity': entries.aggregate(Sum('quantity'))['quantity__sum'] or 0,
        'total_value_kr': total_value / 100,
        'days': days,
        'start_date': start_date,
    }
    return render(request, 'reports/shrinkage_report.html', context)


@login_required
def inventory_report(request):
    """Beholdningsrapport - viser produkter med verdi."""
    org_id, org_name, event = get_org_context(request)
    
    # Hent produkter for organisasjonen
    products = Product.objects.filter(is_active=True)
    if org_id:
        products = products.filter(betala_organization_id=org_id)
    products = products.exclude(betala_is_bundles=True).order_by('category_name', 'name')
    
    # Beregn verdier
    total_products = products.count()
    total_retail_value = 0
    total_cost_value = 0
    
    by_category = {}
    
    for product in products:
        if product.price_ore:
            total_retail_value += product.price_ore
        if product.purchase_price_ore:
            total_cost_value += product.purchase_price_ore
        
        cat_name = product.category_name if product.category_name else 'Uten kategori'
        if cat_name not in by_category:
            by_category[cat_name] = {
                'items': [],
                'total_count': 0,
                'total_value': 0
            }
        by_category[cat_name]['items'].append(product)
        by_category[cat_name]['total_count'] += 1
        if product.price_ore:
            by_category[cat_name]['total_value'] += product.price_ore
    
    # Konverter total_value til kr for hver kategori
    for cat_data in by_category.values():
        cat_data['total_value_kr'] = Decimal(cat_data['total_value']) / 100
    
    context = {
        'event': event,
        'organization_name': org_name,
        'products': products,
        'by_category': by_category,
        'total_products': total_products,
        'total_retail_value_kr': Decimal(total_retail_value) / 100,
        'total_cost_value_kr': Decimal(total_cost_value) / 100,
        'gross_margin_kr': Decimal(total_retail_value - total_cost_value) / 100,
    }
    return render(request, 'reports/inventory_report.html', context)


@login_required
def sales_report(request):
    """Salgsrapport fra Betala-synkroniserte data."""
    org_id, org_name, event = get_org_context(request)
    
    # Tidsperiode
    days = int(request.GET.get('days', 7))
    start_date = date.today() - timedelta(days=days)
    
    start = timezone.make_aware(
        timezone.datetime.combine(start_date, timezone.datetime.min.time())
    )
    
    # Salg fra lagertransaksjoner
    sales = StockTransaction.objects.filter(
        transaction_type=StockTransaction.TransactionType.SALE,
        transaction_date__gte=start
    )
    if event:
        sales = sales.filter(event=event)
    sales = sales.select_related('product')
    
    # Per produkt - gruppér og inkluder produktobjekt
    from collections import defaultdict
    product_sales = defaultdict(lambda: {'qty': 0, 'revenue': 0, 'product': None})
    
    for tx in sales:
        if tx.product:
            pid = tx.product.id
            product_sales[pid]['product'] = tx.product
            product_sales[pid]['qty'] += abs(tx.quantity or 0)
            if tx.product.price_ore:
                product_sales[pid]['revenue'] += abs(tx.quantity or 0) * tx.product.price_ore
    
    by_product = sorted(
        [{'product': v['product'], 'qty': v['qty'], 'revenue_kr': Decimal(v['revenue']) / 100}
         for v in product_sales.values() if v['product']],
        key=lambda x: -x['qty']
    )
    
    # Beregn omsetning
    total_revenue = sum(v['revenue'] for v in product_sales.values())
    
    # Betala-transaksjoner for perioden
    betala_transactions = []
    betala_total = 0
    if event:
        betala_transactions = BetalaTransactionSync.objects.filter(
            event=event,
            finalized_at__gte=start,
            is_void=False
        ).order_by('-finalized_at')
        betala_total = betala_transactions.aggregate(
            total=Sum('total_amount_ore')
        )['total'] or 0
    
    context = {
        'event': event,
        'organization_name': org_name,
        'by_product': by_product,
        'total_transactions': sales.count(),
        'total_items_sold': abs(sales.aggregate(Sum('quantity'))['quantity__sum'] or 0),
        'total_revenue_kr': Decimal(total_revenue) / 100,
        'betala_transactions': betala_transactions,
        'betala_total_kr': Decimal(betala_total) / 100,
        'days': days,
        'start_date': start_date,
    }
    return render(request, 'reports/sales_report.html', context)


@login_required
def export_inventory_excel(request):
    """Eksporter lagerbeholdning til Excel."""
    event = get_active_event(request)
    
    if not event:
        messages.error(request, 'Velg et event først')
        return redirect('reports:index')
    
    stock_levels = StockLevel.objects.filter(
        event=event
    ).select_related('product', 'product__category')
    
    generator = InventoryExcelGenerator()
    output = generator.generate(event, stock_levels)
    
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f'lagerbeholdning_{event.name}_{date.today()}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def export_transactions_excel(request):
    """Eksporter transaksjoner til Excel."""
    event = get_active_event(request)
    
    if not event:
        messages.error(request, 'Velg et event først')
        return redirect('reports:index')
    
    days = int(request.GET.get('days', 7))
    start_date = date.today() - timedelta(days=days)
    
    transactions = StockTransaction.objects.filter(
        event=event,
        transaction_date__gte=start_date
    ).select_related('product', 'created_by')
    
    generator = TransactionExcelGenerator()
    output = generator.generate(event, transactions, start_date)
    
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f'transaksjoner_{event.name}_{start_date}_{date.today()}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def stock_count_pdf(request, pk):
    """Eksporter varetelling til PDF."""
    from inventory.models import StockCount
    from .generators import StockCountPDFGenerator
    from django.shortcuts import get_object_or_404
    
    count = get_object_or_404(StockCount, pk=pk)
    
    # Velg format: 'partial' for sortert per deltelling, ellers samlet
    format_type = request.GET.get('format', 'combined')
    
    generator = StockCountPDFGenerator()
    
    if format_type == 'partial':
        output = generator.generate_by_partial(count)
        suffix = '_per_deltelling'
    else:
        output = generator.generate(count)
        suffix = ''
    
    response = HttpResponse(
        output.read(),
        content_type='application/pdf'
    )
    
    # Lag filnavn
    safe_name = count.name.replace(' ', '_').replace('/', '-')[:30]
    filename = f'tellerapport_{safe_name}{suffix}_{date.today()}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def stock_count_list_for_report(request):
    """Liste over fullførte varetelinger for rapporter."""
    from inventory.models import StockCount
    
    org_id, org_name, event = get_org_context(request)
    
    # Hent fullførte tellinger (ikke deltellinger)
    counts = StockCount.objects.filter(
        status__in=[StockCount.Status.COMPLETED, StockCount.Status.IMPORTED],
        parent_count__isnull=True
    )
    
    if event:
        counts = counts.filter(event=event)
    
    counts = counts.select_related(
        'event', 'started_by', 'completed_by'
    ).prefetch_related('partial_counts').order_by('-completed_at')
    
    context = {
        'counts': counts,
        'event': event,
        'organization_name': org_name,
    }
    return render(request, 'reports/stock_count_list.html', context)
