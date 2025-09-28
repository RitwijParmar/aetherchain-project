import json
import base64
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .tasks import run_impact_analysis

# --- Imports for the REST API ---
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Alert
from .serializers import AlertSerializer
from .permissions import IsBearerAuthenticated

# --- Existing Pub/Sub Worker View ---
@csrf_exempt
def process_task(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Unsupported method")
    try:
        envelope = json.loads(request.body)
        pubsub_message = envelope['message']['data']
        event_data_str = base64.b64decode(pubsub_message).decode('utf-8')
        event_data = json.loads(event_data_str)
        print(f"--- [HTTP WORKER] Received task via Pub/Sub Push: {event_data} ---")
        run_impact_analysis(event_data, save_to_db=True)
        return HttpResponse(status=204)
    except Exception as e:
        print(f"Error processing Pub/Sub message: {e}")
        return HttpResponse(status=500)

# --- SECURED Read-Only ViewSet for the Alerts API ---
class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Alert.objects.all().order_by('-created_at')
    serializer_class = AlertSerializer
    permission_classes = [IsBearerAuthenticated]

# --- FINAL CORRECTED "What-If" Simulation Endpoint ---
class SimulateImpactView(APIView):
    """
    Accepts a POST request with either a 'location' or a 'supplier_name'
    to run a simulated impact analysis without saving the result.
    """
    permission_classes = [IsBearerAuthenticated]

    def post(self, request, *args, **kwargs):
        location = request.data.get('location')
        supplier_name = request.data.get('supplier_name')
        
        event_data = None

        if location:
            event_data = {
                "description": f"Simulated what-if analysis for {location}",
                "location": location
            }
        elif supplier_name:
            event_data = {
                "description": f"Simulated what-if analysis for supplier {supplier_name}",
                "supplier_name": supplier_name,
                "event_type": request.data.get('event_type', 'Supplier Disruption')
            }

        if not event_data:
            return Response({'error': 'Either "location" or "supplier_name" must be provided.'}, status=400)

        analysis_result = run_impact_analysis(event_data, save_to_db=False)

        if analysis_result:
            return Response(analysis_result, status=200)
        else:
            return Response({'message': 'No affected assets found or an error occurred during analysis.'}, status=404)
