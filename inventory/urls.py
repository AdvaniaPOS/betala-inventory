"""
URL konfigurasjon for inventory app.
"""

from django.urls import path, include
from . import views

app_name = 'inventory'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    path('toggle-auto-sync/', views.toggle_auto_sync, name='toggle_auto_sync'),
    
    # Produkter
    path('produkter/', views.product_list, name='product_list'),
    path('produkter/<int:betala_id>/', views.product_detail, name='product_detail'),
    path('produkter/<int:betala_id>/rediger/', views.product_edit, name='product_edit'),
    path('produkter/<int:betala_id>/pakke/', views.bundle_edit, name='bundle_edit'),
    path('produkter/<int:betala_id>/enheter/', views.product_units, name='product_units'),
    
    # Lagerbeholdning
    path('beholdning/', views.stock_level_list, name='stock_level_list'),
    path('lav-beholdning/', views.low_stock_alert, name='low_stock_alert'),
    
    # Varemottak
    path('mottak/', views.receiving_list, name='receiving_list'),
    path('mottak/ny/', views.receiving_create, name='receiving_create'),
    path('mottak/<int:pk>/', views.receiving_detail, name='receiving_detail'),
    
    # Innkjøpsordre
    path('innkjop/', views.purchase_order_list, name='purchase_order_list'),
    path('innkjop/ny/', views.purchase_order_create, name='purchase_order_create'),
    path('innkjop/<int:pk>/', views.purchase_order_detail, name='purchase_order_detail'),
    path('innkjop/<int:pk>/rediger/', views.purchase_order_edit, name='purchase_order_edit'),
    path('innkjop/<int:pk>/bestilt/', views.purchase_order_mark_ordered, name='purchase_order_mark_ordered'),
    path('innkjop/<int:pk>/kanseller/', views.purchase_order_cancel, name='purchase_order_cancel'),
    path('innkjop/<int:pk>/avslutt/', views.purchase_order_close, name='purchase_order_close'),
    path('innkjop/<int:pk>/motta/', views.purchase_order_receive, name='purchase_order_receive'),
    
    # Svinn
    path('svinn/', views.shrinkage_list, name='shrinkage_list'),
    path('svinn/ny/', views.shrinkage_create, name='shrinkage_create'),
    
    # Varetelling
    path('telling/', views.stock_count_list, name='stock_count_list'),
    path('telling/ny/', views.stock_count_create, name='stock_count_create'),
    path('telling/<int:pk>/', views.stock_count_detail, name='stock_count_detail'),
    path('telling/<int:pk>/mobil/', views.stock_count_mobile, name='stock_count_mobile'),
    path('telling/<int:pk>/importer/', views.import_partial_counts, name='import_partial_counts'),
    path('telling/<int:pk>/slett/', views.stock_count_delete, name='stock_count_delete'),
    
    # Transaksjoner
    path('transaksjoner/', views.transaction_list, name='transaction_list'),
    
    # Leverandører
    path('leverandorer/', views.supplier_list, name='supplier_list'),
    path('leverandorer/ny/', views.supplier_create, name='supplier_create'),
    path('leverandorer/<int:pk>/rediger/', views.supplier_edit, name='supplier_edit'),
    
    # Events
    path('events/', views.event_list, name='event_list'),
    path('events/<int:pk>/', views.event_detail, name='event_detail'),
    
    # API (nested)
    path('api/', include('inventory.api.urls', namespace='api')),
]
