#!/bin/bash
set -e

PROJECT="aetherchain-v2"
REGION="us-central1"
SERVICE="aetherchain-worker"
TAG="v$(date +%Y%m%d%H%M%S)"
IMAGE="gcr.io/$PROJECT/$SERVICE:$TAG"
CONNECTOR="aetherchain-connector"

echo "Building and Pushing Docker image for linux/amd64..."
docker buildx build --platform linux/amd64 -t $IMAGE . --push

echo "Deploying to Cloud Run with mounted secrets..."
gcloud run deploy $SERVICE \
  --image $IMAGE \
  --platform managed \
  --region $REGION \
  --project $PROJECT \
  --allow-unauthenticated \
  --vpc-connector $CONNECTOR \
  --vpc-egress=private-ranges-only \
  --set-secrets="POSTGRES_URI=aetherchain-postgres-uri:latest,NEO4J_PASSWORD=aetherchain-neo4j-password:latest,DJANGO_SECRET_KEY=aetherchain-django-secret-key:latest"

echo "Deployed image: $IMAGE to $SERVICE."
