from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_GDELT_QUERY = (
    '("supply chain" OR logistics OR "port congestion" OR '
    '"supplier disruption" OR "factory shutdown" OR "shipping delay")'
)


@dataclass
class IngestStats:
    fetched_articles: int
    prepared_documents: int
    imported_success: int
    imported_failure: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def gdelt_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def stable_document_id(url: str, seen_date: str) -> str:
    seed = f"{url.strip()}|{seen_date.strip()}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]
    return f"gdelt-{digest}"


def normalize_gdelt_query(query: str) -> str:
    cleaned = str(query or "").strip()
    if not cleaned:
        return DEFAULT_GDELT_QUERY

    upper = cleaned.upper()
    has_or = " OR " in upper
    starts_grouped = cleaned.startswith("(") and cleaned.endswith(")")
    if has_or and not starts_grouped:
        return f"({cleaned})"
    return cleaned


def fetch_gdelt_articles(
    query: str,
    start_time: datetime,
    end_time: datetime,
    max_records: int,
    timeout_seconds: int,
    max_attempts: int = 4,
    allow_no_window_fallback: bool = True,
) -> list[dict[str, Any]]:
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(max_records),
        "startdatetime": gdelt_timestamp(start_time),
        "enddatetime": gdelt_timestamp(end_time),
        "sort": "DateDesc",
    }

    articles = _request_gdelt_articles(
        params=params,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )
    if articles or not allow_no_window_fallback:
        return articles

    fallback_params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(max_records),
        "sort": "DateDesc",
    }
    return _request_gdelt_articles(
        params=fallback_params,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


def _request_gdelt_articles(
    *,
    params: dict[str, str],
    timeout_seconds: int,
    max_attempts: int,
) -> list[dict[str, Any]]:
    if max_attempts < 1:
        max_attempts = 1

    for attempt in range(1, max_attempts + 1):
        response = requests.get(
            GDELT_DOC_API_URL,
            params=params,
            timeout=timeout_seconds,
        )

        if response.status_code == 429:
            if attempt < max_attempts:
                time.sleep(5 * attempt)
                continue
            raise RuntimeError(
                "GDELT rate limit reached (HTTP 429). Wait a minute and retry with lower frequency."
            )

        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            if "please limit requests to one every 5 seconds" in text.lower():
                if attempt < max_attempts:
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(
                    "GDELT returned rate-limit message text repeatedly. Retry later."
                )
            return []

        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            return []
        return [item for item in articles if isinstance(item, dict)]

    return []


def build_discovery_documents(
    articles: list[dict[str, Any]],
    query_tag: str,
    max_documents: int,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    ingested_at = utc_now().isoformat()

    for article in articles:
        doc = _article_to_document(article, query_tag=query_tag, ingested_at=ingested_at)
        if not doc:
            continue

        document_id = str(doc.get("id", "")).strip()
        if not document_id or document_id in seen_ids:
            continue

        seen_ids.add(document_id)
        prepared.append(doc)
        if len(prepared) >= max_documents:
            break

    return prepared


def import_discovery_documents_inline(
    *,
    project_number: str,
    project_id: str,
    datastore_id: str,
    documents: list[dict[str, Any]],
    headers: dict[str, str],
    timeout_seconds: int,
    batch_size: int,
) -> tuple[int, int]:
    if not documents:
        return 0, 0

    parent = (
        f"projects/{project_number}/locations/global/collections/default_collection/"
        f"dataStores/{datastore_id}/branches/default_branch"
    )
    import_url = f"https://discoveryengine.googleapis.com/v1/{parent}/documents:import"

    success_total = 0
    failure_total = 0

    for batch in _chunked(documents, batch_size):
        payload = {
            "inlineSource": {"documents": batch},
            "reconciliationMode": "INCREMENTAL",
        }

        response = requests.post(
            import_url,
            headers=headers,
            data=json.dumps(payload),
            timeout=timeout_seconds,
        )
        response.raise_for_status()

        operation = response.json()
        final_op = _wait_for_operation(
            operation=operation,
            headers=headers,
            project_id=project_id,
            timeout_seconds=timeout_seconds,
        )

        metadata = final_op.get("metadata", {}) if isinstance(final_op, dict) else {}
        if isinstance(metadata, dict):
            success_total += _safe_int(metadata.get("successCount"))
            failure_total += _safe_int(metadata.get("failureCount"))
        else:
            success_total += len(batch)

    return success_total, failure_total


def write_json(path: str, payload: Any) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)


def write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def default_window(hours: int) -> tuple[datetime, datetime]:
    end_time = utc_now()
    start_time = end_time - timedelta(hours=hours)
    return start_time, end_time


def _article_to_document(
    article: dict[str, Any],
    *,
    query_tag: str,
    ingested_at: str,
) -> dict[str, Any] | None:
    url = (
        _clean(article.get("url"))
        or _clean(article.get("url_mobile"))
        or _clean(article.get("urlmobile"))
    )
    title = _clean(article.get("title"))
    seen_date = _clean(article.get("seendate"))

    if not url or not title:
        return None

    doc_id = stable_document_id(url=url, seen_date=seen_date)
    language = _clean(article.get("language"))
    source_country = _clean(article.get("sourcecountry"))
    domain = _clean(article.get("domain"))

    summary_text = _compose_document_text(
        title=title,
        url=url,
        domain=domain,
        language=language,
        source_country=source_country,
        query_tag=query_tag,
    )

    return {
        "id": doc_id,
        "structData": {
            "title": title,
            "url": url,
            "domain": domain,
            "language": language,
            "source_country": source_country,
            "seen_date": seen_date,
            "query_tag": query_tag,
            "ingested_at": ingested_at,
        },
        "content": {
            "mimeType": "text/plain",
            "rawBytes": base64.b64encode(summary_text.encode("utf-8")).decode("ascii"),
        },
    }


def _compose_document_text(
    *,
    title: str,
    url: str,
    domain: str,
    language: str,
    source_country: str,
    query_tag: str,
) -> str:
    parts = [
        f"Title: {title}",
        f"Source URL: {url}",
        f"Source Domain: {domain}",
        f"Language: {language}",
        f"Source Country: {source_country}",
        f"Matched Query: {query_tag}",
    ]
    text = "\n".join([part for part in parts if part.strip()])
    return text[:4000]


def _wait_for_operation(
    *,
    operation: dict[str, Any],
    headers: dict[str, str],
    project_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not isinstance(operation, dict):
        return operation
    if operation.get("done"):
        return operation

    op_name = str(operation.get("name", "")).strip()
    if not op_name:
        return operation

    op_url = f"https://discoveryengine.googleapis.com/v1/{op_name}"
    deadline = time.time() + max(timeout_seconds, 20)

    while time.time() < deadline:
        response = requests.get(op_url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        current = response.json()
        if current.get("done"):
            if current.get("error"):
                raise RuntimeError(
                    f"Discovery import operation failed for {project_id}: {current['error']}"
                )
            return current
        time.sleep(2)

    raise RuntimeError(f"Timed out waiting for operation {op_name}")


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
