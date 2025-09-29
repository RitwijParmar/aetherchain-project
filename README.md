

# **AetherChain: A Predictive Supply Chain Intelligence Platform**

**Status:** Stable, Production Ready
**Author:** Ritwij Parmar

## **1. Introduction & Project Philosophy**

AetherChain is a serverless intelligence platform built on Google Cloud Platform, designed to transform supply chain management from a reactive to a proactive discipline.

Our core philosophy is that in an increasingly volatile world, organizations can no longer afford to learn about disruptions after they have occurred. AetherChain was built to serve as an autonomous early warning system. It continuously scans for real-world events, uses a graph-based representation of the supply chain to understand complex relationships, and leverages Large Language Models to translate raw data into human-readable, actionable intelligence.

This document serves as the single source of truth for the project's architecture, code, operational procedures, and future roadmap.

---

## **2. Important Notice: Operational Status & Service Dependencies**

This project's architecture relies on several best-in-class, third-party managed services for its core database functionality. It is critical for any user or developer to be aware of the current billing status of these dependencies.

*   **Trial Account Dependency:** The **Neo4j AuraDB** (graph database) and **Supabase** (PostgreSQL database) instances for this project are currently configured using **free-tier or time-limited trial accounts.** These accounts are subject to suspension, data deletion, or functional limitations upon the expiration of their respective trial periods.

*   **Impact on Functionality:** Should these external services be suspended, the AetherChain platform will **cease to function correctly,** as it will lose its ability to read from its knowledge graph and write to its alert log. All API endpoints that rely on this data will fail.

*   **Recommendation for Production Use:** For long-term stability and any mission-critical or production-level deployment, it is **essential to upgrade the Neo4j AuraDB and Supabase accounts to a permanent, paid billing plan.**

Furthermore, the **Google Cloud Platform** components are operating on a standard, post-free-trial account. All usage of Cloud Run, Cloud Functions, Vertex AI, and other GCP services will incur costs according to standard pricing.

---

## **3. Core Capabilities**

*   **Event-Driven Architecture:** A decoupled and scalable system built on Google Cloud Pub/Sub, ensuring that components can evolve independently.
*   **AI-Powered Analysis:** Leverages the **Mistral Small model via Google Vertex AI** to perform Retrieval-Augmented Generation (RAG). This transforms a simple list of affected assets into a qualitative impact analysis and a specific, actionable recommendation.
*   **Graph-Based Intelligence:** The supply chain is modeled as a rich graph in **Neo4j AuraDB**. This allows for complex, multi-tier impact analysis that traditional databases cannot perform, such as analyzing disruptions by a specific port or a single component supplier.
*   **"What-If" Simulation:** A secure API endpoint allows for on-demand risk assessment of hypothetical scenarios, enabling strategic planning.
*   **Automated Intelligence Gathering:** A scheduled **Google Cloud Function** acts as an autonomous "sentinel," continuously scanning the GDELT news API for potential disruption events.
*   **Automated CI/CD:** A fully configured GitHub Actions pipeline provides continuous integration and deployment, enabling rapid, reliable, and zero-touch updates to the platform.

## **4. Technology Stack**

*   **Backend:** Python 3.11, Django, Gunicorn
*   **Cloud Platform:** Google Cloud Platform (GCP)
    *   **Compute:** Cloud Run (Services & Jobs), Cloud Functions
    *   **Messaging:** Cloud Pub/Sub
    *   **Networking:** VPC, VPC Connector
    *   **AI/ML:** Vertex AI
    *   **Security:** Secret Manager, IAM
    *   **Deployment:** Cloud Build, GitHub Actions
*   **Databases:**
    *   **Graph Database:** Neo4j AuraDB (Cloud Hosted - **Trial Account**)
    *   **Relational Database:** Supabase (Cloud Hosted PostgreSQL - **Trial Account**)
*   **Data Source:** GDELT Project API

## **5. Architectural Deep Dive**

The system operates through a seamless, automated flow:

1.  **Scheduled Trigger:** The **Google Cloud Scheduler** job `run-gdelt-sentinel-daily` runs once per day, making an HTTP GET request to the `aetherchain-gdelt-sentinel` Cloud Function.

2.  **Intelligence Gathering (`aetherchain-gdelt-sentinel`):** The **Cloud Function** queries the GDELT news API for articles from the last 24 hours matching keywords like "port congestion." If relevant events are found, it publishes a JSON message to the **`aetherchain-tasks` Pub/Sub Topic**.

3.  **Core Analysis Pipeline (`aetherchain-worker`):** The **Django-based service** receives the event, connects to **Neo4j AuraDB**, and executes a Cypher query. It constructs a prompt for the **Vertex AI (Mistral Small) API** and saves the structured JSON response to the **Supabase PostgreSQL** database.

4.  **Data Access & Simulation (API):** A secure, token-protected **REST API** (`/api/alerts/` and `/api/simulate/`) exposes the platform's intelligence for consumption.

## **6. Project Setup and Local Development**

### **6.1. Prerequisites**

*   Python 3.11
*   `gcloud` CLI (authenticated to your GCP account)
*   Docker Desktop
*   Git

### **6.2. Initial Setup**

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/RitwijParmar/aetherchain-project.git
    cd aetherchain-project
    ```
2.  **Set Up Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
3.  **Local Environment Configuration:** Create a `.env` file in the project root. This file is ignored by Git and must never be committed.

    **File: `.env`**
    ```
    POSTGRES_URI="[Your Supabase PostgreSQL URI]"
    NEO4J_URI="[Your Neo4j AuraDB Host]"
    NEO4J_USERNAME="neo4j"
    NEO4J_PASSWORD="[Your Neo4j Password]"
    GCP_PROJECT_ID="aetherchain-v2"
    SECRET_KEY="[A strong, randomly generated Django Secret Key]"
    API_TOKEN="[A strong, randomly generated API Token for local testing]"
    ```

### **6.3. Database Seeding**

#### **6.3.1. Neo4j Graph Database**

Run the following query in your Neo4j Aura Browser to ensure a clean and correctly structured graph. This script is idempotent and can be run safely multiple times.

```cypher
// This script will idempotently create the required graph schema.
MERGE (p1:Port {name: 'Port of Los Angeles'});
MERGE (r1:Route {route_id: 'VNHCM-USLAX'});
MERGE (prod1:Product {sku: 'SHOE-ABC'});
MERGE (prod2:Product {sku: 'BOOT-XYZ'});
MERGE (s1:Supplier {name: 'Vietnam Footwear Co.', location: 'Ho Chi Minh City, Vietnam'});

// Merge relationships to ensure a fully connected graph
MERGE (r1)-[:DESTINED_FOR]->(p1);
MERGE (prod1)-[:CARRIES]->(r1);
MERGE (prod2)-[:CARRIES]->(r1);
MERGE (s1)-[:SUPPLIES]->(prod1);
```

#### **6.3.2. PostgreSQL Database**

Run standard Django migrations to create the `Alert` table.
```bash
python src/manage.py migrate
```

### **6.4. Running the Local Development Server**
```bash
python src/manage.py runserver
```

## **7. Automated CI/CD Deployment**

The project is configured with a complete CI/CD pipeline using GitHub Actions. All deployments are handled automatically upon pushing to the `main` branch.

### **7.1. Deployment Prerequisites (One-Time Setup)**

*   All necessary GCP APIs are enabled (`cloudbuild.googleapis.com`, `run.googleapis.com`, `secretmanager.googleapis.com`, etc.).
*   A **GitHub Environment** named `production` has been created.
*   The `GCP_PROJECT_ID` and `GCP_SA_KEY` (a JSON key for a dedicated GCP service account) secrets are stored as **Environment Secrets** within the `production` environment on GitHub.
*   The application secrets (`aetherchain-postgres-uri`, `aetherchain-neo4j-password`, etc.) are stored in **Google Cloud Secret Manager**.
*   All necessary **IAM Permissions** are granted to the relevant service accounts as outlined in the project's operational history.

### **7.2. The CI/CD Workflow**

The `.github/workflows/deploy.yml` file governs the deployment. It automatically builds a new Docker image, deploys it to the `aetherchain-worker` service with all secrets mounted, and runs the `aetherchain-migrator` job.

### **7.3. How to Deploy**

Simply commit your changes and push them to the `main` branch. The CI/CD pipeline will handle the rest.
```bash
git push origin main
```

## **8. API Reference**

**Base URL:** `https://aetherchain-worker-210451460324.us-central1.run.app`

### **8.1. List Alerts**

*   **Endpoint:** `/api/alerts/`
*   **Method:** `GET`
*   **Authentication:** Bearer Token
*   **Headers:** `Authorization: Bearer [YOUR_API_TOKEN]`

### **8.2. "What-If" Simulation**

*   **Endpoint:** `/api/simulate/`
*   **Method:** `POST`
*   **Authentication:** Bearer Token
*   **Headers:** `Authorization: Bearer [YOUR_API_TOKEN]`, `Content-Type: application/json`
*   **Request Body (Supplier Disruption):**
    ```json
    {
        "supplier_name": "Vietnam Footwear Co."
    }
    ```
*   **Request Body (Location Disruption):**
    ```json
    {
        "location": "Port of Los Angeles"
    }
    ```
*   **Success Response (200 OK):** The direct, unsaved JSON analysis from the LLM.

## **9. Future Roadmap**

With the core platform now stable and automated, the following strategic initiatives can be pursued:

1.  **Upgrade Service Plans:** The highest priority is to move the Neo4j and Supabase databases to permanent, paid plans to ensure production stability and remove the limitations of the trial accounts.
2.  **Financial Impact Analysis:** Enhance the graph and LLM prompts to include financial data (e.g., product value, late-delivery penalties) to allow the AI to estimate the quantitative financial impact of a disruption.
3.  **Dashboard Development:** Create a web-based frontend that communicates with the secure REST API to visualize supply chain routes, display alerts on an interactive map, and provide a user-friendly UI for the "What-If" simulation tool.
4.  **Proactive Notifications:** Integrate with services like Slack, Microsoft Teams, or Twilio to push critical alerts directly to the relevant operations channels and stakeholders.
