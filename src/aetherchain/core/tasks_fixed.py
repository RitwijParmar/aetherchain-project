import os
import json
import requests
from celery import shared_task
from .models import Alert
from neomodel import db
from django.conf import settings
from google.auth import default as gcp_auth_default
from google.auth.transport.requests import Request as gcp_auth_request

@shared_task
def run_impact_analysis(event_data):
    """
    Runs an impact analysis for a supply chain event using a cloud LLM
    and stores the result in the Alert database model.
    """
    print(f"--- [TASK LOGIC] Starting analysis for event: {event_data['description']} ---")
    event_location = event_data['location']
    event_type = "Port Congestion"

    print(f"--- [TASK LOGIC] Retrieving assets from Neo4j...")
    query = f"MATCH (p)-[:CARRIES]-(r)-[:DESTINED_FOR]->(port) WHERE port.name = '{event_location}' RETURN p.sku as product_sku, r.route_id as route_id"
    results, meta = db.cypher_query(query)

    if not results:
        print("--- [TASK LOGIC] No affected assets found. Halting process.")
        return

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
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}"
            f"/locations/{region}/publishers/mistralai/models/{model_id}:rawPredict"
        )

        prompt_content = [
            {
                "role": "system",
                "content": (
                    "You are a supply chain risk analyst. Reply STRICTLY as valid JSON with the following fields:"
                    "impact_analysis, recommended_action, and summary_description."
                    "Do not add any extra verbiage or formatting."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Analyze the impact of a '{event_type}' event at '{event_location}' "
                    f"affecting these assets: {affected_assets_str}."
                ),
            },
        ]
        json_schema = {
            "type": "object",
            "properties": {
                "impact_analysis": {
                    "type": "string",
                    "description": "Detailed impact analysis of the event",
                },
                "recommended_action": {
                    "type": "string",
                    "description": "Specific recommended action to mitigate the impact",
                },
                "summary_description": {
                    "type": "string",
                    "description": "Short summary description suitable for a title",
                },
            },
            "required": [
                "impact_analysis",
                "recommended_action",
                "summary_description",
            ],
            "additionalProperties": False,
        }
        payload = {
            "model": model_id,
            "messages": prompt_content,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "supply_chain_analysis",
                    "strict": True,
                    "schema": json_schema,
                },
            },
        }
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        response = requests.post(url, headers=headers, json=payload)
        print(f"--- [TASK LOGIC] API returned status code: {response.status_code}")
        response.raise_for_status()

        response_data = response.json()
        llm_raw = response_data["choices"][0]["message"]["content"]
        print(f"--- [TASK LOGIC] Raw LLM response: {llm_raw}")

        # If already parsed as dict, use directly
        if isinstance(llm_raw, dict):
            analysis_data = llm_raw
        else:
            # Sometimes the response is a JSON string (or wrongly wrapped as a string)
            try:
                analysis_data = json.loads(llm_raw)
            except Exception as e:
                print(f"--- [TASK LOGIC] JSON decoding failed: {str(e)}")
                print(f"--- [TASK LOGIC] Fallback: printing raw response for debugging.")
                print(llm_raw)
                return

        try:
            new_alert = Alert.objects.create(
                impact_analysis=analysis_data["impact_analysis"],
                recommended_action=analysis_data["recommended_action"],
                summary_description=analysis_data["summary_description"],
            )
            print(f"--- [TASK LOGIC] Successfully saved Alert ID: {new_alert.id} to the database. ---")
        except KeyError as ke:
            print(f"--- [TASK LOGIC] Missing expected key in analysis_data: {ke}")
            print(f"Analysis data received: {analysis_data}")

    except requests.exceptions.HTTPError as http_err:
        print(f"--- [TASK LOGIC] HTTP Error calling Mistral API: {http_err}")
        print(f"--- [TASK LOGIC] Response Body: {response.text}")
    except Exception as e:
        print(f"--- [TASK LOGIC] Error processing response or saving to DB: {e}")
