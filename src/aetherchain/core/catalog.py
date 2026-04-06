from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from neomodel import db

logger = logging.getLogger(__name__)

CATALOG_KINDS = ("ports", "suppliers", "skus", "routes")

FALLBACK_CATALOG: dict[str, list[str]] = {
    "ports": [
        "Port of Los Angeles",
        "Port of Long Beach",
        "Port of New York and New Jersey",
        "Port of Savannah",
        "Port of Houston",
        "Port of Seattle",
        "Port of Oakland",
        "Port of Rotterdam",
        "Port of Antwerp-Bruges",
        "Port of Hamburg",
        "Port of Bremerhaven",
        "Port of Singapore",
        "Port Klang",
        "Port of Tanjung Pelepas",
        "Port of Shanghai",
        "Port of Ningbo-Zhoushan",
        "Port of Shenzhen",
        "Port of Busan",
        "Port of Jebel Ali",
        "Port of Santos",
    ],
    "suppliers": [
        "Vietnam Footwear Co.",
        "Pacific Components Ltd.",
        "Andes Textiles Group",
        "Pacific Apparel Supplier",
        "Delta Semicon Manufacturing",
        "Shenzhen Assembly Hub",
        "Nordic Specialty Chemicals",
        "Mekong Electronics Partners",
        "Atlas Auto Systems",
        "BlueHarbor Packaging",
        "Rhein Industrial Plastics",
        "Iberia Precision Metals",
        "Kanto Mobility Components",
        "Gujarat Agro Inputs",
        "Qingdao Marine Systems",
    ],
    "skus": [
        "SHOE-ABC",
        "BOOT-XYZ",
        "APP-321",
        "APP-998",
        "ELEC-154",
        "ELEC-212",
        "MED-440",
        "AUTO-778",
        "PACK-006",
        "CHEM-331",
        "AGRO-782",
        "HOME-165",
        "FASH-905",
        "SPRT-781",
        "TOOL-249",
    ],
    "routes": [
        "VNHCM-USLAX",
        "VNHCM-USSEA",
        "CNSHA-USLAX",
        "NLRTM-USNYC",
        "SGSIN-USLGB",
        "CNSZX-USLAX",
        "KRPUS-USSEA",
        "DEHAM-USSAV",
        "AEJEA-USHOU",
        "BRSSZ-USMIA",
        "MYPKG-USOAK",
        "INMUN-USNYC",
    ],
}


@dataclass
class CatalogContext:
    q: str
    q_lc: str
    location_lc: str
    supplier_lc: str
    limit: int


def load_catalog_snapshot(
    *,
    q: str = "",
    location: str = "",
    supplier_name: str = "",
    kind: str = "all",
    limit: int = 20,
) -> dict[str, Any]:
    normalized_kind = str(kind or "all").strip().lower()
    if normalized_kind not in {"all", *CATALOG_KINDS}:
        normalized_kind = "all"

    normalized_limit = max(5, min(int(limit or 20), 50))
    context = CatalogContext(
        q=str(q or "").strip(),
        q_lc=str(q or "").strip().lower(),
        location_lc=str(location or "").strip().lower(),
        supplier_lc=str(supplier_name or "").strip().lower(),
        limit=normalized_limit,
    )

    requested_kinds = CATALOG_KINDS if normalized_kind == "all" else (normalized_kind,)
    graph_catalog = _fetch_graph_catalog(context, requested_kinds)
    has_graph_data = any(bool(graph_catalog.get(kind_name)) for kind_name in requested_kinds)

    source = "neo4j" if has_graph_data else "fallback"
    snapshot: dict[str, Any] = {
        "source": source,
        "query": context.q,
    }

    for kind_name in requested_kinds:
        graph_items = graph_catalog.get(kind_name, [])
        fallback_items = _filter_options(FALLBACK_CATALOG[kind_name], context.q_lc)
        snapshot[kind_name] = _dedupe_with_limit(graph_items + fallback_items, context.limit)

    if normalized_kind != "all":
        snapshot["kind"] = normalized_kind

    return snapshot


def _fetch_graph_catalog(context: CatalogContext, requested_kinds: tuple[str, ...]) -> dict[str, list[str]]:
    params = {
        "q": context.q_lc,
        "location": context.location_lc,
        "supplier": context.supplier_lc,
        "limit": context.limit,
    }

    queries: dict[str, str] = {
        "ports": (
            "MATCH (port:Port) "
            "WHERE $q = '' OR toLower(port.name) CONTAINS $q "
            "RETURN DISTINCT port.name AS value "
            "ORDER BY value LIMIT $limit"
        ),
        "suppliers": (
            "MATCH (s:Supplier) "
            "OPTIONAL MATCH (s)-[:SUPPLIES]->(:Product)-[:CARRIES]->(:Route)-[:DESTINED_FOR]->(port:Port) "
            "WHERE ($q = '' OR toLower(s.name) CONTAINS $q) "
            "AND ($location = '' OR toLower(port.name) CONTAINS $location) "
            "RETURN DISTINCT s.name AS value "
            "ORDER BY value LIMIT $limit"
        ),
        "skus": (
            "MATCH (p:Product) "
            "OPTIONAL MATCH (p)-[:CARRIES]->(r:Route)-[:DESTINED_FOR]->(port:Port) "
            "OPTIONAL MATCH (s:Supplier)-[:SUPPLIES]->(p) "
            "WHERE ($q = '' OR toLower(p.sku) CONTAINS $q) "
            "AND ($location = '' OR toLower(port.name) CONTAINS $location) "
            "AND ($supplier = '' OR toLower(s.name) CONTAINS $supplier) "
            "RETURN DISTINCT p.sku AS value "
            "ORDER BY value LIMIT $limit"
        ),
        "routes": (
            "MATCH (r:Route) "
            "OPTIONAL MATCH (r)<-[:CARRIES]-(p:Product) "
            "OPTIONAL MATCH (r)-[:DESTINED_FOR]->(port:Port) "
            "OPTIONAL MATCH (s:Supplier)-[:SUPPLIES]->(p) "
            "WHERE ($q = '' OR toLower(r.route_id) CONTAINS $q) "
            "AND ($location = '' OR toLower(port.name) CONTAINS $location) "
            "AND ($supplier = '' OR toLower(s.name) CONTAINS $supplier) "
            "RETURN DISTINCT r.route_id AS value "
            "ORDER BY value LIMIT $limit"
        ),
    }

    graph_catalog: dict[str, list[str]] = {kind_name: [] for kind_name in requested_kinds}
    try:
        for kind_name in requested_kinds:
            rows, _ = db.cypher_query(queries[kind_name], params)
            graph_catalog[kind_name] = _rows_to_values(rows)
    except Exception as exc:
        logger.warning("Catalog lookup via Neo4j failed; using fallback catalog: %s", exc)
        return {kind_name: [] for kind_name in requested_kinds}

    return graph_catalog


def _rows_to_values(rows: list[list[Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        if not row:
            continue
        value = str(row[0] or "").strip()
        if value:
            values.append(value)
    return values


def _filter_options(options: list[str], q_lc: str) -> list[str]:
    if not q_lc:
        return list(options)
    return [option for option in options if q_lc in option.lower()]


def _dedupe_with_limit(options: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for option in options:
        normalized = option.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result
