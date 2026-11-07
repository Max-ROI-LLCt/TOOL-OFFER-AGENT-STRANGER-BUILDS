"""Synthetic presentation regressions; no browser or paid-service observation."""

import copy
import json
from unittest import TestCase

from uagents_core.contrib.protocols.chat.cards import CustomCardPayload

from tests.support import FakeFetcher, INTAKE, StoreTestMixin, card_selection
from tests.test_readiness import fixture
from tool_offer_agent.guided_cards import fact_preview, valid_metadata
from tool_offer_agent.offer_representation import human_highlight
from tool_offer_agent.drafting import human_fact
from tool_offer_agent.readiness import assess
from tool_offer_agent.readiness_cards import card_metadata, evidence_summary
from tool_offer_agent.workflow import Workflow


class JudgingPolishTests(StoreTestMixin, TestCase):
    def test_review_full_width_actions_and_strict_schema(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        workflow.handle('synthetic', 'review', INTAKE)
        reply = workflow.handle('synthetic', 'review', 'review offer')
        payload = json.loads(reply.metadata['card_payload'])
        CustomCardPayload.model_validate(payload)
        self.assertTrue(valid_metadata(reply.metadata))
        self.assertNotIn('summary_rows', payload)
        sections = payload['root']['children'][:-2]
        self.assertTrue(all(section['children'][0]['type'] == 'text' for section in sections))
        self.assertIn('export json', sections[-1]['children'][0]['value'])
        self.assertLessEqual(len(reply.metadata['card_payload'].encode()), 8000)
        finish = card_selection(payload, 'approve_cta')
        self.assertIn('Review finished', workflow.handle('synthetic', 'review', json.dumps(finish)))
        self.assertIn('already finished', workflow.handle('synthetic', 'review', json.dumps(finish)))
        for mutation in ('redirect', 'selection', 'input'):
            broken = copy.deepcopy(payload)
            broken['root']['children'][-1][mutation] = 'unexpected'
            metadata = {**reply.metadata, 'card_payload': json.dumps(broken)}
            self.assertFalse(valid_metadata(metadata))

    def test_unicode_excerpt_navigation_is_separate_and_intact(self):
        state = fixture()
        quote = '測定結果 ' * 400
        state['documents'][0]['text'] = quote
        state['draft']['offer']['capabilities'] = [{'text': quote, 'source_url': state['documents'][0]['source_url']} for unused in range(22)]
        before = copy.deepcopy(state)
        report = assess(state, 'synthetic', 'local-only')
        metadata = card_metadata(report)
        payload = json.loads(metadata['card_payload'])
        CustomCardPayload.model_validate(payload)
        self.assertLessEqual(len(metadata['card_payload'].encode()), 8000)
        navigation = payload['root']['children'][-1]['children'][0]['value']
        self.assertIn('Showing 2 of 22 exact quotations.', navigation)
        self.assertIn('readiness text', navigation)
        self.assertIn('readiness json', navigation)
        self.assertNotIn('…', navigation)
        self.assertEqual(state, before)

    def test_singular_detail_and_derived_punctuation_only(self):
        entries = [{'text': 'Synthetic constraint ' + str(index), 'source_url': 'https://example.invalid/spec'} for index in range(4)]
        self.assertIn('1 more detail in', fact_preview(entries, [], projected=True))
        self.assertNotIn('1 more details', fact_preview(entries, [], projected=True))
        schema = {'text': 'retained', 'schema_value': {'200': {'description': 'After settlement.', 'content': {}}}}
        before = copy.deepcopy(schema)
        self.assertIn('settlement..', human_fact(schema))
        self.assertNotIn('settlement..', human_highlight(schema))
        self.assertEqual(schema, before)

    def test_saved_claim_counts_do_not_promote_display_projection(self):
        report = assess(fixture(), 'synthetic', 'local-only')
        before = copy.deepcopy(report)
        self.assertIn('saved claims', evidence_summary(report))
        self.assertIn('recovered schema summaries', evidence_summary(report))
        self.assertEqual(report, before)
