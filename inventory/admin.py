"""
Django Admin konfigurasjon for lagersystemet.
"""

from django.contrib import admin
from django.utils.html import format_html
from import_export.admin import ImportExportModelAdmin
from import_export import resources

from .models import (
    Supplier, Event, Category, Product, StockLevel,
    StockTransaction, ReceivingOrder, ReceivingOrderLine,
    ShrinkageEntry, StockCount, StockCountLine, BetalaSyncLog,
    PurchaseOrder, PurchaseOrderLine, AllowedOrganization
)


# =============================================================================
# RESOURCES (for import/export)
# =============================================================================

class ProductResource(resources.ModelResource):
    class Meta:
        model = Product
        fields = ('id', 'name', 'sku', 'barcode', 'category__name', 
                  'price_ore', 'purchase_price_ore', 'min_stock_level', 'unit')
        export_order = fields


class StockTransactionResource(resources.ModelResource):
    class Meta:
        model = StockTransaction
        fields = ('id', 'product__name', 'transaction_type', 'quantity',
                  'transaction_date', 'reference', 'created_by__username')


# =============================================================================
# INLINE ADMINS
# =============================================================================

class StockLevelInline(admin.TabularInline):
    model = StockLevel
    extra = 0
    readonly_fields = ['created_at', 'updated_at']


class ReceivingOrderLineInline(admin.TabularInline):
    model = ReceivingOrderLine
    extra = 1
    autocomplete_fields = ['product']


class StockCountLineInline(admin.TabularInline):
    model = StockCountLine
    extra = 0
    autocomplete_fields = ['product']
    readonly_fields = ['variance']


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 1
    autocomplete_fields = ['product']
    readonly_fields = ['remaining_quantity']


# =============================================================================
# ADMIN CLASSES
# =============================================================================

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'contact_person', 'email', 'phone', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'contact_person', 'email']


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_date', 'end_date', 'location', 'is_active', 'is_ongoing']
    list_filter = ['is_active', 'start_date']
    search_fields = ['name', 'location']
    date_hierarchy = 'start_date'
    
    fieldsets = (
        (None, {
            'fields': ('name', 'start_date', 'end_date', 'location', 'description', 'is_active')
        }),
        ('Betala kobling', {
            'fields': ('betala_organization_id', 'betala_sales_point_group_id'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'color_badge', 'sort_order', 'is_active', 'betala_category_id']
    list_filter = ['is_active']
    search_fields = ['name']
    list_editable = ['sort_order']
    
    def color_badge(self, obj):
        if obj.color:
            return format_html(
                '<span style="background-color: {}; padding: 2px 8px; '
                'border-radius: 3px;">{}</span>',
                obj.color, obj.color
            )
        return '-'
    color_badge.short_description = 'Farge'


@admin.register(Product)
class ProductAdmin(ImportExportModelAdmin):
    resource_class = ProductResource
    
    list_display = ['name', 'category', 'price_display', 'min_stock_level', 
                    'track_inventory', 'is_active', 'betala_product_id']
    list_filter = ['category', 'is_active', 'track_inventory', 'supplier']
    search_fields = ['name', 'sku', 'barcode', 'description']
    autocomplete_fields = ['category', 'supplier']
    list_editable = ['min_stock_level', 'track_inventory']
    
    inlines = [StockLevelInline]
    
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'category', 'is_active')
        }),
        ('Prising', {
            'fields': ('price_ore', 'vat_ore', 'vat_factor')
        }),
        ('Lager', {
            'fields': ('sku', 'barcode', 'unit', 'min_stock_level', 'track_inventory')
        }),
        ('Innkjøp', {
            'fields': ('supplier', 'purchase_price_ore')
        }),
        ('Betala', {
            'fields': ('betala_product_id', 'betala_article_group_id'),
            'classes': ('collapse',)
        }),
    )
    
    def price_display(self, obj):
        if obj.price_ore:
            return f'{obj.price_ore / 100:.2f} kr'
        return '-'
    price_display.short_description = 'Pris'


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ['product', 'event', 'quantity', 'location', 'is_low_stock']
    list_filter = ['event', 'product__category']
    search_fields = ['product__name', 'location']
    autocomplete_fields = ['product', 'event']
    
    def is_low_stock(self, obj):
        if obj.is_low_stock:
            return format_html(
                '<span style="color: red; font-weight: bold;">⚠ Lav</span>'
            )
        return '✓'
    is_low_stock.short_description = 'Status'


@admin.register(StockTransaction)
class StockTransactionAdmin(ImportExportModelAdmin):
    resource_class = StockTransactionResource
    
    list_display = ['transaction_date', 'product', 'transaction_type', 
                    'quantity_display', 'event', 'reference', 'created_by']
    list_filter = ['transaction_type', 'event', 'transaction_date']
    search_fields = ['product__name', 'reference', 'notes']
    autocomplete_fields = ['product', 'event', 'supplier']
    date_hierarchy = 'transaction_date'
    readonly_fields = ['created_at', 'updated_at']
    
    def quantity_display(self, obj):
        if obj.quantity >= 0:
            return format_html(
                '<span style="color: green;">+{}</span>',
                obj.quantity
            )
        return format_html(
            '<span style="color: red;">{}</span>',
            obj.quantity
        )
    quantity_display.short_description = 'Antall'


@admin.register(ReceivingOrder)
class ReceivingOrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'supplier', 'event', 'status', 'received_date', 
                    'total_items', 'received_by']
    list_filter = ['status', 'event', 'supplier', 'received_date']
    search_fields = ['order_number', 'delivery_note', 'supplier__name']
    autocomplete_fields = ['event', 'supplier', 'received_by', 'verified_by', 'purchase_order']
    date_hierarchy = 'received_date'
    
    inlines = [ReceivingOrderLineInline]


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'supplier', 'event', 'status', 'order_date',
                    'expected_delivery', 'total_items', 'receive_progress_percent', 'created_by']
    list_filter = ['status', 'event', 'supplier', 'order_date']
    search_fields = ['order_number', 'supplier_reference', 'supplier__name']
    autocomplete_fields = ['event', 'supplier', 'created_by']
    date_hierarchy = 'created_at'
    readonly_fields = ['total_ordered', 'total_received', 'total_cost_kr', 'receive_progress_percent']
    
    inlines = [PurchaseOrderLineInline]
    
    fieldsets = (
        (None, {
            'fields': ('order_number', 'event', 'supplier', 'status')
        }),
        ('Datoer', {
            'fields': ('order_date', 'expected_delivery')
        }),
        ('Referanser', {
            'fields': ('supplier_reference',)
        }),
        ('Totaler (beregnet)', {
            'fields': ('total_ordered', 'total_received', 'total_cost_kr', 'receive_progress_percent'),
            'classes': ('collapse',)
        }),
        ('Notater', {
            'fields': ('notes',)
        }),
    )


@admin.register(ShrinkageEntry)
class ShrinkageEntryAdmin(admin.ModelAdmin):
    list_display = ['registered_date', 'product', 'quantity', 'reason', 
                    'event', 'registered_by']
    list_filter = ['reason', 'event', 'registered_date']
    search_fields = ['product__name', 'notes']
    autocomplete_fields = ['product', 'event']
    date_hierarchy = 'registered_date'
    
    def get_changeform_initial_data(self, request):
        return {'registered_by': request.user}


@admin.register(StockCount)
class StockCountAdmin(admin.ModelAdmin):
    list_display = ['name', 'event', 'status', 'started_at', 'location', 'started_by']
    list_filter = ['status', 'event']
    search_fields = ['name', 'location']
    autocomplete_fields = ['event', 'started_by', 'completed_by']
    
    inlines = [StockCountLineInline]


@admin.register(BetalaSyncLog)
class BetalaSyncLogAdmin(admin.ModelAdmin):
    list_display = ['started_at', 'sync_type', 'status', 'items_processed',
                    'items_created', 'items_updated', 'items_failed', 'triggered_by']
    list_filter = ['sync_type', 'status', 'started_at']
    readonly_fields = ['started_at', 'completed_at', 'sync_type', 'status',
                       'items_processed', 'items_created', 'items_updated',
                       'items_failed', 'error_message', 'details', 'triggered_by']
    date_hierarchy = 'started_at'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AllowedOrganization)
class AllowedOrganizationAdmin(admin.ModelAdmin):
    """Admin for å administrere godkjente organisasjoner."""
    list_display = ['name', 'betala_org_id', 'identifier', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'betala_org_id', 'identifier']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Organisasjonsinformasjon', {
            'fields': ('name', 'betala_org_id', 'identifier')
        }),
        ('Status', {
            'fields': ('is_active', 'notes')
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        # Betala org ID kan ikke endres etter opprettelse
        if obj:
            return ['betala_org_id', 'created_at', 'updated_at']
        return []
    
    def get_fieldsets(self, request, obj=None):
        # Vis metadata kun ved redigering
        fieldsets = list(super().get_fieldsets(request, obj))
        if obj:
            fieldsets.append(
                ('Metadata', {
                    'fields': ('created_at', 'updated_at'),
                    'classes': ('collapse',)
                })
            )
        return fieldsets


# Admin site customization
admin.site.site_header = 'Betala Inventory'
admin.site.site_title = 'Betala Inventory'
admin.site.index_title = 'Administrasjon'
