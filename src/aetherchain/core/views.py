from __future__ import annotations

import base64
import json

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import CATALOG_KINDS, load_catalog_snapshot
from .models import Alert
from .permissions import IsBearerAuthenticated
from .serializers import AlertSerializer
from .tasks import normalize_string_list, run_impact_analysis


def _decode_pubsub_envelope(body: bytes) -> dict:
    envelope = json.loads(body or "{}")
    message = envelope.get('message')
    if not isinstance(message, dict) or 'data' not in message:
        raise ValueError('Invalid Pub/Sub envelope: missing "message.data".')

    event_data_str = base64.b64decode(message['data']).decode('utf-8')
    return json.loads(event_data_str)


def _clean_text(data, key: str, max_len: int) -> str:
    return str(data.get(key) or '').strip()[:max_len]


def _clean_int(value, minimum: int = 1, maximum: int = 180):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum:
        return None
    return min(parsed, maximum)


def _build_scenario_payload(data) -> tuple[dict, str | None]:
    location = _clean_text(data, 'location', 140)
    supplier_name = _clean_text(data, 'supplier_name', 140)
    event_type = _clean_text(data, 'event_type', 120)
    business_priority = _clean_text(data, 'business_priority', 120)
    context_note = _clean_text(data, 'context_note', 280)
    horizon_days = _clean_int(data.get('horizon_days'))

    product_skus = normalize_string_list(data.get('product_skus') or data.get('product_sku'))
    route_ids = normalize_string_list(data.get('route_ids') or data.get('route_id'))

    if not any([location, supplier_name, product_skus, route_ids]):
        return {}, 'Choose at least one target: location, supplier, SKU, or route.'

    if not event_type:
        if supplier_name:
            event_type = 'Supplier Disruption'
        elif location:
            event_type = 'Port Congestion'
        else:
            event_type = 'Supply Network Disruption'

    event_target = location or supplier_name or ', '.join((product_skus + route_ids)[:2])
    event_data = {
        "description": f"Scenario analysis for {event_target}",
        "event_type": event_type,
    }
    if location:
        event_data['location'] = location
    if supplier_name:
        event_data['supplier_name'] = supplier_name
    if product_skus:
        event_data['product_skus'] = product_skus
    if route_ids:
        event_data['route_ids'] = route_ids
    if business_priority:
        event_data['business_priority'] = business_priority
    if context_note:
        event_data['context_note'] = context_note
    if horizon_days:
        event_data['horizon_days'] = horizon_days

    return event_data, None


@csrf_exempt
def process_task(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Unsupported method")

    try:
        event_data = _decode_pubsub_envelope(request.body)
        run_impact_analysis(event_data, save_to_db=True)
        return HttpResponse(status=204)
    except Exception as e:
        print(f"Error processing Pub/Sub message: {e}")
        return HttpResponse(status=500)


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Alert.objects.all().order_by('-created_at')
    serializer_class = AlertSerializer
    permission_classes = [IsBearerAuthenticated]


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, *args, **kwargs):
        return Response({'status': 'ok'}, status=200)


class ProductHomeView(TemplateView):
    template_name = 'core/home.html'


class CatalogOptionsView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, *args, **kwargs):
        kind = str(request.query_params.get('kind') or 'all').strip().lower()
        if kind not in {'all', *CATALOG_KINDS}:
            return Response({'error': 'Unsupported kind. Use all, ports, suppliers, skus, or routes.'}, status=400)

        q = str(request.query_params.get('q') or '').strip()
        location = str(request.query_params.get('location') or '').strip()
        supplier_name = str(request.query_params.get('supplier_name') or '').strip()
        limit = _clean_int(request.query_params.get('limit'), minimum=5, maximum=50) or 18

        snapshot = load_catalog_snapshot(
            q=q,
            location=location,
            supplier_name=supplier_name,
            kind=kind,
            limit=limit,
        )
        return Response(snapshot, status=200)


class SimulateImpactView(APIView):
    permission_classes = [IsBearerAuthenticated]

    def post(self, request, *args, **kwargs):
        event_data, error_message = _build_scenario_payload(request.data)
        if error_message:
            return Response({'error': error_message}, status=400)

        analysis_result = run_impact_analysis(event_data, save_to_db=False)
        if analysis_result:
            return Response(analysis_result, status=200)
        return Response({'message': 'No affected assets found or an error occurred during analysis.'}, status=404)


class PublicSimulateView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, *args, **kwargs):
        event_data, error_message = _build_scenario_payload(request.data)
        if error_message:
            return Response({'error': error_message}, status=400)

        analysis_result = run_impact_analysis(event_data, save_to_db=False)
        if not analysis_result:
            return Response(
                {'message': 'No impacted assets were detected for this scenario.'},
                status=404,
            )

        return Response(analysis_result, status=200)
