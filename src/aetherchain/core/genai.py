from __future__ import annotations

import json
import logging
from typing import Any

import requests
from django.conf import settings

from .gcp_auth import build_google_auth_headers, resolve_gcp_project_id

logger = logging.getLogger(__name__)


RESPONSE_KEYS = (
    "summary_description",
    "impact_analysis",
    "recommended_action",
)


def generate_decision_narrative(
    event_data: dict[str, Any],
    impacted_assets: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    deterministic_summary: dict[str, Any],
) -> dict[str, str] | None:
    if bool(getattr(settings, "CREDIT_FIRST_MODE", True)):
        return None

    model = str(getattr(settings, "VERTEX_GENAI_MODEL", "")).strip()
    if not model:
        return None

    project_id = resolve_gcp_project_id()
    if not project_id:
        logger.info("Skipping GenAI narrative: GCP project is not configured.")
        return None

    location = str(getattr(settings, "VERTEX_GENAI_LOCATION", "us-central1")).strip() or "us-central1"
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/"
        f"publishers/google/models/{model}:generateContent"
    )

    prompt = _build_prompt(event_data, impacted_assets, evidence, deterministic_summary)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
            "maxOutputTokens": int(getattr(settings, "VERTEX_GENAI_MAX_OUTPUT_TOKENS", 350)),
            "responseMimeType": "application/json",
        },
    }

    try:
        headers = build_google_auth_headers(project_id)
        headers["Content-Type"] = "application/json"
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=getattr(settings, "EXTERNAL_REQUEST_TIMEOUT_SECONDS", 20),
        )
        response.raise_for_status()
        candidate_text = _extract_text(response.json())
        parsed = _extract_json_dict(candidate_text)
        if not parsed:
            return None

        cleaned = {
            key: str(parsed.get(key, "")).strip()
            for key in RESPONSE_KEYS
        }
        if any(not cleaned[key] for key in RESPONSE_KEYS):
            return None

        cleaned["summary_description"] = cleaned["summary_description"][:255]
        return cleaned
    except Exception as exc:
        logger.warning("GenAI narrative generation failed: %s", exc)
        return None


def _build_prompt(
    event_data: dict[str, Any],
    impacted_assets: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    deterministic_summary: dict[str, Any],
) -> str:
    payload = {
        "event_data": event_data,
        "impacted_assets_sample": impacted_assets[:10],
        "impacted_assets_count": len(impacted_assets),
        "evidence_sample": evidence[:5],
        "evidence_count": len(evidence),
        "deterministic_baseline": deterministic_summary,
    }
    data_blob = json.dumps(payload, ensure_ascii=True)
    return (
        "You are generating concise executive decision text for a supply-chain risk event. "
        "Return ONLY valid JSON with keys: summary_description, impact_analysis, recommended_action. "
        "Do not invent facts that are not implied by the input. "
        f"Input: {data_blob}"
    )


def _extract_text(response_data: dict[str, Any]) -> str:
    candidates = response_data.get("candidates")
    if not isinstance(candidates, list):
        return ""

    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        if not isinstance(parts, list):
            continue
        for part in parts:
            text = part.get("text") if isinstance(part, dict) else None
            if text:
                return str(text)
    return ""


def _extract_json_dict(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
