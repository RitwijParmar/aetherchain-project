"""
Legacy compatibility layer.

Historically the project used this module as the main pipeline entrypoint.
The active implementation now lives in ``tasks.run_impact_analysis``.
"""

from .tasks import run_impact_analysis


def run_alert_pipeline(event_data, save_to_db=True):
    return run_impact_analysis(event_data, save_to_db=save_to_db)
