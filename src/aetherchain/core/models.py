from django.db import models


class Port(models.Model):
    name = models.CharField(max_length=100)
    country = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.name} ({self.country})"


class Alert(models.Model):
    event_type = models.CharField(max_length=120, default='Supply Risk Event')
    event_target = models.CharField(max_length=255, default='', blank=True)
    impact_analysis = models.TextField()
    recommended_action = models.TextField()
    summary_description = models.CharField(max_length=255)
    risk_score = models.FloatField(default=0.0)
    confidence_score = models.FloatField(default=0.0)
    estimated_delay_days = models.FloatField(null=True, blank=True)
    estimated_cost_impact_usd = models.FloatField(null=True, blank=True)
    evidence_summary = models.JSONField(default=list, blank=True)
    raw_context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Alert for {self.summary_description} at {self.created_at}"
