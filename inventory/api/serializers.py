"""
REST API serializers for lagersystemet.
"""

from rest_framework import serializers
from inventory.models import (
    Product, Category, StockLevel, StockTransaction,
    Event, ShrinkageEntry, Supplier, UnitOfMeasure
)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'color', 'sort_order']


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ['id', 'name', 'contact_person', 'email', 'phone']


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    """Serializer for enheter."""
    class Meta:
        model = UnitOfMeasure
        fields = [
            'id', 'name', 'short_name', 'conversion_factor',
            'is_purchase_unit', 'is_sale_unit', 'is_count_unit', 'sort_order'
        ]


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source='category',
        write_only=True,
        required=False
    )
    price_kr = serializers.SerializerMethodField()
    current_stock = serializers.SerializerMethodField()
    units = UnitOfMeasureSerializer(many=True, read_only=True)
    formatted_stock = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'category', 'category_id',
            'sku', 'barcode', 'unit', 'price_ore', 'price_kr',
            'min_stock_level', 'track_inventory', 'is_active',
            'current_stock', 'betala_product_id',
            'base_unit_type', 'use_unit_conversion', 'units', 'formatted_stock'
        ]
    
    def get_price_kr(self, obj):
        return obj.price_kr
    
    def get_current_stock(self, obj):
        event_id = self.context.get('event_id')
        if event_id:
            return obj.get_current_stock(event_id=event_id)
        return obj.get_current_stock()
    
    def get_formatted_stock(self, obj):
        """Hent formatert lagerbeholdning med enheter."""
        if obj.use_unit_conversion:
            return obj.format_stock_display()
        return None


class ProductListSerializer(serializers.ModelSerializer):
    """Lettvekts-serializer for lister."""
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'sku', 'barcode', 'category_name', 'price_ore', 'unit']


class EventSerializer(serializers.ModelSerializer):
    is_ongoing = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'name', 'start_date', 'end_date', 'location',
            'description', 'is_active', 'is_ongoing'
        ]
    
    def get_is_ongoing(self, obj):
        return obj.is_ongoing


class StockLevelSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source='product',
        write_only=True
    )
    event = EventSerializer(read_only=True)
    event_id = serializers.PrimaryKeyRelatedField(
        queryset=Event.objects.all(),
        source='event',
        write_only=True
    )
    is_low_stock = serializers.SerializerMethodField()
    
    class Meta:
        model = StockLevel
        fields = [
            'id', 'product', 'product_id', 'event', 'event_id',
            'quantity', 'location', 'is_low_stock'
        ]
    
    def get_is_low_stock(self, obj):
        return obj.is_low_stock


class StockTransactionSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source='product',
        write_only=True
    )
    event_id = serializers.PrimaryKeyRelatedField(
        queryset=Event.objects.all(),
        source='event',
        write_only=True,
        required=False
    )
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display',
        read_only=True
    )
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True
    )
    
    class Meta:
        model = StockTransaction
        fields = [
            'id', 'product', 'product_id', 'event_id',
            'transaction_type', 'transaction_type_display',
            'quantity', 'unit_cost_ore', 'reference', 'notes',
            'location', 'transaction_date', 'created_by_name'
        ]
        read_only_fields = ['created_by_name']


class ShrinkageEntrySerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source='product',
        write_only=True
    )
    event_id = serializers.PrimaryKeyRelatedField(
        queryset=Event.objects.all(),
        source='event',
        write_only=True
    )
    reason_display = serializers.CharField(
        source='get_reason_display',
        read_only=True
    )
    
    class Meta:
        model = ShrinkageEntry
        fields = [
            'id', 'product', 'product_id', 'event_id',
            'quantity', 'reason', 'reason_display',
            'location', 'notes', 'registered_date'
        ]
