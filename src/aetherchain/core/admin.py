from django.contrib import admin

from .models import Alert, Port


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'event_type',
        'event_target',
        'risk_score',
        'confidence_score',
        'created_at',
    )
    list_filter = ('event_type', 'created_at')
    search_fields = ('event_target', 'summary_description', 'impact_analysis')


@admin.register(Port)
class PortAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'country')
    search_fields = ('name', 'country')
