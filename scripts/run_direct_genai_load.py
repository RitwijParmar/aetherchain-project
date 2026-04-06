#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import math
import os
import random
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

ANSWER_QUERIES = [
    "What are the highest-impact supply chain disruption risks this week and the top mitigations?",
    "Summarize expected delay drivers for ocean freight and the fastest operational countermeasures.",
    "Given port congestion and weather risk, what should we prioritize in the next 48 hours?",
    "Which supplier risk signals should trigger immediate rerouting versus wait-and-watch?",
    "Propose a concise risk response plan for inventory with high stockout probability.",
    "What are likely root causes of customs clearance delays and preventive controls?",
    "How should we sequence mitigation when both lead-time risk and quality risk are rising?",
    "What governance checks should we run before switching to alternate suppliers?",
]

PLAYBOOK_QUERIES = [
    "How should we prioritize suppliers for expedited shipping this week?",
    "We have rising delays in two lanes. What should we do first?",
    "Suggest a practical plan for handling sudden port congestion in North America.",
    "Our high-margin SKUs are at risk of stockout. Give a short action plan.",
    "How do we decide between air freight uplift and customer ETA renegotiation?",
    "What escalation path should operations follow for supplier reliability drop?",
    "Give me a decision checklist for route disruption due to weather.",
    "What metrics should daily ops review before changing sourcing allocation?",
]


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * (p / 100.0)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(sorted_values[lower])
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return float(lower_value + (upper_value - lower_value) * (index - lower))


class TokenProvider:
    def __init__(self, gcloud_bin: str, project_id: str):
        self.gcloud_bin = gcloud_bin
        self.project_id = project_id
        self._token = ""
        self._refresh_after = 0.0
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        token = run([self.gcloud_bin, "auth", "print-access-token", "--project", self.project_id])
        self._token = token
        self._refresh_after = time.time() + 45 * 60

    def auth_headers(self) -> dict[str, str]:
        with self._lock:
            if not self._token or time.time() >= self._refresh_after:
                self._refresh()
            token = self._token
        return {
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": self.project_id,
            "Content-Type": "application/json",
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate direct GenAI load against Vertex AI Search Answer API and Conversational Agents "
            "Playbook detectIntent API, without Cloud Run /api/simulate traffic."
        )
    )
    parser.add_argument("--project-id", default=os.getenv("PROJECT_ID", "project-2281c357-4539-4bc6-b96"))
    parser.add_argument("--project-number", default="")
    parser.add_argument("--gcloud-bin", default="./google-cloud-sdk/bin/gcloud")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--user-prefix", default="credit-burn")
    parser.add_argument("--session-pool-size", type=int, default=64)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--max-retries", type=int, default=2)

    parser.add_argument("--engine-id", default="supplynerva-enterprise")
    parser.add_argument("--serving-config", default="")
    parser.add_argument("--serving-config-secret", default="aetherchain-vertex-search-serving-config")
    parser.add_argument("--answer-count", type=int, default=2000)
    parser.add_argument("--answer-concurrency", type=int, default=24)
    parser.add_argument("--answer-qps", type=float, default=35.0)
    parser.add_argument("--answer-price-per-1k", type=float, default=8.0)

    parser.add_argument("--playbook-count", type=int, default=1000)
    parser.add_argument("--playbook-concurrency", type=int, default=16)
    parser.add_argument("--playbook-qps", type=float, default=18.0)
    parser.add_argument("--playbook-location", default="global")
    parser.add_argument("--playbook-agent-name", default="")
    parser.add_argument("--playbook-name", default="")
    parser.add_argument("--playbook-agent-display-name", default="SupplyNerva Playbook Agent")
    parser.add_argument("--playbook-display-name", default="Supply Operations Copilot")
    parser.add_argument("--playbook-price-per-1k", type=float, default=0.0)
    return parser.parse_args()


def resolve_gcloud_bin(explicit: str) -> str:
    if explicit and Path(explicit).exists():
        return explicit
    if explicit and "/" not in explicit:
        found = subprocess.run(["which", explicit], text=True, capture_output=True)
        if found.returncode == 0:
            return found.stdout.strip()
    if Path("/Users/ritwij/google-cloud-sdk/bin/gcloud").exists():
        return "/Users/ritwij/google-cloud-sdk/bin/gcloud"
    raise RuntimeError("gcloud binary not found. Set --gcloud-bin explicitly.")


def resolve_project_number(project_id: str, gcloud_bin: str, explicit: str) -> str:
    if explicit:
        return explicit
    return run([gcloud_bin, "projects", "describe", project_id, "--format=value(projectNumber)"])


def try_read_secret(project_id: str, gcloud_bin: str, secret_name: str) -> str:
    cmd = [
        gcloud_bin,
        "secrets",
        "versions",
        "access",
        "latest",
        "--secret",
        secret_name,
        "--project",
        project_id,
    ]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def resolve_serving_config(
    project_id: str,
    project_number: str,
    engine_id: str,
    gcloud_bin: str,
    serving_config: str,
    serving_config_secret: str,
) -> str:
    if serving_config:
        return serving_config

    secret_value = try_read_secret(project_id, gcloud_bin, serving_config_secret)
    if secret_value:
        return secret_value

    return (
        f"projects/{project_number}/locations/global/collections/default_collection/"
        f"engines/{engine_id}/servingConfigs/default_search"
    )


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: int = 45,
) -> tuple[int, dict[str, Any] | None, str]:
    response = requests.request(
        method,
        url,
        headers=headers,
        data=json.dumps(payload) if payload is not None else None,
        timeout=timeout,
    )
    body: dict[str, Any] | None = None
    raw = ""
    try:
        body = response.json()
    except Exception:
        raw = response.text
    return response.status_code, body, raw


def verify_discovery_engine_config(serving_config: str, token_provider: TokenProvider, timeout: int) -> dict[str, Any]:
    engine_name = serving_config.split("/servingConfigs/")[0]
    url = f"https://discoveryengine.googleapis.com/v1/{engine_name}"
    status, body, raw = _request_json(
        method="GET",
        url=url,
        headers=token_provider.auth_headers(),
        timeout=timeout,
    )
    if status >= 300 or not isinstance(body, dict):
        raise RuntimeError(f"Could not fetch engine config ({status}): {body or raw}")
    return body


def discover_playbook_resources(
    *,
    project_id: str,
    location: str,
    token_provider: TokenProvider,
    playbook_agent_name: str,
    playbook_name: str,
    playbook_agent_display_name: str,
    playbook_display_name: str,
    timeout: int,
) -> tuple[str, str, str]:
    api_host = "global-dialogflow.googleapis.com" if location == "global" else f"{location}-dialogflow.googleapis.com"

    if playbook_name and playbook_agent_name:
        return api_host, playbook_agent_name, playbook_name

    agent_name = playbook_agent_name
    if not agent_name:
        list_agents_url = f"https://{api_host}/v3/projects/{project_id}/locations/{location}/agents"
        status, body, raw = _request_json(
            method="GET",
            url=list_agents_url,
            headers=token_provider.auth_headers(),
            timeout=timeout,
        )
        if status >= 300 or not isinstance(body, dict):
            raise RuntimeError(f"Could not list agents ({status}): {body or raw}")
        agents = body.get("agents", [])
        for agent in agents:
            if agent.get("displayName") == playbook_agent_display_name:
                agent_name = str(agent.get("name", ""))
                break
        if not agent_name and len(agents) == 1:
            agent_name = str(agents[0].get("name", ""))

    if not agent_name:
        raise RuntimeError(
            "No playbook agent resolved. Pass --playbook-agent-name or run scripts/provision_playbook_agent.py first."
        )

    resolved_playbook_name = playbook_name
    if not resolved_playbook_name:
        list_playbooks_url = f"https://{api_host}/v3/{agent_name}/playbooks"
        status, body, raw = _request_json(
            method="GET",
            url=list_playbooks_url,
            headers=token_provider.auth_headers(),
            timeout=timeout,
        )
        if status >= 300 or not isinstance(body, dict):
            raise RuntimeError(f"Could not list playbooks ({status}): {body or raw}")
        playbooks = body.get("playbooks", [])
        for playbook in playbooks:
            if playbook.get("displayName") == playbook_display_name:
                resolved_playbook_name = str(playbook.get("name", ""))
                break
        if not resolved_playbook_name and len(playbooks) == 1:
            resolved_playbook_name = str(playbooks[0].get("name", ""))

    if not resolved_playbook_name:
        raise RuntimeError(
            "No playbook resolved. Pass --playbook-name or run scripts/provision_playbook_agent.py first."
        )
    return api_host, agent_name, resolved_playbook_name


def summarize_stats(
    label: str,
    status_counts: dict[str, int],
    latencies_ms: list[float],
    duration_s: float,
    total_requests: int,
) -> dict[str, Any]:
    total = total_requests
    ok = status_counts.get("ok", 0)
    failed = total - ok
    qps = total / duration_s if duration_s > 0 else 0.0
    return {
        "label": label,
        "total": total,
        "ok": ok,
        "failed": failed,
        "success_rate": (ok / total) if total else 0.0,
        "duration_seconds": duration_s,
        "observed_qps": qps,
        "latency_ms_avg": statistics.mean(latencies_ms) if latencies_ms else 0.0,
        "latency_ms_p50": percentile(latencies_ms, 50),
        "latency_ms_p95": percentile(latencies_ms, 95),
        "status_counts": status_counts,
    }


def run_load(
    *,
    label: str,
    count: int,
    concurrency: int,
    qps: float,
    worker: Callable[[int], tuple[bool, float, str]],
) -> dict[str, Any]:
    if count <= 0:
        return summarize_stats(label, {"ok": 0}, [], 0.0, total_requests=0)

    interval = (1.0 / qps) if qps > 0 else 0.0
    next_submit = time.perf_counter()

    status_counts: dict[str, int] = {}
    latencies: list[float] = []
    start = time.perf_counter()

    def record(ok: bool, latency_ms: float, code: str) -> None:
        latencies.append(latency_ms)
        status_counts["ok" if ok else "fail"] = status_counts.get("ok" if ok else "fail", 0) + 1
        status_counts[code] = status_counts.get(code, 0) + 1

    with futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        pending: dict[futures.Future[tuple[bool, float, str]], int] = {}
        submitted = 0

        while submitted < count or pending:
            while submitted < count and len(pending) < max(1, concurrency):
                if interval > 0:
                    now = time.perf_counter()
                    if now < next_submit:
                        time.sleep(next_submit - now)
                        now = time.perf_counter()
                    next_submit = now + interval
                future = pool.submit(worker, submitted)
                pending[future] = submitted
                submitted += 1

            if not pending:
                continue

            done, _ = futures.wait(pending.keys(), return_when=futures.FIRST_COMPLETED)
            for finished in done:
                pending.pop(finished, None)
                ok, latency_ms, code = finished.result()
                record(ok, latency_ms, code)

    duration = time.perf_counter() - start
    return summarize_stats(label, status_counts, latencies, duration, total_requests=count)


def main() -> int:
    args = parse_args()
    random.seed(args.seed)

    gcloud_bin = resolve_gcloud_bin(args.gcloud_bin)
    project_number = resolve_project_number(args.project_id, gcloud_bin, args.project_number)
    token_provider = TokenProvider(gcloud_bin=gcloud_bin, project_id=args.project_id)

    serving_config = resolve_serving_config(
        project_id=args.project_id,
        project_number=project_number,
        engine_id=args.engine_id,
        gcloud_bin=gcloud_bin,
        serving_config=args.serving_config,
        serving_config_secret=args.serving_config_secret,
    )

    engine = verify_discovery_engine_config(
        serving_config=serving_config,
        token_provider=token_provider,
        timeout=args.timeout_seconds,
    )
    search_config = ((engine.get("searchEngineConfig") or {}) if isinstance(engine, dict) else {})

    playbook_api_host = ""
    playbook_agent_name = args.playbook_agent_name
    playbook_name = args.playbook_name
    if args.playbook_count > 0:
        playbook_api_host, playbook_agent_name, playbook_name = discover_playbook_resources(
            project_id=args.project_id,
            location=args.playbook_location,
            token_provider=token_provider,
            playbook_agent_name=args.playbook_agent_name,
            playbook_name=args.playbook_name,
            playbook_agent_display_name=args.playbook_agent_display_name,
            playbook_display_name=args.playbook_display_name,
            timeout=args.timeout_seconds,
        )

    answer_url = f"https://discoveryengine.googleapis.com/v1/{serving_config}:answer"

    def request_with_retries(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str, float]:
        start = time.perf_counter()
        attempt = 0
        while True:
            status, body, raw = _request_json(
                method="POST",
                url=url,
                headers=token_provider.auth_headers(),
                payload=payload,
                timeout=args.timeout_seconds,
            )
            retryable = status in {429, 500, 503, 504}
            if retryable and attempt < args.max_retries:
                backoff = (0.35 * (2**attempt)) + (random.random() * 0.15)
                time.sleep(backoff)
                attempt += 1
                continue
            latency_ms = (time.perf_counter() - start) * 1000.0
            return status, body, raw, latency_ms

    def answer_worker(index: int) -> tuple[bool, float, str]:
        query = ANSWER_QUERIES[index % len(ANSWER_QUERIES)]
        payload = {
            "query": {"text": query},
            "answerGenerationSpec": {"includeCitations": True, "answerLanguageCode": "en"},
            "userPseudoId": f"{args.user_prefix}-search-{index}",
        }
        status, body, raw, latency_ms = request_with_retries(answer_url, payload)
        if status >= 300:
            return False, latency_ms, f"http_{status}"
        if not isinstance(body, dict):
            return False, latency_ms, "bad_json"
        if "error" in body:
            return False, latency_ms, "api_error"
        answer = body.get("answer") or {}
        if answer.get("state") and answer.get("state") != "SUCCEEDED":
            return False, latency_ms, f"answer_{answer.get('state', 'unknown').lower()}"
        if not answer.get("answerText"):
            return False, latency_ms, "empty_answer"
        return True, latency_ms, "http_200"

    def playbook_worker(index: int) -> tuple[bool, float, str]:
        query = PLAYBOOK_QUERIES[index % len(PLAYBOOK_QUERIES)]
        session_suffix = index % max(1, args.session_pool_size)
        session = f"{playbook_agent_name}/sessions/{args.user_prefix}-pb-{session_suffix}"
        payload = {
            "queryInput": {
                "text": {"text": query},
                "languageCode": "en",
            },
            "queryParams": {
                "currentPlaybook": playbook_name,
            },
        }
        url = f"https://{playbook_api_host}/v3/{session}:detectIntent"
        status, body, raw, latency_ms = request_with_retries(url, payload)
        if status >= 300:
            return False, latency_ms, f"http_{status}"
        if not isinstance(body, dict):
            return False, latency_ms, "bad_json"
        if "error" in body:
            return False, latency_ms, "api_error"
        match_type = (((body.get("queryResult") or {}).get("match") or {}).get("matchType") or "")
        if match_type != "PLAYBOOK":
            return False, latency_ms, f"match_{match_type or 'none'}"
        return True, latency_ms, "http_200"

    print(f"Project: {args.project_id} ({project_number})")
    print(f"Serving config: {serving_config}")
    print(
        "Engine search config: "
        f"tier={search_config.get('searchTier')} addOns={search_config.get('searchAddOns', [])}"
    )
    if args.playbook_count > 0:
        print(f"Playbook agent: {playbook_agent_name}")
        print(f"Playbook: {playbook_name}")

    answer_stats = run_load(
        label="vertex_search_answer",
        count=args.answer_count,
        concurrency=args.answer_concurrency,
        qps=args.answer_qps,
        worker=answer_worker,
    )
    playbook_stats = run_load(
        label="playbook_detect_intent",
        count=args.playbook_count,
        concurrency=args.playbook_concurrency,
        qps=args.playbook_qps,
        worker=playbook_worker,
    )

    est_answer_cost = (args.answer_count / 1000.0) * args.answer_price_per_1k
    est_playbook_cost = (args.playbook_count / 1000.0) * args.playbook_price_per_1k
    est_total_cost = est_answer_cost + est_playbook_cost

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        Path(args.output_json)
        if args.output_json
        else Path("reports/genai_load") / f"direct_genai_load_{now}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at_utc": now,
        "project_id": args.project_id,
        "project_number": project_number,
        "serving_config": serving_config,
        "engine_search_config": search_config,
        "playbook_location": args.playbook_location,
        "playbook_agent_name": playbook_agent_name,
        "playbook_name": playbook_name,
        "answer_stats": answer_stats,
        "playbook_stats": playbook_stats,
        "cost_estimate_usd": {
            "answer_price_per_1k": args.answer_price_per_1k,
            "playbook_price_per_1k": args.playbook_price_per_1k,
            "estimated_answer_cost": est_answer_cost,
            "estimated_playbook_cost": est_playbook_cost,
            "estimated_total_cost": est_total_cost,
        },
    }
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report["answer_stats"], indent=2))
    print(json.dumps(report["playbook_stats"], indent=2))
    print(
        "Estimated direct-traffic spend (USD): "
        f"answer={est_answer_cost:.2f}, playbook={est_playbook_cost:.2f}, total={est_total_cost:.2f}"
    )
    print(f"Report: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
