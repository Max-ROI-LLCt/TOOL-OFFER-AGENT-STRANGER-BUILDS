from tests.support import card_selection
import copy
import json
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
from uuid import uuid4

from tests.support import FakeFetcher, INTAKE, StoreTestMixin
from tool_offer_agent.chat import create_text_chat, respond
from tool_offer_agent.guided_cards import valid_metadata
from tool_offer_agent.workflow import Workflow
from tool_offer_agent.drafting import human_fact, presentation_fact, verified_derivation


def business_state(state):
    return {key: value for key, value in state.items() if key not in {
        'guided_card', 'guided_actions', 'deliveries', 'conversation', 'last_message_timestamp'}}


class CardClientTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        self.workflow.handle('seller', 'session', INTAKE)
        self.key = self.store.key('seller', 'session')
        state = self.store.load(self.key)
        state.pop('onboarding_shown', None)
        state['draft'].pop('draft_version', None)
        self.store.save(self.key, state)
        self.workflow.conversation = Mock()

    def card(self, command='review offer', cta='approve_cta'):
        reply = self.workflow.handle('seller', 'session', command)
        self.assertTrue(valid_metadata(reply.metadata))
        if command == 'review intake' and cta == 'submit_cta':
            reply = self.workflow.handle('seller', 'session', json.dumps(json.loads(reply.metadata['card_payload'])['approve_cta']['selection']))
            self.assertTrue(valid_metadata(reply.metadata))
        return card_selection(json.loads(reply.metadata['card_payload']), cta)

    def test_observed_client_approved_flag_finishes_without_onboarding_or_authorization(self):
        selection = {**self.card(), 'approved': True}
        before = business_state(self.store.load(self.key))
        reply = self.workflow.handle('seller', 'session', json.dumps(selection), message_id='actual-shape')
        self.assertIn('Review finished', reply)
        self.assertNotIn('travel planners', reply)
        self.assertEqual(business_state(self.store.load(self.key)), before)
        self.assertNotIn('guided_card', self.store.load(self.key))
        self.assertEqual(self.workflow.handle('seller', 'session', json.dumps(selection), message_id='actual-shape'), reply)
        repeated = self.workflow.handle('seller', 'session', json.dumps(selection), message_id='new-delivery')
        self.assertIn('already finished', repeated)
        self.assertEqual(business_state(self.store.load(self.key)), before)
        self.workflow.conversation.interpret.assert_not_called()

    def test_strict_flag_shape_duplicates_and_intake_separation(self):
        selection = self.card()
        before = self.store.load(self.key)
        for extra in ({'approved': False}, {'approved': 'true'}, {'approved': 1},
                      {'approved': True, 'pricing': 'invented'}, {'approved': True, 'purchase': True}):
            reply = self.workflow.handle('seller', 'session', json.dumps({**selection, **extra}))
            self.assertIn('Invalid card selection', reply)
            self.assertEqual(self.store.load(self.key), before)
        repeated_key = json.dumps({**selection, 'approved': True})[:-1] + ',"approved":true}'
        self.assertIn('Invalid card selection', self.workflow.handle('seller', 'session', repeated_key))
        self.assertEqual(self.store.load(self.key), before)

    def test_edit_flag_correction_cancel_and_stale(self):
        selection = {**self.card(cta='reject_cta'), 'approved': False}
        reply = self.workflow.handle('seller', 'session', json.dumps(selection))
        correction = json.loads(reply.metadata['card_payload'])['submit_cta']['selection']
        corrected = self.workflow.handle('seller', 'session', json.dumps({**correction, 'field': 'pricing', 'value': 'Undecided'}))
        self.assertIn('Saved your pricing', corrected)
        self.assertEqual(self.store.load(self.key)['fields']['pricing'], 'Undecided')
        self.assertIn('stale', self.workflow.handle('seller', 'session', json.dumps(selection)))
        self.card('review intake', 'submit_cta')
        self.assertIn('cancelled', self.workflow.handle('seller', 'session', 'cancel form'))
        self.assertNotIn('guided_card', self.store.load(self.key))

    def test_text_finish_and_cross_session_revision_binding(self):
        selection = self.card()
        self.assertIn('stale', self.workflow.handle('other', 'session', json.dumps({**selection, 'approved': True})))
        reply = self.workflow.handle('seller', 'session', 'Finish review (no approval or purchase)')
        self.assertIn('Review finished', reply)
        self.assertIn('already finished', self.workflow.handle('seller', 'session', 'finish review'))
        state = self.store.load(self.key)
        state['revision'] += 1
        self.store.save(self.key, state)
        self.assertIn('stale', self.workflow.handle('seller', 'session', json.dumps({**selection, 'approved': True})))


class CardTransportTests(StoreTestMixin, IsolatedAsyncioTestCase):
    async def test_actual_direct_mention_shape(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        session = str(uuid4())
        workflow.handle('seller', session, INTAKE)
        card = workflow.handle('seller', session, 'review offer')
        selection = card_selection(json.loads(card.metadata['card_payload']), 'approve_cta')
        context = SimpleNamespace(session=session, send=AsyncMock())
        await respond(context, 'seller', create_text_chat('@tool-offer-builder ' + json.dumps({**selection, 'approved': True})), workflow)
        reply = context.send.call_args_list[-1].args[1].text()
        self.assertIn('Review finished', reply)
        self.assertNotIn('Invalid card selection', reply)


class LegacyPresentationTests(TestCase):
    def test_complete_schema_recovered_without_modifying_clipped_legacy_evidence(self):
        responses = {'200': {'description': 'Complete result', 'content': {'application/json': {'schema': {
            'type': 'object', 'properties': {f'field_{index}': {'type': 'string', 'description': 'Meaningful value.'} for index in range(55)}}}}}}
        source = {'openapi': '3.1.0', 'paths': {'/convert': {'post': {'responses': responses}}}}
        document = {'source_url': 'https://example.com/spec.json', 'text': json.dumps(source)}
        entry = {'text': json.dumps(responses)[:2000], 'source_url': document['source_url'], 'location': 'paths[/convert].post.responses'}
        before = copy.deepcopy(entry)
        projected = presentation_fact(entry, [document])
        self.assertEqual(projected['schema_value'], responses)
        self.assertTrue(verified_derivation(projected, document['text']))
        self.assertNotIn('{"200"', human_fact(projected))
        self.assertIn('field_23', human_fact(projected))
        self.assertIn('additional fields retained in machine JSON', human_fact(projected))
        self.assertIn('field_54', projected['schema_value']['200']['content']['application/json']['schema']['properties'])
        self.assertEqual(entry, before)
        self.assertNotIn('schema_value', presentation_fact({**entry, 'text': entry['text'] + 'invented'}, [document]))

    def test_legacy_structural_fragment_is_not_a_fact_but_narrative_punctuation_survives(self):
        source = json.dumps({'first': 'Descriptive text: braces {work}; punctuation is meaningful.', 'second': {'length_cm': 10}})
        document = {'source_url': 'https://example.com/spec.json', 'text': source}
        start = source.index('punctuation')
        end = source.index('length_cm') + 7
        entry = {'source_url': document['source_url'], 'location': f'text[{start}:{end}]', 'text': source[start:end]}
        projected = presentation_fact(entry, [document])
        self.assertEqual(projected['evidence_status'], 'legacy_fragment_requires_review')
        self.assertNotIn('"second"', projected['text'])
        end = start + len('punctuation')
        narrative = presentation_fact({**entry, 'location': f'text[{start}:{end}]', 'text': source[start:end]}, [document])
        self.assertEqual(narrative['text'], json.loads(source)['first'])
        self.assertTrue(verified_derivation(narrative, source))
