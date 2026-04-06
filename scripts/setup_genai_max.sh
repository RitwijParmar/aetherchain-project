#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <PROJECT_ID> <REGION>"
  echo "Example: $0 project-2281c357-4539-4bc6-b96 us-central1"
  echo "Optional env: SETUP_ADC=1 PROVISION_SEARCH=1 PROVISION_PLAYBOOK=1 PLAYBOOK_LOCATION=global EXPECTED_ACCOUNT=ritiwj@gmail.com"
  exit 1
fi

PROJECT_ID="$1"
REGION="$2"
EXPECTED_ACCOUNT="${EXPECTED_ACCOUNT:-ritiwj@gmail.com}"
GCLOUD_BIN="${GCLOUD_BIN:-}"
SETUP_ADC="${SETUP_ADC:-0}"
PROVISION_SEARCH="${PROVISION_SEARCH:-1}"
PROVISION_PLAYBOOK="${PROVISION_PLAYBOOK:-1}"
PLAYBOOK_LOCATION="${PLAYBOOK_LOCATION:-global}"

if [[ -z "${GCLOUD_BIN}" ]]; then
  if command -v gcloud >/dev/null 2>&1; then
    GCLOUD_BIN="$(command -v gcloud)"
  elif [[ -x "/Users/ritwij/google-cloud-sdk/bin/gcloud" ]]; then
    GCLOUD_BIN="/Users/ritwij/google-cloud-sdk/bin/gcloud"
  else
    echo "ERROR: gcloud not found. Install Cloud SDK or set GCLOUD_BIN."
    exit 1
  fi
fi

echo "Configuring project ${PROJECT_ID} in region ${REGION} for Search-first GenAI usage..."

"${GCLOUD_BIN}" config set project "${PROJECT_ID}" >/dev/null
ACTIVE_ACCOUNT="$("${GCLOUD_BIN}" config get-value account 2>/dev/null || true)"

if [[ "${ACTIVE_ACCOUNT}" != "${EXPECTED_ACCOUNT}" ]]; then
  echo "ERROR: Active gcloud account is '${ACTIVE_ACCOUNT}', expected '${EXPECTED_ACCOUNT}'."
  echo "Run: gcloud config set account ${EXPECTED_ACCOUNT}"
  exit 1
fi

echo "Using account: ${ACTIVE_ACCOUNT}"

echo "Enabling required APIs..."
"${GCLOUD_BIN}" services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  pubsub.googleapis.com \
  bigquery.googleapis.com \
  dataflow.googleapis.com \
  aiplatform.googleapis.com \
  discoveryengine.googleapis.com \
  serviceusage.googleapis.com

echo
echo "Checking Application Default Credentials (ADC)..."
if "${GCLOUD_BIN}" auth application-default print-access-token >/dev/null 2>&1; then
  echo "ADC already configured."
else
  echo "ADC not configured."
  if [[ "${SETUP_ADC}" == "1" ]]; then
    echo "Running interactive ADC login..."
    "${GCLOUD_BIN}" auth application-default login
  else
    echo "Skipping interactive ADC login (SETUP_ADC=${SETUP_ADC})."
    echo "Run this once:"
    echo "  ${GCLOUD_BIN} auth application-default login"
  fi
fi

if "${GCLOUD_BIN}" auth application-default print-access-token >/dev/null 2>&1; then
  if "${GCLOUD_BIN}" auth application-default set-quota-project "${PROJECT_ID}" >/dev/null 2>&1; then
    echo "ADC quota project set to ${PROJECT_ID}."
  else
    echo "WARNING: Could not set ADC quota project automatically."
    echo "Run:"
    echo "  ${GCLOUD_BIN} auth application-default set-quota-project ${PROJECT_ID}"
  fi
else
  echo "WARNING: ADC is still unavailable; local Discovery/Vertex calls may fail."
fi

if [[ "${PROVISION_SEARCH}" == "1" ]]; then
  echo
  echo "Provisioning Discovery Engine search resources (datastore + engine + secret)..."
  python3 scripts/provision_discovery_search.py \
    --project-id "${PROJECT_ID}" \
    --gcloud-bin "${GCLOUD_BIN}" \
    --seed-sample-docs
else
  echo
  echo "Skipping Discovery Engine provisioning (PROVISION_SEARCH=${PROVISION_SEARCH})."
fi

if [[ "${PROVISION_PLAYBOOK}" == "1" ]]; then
  echo
  echo "Provisioning Conversational Agents playbook resources..."
  python3 scripts/provision_playbook_agent.py \
    --project-id "${PROJECT_ID}" \
    --location "${PLAYBOOK_LOCATION}" \
    --gcloud-bin "${GCLOUD_BIN}"
else
  echo
  echo "Skipping Conversational Agent playbook provisioning (PROVISION_PLAYBOOK=${PROVISION_PLAYBOOK})."
fi

echo
echo "Next manual steps:"
if [[ "${PROVISION_SEARCH}" == "1" ]]; then
  echo "- Confirm provisioned serving config is the expected one in Secret Manager."
else
  echo "- Create / confirm Vertex AI Search data store, engine, and serving config."
  echo "- Save serving config path into Secret Manager:"
  echo "   gcloud secrets create aetherchain-vertex-search-serving-config --replication-policy=automatic"
  echo "   printf '%s' 'projects/PROJECT/locations/global/collections/default_collection/engines/ENGINE_ID/servingConfigs/default_search' | \\"
  echo "     gcloud secrets versions add aetherchain-vertex-search-serving-config --data-file=-"
fi
echo "- (Optional, recommended) set Gemini model env var for narrative generation:"
echo "   export VERTEX_GENAI_MODEL=gemini-2.0-flash-001"
echo "- Ensure API bearer token secret exists:"
echo "   gcloud secrets versions add aetherchain-api-bearer-token --data-file=token.txt"
echo "- Run stack check:"
echo "   python src/manage.py check_genai_stack --project-id ${PROJECT_ID}"
echo "- Run direct GenAI load (no /api/simulate traffic):"
echo "   python3 scripts/run_direct_genai_load.py --project-id ${PROJECT_ID}"
echo "- (Recommended) turn on Detailed Billing Export to BigQuery for credit tracking."
echo
echo "Done."
