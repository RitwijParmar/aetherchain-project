import os
import json
import requests
from .models import Alert
from neomodel import db
from django.conf import settings
from google.auth import default as gcp_auth_default
from google.auth.transport.requests import Request as gcp_auth_request

def run_impact_analysis(event_data, save_to_db=True):
    print(f"--- [TASK LOGIC] Starting analysis for event: {event_data['description']} ---")
    event_location = event_data['location']
    event_type = event_data.get('type', "Port Congestion")

    print(f"--- [TASK LOGIC] Retrieving assets from Neo4j...")
    query = f"MATCH (p)-[:CARRIES]-(r)-[:DESTINED_FOR]->(port) WHERE port.name = '{event_location}' RETURN p.sku as product_sku, r.route_id as route_id"
    results, meta = db.cypher_query(query)

    if not results:
        print(f"--- [TASK LOGIC] No affected assets found. Halting process.")
        return None

    affected_assets_str = ", ".join([f"Product SKU {row[0]} on Route {row[1]}" for row in results])
    print(f"--- [TASK LOGIC] Found affected assets: {affected_assets_str}")

    print("--- [TASK LOGIC] Calling Vertex AI Mistral Small API...")
    
    try:
        credentials, project_id = gcp_auth_default()
        if not credentials.valid:
            credentials.refresh(gcp_auth_request())
        access_token = credentials.token

        model_id = "mistral-small-2503"
        region = "us-central1"
        url = f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{region}/publishers/mistralai/models/{model_id}:rawPredict"
        
        # CORRECTED PAYLOAD: This schema is restored to the exact working version from the Master Prompt.
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "You are a supply chain risk analyst. Provide analysis in the exact JSON format specified."},
                {"role": "user", "content": f"Analyze the impact of a '{event_type}' event at '{event_location}' affecting these assets: {affected_assets_str}."}
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "supply_chain_analysis",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "impact_analysis": {"type": "string", "description": "Detailed impact analysis of the event"},
                            "recommended_action": {"type": "string", "description": "Specific recommended action to mitigate the impact"},
                            "summary_description": {"type": "string", "description": "Short summary description suitable for a title"}
                        },
                        "required": ["impact_analysis", "recommended_action", "summary_description"],
                        "additionalProperties": False
                    }
                }
            }
        }
        
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        response_data = response.json()
        llm_text_response = response_data["choices"][0]["message"]["content"]
        
        print(f"--- [TASK LOGIC] SUCCESS! AI Response received from Mistral.")
        
        analysis_data = json.loads(llm_text_response)
        
        if save_to_db:
            new_alert = Alert.objects.create(**analysis_data)
            print(f"--- [TASK LOGIC] Successfully saved Alert ID: {new_alert.id} to the database. ---")
        else:
            print(f"--- [TASK LOGIC] Skipping database save as requested. ---")

        return analysis_data

    except requests.exceptions.HTTPError as http_err:
        print(f"--- [TASK LOGIC] HTTP Error calling Mistral API: {http_err}")
        print(f"--- [TASK LOGIC] Response Body: {response.text}")
        return None
    except Exception as e:
        print(f"--- [TASK LOGIC] An error occurred: {e}")
        return None
