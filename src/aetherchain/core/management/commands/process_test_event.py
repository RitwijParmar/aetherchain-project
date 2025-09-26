from django.core.management.base import BaseCommand
import json
import os
from google.oauth2 import service_account
import requests

class Command(BaseCommand):
    help = 'Publishes a simulated test event to Pub/Sub topic using REST API.'
    
    def handle(self, *args, **options):
        test_event = {
            "description": "Major congestion reported at the Port of Los Angeles due to labor disputes.",
            "location": "Port of Los Angeles"
        }
        
        self.stdout.write(self.style.SUCCESS(f"--- [SENTINEL] Publishing event to Pub/Sub: {test_event['location']} ---"))
        
        # Use REST API instead of client library to avoid pkg_resources issue
        self.publish_via_rest_api(test_event)
        
        self.stdout.write(self.style.SUCCESS('--- [SENTINEL] Event published successfully! ---'))
    
    def publish_via_rest_api(self, message_data):
        """Publish to Pub/Sub using REST API to avoid client library issues"""
        import base64
        from google.auth import default
        from google.auth.transport.requests import Request
        
        # Get default credentials
        credentials, project_id = default()
        
        if not credentials.valid:
            credentials.refresh(Request())
        
        # Prepare the message
        message_json = json.dumps(message_data)
        message_bytes = message_json.encode('utf-8')
        base64_encoded = base64.b64encode(message_bytes).decode('utf-8')
        
        # Prepare the request
        url = f"https://pubsub.googleapis.com/v1/projects/{project_id}/topics/aetherchain-tasks:publish"
        
        headers = {
            'Authorization': f'Bearer {credentials.token}',
            'Content-Type': 'application/json'
        }
        
        body = {
            "messages": [
                {
                    "data": base64_encoded
                }
            ]
        }
        
        # Make the request
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        
        return response.json()
