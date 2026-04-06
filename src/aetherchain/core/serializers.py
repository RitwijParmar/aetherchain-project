from rest_framework import serializers
from .models import Alert


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = [
            'id',
            'event_type',
            'event_target',
            'summary_description',
            'impact_analysis',
            'recommended_action',
            'risk_score',
            'confidence_score',
            'estimated_delay_days',
            'estimated_cost_impact_usd',
            'evidence_summary',
            'raw_context',
            'created_at',
        ]
