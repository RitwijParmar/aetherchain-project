import os
import requests
import json
from dotenv import load_dotenv
from .models import Port, Alert
from neomodel import db

load_dotenv()



CONTEXT:
- A "{event_type}" event is happening at the "{event_location}".
- Our knowledge graph shows the following assets are directly impacted: {affected_assets_str}.
- Historical precedent for this type of event suggests delays of 10-15 days.
- An alternative mitigation route is available through the 'Port of Seattle'.

TASK:
Generate a concise, actionable alert in three parts separated by "|||". Do not add any extra formatting, numbering, or newlines.
1. Impact Analysis: A one-sentence summary of the business impact.
2. Recommended Action: The single most important next step to mitigate the risk.
3. Summary Description: A short description for the alert title, like "Congestion at Port of Los Angeles".
"""
    
    API_URL = "https://router.huggingface.co/v1/chat/completions"
    
    HF_TOKEN = "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" # Hardcoded Token
    
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messages": [{"role": "user", "content": prompt_template}],
        "model": "meta-llama/Meta-Llama-3-8B-Instruct", # <-- THE FINAL FIX IS HERE
        "stream": False
    }
    
    response = requests.post(API_URL, headers=headers, json=payload)
    
    if response.status_code != 200:
        print(f"Error from Hugging Face API. Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        return

    response_data = response.json()
    
    print("Processing LLM response and saving to database...")
    try:
        llm_text_response = response_data['choices'][0]['message']['content']
        cleaned_text = llm_text_response.strip().replace('\n', '')
        parts = cleaned_text.split('|||')
        impact = parts[0].strip()
        recommendation = parts[1].strip()
        description = parts[2].strip()
        alert = Alert.objects.create(event_description=description, impact_analysis=impact, recommendation=recommendation)
        print(f"--- Successfully created Alert ID: {alert.id} ---")
    except (KeyError, IndexError, Exception) as e:
        print(f"Error processing Hugging Face response: {e}\nFull response was:\n---\n{response_data}\n---")
