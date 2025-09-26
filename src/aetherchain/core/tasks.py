from django.conf import settings
import requests
import json
import re # Import the regular expressions library
from celery import shared_task
from .models import Alert
from neomodel import db

@shared_task
def run_impact_analysis(event_data):
    print(f"--- [TASK LOGIC] Starting analysis for event: {event_data['description']} ---")
    event_location = event_data['location']
    event_type = "Port Congestion"

    print(f"--- [TASK LOGIC] Retrieving assets from Neo4j...")
    query = f"MATCH (p)-[:CARRIES]-(r)-[:DESTINED_FOR]->(port) WHERE port.name = '{event_location}' RETURN p.sku as product_sku, r.route_id as route_id"
    results, meta = db.cypher_query(query)

    if not results:
        print(f"--- [TASK LOGIC] No affected assets found. Halting process.")
        return

    affected_assets_str = ", ".join([f"Product SKU {row[0]} on Route {row[1]}" for row in results])
    print(f"--- [TASK LOGIC] Found affected assets: {affected_assets_str}")

    print("--- [TASK LOGIC] Calling Hugging Face API...")
    prompt_template = f"""Analyze the impact of a "{event_type}" event at "{event_location}" on assets: {affected_assets_str}.
Respond ONLY with the analysis in three specific parts separated by "|||". Do not add any extra text, titles, or formatting.

Part 1: A detailed impact analysis.
|||
Part 2: A specific, recommended action.
|||
Part 3: A short summary description for a title.
"""
    API_URL = "https://router.huggingface.co/v1/chat/completions"
    HF_TOKEN = settings.HF_TOKEN
    headers = { "Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json" }
    payload = { "messages": [{"role": "user", "content": prompt_template}], "model": "meta-llama/Meta-Llama-3-8B-Instruct", "stream": False }
    response = requests.post(API_URL, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"--- [TASK LOGIC] Error from API. Status: {response.status_code}")
        return

    response_data = response.json()
    try:
        llm_text_response = response_data['choices'][0]['message']['content']
        print(f"--- [TASK LOGIC] SUCCESS! AI Response received.")
        
        # --- BULLETPROOF PARSING LOGIC ---
        # Use regular expressions to split, allowing for whitespace and extra text
        parts = re.split(r'\s*\|\|\|\s*', llm_text_response.strip())
        
        if len(parts) == 3:
            # Clean each part aggressively
            analysis = re.sub(r'^\s*Part \d:.*?\n', '', parts[0]).strip()
            action = re.sub(r'^\s*Part \d:.*?\n', '', parts[1]).strip()
            summary = re.sub(r'^\s*Part \d:.*?\n', '', parts[2]).strip()

            # Further cleaning to remove common AI artifacts
            analysis = analysis.replace("Impact Analysis:", "").strip()
            action = action.replace("Recommended Action:", "").strip()
            summary = summary.replace("Summary Description:", "").strip()

            if not all([analysis, action, summary]):
                 print(f"--- [TASK LOGIC] ERROR: One of the parsed parts is empty after cleaning. Full response: {llm_text_response}")
                 return

            new_alert = Alert.objects.create(
                impact_analysis=analysis,
                recommended_action=action,
                summary_description=summary
            )
            print(f"--- [TASK LOGIC] Successfully saved Alert ID: {new_alert.id} to the database. ---")
        else:
            print(f"--- [TASK LOGIC] ERROR: LLM response could not be split into 3 parts. Parts found: {len(parts)}. Full response: {llm_text_response}")

    except Exception as e:
        print(f"--- [TASK LOGIC] Error processing response or saving to DB: {e}")
