from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'alerts', views.AlertViewSet, basename='alert')

urlpatterns = [
    path('', views.ProductHomeView.as_view(), name='home'),
    path('healthz/', views.HealthView.as_view(), name='healthz'),
    path('process_task/', views.process_task, name='process_task'),
    path('experience/catalog/', views.CatalogOptionsView.as_view(), name='catalog_options'),
    path('experience/simulate/', views.PublicSimulateView.as_view(), name='public_simulate'),
    path('api/simulate/', views.SimulateImpactView.as_view(), name='simulate_impact'),
    path('api/', include(router.urls)),
]
