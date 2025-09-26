from django.urls import path
from . import views

urlpatterns = [
    path('process-task', views.process_task, name='process_task'),
]
