# SupplyNerva (AetherChain Project)

SupplyNerva is a production-oriented supply risk decision product built on top of the AetherChain codebase.

It answers one operator question fast:

> Given a disruption, what action should we take now?

The app combines graph impact mapping, retrieval-backed evidence, deterministic scoring, and optional generative narrative refinement.

## 1. Product Snapshot

- Product name: `SupplyNerva`
- Repository name: `aetherchain-project`
- Runtime type: Django API + web app on Cloud Run
- Main mode: scenario simulation (non-destructive)
- Decision output: structured packet (`risk`, `confidence`, `delay`, `cost`, `recommended_action`, evidence)

Core user outcomes:

1. Define a disruption scope (port/supplier/SKU/route).
2. Generate a decision packet in seconds.
3. Understand impacted assets and act with one recommended next step.

## 2. Interface Guide (Complete UI Walkthrough)

The public interface is served from `/`.

### 2.1 Home / Hero

- Brand and product framing for supply decisioning.
- CTA to jump directly into the scenario flow.

### 2.2 Scenario Form (Primary Flow)

The operator panel supports both broad and narrow scenario scopes.

Target selection:

- `Port or location` (radio)
- `Supplier` (radio)

Target input:

- Location text input with live catalog suggestions (`datalist`).
- Supplier text input with live catalog suggestions (`datalist`).

Portfolio filters (optional but first-class):

- SKU token input:
  - type value
  - press `Enter` or click `Add`
  - tokenized chips with remove action
- Route token input:
  - same UX as SKU token input

Scenario controls:

- `Disruption type` selector
- `Planning horizon` selector (`3`, `7`, `14`, `30` days)
- `Business priority` text field
- `Context note` free text

Submission:

- `Generate Decision` button submits JSON to `/experience/simulate/`
- Simulation is non-destructive and does not write alert rows

### 2.3 Result Panel

State management:

- Empty state: prompt to run scenario
- Loading state: rotating analysis messages
- Error state: actionable message
- Success state: full decision packet

Success view contains:

- `summary_description`
- `impact_analysis`
- `recommended_action`
- `Scenario Target` and scoped summary
- Metrics:
  - risk
  - confidence
  - estimated delay
  - estimated cost
- Impacted assets table:
  - SKU
  - route
  - supplier
  - port
- Supporting evidence list (title/snippet/link)

### 2.4 Catalog Behavior

The frontend fetches `/experience/catalog/` for live options:

- `ports`
- `suppliers`
- `skus`
- `routes`

Catalog source indicator:

- `live graph` (Neo4j-backed)
- `fallback catalog` (in-app fallback data)

## 3. API Surface

All endpoints are defined under `src/aetherchain/core/urls.py`.

Public endpoints:

- `GET /` - SupplyNerva web app
- `GET /healthz/` - health check
- `GET /experience/catalog/` - scenario option catalog
- `POST /experience/simulate/` - public simulation endpoint

Worker and protected endpoints:

- `POST /process_task/` - Pub/Sub push worker ingress
- `POST /api/simulate/` - bearer-protected simulation endpoint
- `GET /api/alerts/` - bearer-protected historical alerts

### 3.1 `GET /experience/catalog/`

Query params:

- `kind`: `all | ports | suppliers | skus | routes`
- `q`: free text filter
- `location`: optional location context
- `supplier_name`: optional supplier context
- `limit`: bounded option count (`5..50`)

Response shape (example):

```json
{
  "source": "fallback",
  "query": "",
  "ports": ["Port of Los Angeles"],
  "suppliers": ["Vietnam Footwear Co."],
  "skus": ["SHOE-ABC"],
  "routes": ["VNHCM-USLAX"]
}
```

### 3.2 `POST /experience/simulate/`

Accepted input fields:

- `location` (optional)
- `supplier_name` (optional)
- `product_skus` or `product_sku` (optional)
- `route_ids` or `route_id` (optional)
- `event_type` (optional, auto-derived if absent)
- `horizon_days` (optional)
- `business_priority` (optional)
- `context_note` (optional)

Validation rule:

- At least one target must be provided from:
  - location
  - supplier_name
  - product_skus
  - route_ids

Response includes:

- `summary_description`
- `impact_analysis`
- `recommended_action`
- `event_type`
- `event_target`
- `risk_score`
- `confidence_score`
- `estimated_delay_days`
- `estimated_cost_impact_usd`
- `evidence_summary`
- `raw_context`

## 4. Decision Pipeline

Execution flow for simulation and worker path:

1. Normalize scenario payload.
2. Build graph lookup query from target/scope.
3. Resolve impacted assets from Neo4j.
4. If graph unavailable or empty and fallback enabled, synthesize fallback impacted assets.
5. Retrieve supporting evidence from Vertex AI Search (Discovery Engine).
6. Build deterministic decision packet:
   - risk
   - confidence
   - delay
   - cost
   - recommendation
7. Optionally refine narrative with Vertex GenAI model (if enabled).
8. Return packet (simulate) or persist `Alert` (worker).

## 5. Data Model

Django model `Alert` stores decision outputs:

- event metadata
- narrative output
- quantified scores
- evidence summary
- raw context

Key fields:

- `event_type`
- `event_target`
- `summary_description`
- `impact_analysis`
- `recommended_action`
- `risk_score`
- `confidence_score`
- `estimated_delay_days`
- `estimated_cost_impact_usd`
- `evidence_summary` (`JSONField`)
- `raw_context` (`JSONField`)

## 6. GenAI and Search Stack

Designed to maximize GenAI-trial usage while keeping non-GenAI spend controlled.

Primary GenAI consumption paths:

1. Vertex AI Search / Discovery Engine
   - search retrieval
   - advanced summary generation
2. Direct GenAI load scripts
   - Search answer traffic
   - Conversational Agents Playbook traffic

Optional narrative generation:

- Vertex model call from `genai.py`
- gated by:
  - `CREDIT_FIRST_MODE`
  - `VERTEX_GENAI_MODEL`

## 7. Data Engineering Backbone

GDELT ingest pipeline:

- extract articles from GDELT
- normalize to Discovery document schema
- dedupe and batch import
- persist raw and normalized artifacts for auditability

Key command:

```bash
python src/manage.py ingest_gdelt_discovery \
  --project-id <PROJECT_ID> \
  --datastore-id supplynerva-store \
  --lookback-hours 6 \
  --max-records 50 \
  --max-import 40 \
  --batch-size 20
```

Guardrail options:

- monthly net budget cap
- billing export table auto-discovery
- fail-closed behavior when configured

## 8. DevOps and Deployment

### 8.1 Runtime

- Cloud Run service hosts web + API
- Worker ingress endpoint supports Pub/Sub push events

### 8.2 Build and delivery

- Dockerized app (`Dockerfile`, `src/Dockerfile`)
- Cloud Build for image build/push
- GitHub Actions workflow for deploy automation

### 8.3 Cost and billing observability

SQL toolkit under `sql/` provides:

- daily GenAI vs non-GenAI spend view
- credit attribution checks
- top non-GenAI leaks
- monthly net guardrail status

### 8.4 Automation scripts

Under `scripts/`:

- `setup_genai_max.sh`
- `provision_discovery_search.py`
- `provision_playbook_agent.py`
- `provision_ingest_automation.sh`
- `run_credit_first_ingest.sh`
- `run_direct_genai_load.py`

## 9. Local Development

### 9.1 Prerequisites

- Python `3.11`
- Docker
- Google Cloud SDK
- authenticated GCP account with project access

### 9.2 Install

```bash
git clone https://github.com/RitwijParmar/aetherchain-project.git
cd aetherchain-project
python3 -m venv venv
source venv/bin/activate
pip install -r src/requirements.txt
```

### 9.3 Environment

Set `.env` (never commit secrets):

```env
POSTGRES_URI=
NEO4J_URI=
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=
GCP_PROJECT_ID=
GCP_QUOTA_PROJECT_ID=
DJANGO_SECRET_KEY=
API_TOKEN=
VERTEX_SEARCH_SERVING_CONFIG=
VERTEX_SEARCH_MAX_RESULTS=8
VERTEX_SEARCH_ENABLE_SUMMARY=true
VERTEX_SEARCH_SUMMARY_RESULT_COUNT=3
CREDIT_FIRST_MODE=true
VERTEX_GENAI_MODEL=
VERTEX_GENAI_LOCATION=us-central1
VERTEX_GENAI_MAX_OUTPUT_TOKENS=350
ENABLE_GRAPH_FALLBACK=true
EXTERNAL_REQUEST_TIMEOUT_SECONDS=20
```

### 9.4 Run

```bash
cd src
python manage.py migrate
python manage.py runserver
```

Then open:

- `http://127.0.0.1:8000/`

## 10. Testing

Run full tests:

```bash
cd src
python manage.py test aetherchain.core.tests
```

Coverage includes:

- public simulate behavior
- protected API behavior
- catalog fallback behavior
- retrieval fallback behavior
- graph fallback behavior
- ingest utility normalization

## 11. Repository Structure

```text
src/aetherchain/core/
  views.py                 # API and web endpoint handlers
  tasks.py                 # impact analysis orchestration
  decision_engine.py       # deterministic decision scoring
  retrieval.py             # Vertex Search evidence retrieval
  genai.py                 # optional GenAI narrative generation
  catalog.py               # scenario catalog provider
  tests.py                 # API, retrieval, ingest, and UI flow tests
  templates/core/home.html # SupplyNerva interface
  static/core/home.css     # SupplyNerva styles
  static/core/home.js      # SupplyNerva client behavior
scripts/                   # provisioning and load/automation scripts
sql/                       # billing and credit guardrail SQL pack
```

## 12. Operational Notes

- Neo4j or retrieval outages do not hard-stop all paths if fallback mode is enabled.
- Simulation endpoint is intentionally non-persistent.
- Worker endpoint can persist alerts for event-driven pipelines.
- If billing export is not configured, SQL guardrail queries will not return full coverage.

## 13. Security and Secrets

- Store credentials in Secret Manager for cloud runtime.
- Use least-privilege IAM for service accounts.
- Avoid hardcoding tokens, URIs, and API keys.
- Keep `.env` local only.

## 14. Known Limitations

- Fallback catalog values are static and should be replaced by production data sources.
- Graph completeness determines quality of impacted asset resolution.
- Discovery indexing is asynchronous; recent ingests may not appear immediately.
- Python 3.9 local environments can break newer Cloud SDK commands; prefer Python 3.10+.

## 15. Roadmap (Practical Next Steps)

1. Connect production-grade master data source for ports/suppliers/SKUs/routes.
2. Add authenticated tenant/org model for multi-team usage.
3. Add scenario history and comparison views in UI.
4. Add SLA-aware recommendation policy variants.
5. Add richer incident timeline and operator collaboration notes.

## 16. License

No explicit license file is currently present. Add a repository license before public/commercial distribution.
