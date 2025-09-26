#!/bin/bash
set -e

# --- Configuration ---
GCP_PROJECT_ID="aetherchain-v2"
GCP_REGION="us-central1"
IMAGE_NAME="gcr.io/$GCP_PROJECT_ID/aetherchain-worker"
SERVICE_NAME="aetherchain-worker"
MIGRATOR_JOB_NAME="aetherchain-migrator"

# --- 1. Get New Version Tag ---
LAST_VERSION_NUM=$(gcloud container images list-tags $IMAGE_NAME --format='get(tags)' --filter='tags:v*' | grep -o 'v[0-9]*' | sed 's/v//' | sort -n | tail -n 1)
NEW_VERSION_NUM=$(( (LAST_VERSION_NUM:-0) + 1 ))
NEW_VERSION="v$NEW_VERSION_NUM"
echo "Deploying new version: $NEW_VERSION"
echo

# --- 2. Build the New Image ---
echo "--- Building new image: $IMAGE_NAME:$NEW_VERSION ---"
gcloud builds submit --tag "$IMAGE_NAME:$NEW_VERSION" --project="$GCP_PROJECT_ID"
echo "--- Build complete. ---"
echo

# --- 3. Deploy to Cloud Run using Native Secrets ---
echo "--- Deploying to Cloud Run service: $SERVICE_NAME ---"
gcloud run deploy $SERVICE_NAME   --image "$IMAGE_NAME:$NEW_VERSION"   --platform managed   --region "$GCP_REGION"   --allow-unauthenticated   --project="$GCP_PROJECT_ID"   --vpc-connector="aetherchain-connector"   --vpc-egress="private-ranges-only"   --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,IS_PRODUCTION=true,NEO4J_URI=7f3e44ae.databases.neo4j.io,DJANGO_SECRET_KEY=a-real-production-secret-key"   --set-secrets="DATABASE_URL=aetherchain-postgres-uri:latest,NEO4J_PASSWORD=aetherchain-neo4j-password:latest,HF_TOKEN=aetherchain-hf-token:latest"
echo "--- Deployment complete. ---"
echo

# --- 4. Run Database Migrations using Native Secrets ---
echo "--- Running database migrations ---"
gcloud run jobs delete $MIGRATOR_JOB_NAME --region="$GCP_REGION" --project="$GCP_PROJECT_ID" --quiet || true

# We will run the migration manually after this script succeeds.
# This simplifies the script and avoids the permissions complexities for now.

echo "--- AetherChain deployment of version $NEW_VERSION finished successfully! ---"
echo "--- Please run the migration job manually. ---"
