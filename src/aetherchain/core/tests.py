import base64
import json
from unittest.mock import patch

import requests
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from .gdelt_ingest import (
    build_discovery_documents,
    fetch_gdelt_articles,
    normalize_gdelt_query,
    stable_document_id,
)
from .management.commands.ingest_gdelt_discovery import (
    _extract_ingested_day,
    _is_billing_export_table_id,
    _normalize_utc_day,
    _sanitize_bq_table_ref,
    _table_preference_score,
)
from .gcp_auth import access_token
from .models import Alert
from .retrieval import fetch_supporting_evidence
from .tasks import _build_graph_lookup


@override_settings(API_TOKEN='test-token')
class SimulateImpactTests(APITestCase):
    @patch('aetherchain.core.tasks.fetch_supporting_evidence')
    @patch('aetherchain.core.tasks.db.cypher_query')
    def test_simulate_location_returns_structured_decision(
        self,
        mock_cypher_query,
        mock_fetch_supporting_evidence,
    ):
        mock_cypher_query.return_value = (
            [
                ['SKU-1', 'R-1'],
                ['SKU-2', 'R-2'],
            ],
            None,
        )
        mock_fetch_supporting_evidence.return_value = [
            {
                'title': 'Port bulletin',
                'uri': 'https://example.com/bulletin',
                'snippet': 'Congestion update',
                'score': 0.8,
            }
        ]

        response = self.client.post(
            reverse('simulate_impact'),
            data={'location': 'Port of Los Angeles', 'event_type': 'Port Congestion'},
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('summary_description', response.data)
        self.assertIn('recommended_action', response.data)
        self.assertIn('risk_score', response.data)
        self.assertIn('confidence_score', response.data)
        self.assertIn('evidence_summary', response.data)
        self.assertGreater(response.data['risk_score'], 0)
        self.assertGreater(response.data['confidence_score'], 0)

    def test_simulate_rejects_missing_event_target(self):
        response = self.client.post(
            reverse('simulate_impact'),
            data={},
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token',
        )
        self.assertEqual(response.status_code, 400)

    def test_alerts_endpoint_requires_token(self):
        Alert.objects.create(
            summary_description='Test',
            impact_analysis='Impact',
            recommended_action='Action',
        )
        response = self.client.get(reverse('alert-list'))
        self.assertEqual(response.status_code, 403)

    @patch('aetherchain.core.decision_engine.generate_decision_narrative')
    @patch('aetherchain.core.tasks.fetch_supporting_evidence')
    @patch('aetherchain.core.tasks.db.cypher_query')
    def test_simulate_prefers_genai_narrative_when_configured(
        self,
        mock_cypher_query,
        mock_fetch_supporting_evidence,
        mock_generate_decision_narrative,
    ):
        mock_cypher_query.return_value = (
            [
                ['SKU-1', 'R-1'],
            ],
            None,
        )
        mock_fetch_supporting_evidence.return_value = []
        mock_generate_decision_narrative.return_value = {
            'summary_description': 'AI summary',
            'impact_analysis': 'AI impact analysis',
            'recommended_action': 'AI recommendation',
        }

        response = self.client.post(
            reverse('simulate_impact'),
            data={'location': 'Port of Los Angeles', 'event_type': 'Port Congestion'},
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['summary_description'], 'AI summary')
        self.assertEqual(response.data['impact_analysis'], 'AI impact analysis')
        self.assertEqual(response.data['recommended_action'], 'AI recommendation')
        self.assertEqual(response.data['raw_context']['narrative_source'], 'vertex_genai')

    @override_settings(ENABLE_GRAPH_FALLBACK=True)
    @patch('aetherchain.core.tasks.fetch_supporting_evidence')
    @patch('aetherchain.core.tasks.db.cypher_query')
    def test_simulate_uses_graph_fallback_when_neo4j_unavailable(
        self,
        mock_cypher_query,
        mock_fetch_supporting_evidence,
    ):
        mock_cypher_query.side_effect = RuntimeError('neo4j unavailable')
        mock_fetch_supporting_evidence.return_value = [
            {
                'title': 'Discovery Summary',
                'uri': '',
                'snippet': 'Contingency routing likely needed.',
                'score': None,
            }
        ]

        response = self.client.post(
            reverse('simulate_impact'),
            data={'location': 'Port of Los Angeles', 'event_type': 'Port Congestion'},
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token',
        )

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data['raw_context']['impacted_assets_count'], 1)


class WorkerIngressTests(APITestCase):
    @patch('aetherchain.core.views.run_impact_analysis')
    def test_process_task_accepts_pubsub_envelope(self, mock_run_impact_analysis):
        payload = {'location': 'Port of Los Angeles', 'event_type': 'Port Congestion'}
        encoded = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')
        envelope = {'message': {'data': encoded}}

        response = self.client.post(
            reverse('process_task'),
            data=json.dumps(envelope),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 204)
        mock_run_impact_analysis.assert_called_once()


class PublicExperienceTests(APITestCase):
    def test_homepage_renders(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'NervaFlow')
        self.assertContains(response, 'Run a scenario in under one minute')

    @patch('aetherchain.core.views.run_impact_analysis')
    def test_public_simulate_endpoint_returns_packet_without_api_token(
        self,
        mock_run_impact_analysis,
    ):
        mock_run_impact_analysis.return_value = {
            'summary_description': 'Port congestion impact on Los Angeles',
            'impact_analysis': 'Route-linked assets are at risk.',
            'recommended_action': 'Rebook through alternate port capacity.',
            'risk_score': 0.62,
            'confidence_score': 0.78,
            'estimated_delay_days': 6.5,
            'estimated_cost_impact_usd': 32000.0,
            'evidence_summary': [],
            'raw_context': {},
        }

        response = self.client.post(
            reverse('public_simulate'),
            data={'location': 'Port of Los Angeles', 'event_type': 'Port Congestion'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('summary_description', response.data)
        self.assertAlmostEqual(response.data['risk_score'], 0.62)

    def test_public_simulate_validates_target(self):
        response = self.client.post(
            reverse('public_simulate'),
            data={'event_type': 'Port Congestion'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.data)

    @patch('aetherchain.core.views.run_impact_analysis')
    def test_public_simulate_accepts_sku_and_route_scope(
        self,
        mock_run_impact_analysis,
    ):
        mock_run_impact_analysis.return_value = {
            'summary_description': 'Network disruption impact',
            'impact_analysis': 'Custom scoped assets are at risk.',
            'recommended_action': 'Escalate mitigations for selected assets.',
            'risk_score': 0.57,
            'confidence_score': 0.64,
            'estimated_delay_days': 5.0,
            'estimated_cost_impact_usd': 18000.0,
            'evidence_summary': [],
            'raw_context': {'impacted_assets': []},
        }

        response = self.client.post(
            reverse('public_simulate'),
            data={
                'event_type': 'Custom Network Risk',
                'product_skus': ['SKU-1', 'SKU-2'],
                'route_ids': 'R-1,R-2',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        sent_event_payload = mock_run_impact_analysis.call_args.args[0]
        self.assertEqual(sent_event_payload['product_skus'], ['SKU-1', 'SKU-2'])
        self.assertEqual(sent_event_payload['route_ids'], ['R-1', 'R-2'])

    @patch('aetherchain.core.catalog.db.cypher_query')
    def test_catalog_endpoint_falls_back_when_graph_unavailable(self, mock_cypher_query):
        mock_cypher_query.side_effect = RuntimeError('neo4j unavailable')

        response = self.client.get(reverse('catalog_options'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['source'], 'fallback')
        self.assertIn('ports', response.data)
        self.assertGreater(len(response.data['ports']), 0)


class GraphLookupBuilderTests(SimpleTestCase):
    def test_graph_lookup_supports_sku_only_scope(self):
        lookup = _build_graph_lookup({'product_skus': ['SKU-ALPHA']})
        self.assertIn('sku_filters', lookup.params)
        self.assertEqual(lookup.params['sku_filters'], ['sku-alpha'])
        self.assertEqual(lookup.event_target, 'SKU-ALPHA')


class GcpAuthFallbackTests(SimpleTestCase):
    @patch('aetherchain.core.gcp_auth._access_token_from_gcloud', return_value='gcloud-token')
    @patch('aetherchain.core.gcp_auth._access_token_from_adc', return_value='')
    def test_access_token_falls_back_to_gcloud(self, mock_adc, mock_gcloud):
        token = access_token()
        self.assertEqual(token, 'gcloud-token')
        mock_adc.assert_called_once()
        mock_gcloud.assert_called_once()


class RetrievalTests(SimpleTestCase):
    @override_settings(
        VERTEX_SEARCH_SERVING_CONFIG='projects/1/locations/global/collections/default_collection/engines/e/servingConfigs/default_search',
        VERTEX_SEARCH_MAX_RESULTS=8,
        VERTEX_SEARCH_ENABLE_SUMMARY=True,
        VERTEX_SEARCH_SUMMARY_RESULT_COUNT=3,
    )
    @patch('aetherchain.core.retrieval.build_google_auth_headers', return_value={'Authorization': 'Bearer token'})
    @patch('aetherchain.core.retrieval.requests.post')
    def test_fetch_supporting_evidence_includes_discovery_summary(
        self,
        mock_post,
        _mock_headers,
    ):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'summary': {'summaryText': 'Port bottleneck likely for 48h.'},
                    'results': [
                        {
                            'relevanceScore': 0.91,
                            'document': {
                                'id': 'doc-1',
                                'derivedStructData': {
                                    'title': 'Port update',
                                    'link': 'https://example.com/port-update',
                                    'snippets': [{'snippet': 'Queue length is rising.'}],
                                },
                            },
                        }
                    ],
                }

        mock_post.return_value = FakeResponse()

        evidence = fetch_supporting_evidence({'location': 'Port of Los Angeles'})

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs['json']
        self.assertIn('summarySpec', payload['contentSearchSpec'])
        self.assertEqual(evidence[0]['title'], 'Discovery Summary')
        self.assertIn('Port bottleneck', evidence[0]['snippet'])
        self.assertEqual(evidence[1]['title'], 'Port update')

    @override_settings(
        VERTEX_SEARCH_SERVING_CONFIG='projects/1/locations/global/collections/default_collection/engines/e/servingConfigs/default_search',
        VERTEX_SEARCH_ENABLE_SUMMARY=True,
    )
    @patch('aetherchain.core.retrieval.build_google_auth_headers', return_value={'Authorization': 'Bearer token'})
    @patch('aetherchain.core.retrieval.requests.post')
    def test_fetch_supporting_evidence_fallbacks_without_summary_spec(
        self,
        mock_post,
        _mock_headers,
    ):
        class BadRequestResponse:
            status_code = 400

            def raise_for_status(self):
                error = requests.HTTPError('bad request')
                error.response = self
                raise error

        class OkResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {'results': []}

        mock_post.side_effect = [BadRequestResponse(), OkResponse()]

        evidence = fetch_supporting_evidence({'location': 'Port of Los Angeles'})

        self.assertEqual(evidence, [])
        self.assertEqual(mock_post.call_count, 2)
        first_payload = mock_post.call_args_list[0].kwargs['json']
        second_payload = mock_post.call_args_list[1].kwargs['json']
        self.assertIn('summarySpec', first_payload['contentSearchSpec'])
        self.assertNotIn('summarySpec', second_payload['contentSearchSpec'])


class GdeltIngestTransformTests(SimpleTestCase):
    def test_stable_document_id_is_deterministic(self):
        doc_id_1 = stable_document_id('https://example.com/a', '20260405T110000Z')
        doc_id_2 = stable_document_id('https://example.com/a', '20260405T110000Z')
        doc_id_3 = stable_document_id('https://example.com/b', '20260405T110000Z')
        self.assertEqual(doc_id_1, doc_id_2)
        self.assertNotEqual(doc_id_1, doc_id_3)
        self.assertTrue(doc_id_1.startswith('gdelt-'))

    def test_build_discovery_documents_dedupes_and_filters(self):
        articles = [
            {
                'url': 'https://news.example.com/item-1',
                'title': 'Port congestion disrupts shipping schedule',
                'seendate': '20260405T110000Z',
                'domain': 'news.example.com',
                'language': 'English',
                'sourcecountry': 'US',
            },
            {
                'url': 'https://news.example.com/item-1',
                'title': 'Port congestion disrupts shipping schedule',
                'seendate': '20260405T110000Z',
            },
            {
                'url': '',
                'title': 'Missing URL should be skipped',
                'seendate': '20260405T120000Z',
            },
        ]

        docs = build_discovery_documents(
            articles=articles,
            query_tag='supply chain disruption',
            max_documents=10,
        )
        self.assertEqual(len(docs), 1)

        document = docs[0]
        self.assertIn('id', document)
        self.assertIn('content', document)
        self.assertIn('structData', document)
        self.assertEqual(document['content']['mimeType'], 'text/plain')
        self.assertTrue(document['content']['rawBytes'])

    def test_build_discovery_documents_accepts_url_mobile_field(self):
        docs = build_discovery_documents(
            articles=[
                {
                    'url': '',
                    'url_mobile': 'https://m.example.com/item-2',
                    'title': 'Supplier strike impacts outbound shipping',
                    'seendate': '20260405T120000Z',
                }
            ],
            query_tag='supplier disruption',
            max_documents=5,
        )
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['structData']['url'], 'https://m.example.com/item-2')

    def test_normalize_gdelt_query_wraps_or_expressions(self):
        raw = '"shipping delay" OR logistics'
        normalized = normalize_gdelt_query(raw)
        self.assertEqual(normalized, '("shipping delay" OR logistics)')

    @patch('aetherchain.core.gdelt_ingest.requests.get')
    def test_fetch_gdelt_articles_handles_non_json_response(self, mock_get):
        class FakeResponse:
            status_code = 200
            text = 'No matching articles.'

            def raise_for_status(self):
                return None

            def json(self):
                raise ValueError('not json')

        mock_get.return_value = FakeResponse()

        from datetime import datetime, timezone

        articles = fetch_gdelt_articles(
            query='test',
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            max_records=5,
            timeout_seconds=1,
            max_attempts=1,
        )
        self.assertEqual(articles, [])


class IngestCapParsingTests(SimpleTestCase):
    def test_normalize_utc_day_from_iso(self):
        utc_day = _normalize_utc_day('2026-04-05T23:44:52.559550+00:00')
        self.assertEqual(utc_day, '2026-04-05')

    def test_normalize_utc_day_from_compact_timestamp(self):
        utc_day = _normalize_utc_day('20260405231500')
        self.assertEqual(utc_day, '2026-04-05')

    def test_extract_ingested_day_from_struct_data(self):
        document = {'structData': {'ingested_at': '2026-04-05T12:00:00Z'}}
        self.assertEqual(_extract_ingested_day(document), '2026-04-05')

    def test_extract_ingested_day_from_json_data_camel_case(self):
        document = {'jsonData': {'ingestedAt': '20260405120000'}}
        self.assertEqual(_extract_ingested_day(document), '2026-04-05')

    def test_extract_ingested_day_returns_empty_when_missing(self):
        self.assertEqual(_extract_ingested_day({'structData': {'title': 'x'}}), '')

    def test_sanitize_bq_table_ref_accepts_wildcard(self):
        table_ref = _sanitize_bq_table_ref('my-proj.billing_export.gcp_billing_export_resource_v1_ABC_*')
        self.assertEqual(table_ref, 'my-proj.billing_export.gcp_billing_export_resource_v1_ABC_*')

    def test_sanitize_bq_table_ref_rejects_invalid(self):
        with self.assertRaisesMessage(CommandError, '--billing-export-table must look like'):
            _sanitize_bq_table_ref('bad table ref')

    def test_billing_export_table_id_matcher(self):
        self.assertTrue(_is_billing_export_table_id('gcp_billing_export_resource_v1_014E29_702A53_1A963B'))
        self.assertTrue(_is_billing_export_table_id('gcp_billing_export_v1_014E29_702A53_1A963B'))
        self.assertFalse(_is_billing_export_table_id('random_table'))

    def test_billing_export_table_preference(self):
        self.assertLess(
            _table_preference_score('gcp_billing_export_resource_v1_abc'),
            _table_preference_score('gcp_billing_export_v1_abc'),
        )
