"""
REST API views for lagersystemet.
"""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum

from inventory.models import (
    Product, StockLevel, StockTransaction, Event, UnitOfMeasure
)
from .serializers import (
    ProductSerializer, ProductListSerializer,
    StockLevelSerializer, StockTransactionSerializer,
    EventSerializer
)


class ProductViewSet(viewsets.ModelViewSet):
    """
    API for produkter.
    
    list: Hent alle produkter
    retrieve: Hent enkelt produkt
    create: Opprett nytt produkt
    update: Oppdater produkt
    stock: Hent lagerbeholdning for produkt
    """
    queryset = Product.objects.filter(is_active=True).select_related('category')
    serializer_class = ProductSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'track_inventory', 'supplier']
    search_fields = ['name', 'sku', 'barcode', 'description']
    ordering_fields = ['name', 'created_at', 'price_ore']
    ordering = ['name']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        return ProductSerializer
    
    @action(detail=True, methods=['get'])
    def stock(self, request, pk=None):
        """Hent lagerbeholdning for produkt."""
        product = self.get_object()
        event_id = request.query_params.get('event_id')
        
        stock_levels = product.stock_levels.all()
        if event_id:
            stock_levels = stock_levels.filter(event_id=event_id)
        
        serializer = StockLevelSerializer(stock_levels, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        """Hent transaksjonshistorikk for produkt."""
        product = self.get_object()
        event_id = request.query_params.get('event_id')
        
        transactions = product.transactions.all().order_by('-transaction_date')[:50]
        if event_id:
            transactions = transactions.filter(event_id=event_id)
        
        serializer = StockTransactionSerializer(transactions, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_barcode(self, request):
        """Finn produkt via strekkode."""
        barcode = request.query_params.get('barcode')
        if not barcode:
            return Response(
                {'error': 'barcode parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            product = Product.objects.get(barcode=barcode)
            serializer = ProductSerializer(product)
            return Response(serializer.data)
        except Product.DoesNotExist:
            return Response(
                {'error': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['get'])
    def units(self, request, pk=None):
        """
        Hent enheter for et produkt.
        
        Query params:
        - type: 'purchase', 'sale', 'count', eller 'all' (default)
        
        Returns:
        - units: Liste med enheter
        - use_unit_conversion: Om produktet bruker enhetskonvertering
        - base_unit_type: Produktets base-enhet (ml, cl, stk)
        """
        product = self.get_object()
        unit_type = request.query_params.get('type', 'all')
        
        response_data = {
            'use_unit_conversion': product.use_unit_conversion,
            'base_unit_type': product.base_unit_type,
            'units': []
        }
        
        if not product.use_unit_conversion:
            return Response(response_data)
        
        # Filtrer enheter basert på type
        units_qs = product.units.filter(is_active=True)
        
        if unit_type == 'purchase':
            units_qs = units_qs.filter(is_purchase_unit=True)
        elif unit_type == 'sale':
            units_qs = units_qs.filter(is_sale_unit=True)
        elif unit_type == 'count':
            units_qs = units_qs.filter(is_count_unit=True)
        
        response_data['units'] = [
            {
                'id': u.id,
                'name': u.name,
                'short_name': u.short_name,
                'conversion_factor': u.conversion_factor,
                'is_purchase_unit': u.is_purchase_unit,
                'is_sale_unit': u.is_sale_unit,
                'is_count_unit': u.is_count_unit,
            }
            for u in units_qs.order_by('sort_order', '-conversion_factor')
        ]
        
        return Response(response_data)
    
    @action(detail=True, methods=['get'])
    def stock_formatted(self, request, pk=None):
        """
        Hent formatert lagerbeholdning med enhetskonvertering.
        
        Query params:
        - event_id: Filtrer på event (valgfritt)
        
        Returns:
        - base_quantity: Antall i base-enheter
        - formatted: Human-readable streng (f.eks. "2 Tanker, 5 Glass")
        - by_unit: Liste med antall per enhet
        """
        product = self.get_object()
        event_id = request.query_params.get('event_id')
        
        event = None
        if event_id:
            try:
                event = Event.objects.get(id=event_id)
            except Event.DoesNotExist:
                pass
        
        from inventory.unit_conversion import get_stock_summary
        summary = get_stock_summary(product, event)
        
        return Response(summary)


class StockLevelViewSet(viewsets.ModelViewSet):
    """
    API for lagernivåer.
    
    Filtrer på event_id for å se beholdning for spesifikt event.
    """
    queryset = StockLevel.objects.select_related('product', 'event')
    serializer_class = StockLevelSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['event', 'product', 'location']
    ordering = ['product__name']
    
    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Hent produkter med lav beholdning."""
        event_id = request.query_params.get('event_id')
        
        queryset = self.get_queryset()
        if event_id:
            queryset = queryset.filter(event_id=event_id)
        
        low_stock = [sl for sl in queryset if sl.is_low_stock]
        serializer = self.get_serializer(low_stock, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Hent lageroversikt/sammendrag."""
        event_id = request.query_params.get('event_id')
        
        queryset = self.get_queryset()
        if event_id:
            queryset = queryset.filter(event_id=event_id)
        
        stats = {
            'total_products': queryset.count(),
            'total_items': queryset.aggregate(Sum('quantity'))['quantity__sum'] or 0,
            'low_stock_count': sum(1 for sl in queryset if sl.is_low_stock),
        }
        return Response(stats)


class StockTransactionViewSet(viewsets.ModelViewSet):
    """
    API for lagertransaksjoner.
    
    Opprett transaksjoner for å justere beholdning manuelt.
    """
    queryset = StockTransaction.objects.select_related(
        'product', 'event', 'created_by'
    ).order_by('-transaction_date')
    serializer_class = StockTransactionSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['event', 'product', 'transaction_type']
    ordering_fields = ['transaction_date', 'created_at']
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API for events (read-only).
    """
    queryset = Event.objects.filter(is_active=True)
    serializer_class = EventSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'location']
    ordering = ['-start_date']
    
    @action(detail=True, methods=['get'])
    def stock_summary(self, request, pk=None):
        """Hent lageroversikt for event."""
        event = self.get_object()
        
        stock_levels = StockLevel.objects.filter(
            event=event
        ).select_related('product')
        
        by_category = {}
        for sl in stock_levels:
            cat_name = sl.product.category.name if sl.product.category else 'Uten kategori'
            if cat_name not in by_category:
                by_category[cat_name] = {'items': 0, 'quantity': 0}
            by_category[cat_name]['items'] += 1
            by_category[cat_name]['quantity'] += sl.quantity
        
        return Response({
            'total_products': stock_levels.count(),
            'total_items': sum(sl.quantity for sl in stock_levels),
            'by_category': by_category,
        })
