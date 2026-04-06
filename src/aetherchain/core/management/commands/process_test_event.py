import json
import base64

import requests
from django.core.management.base import BaseCommand, CommandError

from aetherchain.core.gcp_auth import build_google_auth_headers, resolve_gcp_project_id


class Command(BaseCommand):
    help = 'Publishes a simulated test event to Pub/Sub topic using REST API.'

    def handle(self, *args, **options):
        test_event = {
            "description": "Major congestion reported at the Port of Los Angeles due to labor disputes.",
            "location": "Port of Los Angeles",
            "event_type": "Port Congestion",
        }

        self.stdout.write(self.style.SUCCESS(f"--- [SENTINEL] Publishing event to Pub/Sub: {test_event['location']} ---"))

        self.publish_via_rest_api(test_event)
        self.stdout.write(self.style.SUCCESS('--- [SENTINEL] Event published successfully! ---'))

    def publish_via_rest_api(self, message_data):
        project_id = resolve_gcp_project_id()
        if not project_id:
            raise CommandError(
                'Unable to resolve GCP project id. Set GCP_PROJECT_ID or configure gcloud project.'
            )

        message_json = json.dumps(message_data)
        message_bytes = message_json.encode('utf-8')
        base64_encoded = base64.b64encode(message_bytes).decode('utf-8')

        url = f"https://pubsub.googleapis.com/v1/projects/{project_id}/topics/aetherchain-tasks:publish"
        headers = build_google_auth_headers(project_id)
        headers['Content-Type'] = 'application/json'
        body = {
            "messages": [
                {
                    "data": base64_encoded,
                }
            ]
        }

        response = requests.post(url, headers=headers, json=body, timeout=20)
        response.raise_for_status()
        return response.json()
