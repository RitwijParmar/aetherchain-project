from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .genai import generate_decision_narrative


DEFAULT_COST_PER_IMPACTED_ASSET = 6500.0


@dataclass
class DecisionPacket:
    summary_description: str
    impact_analysis: str
    recommended_action: str
    event_type: str
    event_target: str
    risk_score: float
    confidence_score: float
    estimated_delay_days: float
    estimated_cost_impact_usd: float
    evidence_summary: list[dict[str, Any]]
    raw_context: dict[str, Any]

    def to_model_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_decision_packet(
    event_data: dict[str, Any],
    impacted_assets: list[dict[str, str]],
    evidence: list[dict[str, Any]],
) -> DecisionPacket:
    event_type = _normalize_event_type(event_data)
    target = _event_target(event_data)
    impacted_count = len(impacted_assets)
    evidence_count = len(evidence)

    risk_score = _risk_score(event_type, impacted_count, evidence_count)
    confidence_score = _confidence_score(impacted_count, evidence_count)
    estimated_delay_days = _estimated_delay_days(event_type, impacted_count)
    estimated_cost_impact_usd = round(
        risk_score * max(impacted_count, 1) * DEFAULT_COST_PER_IMPACTED_ASSET,
        2,
    )

    summary = f"{event_type} impact on {target}"
    impact_analysis = (
        f"{event_type} at {target} impacts {impacted_count} route-linked assets. "
        f"Estimated delay is {estimated_delay_days:.1f} days with risk score {risk_score:.2f}."
    )
    scope_note = _scenario_scope_note(event_data)
    if scope_note:
        impact_analysis = f"{impact_analysis} {scope_note}"
    recommendation = _recommended_action(event_type, impacted_count)
    narrative_source = "deterministic"

    narrative = generate_decision_narrative(
        event_data=event_data,
        impacted_assets=impacted_assets,
        evidence=evidence,
        deterministic_summary={
            "summary_description": summary,
            "impact_analysis": impact_analysis,
            "recommended_action": recommendation,
            "risk_score": risk_score,
            "confidence_score": confidence_score,
            "estimated_delay_days": estimated_delay_days,
            "estimated_cost_impact_usd": estimated_cost_impact_usd,
        },
    )
    if narrative:
        summary = narrative["summary_description"]
        impact_analysis = narrative["impact_analysis"]
        recommendation = narrative["recommended_action"]
        narrative_source = "vertex_genai"

    return DecisionPacket(
        summary_description=summary,
        impact_analysis=impact_analysis,
        recommended_action=recommendation,
        event_type=event_type,
        event_target=target,
        risk_score=risk_score,
        confidence_score=confidence_score,
        estimated_delay_days=estimated_delay_days,
        estimated_cost_impact_usd=estimated_cost_impact_usd,
        evidence_summary=evidence[:5],
        raw_context={
            "impacted_assets_count": impacted_count,
            "impacted_assets": impacted_assets[:25],
            "evidence_count": evidence_count,
            "narrative_source": narrative_source,
            "scenario_inputs": _scenario_inputs(event_data),
        },
    )


def _normalize_event_type(event_data: dict[str, Any]) -> str:
    raw = (
        event_data.get("event_type")
        or event_data.get("type")
        or ("Supplier Disruption" if event_data.get("supplier_name") else "Port Congestion")
    )
    return str(raw).strip() or "Supply Risk Event"


def _event_target(event_data: dict[str, Any]) -> str:
    product_skus = _normalized_terms(event_data.get("product_skus") or event_data.get("product_sku"))
    route_ids = _normalized_terms(event_data.get("route_ids") or event_data.get("route_id"))
    return (
        str(event_data.get("supplier_name") or "").strip()
        or str(event_data.get("location") or "").strip()
        or ", ".join((product_skus + route_ids)[:2])
        or "Unknown target"
    )


def _risk_score(event_type: str, impacted_count: int, evidence_count: int) -> float:
    lower_type = event_type.lower()
    base = 0.38
    if "supplier" in lower_type:
        base = 0.52
    elif "port" in lower_type or "congestion" in lower_type:
        base = 0.45
    elif "strike" in lower_type:
        base = 0.60
    elif "weather" in lower_type:
        base = 0.40

    asset_factor = min(impacted_count * 0.06, 0.28)
    evidence_factor = min(evidence_count * 0.02, 0.10)
    return round(_clamp(base + asset_factor + evidence_factor, 0.05, 0.98), 2)


def _confidence_score(impacted_count: int, evidence_count: int) -> float:
    base = 0.35
    asset_signal = min(impacted_count * 0.07, 0.35)
    evidence_signal = min(evidence_count * 0.05, 0.25)
    return round(_clamp(base + asset_signal + evidence_signal, 0.10, 0.95), 2)


def _estimated_delay_days(event_type: str, impacted_count: int) -> float:
    lower_type = event_type.lower()
    if "supplier" in lower_type:
        base = 9.0
    elif "port" in lower_type or "congestion" in lower_type:
        base = 6.0
    elif "weather" in lower_type:
        base = 4.5
    else:
        base = 5.5
    return round(base + min(impacted_count * 0.5, 6.0), 1)


def _recommended_action(event_type: str, impacted_count: int) -> str:
    lower_type = event_type.lower()
    if "supplier" in lower_type:
        return (
            "Activate alternate supplier coverage and place contingency purchase "
            "orders for the top impacted SKUs within 4 hours."
        )
    if "port" in lower_type or "congestion" in lower_type:
        return (
            "Rebook priority loads through alternate ports and pre-allocate inland "
            "capacity for the highest-margin SKUs."
        )
    return (
        f"Trigger contingency routing for {max(impacted_count, 1)} impacted assets and "
        "launch an expedited review with operations leadership."
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _scenario_scope_note(event_data: dict[str, Any]) -> str:
    sku_terms = _normalized_terms(event_data.get("product_skus") or event_data.get("product_sku"))
    route_terms = _normalized_terms(event_data.get("route_ids") or event_data.get("route_id"))
    horizon_days = event_data.get("horizon_days")
    business_priority = str(event_data.get("business_priority", "")).strip()

    fragments: list[str] = []
    if sku_terms:
        fragments.append(f"Scope includes {len(sku_terms)} SKU(s).")
    if route_terms:
        fragments.append(f"Scope includes {len(route_terms)} route(s).")
    if isinstance(horizon_days, int) and horizon_days > 0:
        fragments.append(f"Planning horizon: {horizon_days} days.")
    if business_priority:
        fragments.append(f"Priority objective: {business_priority}.")
    return " ".join(fragments).strip()


def _scenario_inputs(event_data: dict[str, Any]) -> dict[str, Any]:
    horizon_days = event_data.get("horizon_days")
    context_note = str(event_data.get("context_note", "")).strip()
    return {
        "location": str(event_data.get("location", "")).strip(),
        "supplier_name": str(event_data.get("supplier_name", "")).strip(),
        "product_skus": _normalized_terms(event_data.get("product_skus") or event_data.get("product_sku")),
        "route_ids": _normalized_terms(event_data.get("route_ids") or event_data.get("route_id")),
        "business_priority": str(event_data.get("business_priority", "")).strip(),
        "horizon_days": int(horizon_days) if isinstance(horizon_days, int) and horizon_days > 0 else None,
        "context_note": context_note[:280],
    }


def _normalized_terms(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        raw_values = [str(item) for item in value]
    elif isinstance(value, tuple):
        raw_values = [str(item) for item in value]
    else:
        raw_values = [part for part in str(value).replace("\n", ",").split(",")]

    values: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        item = raw.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(item[:64])
        if len(values) >= 8:
            break
    return values
