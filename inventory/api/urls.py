from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'api'

router = DefaultRouter()
router.register('products', views.ProductViewSet, basename='products')
router.register('stock-levels', views.StockLevelViewSet, basename='stock-levels')
router.register('transactions', views.StockTransactionViewSet, basename='transactions')
router.register('events', views.EventViewSet, basename='events')

urlpatterns = [
    path('', include(router.urls)),
]
