from __future__ import annotations

from typing import Any

import requests
from django.core.management.base import BaseCommand, CommandError

from aetherchain.core.gcp_auth import build_google_auth_headers, resolve_gcp_project_id


class Command(BaseCommand):
    help = "Checks Discovery Engine and Vertex GenAI readiness for the active GCP project."

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=str, default='', help='Override project id')

    def handle(self, *args, **options):
        project_id = str(options.get('project_id') or '').strip() or resolve_gcp_project_id()
        if not project_id:
            raise CommandError('Unable to resolve project id. Set GCP_PROJECT_ID or pass --project-id.')

        headers = build_google_auth_headers(project_id)
        headers['Content-Type'] = 'application/json'

        project_number = self._project_number(project_id, headers)
        if not project_number:
            raise CommandError('Failed to resolve project number from Cloud Resource Manager API.')

        engines = self._list_resource(
            url=(
                'https://discoveryengine.googleapis.com/v1/'
                f'projects/{project_number}/locations/global/collections/default_collection/engines'
            ),
            list_key='engines',
            headers=headers,
        )
        data_stores = self._list_resource(
            url=(
                'https://discoveryengine.googleapis.com/v1/'
                f'projects/{project_number}/locations/global/collections/default_collection/dataStores'
            ),
            list_key='dataStores',
            headers=headers,
        )

        self.stdout.write(self.style.SUCCESS(f'Project: {project_id} ({project_number})'))
        self.stdout.write(f'Discovery Engine data stores: {len(data_stores)}')
        self.stdout.write(f'Discovery Engine engines: {len(engines)}')

        if data_stores:
            self.stdout.write('Data stores:')
            for item in data_stores:
                self.stdout.write(f"  - {item.get('name', 'unknown')}")

        if engines:
            self.stdout.write('Engines:')
            for item in engines:
                self.stdout.write(f"  - {item.get('name', 'unknown')}")
        else:
            self.stdout.write(self.style.WARNING('No engines found. Create one before enabling retrieval in production.'))

        if data_stores:
            first_name = str(data_stores[0].get('name', ''))
            datastore_id = self._extract_datastore_id(first_name)
            if datastore_id:
                total_docs, indexed_docs, pending_docs = self._documents_index_status(
                    project_number=project_number,
                    datastore_id=datastore_id,
                    headers=headers,
                )
                self.stdout.write(f'Default-branch documents in {datastore_id}: {total_docs}')
                self.stdout.write(f'Documents with index_time set: {indexed_docs}')
                self.stdout.write(f'Documents still pending indexing: {pending_docs}')

        self.stdout.write('')
        self.stdout.write('Recommended next steps:')
        if not data_stores:
            self.stdout.write('1) Create a Discovery Engine data store and ingest supply evidence corpus.')
        else:
            self.stdout.write('1) Keep ingesting fresh event and route evidence into your data store.')

        if not engines:
            self.stdout.write(
                '2) Create a search engine + serving config, then set VERTEX_SEARCH_SERVING_CONFIG '
                'in Secret Manager/env.'
            )
        else:
            self.stdout.write('2) Confirm VERTEX_SEARCH_SERVING_CONFIG points to the intended engine.')

        self.stdout.write(
            '3) Keep CREDIT_FIRST_MODE=true and VERTEX_GENAI_MODEL unset for credit-first mode.'
        )
        self.stdout.write('4) Optionally set VERTEX_GENAI_MODEL when you intentionally want Vertex Gemini narratives.')
        self.stdout.write('5) Run billing SQL under /sql to verify GenAI credits are applied to used SKUs.')

    def _project_number(self, project_id: str, headers: dict[str, str]) -> str:
        url = f'https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}'
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()
        return str(payload.get('projectNumber', '')).strip()

    def _list_resource(
        self,
        url: str,
        list_key: str,
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()
        items = payload.get(list_key, [])
        if isinstance(items, list):
            return items
        return []

    def _extract_datastore_id(self, datastore_name: str) -> str:
        marker = '/dataStores/'
        if marker not in datastore_name:
            return ''
        return datastore_name.split(marker, 1)[1].strip()

    def _documents_index_status(
        self,
        project_number: str,
        datastore_id: str,
        headers: dict[str, str],
    ) -> tuple[int, int, int]:
        url = (
            'https://discoveryengine.googleapis.com/v1/'
            f'projects/{project_number}/locations/global/collections/default_collection/'
            f'dataStores/{datastore_id}/branches/default_branch/documents'
        )
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()
        documents = payload.get('documents', [])
        if not isinstance(documents, list):
            return 0, 0, 0

        indexed = 0
        pending = 0
        for doc in documents:
            index_status = doc.get('indexStatus') if isinstance(doc, dict) else {}
            if not isinstance(index_status, dict):
                continue
            if index_status.get('indexTime'):
                indexed += 1
            elif index_status.get('pendingMessage'):
                pending += 1
        return len(documents), indexed, pending
