from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from aetherchain.core.gcp_auth import build_google_auth_headers, resolve_gcp_project_id
from aetherchain.core.gdelt_ingest import (
    DEFAULT_GDELT_QUERY,
    IngestStats,
    build_discovery_documents,
    default_window,
    fetch_gdelt_articles,
    import_discovery_documents_inline,
    normalize_gdelt_query,
    write_json,
    write_jsonl,
)


_BQ_TABLE_REF_RE = re.compile(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_*-]+$')
_BILLING_EXPORT_TABLE_ID_RE = re.compile(r'^gcp_billing_export(_resource)?_v1_[A-Za-z0-9_]+$')


def _normalize_utc_day(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return ''

    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return text[:10]

    compact = text[:8]
    if len(compact) == 8 and compact.isdigit():
        return f'{compact[0:4]}-{compact[4:6]}-{compact[6:8]}'

    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return ''

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def _extract_ingested_day(document: Any) -> str:
    if not isinstance(document, dict):
        return ''

    for data_key in ('structData', 'jsonData'):
        data = document.get(data_key)
        if not isinstance(data, dict):
            continue
        for timestamp_key in ('ingested_at', 'ingestedAt'):
            utc_day = _normalize_utc_day(data.get(timestamp_key))
            if utc_day:
                return utc_day
    return ''


def _sanitize_bq_table_ref(value: Any) -> str:
    cleaned = str(value or '').strip().strip('`')
    if not cleaned:
        return ''
    if not _BQ_TABLE_REF_RE.fullmatch(cleaned):
        raise CommandError(
            '--billing-export-table must look like project.dataset.table_or_wildcard '
            '(example: my-billing-proj.billing_export.gcp_billing_export_resource_v1_123ABC_*)'
        )
    return cleaned


def _is_billing_export_table_id(table_id: Any) -> bool:
    return bool(_BILLING_EXPORT_TABLE_ID_RE.fullmatch(str(table_id or '').strip()))


def _table_preference_score(table_id: Any) -> int:
    table = str(table_id or '').strip()
    if table.startswith('gcp_billing_export_resource_v1_'):
        return 0
    if table.startswith('gcp_billing_export_v1_'):
        return 1
    return 9


class Command(BaseCommand):
    help = (
        "Fetches fresh supply-risk events from GDELT and imports normalized documents "
        "into Discovery Engine (credit-first ingest pipeline)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=str, default='', help='Override GCP project id.')
        parser.add_argument('--project-number', type=str, default='', help='Optional project number override.')
        parser.add_argument('--datastore-id', type=str, default='supplynerva-store')
        parser.add_argument('--query', type=str, default=DEFAULT_GDELT_QUERY)
        parser.add_argument('--lookback-hours', type=int, default=6)
        parser.add_argument('--max-records', type=int, default=50)
        parser.add_argument('--max-import', type=int, default=40)
        parser.add_argument('--batch-size', type=int, default=20)
        parser.add_argument('--daily-max-import', type=int, default=200)
        parser.add_argument('--billing-export-table', type=str, default='')
        parser.add_argument('--billing-project-id', type=str, default='')
        parser.add_argument('--monthly-net-budget-usd', type=float, default=0.0)
        parser.add_argument('--monthly-net-stop-buffer-usd', type=float, default=15.0)
        parser.add_argument('--request-timeout', type=int, default=20)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--raw-json-out', type=str, default='')
        parser.add_argument('--jsonl-out', type=str, default='')

    def handle(self, *args, **options):
        project_id = str(options.get('project_id') or '').strip() or resolve_gcp_project_id()
        if not project_id:
            raise CommandError('Unable to resolve project id. Set GCP_PROJECT_ID or pass --project-id.')

        datastore_id = str(options['datastore_id']).strip()
        if not datastore_id:
            raise CommandError('--datastore-id cannot be empty.')

        lookback_hours = max(int(options['lookback_hours']), 1)
        max_records = max(int(options['max_records']), 1)
        max_import = max(int(options['max_import']), 1)
        daily_max_import = int(options['daily_max_import'])
        batch_size = max(int(options['batch_size']), 1)
        timeout_seconds = max(
            int(options['request_timeout']),
            int(getattr(settings, 'EXTERNAL_REQUEST_TIMEOUT_SECONDS', 20)),
        )

        query = normalize_gdelt_query(str(options['query']).strip() or DEFAULT_GDELT_QUERY)
        billing_export_table = _sanitize_bq_table_ref(options.get('billing_export_table'))
        billing_project_id = str(options.get('billing_project_id') or '').strip() or project_id
        monthly_net_budget_usd = max(float(options.get('monthly_net_budget_usd') or 0.0), 0.0)
        monthly_net_stop_buffer_usd = max(
            float(options.get('monthly_net_stop_buffer_usd') or 0.0),
            0.0,
        )

        headers = build_google_auth_headers(project_id)
        headers['Content-Type'] = 'application/json'
        project_number = str(options.get('project_number') or '').strip()
        if not project_number:
            project_number = self._project_number(project_id, headers)

        if monthly_net_budget_usd > 0:
            if not billing_export_table:
                billing_export_table = self._autodetect_billing_export_table(
                    billing_project_id=billing_project_id,
                    headers=headers,
                    timeout_seconds=timeout_seconds,
                )
                if billing_export_table:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Auto-detected billing export table: {billing_export_table}'
                        )
                    )
            if not billing_export_table:
                self.stdout.write(
                    self.style.WARNING(
                        'Monthly budget guardrail requested, but --billing-export-table is empty. '
                        'Budget guardrail is disabled for this run.'
                    )
                )
            else:
                try:
                    gross_usd, credits_usd, net_usd = self._month_to_date_net_cost(
                        billing_project_id=billing_project_id,
                        billing_export_table=billing_export_table,
                        headers=headers,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception as exc:
                    self.stdout.write(
                        self.style.ERROR(f'Budget guardrail check failed: {exc}')
                    )
                    self.stdout.write(
                        self.style.WARNING(
                            'Fail-closed guardrail mode: skipping ingest cycle.'
                        )
                    )
                    return

                remaining_budget = monthly_net_budget_usd - net_usd
                self.stdout.write(
                    f'Budget guardrail (UTC MTD): gross={gross_usd:.2f}, '
                    f'credits={credits_usd:.2f}, net={net_usd:.2f}, '
                    f'budget={monthly_net_budget_usd:.2f}, remaining={remaining_budget:.2f}, '
                    f'stop_buffer={monthly_net_stop_buffer_usd:.2f}'
                )
                if remaining_budget <= monthly_net_stop_buffer_usd:
                    self.stdout.write(
                        self.style.WARNING(
                            'Monthly net budget guardrail reached. Skipping ingest cycle.'
                        )
                    )
                    return

        effective_max_import = max_import
        if daily_max_import > 0:
            today_count, total_docs, missing_ingested_day, utc_day = self._count_documents_ingested_today(
                project_number=project_number,
                datastore_id=datastore_id,
                headers=headers,
            )
            remaining_capacity = max(daily_max_import - today_count, 0)
            effective_max_import = min(max_import, remaining_capacity)
            self.stdout.write(
                f'Daily cap check (UTC day {utc_day}): existing={today_count}, cap={daily_max_import}, '
                f'remaining={remaining_capacity}, requested={max_import}, effective={effective_max_import}'
            )
            if missing_ingested_day > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f'Count note: {missing_ingested_day} of {total_docs} existing docs had no ingested timestamp metadata '
                        'and were excluded from UTC-day cap counting.'
                    )
                )
            if effective_max_import <= 0:
                self.stdout.write(
                    self.style.WARNING('Daily import cap reached, skipping this ingest cycle.')
                )
                return

        start_time, end_time = default_window(lookback_hours)
        self.stdout.write(
            f'Ingest window (UTC): {start_time.isoformat()} -> {end_time.isoformat()} '
            f'| query="{query}"'
        )

        articles = fetch_gdelt_articles(
            query=query,
            start_time=start_time,
            end_time=end_time,
            max_records=max_records,
            timeout_seconds=timeout_seconds,
        )

        if options['raw_json_out']:
            write_json(str(options['raw_json_out']), articles)
            self.stdout.write(f'Wrote raw GDELT payload: {options["raw_json_out"]}')

        documents = build_discovery_documents(
            articles=articles,
            query_tag=query,
            max_documents=effective_max_import,
        )

        if options['jsonl_out']:
            write_jsonl(str(options['jsonl_out']), documents)
            self.stdout.write(f'Wrote normalized JSONL: {options["jsonl_out"]}')

        stats = IngestStats(
            fetched_articles=len(articles),
            prepared_documents=len(documents),
            imported_success=0,
            imported_failure=0,
        )

        self.stdout.write(f'Fetched articles: {stats.fetched_articles}')
        self.stdout.write(f'Prepared documents: {stats.prepared_documents}')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run enabled, skipping Discovery import.'))
            return

        if not documents:
            self.stdout.write(self.style.WARNING('No documents prepared for import.'))
            return

        imported_success, imported_failure = import_discovery_documents_inline(
            project_number=project_number,
            project_id=project_id,
            datastore_id=datastore_id,
            documents=documents,
            headers=headers,
            timeout_seconds=timeout_seconds,
            batch_size=batch_size,
        )

        stats.imported_success = imported_success
        stats.imported_failure = imported_failure

        self.stdout.write(self.style.SUCCESS('Discovery ingest completed.'))
        self.stdout.write(f'Imported success: {stats.imported_success}')
        self.stdout.write(f'Imported failure: {stats.imported_failure}')

    def _project_number(self, project_id: str, headers: dict[str, str]) -> str:
        url = f'https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}'
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()

        project_number = str(payload.get('projectNumber', '')).strip()
        if not project_number:
            raise CommandError(f'Failed to resolve project number for {project_id}.')
        return project_number

    def _count_documents_ingested_today(
        self,
        *,
        project_number: str,
        datastore_id: str,
        headers: dict[str, str],
    ) -> tuple[int, int, int, str]:
        utc_day = datetime.now(timezone.utc).date().isoformat()
        base_url = (
            'https://discoveryengine.googleapis.com/v1/'
            f'projects/{project_number}/locations/global/collections/default_collection/'
            f'dataStores/{datastore_id}/branches/default_branch/documents'
        )

        total = 0
        total_documents = 0
        missing_ingested_day = 0
        next_page_token = ''

        while True:
            params: dict[str, str] = {'pageSize': '100'}
            if next_page_token:
                params['pageToken'] = next_page_token

            response = requests.get(base_url, headers=headers, params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()

            documents = payload.get('documents', [])
            if isinstance(documents, list):
                for document in documents:
                    total_documents += 1
                    ingested_day = _extract_ingested_day(document)
                    if not ingested_day:
                        missing_ingested_day += 1
                        continue
                    if ingested_day == utc_day:
                        total += 1

            next_page_token = str(payload.get('nextPageToken', '')).strip()
            if not next_page_token:
                break

        return total, total_documents, missing_ingested_day, utc_day

    def _month_to_date_net_cost(
        self,
        *,
        billing_project_id: str,
        billing_export_table: str,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> tuple[float, float, float]:
        query = f"""
SELECT
  COALESCE(SUM(cost), 0.0) AS gross_cost_usd,
  COALESCE(SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0.0)), 0.0) AS credits_usd,
  COALESCE(SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0.0)), 0.0) AS net_cost_usd
FROM `{billing_export_table}`
WHERE DATE(usage_start_time) BETWEEN DATE_TRUNC(CURRENT_DATE("UTC"), MONTH) AND CURRENT_DATE("UTC")
"""
        url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{billing_project_id}/queries'
        payload = {
            'query': query,
            'useLegacySql': False,
            'maxResults': 1,
            'timeoutMs': int(max(timeout_seconds, 20) * 1000),
        }
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
        result = response.json()

        attempts = 0
        while not result.get('jobComplete', False) and attempts < 6:
            attempts += 1
            job_ref = result.get('jobReference', {}) if isinstance(result, dict) else {}
            job_id = str(job_ref.get('jobId', '')).strip()
            location = str(job_ref.get('location', '')).strip() or 'US'
            if not job_id:
                break
            time.sleep(2)
            poll_url = (
                f'https://bigquery.googleapis.com/bigquery/v2/projects/{billing_project_id}/queries/{job_id}'
            )
            poll_params = {'location': location, 'maxResults': '1'}
            poll_response = requests.get(
                poll_url,
                headers=headers,
                params=poll_params,
                timeout=timeout_seconds,
            )
            poll_response.raise_for_status()
            result = poll_response.json()

        rows = result.get('rows', [])
        if not isinstance(rows, list) or not rows:
            return 0.0, 0.0, 0.0

        first_row = rows[0] if isinstance(rows[0], dict) else {}
        fields = first_row.get('f', []) if isinstance(first_row, dict) else []
        if not isinstance(fields, list):
            return 0.0, 0.0, 0.0

        return (
            self._field_to_float(fields, 0),
            self._field_to_float(fields, 1),
            self._field_to_float(fields, 2),
        )

    def _field_to_float(self, fields: list[Any], index: int) -> float:
        if index < 0 or index >= len(fields):
            return 0.0
        item = fields[index]
        if not isinstance(item, dict):
            return 0.0
        value = item.get('v')
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _autodetect_billing_export_table(
        self,
        *,
        billing_project_id: str,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> str:
        scan_projects_env = str(getattr(settings, 'BILLING_EXPORT_SCAN_PROJECTS', '') or '').strip()
        scan_projects: list[str] = []
        for project_id in [billing_project_id] + [item.strip() for item in scan_projects_env.split(',')]:
            if project_id and project_id not in scan_projects:
                scan_projects.append(project_id)

        candidates: list[tuple[int, str]] = []
        for project_id in scan_projects:
            for dataset_id in self._list_bigquery_datasets(
                project_id=project_id,
                headers=headers,
                timeout_seconds=timeout_seconds,
            ):
                for table_id in self._list_bigquery_tables(
                    project_id=project_id,
                    dataset_id=dataset_id,
                    headers=headers,
                    timeout_seconds=timeout_seconds,
                ):
                    if not _is_billing_export_table_id(table_id):
                        continue
                    full_ref = f'{project_id}.{dataset_id}.{table_id}'
                    candidates.append((_table_preference_score(table_id), full_ref))

        if not candidates:
            return ''
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][1]

    def _list_bigquery_datasets(
        self,
        *,
        project_id: str,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> list[str]:
        url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/datasets'
        result: list[str] = []
        token = ''
        while True:
            params: dict[str, str] = {'maxResults': '1000'}
            if token:
                params['pageToken'] = token
            response = requests.get(url, headers=headers, params=params, timeout=timeout_seconds)
            if response.status_code in (403, 404):
                return result
            response.raise_for_status()
            payload = response.json()
            datasets = payload.get('datasets', [])
            if isinstance(datasets, list):
                for item in datasets:
                    if not isinstance(item, dict):
                        continue
                    ref = item.get('datasetReference')
                    if not isinstance(ref, dict):
                        continue
                    dataset_id = str(ref.get('datasetId', '')).strip()
                    if dataset_id:
                        result.append(dataset_id)
            token = str(payload.get('nextPageToken', '')).strip()
            if not token:
                break
        return result

    def _list_bigquery_tables(
        self,
        *,
        project_id: str,
        dataset_id: str,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> list[str]:
        url = (
            f'https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/'
            f'datasets/{dataset_id}/tables'
        )
        result: list[str] = []
        token = ''
        while True:
            params: dict[str, str] = {'maxResults': '1000'}
            if token:
                params['pageToken'] = token
            response = requests.get(url, headers=headers, params=params, timeout=timeout_seconds)
            if response.status_code in (403, 404):
                return result
            response.raise_for_status()
            payload = response.json()
            tables = payload.get('tables', [])
            if isinstance(tables, list):
                for item in tables:
                    if not isinstance(item, dict):
                        continue
                    ref = item.get('tableReference')
                    if not isinstance(ref, dict):
                        continue
                    table_id = str(ref.get('tableId', '')).strip()
                    if table_id:
                        result.append(table_id)
            token = str(payload.get('nextPageToken', '')).strip()
            if not token:
                break
        return result
