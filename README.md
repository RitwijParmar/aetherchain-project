

# AetherChain: A Predictive Supply Chain Intelligence Platform

AetherChain is a 100% serverless intelligence platform built on Google Cloud Platform. It is designed to autonomously detect real-world supply chain disruptions, analyze their impact using a graph database and Large Language Models, and provide actionable recommendations.

## Core Features

*   **Event-Driven Architecture:** Utilizes Google Cloud Pub/Sub to create a decoupled and scalable system.
*   **AI-Powered Analysis:** Leverages Google's Vertex AI models to perform Retrieval-Augmented Generation (RAG), transforming raw disruption data into qualitative impact analysis and actionable recommendations.
*   **Graph-Based Intelligence:** Models the supply chain as a graph in Neo4j AuraDB, enabling complex, multi-tier impact analysis that traditional relational databases cannot perform.
*   **"What-If" Simulation:** A secure API endpoint allows for on-demand risk assessment of hypothetical disruption scenarios (e.g., "What is the impact of a factory fire at Supplier X?").
*   **Automated Intelligence Gathering:** A scheduled Cloud Function acts as a "sentinel," automatically scanning real-world news APIs (like GDELT) for potential disruption events.

---

## Architectural Overview

The system operates through a seamless, event-driven flow:

1.  **Event Trigger:**
    *   A **Google Cloud Scheduler** job runs on a periodic basis (e.g., daily).
    *   It triggers the **`aetherchain-gdelt-sentinel` Google Cloud Function**.

2.  **Intelligence Gathering:**
    *   The **Cloud Function** queries the GDELT news API for articles matching keywords like "port congestion" or "factory fire" at locations of interest.
    *   If a relevant event is found, the function formats a JSON message.
    *   This message is published to the **`aetherchain-tasks` Pub/Sub Topic**.

3.  **Core Analysis Pipeline:**
    *   A push subscription on the topic immediately sends the message via an HTTP POST request to the **`aetherchain-worker` Cloud Run Service**.
    *   This **Django-based service** receives the request and initiates the analysis.
    *   It connects to **Neo4j AuraDB** and executes a Cypher query to find all assets (Products, Routes, etc.) impacted by the event.
    *   The service constructs a detailed prompt with the affected assets and calls the **Vertex AI (Mistral Small) API**.
    *   The LLM returns a structured JSON object containing its analysis, recommendation, and summary.
    *   The worker service parses this response and saves it as a new `Alert` record in the **Supabase PostgreSQL** database.

4.  **Data Access & Simulation:**
    *   A secure, token-protected **REST API** exposes the generated alerts.
    *   A **`/api/simulate/` endpoint** allows authorized users to bypass the sentinel and directly trigger the analysis pipeline for hypothetical scenarios.

## Technology Stack

*   **Backend:** Python 3.11, Django, Gunicorn
*   **Cloud Platform:** Google Cloud Platform (GCP)
    *   **Compute:** Cloud Run (Services & Jobs), Cloud Functions
    *   **Messaging:** Cloud Pub/Sub
    *   **Networking:** VPC, VPC Connector
    *   **AI/ML:** Vertex AI
    *   **Security:** Secret Manager, IAM
    *   **Deployment:** Cloud Build
*   **Databases:**
    *   **Graph Database:** Neo4j AuraDB (Cloud Hosted)
    *   **Relational Database:** Supabase (Cloud Hosted PostgreSQL)
*   **Data Source:** GDELT Project API

---

## Getting Started & Local Setup

### Prerequisites

*   Python 3.11
*   `gcloud` CLI (authenticated to your GCP account)
*   Docker Desktop (for local building, optional)
*   Git

### 1. Clone the Repository

```bash
git clone https://github.com/RitwijParmar/aetherchain-project.git
cd aetherchain-project
```

### 2. Set Up Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration

Create a `.env` file in the project root (`~/aetherchain-project/`) for local development. This file stores your credentials locally and should **never** be committed to Git.

**File: `.env`**
```
# PostgreSQL Database URI
POSTGRES_URI="postgresql://postgres:R@p1182002@db.zkbaafhkxwfkaeghvccr.supabase.co:5432/postgres"

# Neo4j Graph Database Credentials
NEO4J_URI="7f3e44ae.databases.neo4j.io"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="AetherChainIsLive12345"

# Google Cloud Project ID
GCP_PROJECT_ID="aetherchain-v2"

# Django Secret Key (generate a new one for production)
SECRET_KEY="django-insecure-local-development-key"

# API Token for testing the secure API locally
API_TOKEN="your-strong-local-api-token"
```

### 4. Database Setup

#### a) Neo4j Graph Database (CRITICAL)

The database must be seeded with the correct, fully connected graph. Run the following query in your Neo4j Aura Browser to ensure a clean state.

```cypher
// WARNING: This deletes all existing data.
MATCH (n) DETACH DELETE n;

// Recreate the entire graph from scratch
CREATE (p1:Port {name: 'Port of Los Angeles'})
CREATE (r1:Route {route_id: 'VNHCM-USLAX'})
CREATE (prod1:Product {sku: 'SHOE-ABC'})
CREATE (prod2:Product {sku: 'BOOT-XYZ'})
CREATE (s1:Supplier {name: 'Vietnam Footwear Co.', location: 'Ho Chi Minh City, Vietnam'})

// Create all necessary relationships
CREATE (r1)-[:DESTINED_FOR]->(p1)
CREATE (prod1)-[:CARRIES]->(r1)
CREATE (prod2)-[:CARRIES]->(r1)
CREATE (s1)-[:SUPPLIES]->(prod1);
```

#### b) PostgreSQL Database

Run the standard Django migrations to create the `Alert` table in your Supabase instance.

```bash
python src/manage.py migrate```

### 5. Run the Local Development Server

```bash
python src/manage.py runserver
```

---

## Cloud Deployment

Deployment is handled via a manual script that uses Google Cloud Build. The CI/CD pipeline via GitHub Actions is **non-functional and should not be used**.

### 1. Prerequisites (One-Time Setup)

*   All GCP APIs must be enabled (`cloudbuild.googleapis.com`, `run.googleapis.com`, `secretmanager.googleapis.com`, etc.).
*   The following secrets must be created in **Google Cloud Secret Manager**:
    *   `aetherchain-postgres-uri`
    *   `aetherchain-neo4j-password`
    *   `aetherchain-django-secret-key` (Use a strong, randomly generated key)
    *   `aetherchain-api-bearer-token` (Use a strong, randomly generated token)
*   **IAM Permissions must be granted:**
    *   The service account for **`aetherchain-worker`** needs the `Secret Manager Secret Accessor` role for all four secrets.
    *   The **Default Compute Engine service account** (`[PROJECT_NUMBER]-compute@...`) needs the `Secret Manager Secret Accessor` role for the `aetherchain-postgres-uri` secret (this is for the migrator job).

### 2. The Deployment Script

The `deploy.sh` script is the single source of truth for deployment. It automatically handles versioning, building, and deploying the application and its database migrations.

**File: `deploy.sh`**
```bash
#!/bin/bash
set -e
PROJECT_ID="aetherchain-v2"
REGION="us-central1"
SERVICE_NAME="aetherchain-worker"
MIGRATOR_JOB_NAME="aetherchain-migrator"

VERSION_TAG="v\$(date +%Y%m%d%H%M%S)"
IMAGE_TAG="gcr.io/\${PROJECT_ID}/\${SERVICE_NAME}:\${VERSION_TAG}"
echo "--- Generated unique image tag: \${IMAGE_TAG} ---"

echo "--- Building and pushing image... ---"
gcloud builds submit . --tag "\${IMAGE_TAG}" --project="\${PROJECT_ID}"

echo "--- Deploying service '\${SERVICE_NAME}' with secure secrets... ---"
gcloud run deploy "\${SERVICE_NAME}" \
  --image "\${IMAGE_TAG}" \
  --platform managed \
  --region "\${REGION}" \
  --project="\${PROJECT_ID}" \
  --allow-unauthenticated \
  --vpc-connector="aetherchain-connector" \
  --vpc-egress="private-ranges-only" \
  --set-secrets="POSTGRES_URI=aetherchain-postgres-uri:latest,NEO4J_PASSWORD=aetherchain-neo4j-password:latest,DJANGO_SECRET_KEY=aetherchain-django-secret-key:latest,API_TOKEN=aetherchain-api-bearer-token:latest"

echo "--- Updating and running database migrator job... ---"
gcloud run jobs update "\${MIGRATOR_JOB_NAME}" \
  --image "\${IMAGE_TAG}" \
  --command="python","manage.py","migrate" \
  --args="--no-input" \
  --region "\${REGION}" \
  --project="\${PROJECT_ID}" \
  --vpc-connector="aetherchain-connector" \
  --vpc-egress="private-ranges-only" \
  --set-secrets="POSTGRES_URI=aetherchain-postgres-uri:latest"

gcloud run jobs execute "\${MIGRATOR_JOB_NAME}" --region "\${REGION}" --project="\${PROJECT_ID}" --wait

echo "--- Deployment of version \${VERSION_TAG} complete. ---"
```

### 3. Execution

```bash
# Make the script executable (one time)
chmod +x deploy.sh

# Run the deployment
./deploy.sh
```

---

## API Endpoints

**Base URL:** `https://aetherchain-worker-210451460324.us-central1.run.app`

### 1. List Alerts

*   **Endpoint:** `/api/alerts/`
*   **Method:** `GET`
*   **Authentication:** Bearer Token
*   **Headers:** `Authorization: Bearer [YOUR_API_TOKEN]`
*   **Success Response (200 OK):**
    ```json
    [
        {
            "id": 1,
            "impact_analysis": "A factory fire at Vietnam Footwear Co. will halt production...",
            "recommended_action": "Immediately source alternative suppliers for SHOE-ABC...",
            "summary_description": "Critical Fire at Vietnam Footwear Co. impacting SHOE-ABC",
            "created_at": "2025-09-28T21:00:00Z"
        }
    ]
    ```

### 2. "What-If" Simulation

*   **Endpoint:** `/api/simulate/`
*   **Method:** `POST`
*   **Authentication:** Bearer Token
*   **Headers:** `Authorization: Bearer [YOUR_API_TOKEN]`, `Content-Type: application/json`
*   **Request Body (Supplier Disruption):**
    ```json
    {
        "supplier_name": "Vietnam Footwear Co.",
        "event_type": "Factory Fire"
    }
    ```
*   **Request Body (Location Disruption):**
    ```json
    {
        "location": "Port of Los Angeles",
        "event_type": "Port Congestion"
    }
    ```
*   **Success Response (200 OK):** Returns the direct, unsaved JSON analysis from the LLM.
    ```json
    {
        "impact_analysis": "A factory fire at Vietnam Footwear Co. will halt production...",
        "recommended_action": "Immediately source alternative suppliers for SHOE-ABC...",
        "summary_description": "Critical Fire at Vietnam Footwear Co. impacting SHOE-ABC"
    }
    ```
*   **Not Found Response (404 Not Found):**
    ```json
    {
        "message": "No affected assets found or an error occurred during analysis."
    }
    ```
