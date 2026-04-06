from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

from .gcp_auth import build_google_auth_headers

logger = logging.getLogger(__name__)


def fetch_supporting_evidence(event_data: dict[str, Any]) -> list[dict[str, Any]]:
    serving_config = getattr(settings, "VERTEX_SEARCH_SERVING_CONFIG", "").strip()
    if not serving_config:
        return []

    query = _build_search_query(event_data)
    url = f"https://discoveryengine.googleapis.com/v1/{serving_config}:search"
    timeout_seconds = getattr(settings, "EXTERNAL_REQUEST_TIMEOUT_SECONDS", 20)
    headers = build_google_auth_headers()
    headers["Content-Type"] = "application/json"

    use_summary = bool(getattr(settings, "VERTEX_SEARCH_ENABLE_SUMMARY", True))
    payload = _build_search_payload(query=query, include_summary=use_summary)

    response_data = _execute_search(
        url=url,
        headers=headers,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )
    if response_data is None and use_summary:
        logger.info("Retrying Discovery search without summarySpec fallback.")
        payload = _build_search_payload(query=query, include_summary=False)
        response_data = _execute_search(
            url=url,
            headers=headers,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )

    if not isinstance(response_data, dict):
        return []

    evidence: list[dict[str, Any]] = []
    summary_text = _extract_summary_text(response_data)
    if summary_text:
        evidence.append(
            {
                "title": "Discovery Summary",
                "uri": "",
                "snippet": summary_text,
                "score": None,
            }
        )

    for result in response_data.get("results", []):
        document = result.get("document", {})
        derived_data = document.get("derivedStructData", {})
        snippets = derived_data.get("snippets", []) if isinstance(derived_data, dict) else []
        snippet_text = ""
        if snippets and isinstance(snippets, list):
            snippet_text = str(snippets[0].get("snippet", "")).strip()

        title = (
            str(document.get("title", "")).strip()
            or str(derived_data.get("title", "")).strip()
            or str(document.get("id", "Untitled"))
        )
        uri = (
            str(derived_data.get("link", "")).strip()
            or str(derived_data.get("uri", "")).strip()
            or str(document.get("uri", "")).strip()
        )

        evidence.append(
            {
                "title": title,
                "uri": uri,
                "snippet": snippet_text,
                "score": result.get("relevanceScore"),
            }
        )
    return evidence


def _build_search_payload(*, query: str, include_summary: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "pageSize": getattr(settings, "VERTEX_SEARCH_MAX_RESULTS", 8),
        "queryExpansionSpec": {"condition": "AUTO"},
        "spellCorrectionSpec": {"mode": "AUTO"},
        "contentSearchSpec": {"snippetSpec": {"returnSnippet": True}},
    }
    if include_summary:
        payload["contentSearchSpec"]["summarySpec"] = {
            "summaryResultCount": max(int(getattr(settings, "VERTEX_SEARCH_SUMMARY_RESULT_COUNT", 3)), 1),
            "includeCitations": True,
            "ignoreAdversarialQuery": True,
            "ignoreNonSummarySeekingQuery": False,
        }
    return payload


def _execute_search(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any] | None:
    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        response_data = response.json()
        return response_data if isinstance(response_data, dict) else None
    except Exception as exc:
        logger.warning("Vertex AI Search retrieval failed: %s", exc)
        return None


def _extract_summary_text(response_data: dict[str, Any]) -> str:
    summary = response_data.get("summary")
    if not isinstance(summary, dict):
        return ""
    return str(summary.get("summaryText", "")).strip()


def _build_search_query(event_data: dict[str, Any]) -> str:
    sku_terms = _normalize_terms(event_data.get("product_skus") or event_data.get("product_sku"))
    route_terms = _normalize_terms(event_data.get("route_ids") or event_data.get("route_id"))
    business_priority = str(event_data.get("business_priority", "")).strip()
    context_note = str(event_data.get("context_note", "")).strip()
    horizon_days = event_data.get("horizon_days")

    focus_tokens: list[str] = []
    if sku_terms:
        focus_tokens.append(f"focus sku {' '.join(sku_terms[:3])}")
    if route_terms:
        focus_tokens.append(f"focus routes {' '.join(route_terms[:3])}")
    if business_priority:
        focus_tokens.append(f"priority {business_priority}")
    if isinstance(horizon_days, int) and horizon_days > 0:
        focus_tokens.append(f"planning horizon {horizon_days} days")
    if context_note:
        focus_tokens.append(context_note[:140])

    focus_suffix = " ".join(focus_tokens).strip()

    if event_data.get("supplier_name"):
        base = (
            f"supplier disruption for {event_data['supplier_name']} "
            f"mitigation playbooks alternative sourcing route impact"
        )
        return f"{base} {focus_suffix}".strip()
    if event_data.get("location"):
        base = (
            f"port disruption at {event_data['location']} "
            f"rerouting mitigation lead time impact"
        )
        return f"{base} {focus_suffix}".strip()

    base = str(event_data.get("description", "supply chain disruption analysis"))
    return f"{base} {focus_suffix}".strip()


def _normalize_terms(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        raw_values = [str(item) for item in value]
    elif isinstance(value, tuple):
        raw_values = [str(item) for item in value]
    else:
        raw_values = [part for part in str(value).replace("\n", ",").split(",")]

    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        item = raw.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(item[:64])
        if len(terms) >= 8:
            break
    return terms
