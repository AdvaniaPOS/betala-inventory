from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.report_index, name='index'),
    path('daglig/', views.daily_report, name='daily'),
    path('svinn/', views.shrinkage_report, name='shrinkage'),
    path('beholdning/', views.inventory_report, name='inventory'),
    path('salg/', views.sales_report, name='sales'),
    path('tellinger/', views.stock_count_list_for_report, name='stock_counts'),
    path('excel/beholdning/', views.export_inventory_excel, name='export_inventory'),
    path('excel/transaksjoner/', views.export_transactions_excel, name='export_transactions'),
    path('pdf/telling/<int:pk>/', views.stock_count_pdf, name='stock_count_pdf'),
]
