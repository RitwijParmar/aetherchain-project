#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <PROJECT_ID> [REGION]"
  echo "Example: $0 project-2281c357-4539-4bc6-b96 us-central1"
  echo "Optional env:"
  echo "  EXPECTED_ACCOUNT=ritiwj@gmail.com"
  echo "  IMAGE=gcr.io/<project>/aetherchain-worker:<tag>"
  echo "  JOB_NAME=supplynerva-ingest"
  echo "  SCHEDULER_NAME=supplynerva-ingest-2h"
  echo "  SCHEDULE='0 */2 * * *'"
  echo "  SCHEDULE_TIMEZONE=America/New_York"
  echo "  DATASTORE_ID=supplynerva-store"
  echo "  SERVING_CONFIG_SECRET=aetherchain-vertex-search-serving-config"
  echo "  BILLING_EXPORT_SCAN_PROJECTS=fluted-agency-492307-b0"
  echo "  BILLING_EXPORT_TABLE=my-billing-project.billing_export.gcp_billing_export_resource_v1_ABC_*"
  echo "  BILLING_EXPORT_DATASET=billing_export"
  echo "  BILLING_EXPORT_DATASET_LOCATION=US"
  echo "  AUTO_CREATE_BILLING_EXPORT_DATASET=1"
  echo "  MONTHLY_NET_BUDGET_USD=220"
  echo "  MONTHLY_NET_STOP_BUFFER_USD=15"
  echo "  BUDGET_DISPLAY_NAME='SupplyNerva Monthly Guardrail'"
  echo "  BUDGET_THRESHOLDS='0.8,0.9,1.0'"
  echo "  BUDGET_TOPIC=supplynerva-budget-alerts"
  echo "  BUDGET_SUBSCRIPTION=supplynerva-budget-alerts-sub"
  echo "  BUDGET_MESSAGE_RETENTION=2678400s"
  echo "  ENABLE_BUDGET_ALERT_GUARDRAIL=1"
  echo "  DAILY_MAX_IMPORT=120"
  echo "  DELETE_LEGACY_SCHEDULER=1"
  echo "  APPLY_IAM=0"
  echo "  EXECUTE_ONCE=1"
  exit 1
fi

PROJECT_ID="$1"
REGION="${2:-us-central1}"
EXPECTED_ACCOUNT="${EXPECTED_ACCOUNT:-ritiwj@gmail.com}"
GCLOUD_BIN="${GCLOUD_BIN:-}"

JOB_NAME="${JOB_NAME:-supplynerva-ingest}"
SCHEDULER_NAME="${SCHEDULER_NAME:-supplynerva-ingest-2h}"
SCHEDULE="${SCHEDULE:-0 */2 * * *}"
SCHEDULE_TIMEZONE="${SCHEDULE_TIMEZONE:-America/New_York}"
DATASTORE_ID="${DATASTORE_ID:-supplynerva-store}"
SERVING_CONFIG_SECRET="${SERVING_CONFIG_SECRET:-aetherchain-vertex-search-serving-config}"
LOOKBACK_HOURS="${LOOKBACK_HOURS:-6}"
MAX_RECORDS="${MAX_RECORDS:-60}"
MAX_IMPORT="${MAX_IMPORT:-20}"
BATCH_SIZE="${BATCH_SIZE:-15}"
DAILY_MAX_IMPORT="${DAILY_MAX_IMPORT:-120}"
BILLING_EXPORT_TABLE="${BILLING_EXPORT_TABLE:-}"
BILLING_PROJECT_ID="${BILLING_PROJECT_ID:-${PROJECT_ID}}"
BILLING_EXPORT_SCAN_PROJECTS="${BILLING_EXPORT_SCAN_PROJECTS:-fluted-agency-492307-b0}"
BILLING_EXPORT_DATASET="${BILLING_EXPORT_DATASET:-billing_export}"
BILLING_EXPORT_DATASET_LOCATION="${BILLING_EXPORT_DATASET_LOCATION:-US}"
AUTO_CREATE_BILLING_EXPORT_DATASET="${AUTO_CREATE_BILLING_EXPORT_DATASET:-1}"
MONTHLY_NET_BUDGET_USD="${MONTHLY_NET_BUDGET_USD:-220}"
MONTHLY_NET_STOP_BUFFER_USD="${MONTHLY_NET_STOP_BUFFER_USD:-15}"
BUDGET_DISPLAY_NAME="${BUDGET_DISPLAY_NAME:-SupplyNerva Monthly Guardrail}"
BUDGET_THRESHOLDS="${BUDGET_THRESHOLDS:-0.8,0.9,1.0}"
BUDGET_TOPIC="${BUDGET_TOPIC:-supplynerva-budget-alerts}"
BUDGET_SUBSCRIPTION="${BUDGET_SUBSCRIPTION:-supplynerva-budget-alerts-sub}"
BUDGET_MESSAGE_RETENTION="${BUDGET_MESSAGE_RETENTION:-2678400s}"
ENABLE_BUDGET_ALERT_GUARDRAIL="${ENABLE_BUDGET_ALERT_GUARDRAIL:-1}"
DELETE_LEGACY_SCHEDULER="${DELETE_LEGACY_SCHEDULER:-1}"
APPLY_IAM="${APPLY_IAM:-0}"
EXECUTE_ONCE="${EXECUTE_ONCE:-1}"

if [[ -z "${GCLOUD_BIN}" ]]; then
  if command -v gcloud >/dev/null 2>&1; then
    GCLOUD_BIN="$(command -v gcloud)"
  elif [[ -x "./google-cloud-sdk/bin/gcloud" ]]; then
    GCLOUD_BIN="./google-cloud-sdk/bin/gcloud"
  elif [[ -x "/Users/ritwij/google-cloud-sdk/bin/gcloud" ]]; then
    GCLOUD_BIN="/Users/ritwij/google-cloud-sdk/bin/gcloud"
  else
    echo "ERROR: gcloud not found. Install Cloud SDK or set GCLOUD_BIN."
    exit 1
  fi
fi

"${GCLOUD_BIN}" config set project "${PROJECT_ID}" >/dev/null
ACTIVE_ACCOUNT="$("${GCLOUD_BIN}" config get-value account 2>/dev/null || true)"
if [[ "${ACTIVE_ACCOUNT}" != "${EXPECTED_ACCOUNT}" ]]; then
  echo "ERROR: Active gcloud account is '${ACTIVE_ACCOUNT}', expected '${EXPECTED_ACCOUNT}'."
  echo "Run: ${GCLOUD_BIN} config set account ${EXPECTED_ACCOUNT}"
  exit 1
fi

echo "Using account: ${ACTIVE_ACCOUNT}"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"

is_budget_enabled=0
if [[ "${MONTHLY_NET_BUDGET_USD}" != "0" ]] && [[ "${MONTHLY_NET_BUDGET_USD}" != "0.0" ]]; then
  is_budget_enabled=1
fi

echo "Enabling required APIs for automation..."
"${GCLOUD_BIN}" services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  discoveryengine.googleapis.com \
  pubsub.googleapis.com \
  bigquery.googleapis.com \
  bigquerydatatransfer.googleapis.com \
  cloudbilling.googleapis.com \
  billingbudgets.googleapis.com

PROJECT_NUMBER="$("${GCLOUD_BIN}" projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

IMAGE="${IMAGE:-}"
if [[ -z "${IMAGE}" ]]; then
  IMAGE="$(${GCLOUD_BIN} run jobs describe "${JOB_NAME}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --format='value(spec.template.spec.template.spec.containers[0].image)' 2>/dev/null || true)"
fi
if [[ -z "${IMAGE}" ]]; then
  IMAGE="$(${GCLOUD_BIN} run services describe aetherchain-worker \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --format='value(spec.template.spec.containers[0].image)' 2>/dev/null || true)"
fi
if [[ -z "${IMAGE}" ]]; then
  echo "ERROR: Could not resolve container image."
  echo "Set IMAGE env var, e.g. IMAGE=gcr.io/${PROJECT_ID}/aetherchain-worker:<tag>"
  exit 1
fi

echo "Using image: ${IMAGE}"

JOB_SA="${JOB_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
SCHEDULER_SA="${SCHEDULER_SA:-${JOB_SA}}"

echo "Job service account: ${JOB_SA}"
echo "Scheduler service account: ${SCHEDULER_SA}"

if [[ "${is_budget_enabled}" == "1" ]] && [[ "${ENABLE_BUDGET_ALERT_GUARDRAIL}" == "1" ]]; then
  BILLING_ACCOUNT_NAME="$("${GCLOUD_BIN}" billing projects describe "${PROJECT_ID}" --format='value(billingAccountName)' 2>/dev/null || true)"
  if [[ -z "${BILLING_ACCOUNT_NAME}" ]]; then
    echo "ERROR: Could not resolve billing account for project ${PROJECT_ID}."
    echo "Link a billing account first: ${GCLOUD_BIN} billing projects link ${PROJECT_ID} --billing-account <ACCOUNT_ID>"
    exit 1
  fi
  BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_NAME#billingAccounts/}"
  BILLING_ACCOUNT_RESOURCE="billingAccounts/${BILLING_ACCOUNT_ID}"
  BUDGET_TOPIC_PATH="projects/${PROJECT_ID}/topics/${BUDGET_TOPIC}"

  echo "Configuring budget alert guardrail on ${BILLING_ACCOUNT_RESOURCE}..."
  if "${GCLOUD_BIN}" pubsub topics describe "${BUDGET_TOPIC}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Budget topic exists: ${BUDGET_TOPIC}"
  else
    echo "Creating budget topic ${BUDGET_TOPIC}..."
    "${GCLOUD_BIN}" pubsub topics create "${BUDGET_TOPIC}" --project "${PROJECT_ID}" >/dev/null
  fi

  "${GCLOUD_BIN}" pubsub topics add-iam-policy-binding "${BUDGET_TOPIC}" \
    --project "${PROJECT_ID}" \
    --member "serviceAccount:billing-budget-alert@system.gserviceaccount.com" \
    --role "roles/pubsub.publisher" >/dev/null

  if "${GCLOUD_BIN}" pubsub subscriptions describe "${BUDGET_SUBSCRIPTION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    current_topic="$("${GCLOUD_BIN}" pubsub subscriptions describe "${BUDGET_SUBSCRIPTION}" --project "${PROJECT_ID}" --format='value(topic)')"
    if [[ "${current_topic}" != "${BUDGET_TOPIC_PATH}" ]]; then
      echo "ERROR: Subscription ${BUDGET_SUBSCRIPTION} is attached to ${current_topic}, expected ${BUDGET_TOPIC_PATH}."
      echo "Delete or rename BUDGET_SUBSCRIPTION before rerunning."
      exit 1
    fi
    "${GCLOUD_BIN}" pubsub subscriptions update "${BUDGET_SUBSCRIPTION}" \
      --project "${PROJECT_ID}" \
      --message-retention-duration "${BUDGET_MESSAGE_RETENTION}" \
      --expiration-period never >/dev/null
  else
    "${GCLOUD_BIN}" pubsub subscriptions create "${BUDGET_SUBSCRIPTION}" \
      --project "${PROJECT_ID}" \
      --topic "${BUDGET_TOPIC}" \
      --message-retention-duration "${BUDGET_MESSAGE_RETENTION}" \
      --expiration-period never >/dev/null
  fi

  BUDGET_THRESHOLD_VALUES=()
  while IFS= read -r threshold; do
    if [[ -n "${threshold}" ]]; then
      BUDGET_THRESHOLD_VALUES+=("${threshold}")
    fi
  done < <(
    python3 - "${MONTHLY_NET_BUDGET_USD}" "${MONTHLY_NET_STOP_BUFFER_USD}" "${BUDGET_THRESHOLDS}" <<'PY'
import sys

budget = float(sys.argv[1])
stop_buffer = float(sys.argv[2])
raw_thresholds = str(sys.argv[3]).strip()
values = set()
for item in raw_thresholds.split(','):
    text = item.strip()
    if not text:
        continue
    try:
        value = float(text)
    except ValueError:
        continue
    if 0 < value <= 1:
        values.add(round(value, 6))

if budget > 0:
    auto_value = (budget - stop_buffer) / budget
    if 0 < auto_value < 1:
        values.add(round(auto_value, 6))

for value in sorted(values):
    formatted = f"{value:.6f}".rstrip('0').rstrip('.')
    print(formatted)
PY
  )

  if [[ "${#BUDGET_THRESHOLD_VALUES[@]}" -eq 0 ]]; then
    echo "ERROR: No valid budget thresholds resolved. Check BUDGET_THRESHOLDS."
    exit 1
  fi

  existing_budget_name="$("${GCLOUD_BIN}" billing budgets list \
    --billing-account "${BILLING_ACCOUNT_ID}" \
    --filter "displayName='${BUDGET_DISPLAY_NAME}'" \
    --format='value(name)' | head -n 1)"

  budget_amount_arg="${MONTHLY_NET_BUDGET_USD}USD"

  if [[ -n "${existing_budget_name}" ]]; then
    echo "Updating budget ${existing_budget_name}..."
    update_args=(
      "${existing_budget_name}"
      --billing-account "${BILLING_ACCOUNT_ID}"
      --display-name "${BUDGET_DISPLAY_NAME}"
      --budget-amount "${budget_amount_arg}"
      --calendar-period month
      --credit-types-treatment include-all-credits
      --filter-projects "projects/${PROJECT_ID}"
      --notifications-rule-pubsub-topic "${BUDGET_TOPIC_PATH}"
      --clear-threshold-rules
    )
    for threshold in "${BUDGET_THRESHOLD_VALUES[@]}"; do
      update_args+=(--add-threshold-rule "percent=${threshold}")
    done
    "${GCLOUD_BIN}" billing budgets update "${update_args[@]}" >/dev/null
    BUDGET_RESOURCE="${existing_budget_name}"
  else
    echo "Creating budget '${BUDGET_DISPLAY_NAME}'..."
    create_args=(
      --billing-account "${BILLING_ACCOUNT_ID}"
      --display-name "${BUDGET_DISPLAY_NAME}"
      --budget-amount "${budget_amount_arg}"
      --calendar-period month
      --credit-types-treatment include-all-credits
      --filter-projects "projects/${PROJECT_ID}"
      --notifications-rule-pubsub-topic "${BUDGET_TOPIC_PATH}"
    )
    for threshold in "${BUDGET_THRESHOLD_VALUES[@]}"; do
      create_args+=(--threshold-rule "percent=${threshold}")
    done
    BUDGET_RESOURCE="$("${GCLOUD_BIN}" billing budgets create "${create_args[@]}" --format='value(name)')"
  fi

  echo "Budget guardrail topic: ${BUDGET_TOPIC_PATH}"
  echo "Budget guardrail subscription: projects/${PROJECT_ID}/subscriptions/${BUDGET_SUBSCRIPTION}"
  echo "Budget guardrail budget: ${BUDGET_RESOURCE}"
fi

if [[ "${is_budget_enabled}" == "1" ]] && [[ "${AUTO_CREATE_BILLING_EXPORT_DATASET}" == "1" ]]; then
  BQ_BIN=""
  if command -v bq >/dev/null 2>&1; then
    BQ_BIN="$(command -v bq)"
  elif [[ -x "$(dirname "${GCLOUD_BIN}")/bq" ]]; then
    BQ_BIN="$(dirname "${GCLOUD_BIN}")/bq"
  fi
  if [[ -n "${BQ_BIN}" ]]; then
    if "${BQ_BIN}" --project_id "${BILLING_PROJECT_ID}" show --dataset "${BILLING_PROJECT_ID}:${BILLING_EXPORT_DATASET}" >/dev/null 2>&1; then
      echo "Billing export dataset exists: ${BILLING_PROJECT_ID}:${BILLING_EXPORT_DATASET}"
    else
      echo "Creating billing export dataset scaffold: ${BILLING_PROJECT_ID}:${BILLING_EXPORT_DATASET}"
      "${BQ_BIN}" --project_id "${BILLING_PROJECT_ID}" --location "${BILLING_EXPORT_DATASET_LOCATION}" mk --dataset "${BILLING_PROJECT_ID}:${BILLING_EXPORT_DATASET}" >/dev/null
    fi
  else
    echo "WARNING: bq command not found; skipping billing export dataset scaffold."
  fi
fi

RUN_ARGS=(
  "manage.py"
  "ingest_gdelt_discovery"
  "--project-id" "${PROJECT_ID}"
  "--project-number" "${PROJECT_NUMBER}"
  "--datastore-id" "${DATASTORE_ID}"
  "--lookback-hours" "${LOOKBACK_HOURS}"
  "--max-records" "${MAX_RECORDS}"
  "--max-import" "${MAX_IMPORT}"
  "--batch-size" "${BATCH_SIZE}"
  "--daily-max-import" "${DAILY_MAX_IMPORT}"
)

if [[ "${MONTHLY_NET_BUDGET_USD}" != "0" ]] && [[ "${MONTHLY_NET_BUDGET_USD}" != "0.0" ]]; then
  echo "Budget guardrail enabled with monthly net budget ${MONTHLY_NET_BUDGET_USD} (auto-detect table if omitted)."
  if [[ "${BILLING_PROJECT_ID}" != "${PROJECT_ID}" ]]; then
    RUN_ARGS+=("--billing-project-id" "${BILLING_PROJECT_ID}")
  fi
  if [[ -n "${BILLING_EXPORT_TABLE}" ]]; then
    RUN_ARGS+=("--billing-export-table" "${BILLING_EXPORT_TABLE}")
  fi
  RUN_ARGS+=(
    "--monthly-net-budget-usd" "${MONTHLY_NET_BUDGET_USD}"
    "--monthly-net-stop-buffer-usd" "${MONTHLY_NET_STOP_BUFFER_USD}"
  )
else
  echo "Budget guardrail disabled (set MONTHLY_NET_BUDGET_USD>0 to enable)."
fi
RUN_CMD="python"
for arg in "${RUN_ARGS[@]}"; do
  RUN_CMD+=" $(printf '%q' "${arg}")"
done

COMMON_JOB_FLAGS=(
  --image "${IMAGE}"
  --region "${REGION}"
  --project "${PROJECT_ID}"
  --command "/bin/sh"
  --args "-c,${RUN_CMD}"
  --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},GCP_QUOTA_PROJECT_ID=${PROJECT_ID},CREDIT_FIRST_MODE=true,BILLING_EXPORT_SCAN_PROJECTS=${BILLING_EXPORT_SCAN_PROJECTS}"
  --service-account "${JOB_SA}"
)

if "${GCLOUD_BIN}" secrets describe "${SERVING_CONFIG_SECRET}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  COMMON_JOB_FLAGS+=(
    --set-secrets "VERTEX_SEARCH_SERVING_CONFIG=${SERVING_CONFIG_SECRET}:latest"
  )
else
  echo "WARNING: Secret ${SERVING_CONFIG_SECRET} not found; creating job without VERTEX_SEARCH_SERVING_CONFIG."
fi

if "${GCLOUD_BIN}" run jobs describe "${JOB_NAME}" --region "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Updating Cloud Run job ${JOB_NAME}..."
  "${GCLOUD_BIN}" run jobs update "${JOB_NAME}" "${COMMON_JOB_FLAGS[@]}"
else
  echo "Creating Cloud Run job ${JOB_NAME}..."
  "${GCLOUD_BIN}" run jobs create "${JOB_NAME}" "${COMMON_JOB_FLAGS[@]}"
fi

RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"

if "${GCLOUD_BIN}" scheduler jobs describe "${SCHEDULER_NAME}" --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Updating Cloud Scheduler job ${SCHEDULER_NAME}..."
  "${GCLOUD_BIN}" scheduler jobs update http "${SCHEDULER_NAME}" \
    --location "${REGION}" \
    --project "${PROJECT_ID}" \
    --schedule "${SCHEDULE}" \
    --time-zone "${SCHEDULE_TIMEZONE}" \
    --uri "${RUN_URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA}" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --message-body '{}'
else
  echo "Creating Cloud Scheduler job ${SCHEDULER_NAME}..."
  "${GCLOUD_BIN}" scheduler jobs create http "${SCHEDULER_NAME}" \
    --location "${REGION}" \
    --project "${PROJECT_ID}" \
    --schedule "${SCHEDULE}" \
    --time-zone "${SCHEDULE_TIMEZONE}" \
    --uri "${RUN_URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA}" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --message-body '{}'
fi

LEGACY_SCHEDULER_NAME="supplynerva-ingest-6h"
if [[ "${SCHEDULER_NAME}" != "${LEGACY_SCHEDULER_NAME}" ]] && \
   "${GCLOUD_BIN}" scheduler jobs describe "${LEGACY_SCHEDULER_NAME}" --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  if [[ "${DELETE_LEGACY_SCHEDULER}" == "1" ]]; then
    echo "Deleting legacy scheduler job ${LEGACY_SCHEDULER_NAME} to avoid duplicate triggers..."
    "${GCLOUD_BIN}" scheduler jobs delete "${LEGACY_SCHEDULER_NAME}" \
      --location "${REGION}" \
      --project "${PROJECT_ID}" \
      --quiet
  else
    echo "WARNING: Legacy scheduler ${LEGACY_SCHEDULER_NAME} still exists and may duplicate ingest runs."
  fi
fi

if [[ "${APPLY_IAM}" == "1" ]]; then
  echo "Applying IAM bindings (project-level) ..."
  "${GCLOUD_BIN}" projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${JOB_SA}" \
    --role "roles/secretmanager.secretAccessor" >/dev/null

  "${GCLOUD_BIN}" projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${JOB_SA}" \
    --role "roles/discoveryengine.editor" >/dev/null

  "${GCLOUD_BIN}" projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SCHEDULER_SA}" \
    --role "roles/run.developer" >/dev/null

  "${GCLOUD_BIN}" projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SCHEDULER_SA}" \
    --role "roles/run.invoker" >/dev/null

  echo "IAM bindings applied."
else
  echo "Skipped IAM auto-apply (APPLY_IAM=${APPLY_IAM})."
  echo "If run/permission errors occur, re-run with APPLY_IAM=1 or grant roles manually."
fi

if [[ "${EXECUTE_ONCE}" == "1" ]]; then
  echo "Executing Cloud Run job once for smoke check..."
  "${GCLOUD_BIN}" run jobs execute "${JOB_NAME}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --wait
fi

echo
echo "Automation provisioned:"
echo "- Cloud Run job: ${JOB_NAME}"
echo "- Scheduler job: ${SCHEDULER_NAME}"
echo "- Schedule: ${SCHEDULE} (${SCHEDULE_TIMEZONE})"
echo "- Run endpoint: ${RUN_URI}"
if [[ "${is_budget_enabled}" == "1" ]] && [[ "${ENABLE_BUDGET_ALERT_GUARDRAIL}" == "1" ]]; then
  echo "- Budget alert guardrail: enabled (${BUDGET_DISPLAY_NAME})"
fi
if [[ -z "${BILLING_EXPORT_TABLE}" ]] && [[ "${is_budget_enabled}" == "1" ]]; then
  echo "- Billing export table: not pinned (runtime auto-detect enabled)"
  echo "  If no table is found at runtime, table-based MTD guardrail will self-disable for that execution."
  echo "  Enable Cloud Billing export in Console to ${BILLING_PROJECT_ID}:${BILLING_EXPORT_DATASET} for strict table-based enforcement."
fi
