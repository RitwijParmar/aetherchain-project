from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create a router and register our AlertViewSet with it.
router = DefaultRouter()
router.register(r'alerts', views.AlertViewSet, basename='alert')

# The API URLs are now determined automatically by the router.
# We also add the existing 'process_task' URL and the new 'simulate' URL.
urlpatterns = [
    path('process_task/', views.process_task, name='process_task'),
    path('api/simulate/', views.SimulateImpactView.as_view(), name='simulate_impact'),
    path('api/', include(router.urls)),
]
