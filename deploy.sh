#!/bin/bash
#
# Definitive, Production-Grade Deployment Script for AetherChain
# This version corrects the syntax for the gcloud run jobs update command.
#

# --- Configuration ---
set -e
PROJECT_ID="aetherchain-v2"
REGION="us-central1"
SERVICE_NAME="aetherchain-worker"
MIGRATOR_JOB_NAME="aetherchain-migrator"

# --- 1. Generate a Unique Version Tag ---
VERSION_TAG="v$(date +%Y%m%d%H%M%S)"
IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:${VERSION_TAG}"
echo "--- Generated unique image tag: ${IMAGE_TAG} ---"

# --- 2. Build and Push the Container Image ---
echo "--- Building and pushing image with 'docker buildx'... ---"
docker buildx build --platform linux/amd64 --file Dockerfile -t "${IMAGE_TAG}" . --push

# --- 3. Deploy the Main Service ---
echo "--- Deploying service '${SERVICE_NAME}' with secure secrets... ---"
gcloud run deploy "${SERVICE_NAME}"   --image "${IMAGE_TAG}"   --platform managed   --region "${REGION}"   --project="${PROJECT_ID}"   --allow-unauthenticated   --vpc-connector="aetherchain-connector"   --vpc-egress="private-ranges-only"   --set-secrets="POSTGRES_URI=aetherchain-postgres-uri:latest,NEO4J_PASSWORD=aetherchain-neo4j-password:latest,DJANGO_SECRET_KEY=aetherchain-django-secret-key:latest"

# --- 4. Update and Run the Database Migration Job (CORRECTED SYNTAX) ---
echo "--- Updating and running database migrator job '${MIGRATOR_JOB_NAME}'... ---"
# The --args are now a single string, as required by the command.
gcloud run jobs update "${MIGRATOR_JOB_NAME}"   --image "${IMAGE_TAG}"   --command="python","manage.py","migrate"   --args="--no-input"   --region "${REGION}"   --project="${PROJECT_ID}"   --vpc-connector="aetherchain-connector"   --vpc-egress="private-ranges-only"   --set-secrets="POSTG-RES_URI=aetherchain-postgres-uri:latest"

# Execute the job to apply migrations and wait for it to complete.
gcloud run jobs execute "${MIGRATOR_JOB_NAME}" --region "${REGION}" --project="${PROJECT_ID}" --wait

echo "--- Deployment of version ${VERSION_TAG} complete. ---"
