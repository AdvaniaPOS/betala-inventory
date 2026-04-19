from django.urls import path
from . import views

app_name = 'betala_sync'

urlpatterns = [
    # Betala innlogging og organisasjonsvalg
    path('login/', views.betala_login, name='betala_login'),
    path('organisasjoner/', views.betala_select_organization, name='select_organization'),
    path('bytt-organisasjon/', views.betala_switch_organization, name='switch_organization'),
    path('synkroniser/', views.betala_sync_organization, name='sync_organization'),
    path('salgspunkt-omrade/', views.betala_select_sales_point_area, name='select_sales_point_area'),
    path('synkroniser-omrade/', views.betala_sync_sales_point_area, name='sync_sales_point_area'),
    path('resultat/', views.betala_sync_result, name='sync_result'),
    path('logg-ut/', views.betala_logout, name='betala_logout'),
    
    # Eksisterende synkronisering
    path('', views.sync_dashboard, name='dashboard'),
    path('produkter/', views.sync_products, name='sync_products'),
    path('salg/', views.sync_sales, name='sync_sales'),
    path('logg/', views.sync_log_list, name='log_list'),
]
