import json
import base64
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from .tasks import run_impact_analysis

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
        # We call the task synchronously for Cloud Run
        run_impact_analysis(event_data)
        return HttpResponse(status=204)
    except Exception as e:
        print(f"Error processing Pub/Sub message: {e}")
        return HttpResponse(status=500)
