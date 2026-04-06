from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from neomodel import db

from .decision_engine import build_decision_packet
from .models import Alert
from .retrieval import fetch_supporting_evidence

logger = logging.getLogger(__name__)


@dataclass
class GraphLookup:
    event_type: str
    event_target: str
    query: str
    params: dict[str, Any]


def run_impact_analysis(event_data, save_to_db=True):
    try:
        graph_lookup = _build_graph_lookup(event_data)
        impacted_assets: list[dict[str, str]] = []

        try:
            results, _ = db.cypher_query(graph_lookup.query, graph_lookup.params)
            impacted_assets = _normalize_graph_rows(results)
        except Exception as exc:
            logger.warning("Graph lookup failed; using fallback impacted assets: %s", exc)

        if not impacted_assets:
            if bool(getattr(settings, 'ENABLE_GRAPH_FALLBACK', True)):
                impacted_assets = _fallback_impacted_assets(graph_lookup, event_data)
                logger.info(
                    "Using fallback impacted assets for event target %s: %s rows",
                    graph_lookup.event_target,
                    len(impacted_assets),
                )
            else:
                logger.info("No impacted assets found for event: %s", event_data)
                return None

        enriched_event_data = dict(event_data)
        enriched_event_data.setdefault("event_type", graph_lookup.event_type)
        enriched_event_data.setdefault("event_target", graph_lookup.event_target)

        if "product_skus" not in enriched_event_data:
            enriched_event_data["product_skus"] = normalize_string_list(
                event_data.get("product_skus") or event_data.get("product_sku")
            )
        if "route_ids" not in enriched_event_data:
            enriched_event_data["route_ids"] = normalize_string_list(
                event_data.get("route_ids") or event_data.get("route_id")
            )

        evidence = fetch_supporting_evidence(enriched_event_data)
        decision = build_decision_packet(enriched_event_data, impacted_assets, evidence)
        payload = decision.to_model_payload()

        if save_to_db:
            new_alert = Alert.objects.create(**payload)
            payload["id"] = new_alert.id

        return payload
    except ValueError as exc:
        logger.warning("Invalid event payload: %s", exc)
        return None
    except Exception as exc:
        logger.exception("Impact analysis failed: %s", exc)
        return None


def _build_graph_lookup(event_data: dict[str, Any]) -> GraphLookup:
    supplier_name = str(event_data.get('supplier_name', '')).strip()
    location = str(event_data.get('location', '')).strip()
    product_skus = normalize_string_list(event_data.get('product_skus') or event_data.get('product_sku'))
    route_ids = normalize_string_list(event_data.get('route_ids') or event_data.get('route_id'))

    sku_filters = [item.lower() for item in product_skus]
    route_filters = [item.lower() for item in route_ids]
    location_lc = location.lower()
    supplier_lc = supplier_name.lower()

    if supplier_name:
        return GraphLookup(
            event_type=str(event_data.get('event_type') or 'Supplier Disruption'),
            event_target=supplier_name,
            query=(
                "MATCH (s:Supplier)-[:SUPPLIES]->(p:Product)-[:CARRIES]->(r:Route) "
                "OPTIONAL MATCH (r)-[:DESTINED_FOR]->(port:Port) "
                "WHERE toLower(s.name) CONTAINS $supplier_name_lc "
                "AND ($location_lc = '' OR toLower(port.name) CONTAINS $location_lc) "
                "AND (size($sku_filters) = 0 OR toLower(p.sku) IN $sku_filters) "
                "AND (size($route_filters) = 0 OR toLower(r.route_id) IN $route_filters) "
                "RETURN p.sku as product_sku, r.route_id as route_id, "
                "coalesce(port.name, '') as port_name, s.name as supplier_name "
                "LIMIT 120"
            ),
            params={
                'supplier_name_lc': supplier_lc,
                'location_lc': location_lc,
                'sku_filters': sku_filters,
                'route_filters': route_filters,
            },
        )

    if location:
        return GraphLookup(
            event_type=str(event_data.get('event_type') or event_data.get('type') or 'Port Congestion'),
            event_target=location,
            query=(
                "MATCH (port:Port)<-[:DESTINED_FOR]-(r:Route)<-[:CARRIES]-(p:Product) "
                "OPTIONAL MATCH (s:Supplier)-[:SUPPLIES]->(p) "
                "WHERE toLower(port.name) CONTAINS $location_lc "
                "AND ($supplier_lc = '' OR toLower(s.name) CONTAINS $supplier_lc) "
                "AND (size($sku_filters) = 0 OR toLower(p.sku) IN $sku_filters) "
                "AND (size($route_filters) = 0 OR toLower(r.route_id) IN $route_filters) "
                "RETURN p.sku as product_sku, r.route_id as route_id, "
                "coalesce(port.name, '') as port_name, coalesce(s.name, '') as supplier_name "
                "LIMIT 120"
            ),
            params={
                'location_lc': location_lc,
                'supplier_lc': supplier_lc,
                'sku_filters': sku_filters,
                'route_filters': route_filters,
            },
        )

    if product_skus or route_ids:
        target = ', '.join((product_skus + route_ids)[:2])
        target = target or 'selected assets'
        return GraphLookup(
            event_type=str(event_data.get('event_type') or 'Supply Network Disruption'),
            event_target=target,
            query=(
                "MATCH (p:Product)-[:CARRIES]->(r:Route) "
                "OPTIONAL MATCH (r)-[:DESTINED_FOR]->(port:Port) "
                "OPTIONAL MATCH (s:Supplier)-[:SUPPLIES]->(p) "
                "WHERE (size($sku_filters) = 0 OR toLower(p.sku) IN $sku_filters) "
                "AND (size($route_filters) = 0 OR toLower(r.route_id) IN $route_filters) "
                "RETURN p.sku as product_sku, r.route_id as route_id, "
                "coalesce(port.name, '') as port_name, coalesce(s.name, '') as supplier_name "
                "LIMIT 120"
            ),
            params={
                'sku_filters': sku_filters,
                'route_filters': route_filters,
            },
        )

    raise ValueError('Event payload must include location, supplier_name, product_skus, or route_ids.')


def _normalize_graph_rows(rows: list[list[Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not row:
            continue

        product_sku = str(row[0] or '').strip() if len(row) > 0 else ''
        route_id = str(row[1] or '').strip() if len(row) > 1 else ''
        port_name = str(row[2] or '').strip() if len(row) > 2 else ''
        supplier_name = str(row[3] or '').strip() if len(row) > 3 else ''

        if not product_sku and not route_id:
            continue

        normalized.append(
            {
                "product_sku": product_sku or "UNKNOWN-SKU",
                "route_id": route_id or "UNASSIGNED-ROUTE",
                "port_name": port_name,
                "supplier_name": supplier_name,
            }
        )

    return normalized


def _fallback_impacted_assets(
    graph_lookup: GraphLookup,
    event_data: dict[str, Any],
) -> list[dict[str, str]]:
    target_slug = (
        graph_lookup.event_target.lower()
        .replace(' ', '-')
        .replace('.', '')
        .replace('/', '-')
    )[:24] or "unknown"
    event_slug = graph_lookup.event_type.lower().replace(' ', '-')[:18] or "supply-risk"

    skus = normalize_string_list(event_data.get('product_skus') or event_data.get('product_sku'))
    routes = normalize_string_list(event_data.get('route_ids') or event_data.get('route_id'))

    if not skus:
        skus = [f"SIM-{event_slug}-A", f"SIM-{event_slug}-B"]
    if not routes:
        routes = [f"SIM-{target_slug}-R1", f"SIM-{target_slug}-R2"]

    fallback_rows: list[dict[str, str]] = []
    row_count = max(len(skus), len(routes), 2)
    for idx in range(row_count):
        fallback_rows.append(
            {
                "product_sku": skus[idx % len(skus)],
                "route_id": routes[idx % len(routes)],
                "port_name": str(event_data.get('location', '')).strip(),
                "supplier_name": str(event_data.get('supplier_name', '')).strip(),
            }
        )

    return fallback_rows[:8]


def normalize_string_list(value: Any, max_items: int = 8, max_length: int = 64) -> list[str]:
    raw_items: list[str] = []
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    elif isinstance(value, tuple):
        raw_items = [str(item) for item in value]
    elif isinstance(value, str):
        raw_items = [part for chunk in value.split('\n') for part in chunk.split(',')]
    elif value is not None:
        raw_items = [str(value)]

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = str(raw or '').strip()
        if not item:
            continue
        item = item[:max_length]
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
        if len(cleaned) >= max_items:
            break

    return cleaned
