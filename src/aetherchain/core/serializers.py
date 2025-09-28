from rest_framework import serializers
from .models import Alert

class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = ['id', 'impact_analysis', 'recommended_action', 'summary_description', 'created_at']
