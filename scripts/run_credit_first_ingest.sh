#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${PROJECT_ID:-project-2281c357-4539-4bc6-b96}}"
DATASTORE_ID="${DATASTORE_ID:-supplynerva-store}"
LOOKBACK_HOURS="${LOOKBACK_HOURS:-6}"
MAX_RECORDS="${MAX_RECORDS:-40}"
MAX_IMPORT="${MAX_IMPORT:-30}"
BATCH_SIZE="${BATCH_SIZE:-15}"
DRY_RUN="${DRY_RUN:-0}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RAW_OUT="data/gdelt/raw_${STAMP}.json"
NORM_OUT="data/gdelt/normalized_${STAMP}.jsonl"

CMD=(
  python3 src/manage.py ingest_gdelt_discovery
  --project-id "${PROJECT_ID}"
  --datastore-id "${DATASTORE_ID}"
  --lookback-hours "${LOOKBACK_HOURS}"
  --max-records "${MAX_RECORDS}"
  --max-import "${MAX_IMPORT}"
  --batch-size "${BATCH_SIZE}"
  --raw-json-out "${RAW_OUT}"
  --jsonl-out "${NORM_OUT}"
)

if [[ "${DRY_RUN}" == "1" ]]; then
  CMD+=(--dry-run)
fi

echo "Running credit-first Discovery ingest for project ${PROJECT_ID}..."
"${CMD[@]}"

echo "Artifacts:"
echo "- ${RAW_OUT}"
echo "- ${NORM_OUT}"
