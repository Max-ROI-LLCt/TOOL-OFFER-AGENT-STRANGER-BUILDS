from tests.support import card_selection
import copy
import json
from unittest import TestCase
from unittest.mock import Mock

from tests.support import DOC_URL, INTAKE, FakeFetcher, StoreTestMixin
from tool_offer_agent.export_delivery import REPLY_BYTES, part, reassemble, snapshot
from tool_offer_agent.offer_representation import buyer_explanation, buyer_readable, display_facts
from tool_offer_agent.workflow import Workflow


class BuyerViewTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        self.workflow.handle('seller', 'session', INTAKE)
        self.key = self.store.key('seller', 'session')
        self.state = self.store.load(self.key)
        self.workflow.conversation = Mock()

    def render(self, draft=None, documents=None):
        return buyer_explanation(draft or self.state['draft'], documents=documents or self.state['draft_documents'])

    def test_routes_are_distinct_without_state_mutation_or_model_calls(self):
        concise = self.workflow.handle('seller', 'session', 'buyer explanation')
        detailed = self.workflow.handle('seller', 'session', 'export buyer readable')
        self.assertNotEqual(concise, detailed)
        self.assertIn('Concise derived overview', concise)
        self.assertEqual(detailed, buyer_readable(self.state['draft'], self.state.get('restrictions'), documents=self.state['draft_documents']))
        self.assertEqual(self.workflow.render_response('seller', 'session', concise, 'buyer explanation'), concise)
        self.assertEqual(self.store.load(self.key), self.state)
        self.workflow.conversation.interpret.assert_not_called()

    def test_material_seller_terms_and_evidence_distinctions_are_preserved(self):
        draft = copy.deepcopy(self.state['draft'])
        draft['offer']['payment_status'] = 'tentative_seller_statement'
        draft['offer']['payment_instructions'] = 'Probably Stripe; not set up. No automatic charges.'
        text = self.render(draft)
        for field in ('pricing', 'payment_instructions', 'access_instructions', 'invocation_instructions'):
            self.assertIn(draft['offer'][field], text)
        self.assertIn(draft['seller']['intended_customer'], text)
        self.assertIn('Payment is tentative', text)
        self.assertIn('UTF-8 CSV only; maximum 1000 rows.', text)
        self.assertIn('not seller authority', text)
        self.assertIn('not a quotation', text)
        self.assertIn('Sources (documentation claims, not verified behavior)', text)
        draft['offer']['job'] = 'Convert only approved accounting rows; never publish the result.'
        self.assertIn('Seller-scoped proposed job: ' + draft['offer']['job'], self.render(draft))

    def test_duplicate_facts_merge_but_keep_both_sources(self):
        draft = copy.deepcopy(self.state['draft'])
        fact = {'text': 'Returns dimensions; never books delivery.', 'source_url': DOC_URL, 'location': None}
        draft['offer']['capabilities'].append(fact)
        draft['offer']['limitations'].extend([fact, {**fact, 'source_url': 'https://docs.example.com/terms'}])
        text = self.render(draft)
        self.assertEqual(text.count(fact['text']), 1)
        self.assertIn('https://docs.example.com/terms', text)
        self.assertIn('[1] [2]', text)

    def test_other_operation_schemas_are_not_presented_as_selected_invocation(self):
        draft = copy.deepcopy(self.state['draft'])
        draft['offer']['capabilities'].append({'text': 'POST /archive: Archive old records', 'source_url': DOC_URL, 'source_pointer': '/paths/~1archive/post'})
        draft['offer']['inputs'].append({'text': 'Archive storage credentials', 'source_url': DOC_URL, 'source_pointer': '/paths/~1archive/post/requestBody'})
        draft['offer']['limitations'].append({'text': 'Archive retention is 7 days.', 'source_url': DOC_URL, 'source_pointer': '/paths/~1archive/post/x-limitations'})
        text = self.render(draft)
        self.assertIn('1 other documented operations', text)
        self.assertNotIn('Archive storage credentials', text)
        self.assertIn('Archive retention is 7 days.', text)
        self.assertIn('Archive storage credentials', buyer_readable(draft))
        draft['offer']['invocation_instructions'] = 'POST /not-documented'
        text = self.render(draft)
        self.assertIn('Archive storage credentials', text)
        self.assertNotIn('Interface highlights follow', text)

    def test_no_explicit_operation_keeps_all_documented_operations(self):
        draft = copy.deepcopy(self.state['draft'])
        draft['offer']['invocation_instructions'] = 'Use the documented interface.'
        text = self.render(draft)
        self.assertIn('POST /convert', text)
        self.assertNotIn('other documented operations', text)

    def test_small_schema_keeps_required_types_and_large_schema_has_explicit_detail_link(self):
        draft = copy.deepcopy(self.state['draft'])
        schema = {'type': 'object', 'required': ['length'], 'properties': {'length': {'type': 'number', 'exclusiveMinimum': 0}}}
        draft['offer']['inputs'] = [{'text': 'Exact input schema', 'schema_value': schema, 'source_url': DOC_URL}]
        self.assertIn('length (required): number', self.render(draft))
        schema['properties'].update({f'field_{index}': {'type': 'string', 'description': 'Exact descriptive constraint ' * 10} for index in range(20)})
        text = self.render(draft)
        self.assertIn('more fields', text)
        self.assertIn('full constraints in complete offer', text)
        self.assertIn('field_19', buyer_readable(draft))

    def test_legacy_clipped_plain_text_is_completed_from_exact_retained_line(self):
        draft = copy.deepcopy(self.state['draft'])
        draft.pop('draft_version', None)
        source = 'Introduction\nReturns text; no delivery, approval or payment is executed.\nNext topic\n'
        excerpt = 'Returns text; no deli'
        start = source.index(excerpt)
        fact = {'text': excerpt, 'source_url': DOC_URL, 'location': f'text[{start}:{start + len(excerpt)}]'}
        draft['offer']['limitations'] = [fact]
        original = copy.deepcopy(draft)
        text = self.render(draft, [{'source_url': DOC_URL, 'text': source}])
        self.assertIn('Returns text; no delivery, approval or payment is executed.', text)
        self.assertNotIn('Next topic', text)
        self.assertIn('legacy numbering', text)
        self.assertEqual(draft, original)
        self.assertIn(excerpt, buyer_readable(draft))

    def test_unaligned_excerpt_is_not_extended_from_a_different_source(self):
        draft = copy.deepcopy(self.state['draft'])
        fact = {'text': 'No sales.', 'source_url': DOC_URL, 'location': 'text[0:9]'}
        draft['offer']['limitations'] = [fact]
        text = self.render(draft, [{'source_url': DOC_URL, 'text': 'Purchases permitted.'}])
        self.assertIn('No sales.', text)
        self.assertNotIn('Purchases permitted.', text)

    def test_legacy_json_fragment_is_not_asserted_as_complete_evidence(self):
        draft = copy.deepcopy(self.state['draft'])
        source = '{\n"length_cm": {\n"type": "number"\n}\n}'
        excerpt = '"length_cm": {'
        start = source.index(excerpt)
        draft['offer']['inputs'] = [{'text': excerpt, 'source_url': DOC_URL, 'location': f'text[{start}:{start + len(excerpt)}]'}]
        text = self.render(draft, [{'source_url': DOC_URL, 'text': source}])
        self.assertNotIn(excerpt, text)
        self.assertIn('1 incomplete legacy JSON excerpt appearances represent 1 unique source fragments', text)

    def test_retained_structured_recovery_preserves_pointers_and_selected_operation(self):
        description = 'Check supplied claims: report gaps, contradictions; do not execute repairs.'
        spec = {'openapi': '3.1.0', 'paths': {'/check': {'post': {'description': description}},
                '/repair': {'post': {'description': 'Propose a separate repair.'}}},
                'components': {'schemas': {'Input': {'type': 'object', 'required': ['schema', 'candidate'],
                    'properties': {'schema': {'const': 'CHECK_V1'}, 'candidate': {'type': 'string'}, 'notes': {'type': 'string'}}}}}}
        for indent in (None, 2):
            with self.subTest(indent=indent):
                source = json.dumps(spec, indent=indent)
                documents = [{'source_url': DOC_URL, 'text': source}]
                start = source.index('"description"')
                end = source.index('contradictions') + 5
                excerpt = {'text': source[start:end], 'source_url': DOC_URL, 'location': f'text[{start}:{end}]'}
                draft = copy.deepcopy(self.state['draft'])
                draft['offer'].update(job='Prepare a source-attributed offer; do not claim execution.', invocation_instructions='POST /check')
                draft['offer']['capabilities'] = [{'text': 'POST /check: Check supplied claims', 'source_url': DOC_URL,
                    'source_pointer': '/paths/~1check/post'}, excerpt, {'text': DOC_URL, 'source_url': DOC_URL},
                    {'text': 'The example deliberately contains a contradiction.', 'source_url': DOC_URL}]
                draft['offer']['inputs'] = [excerpt, {'text': 'Request body', 'source_url': DOC_URL,
                    'source_pointer': '/paths/~1check/post/requestBody',
                    'schema_value': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Input'}}}}}]
                draft['offer']['documented_commercial_terms'] = [excerpt, {'text': DOC_URL, 'source_url': DOC_URL}]
                before = copy.deepcopy(draft)
                projected, recovery = display_facts(draft['offer'], documents)
                self.assertEqual((recovery['appearances'], recovery['unique_fragments']), (3, 1))
                self.assertEqual(recovery['recovered_values'][0]['source_pointer'], '/paths/~1check/post/description')
                self.assertEqual(recovery['recovered_values'][0]['text'], description)
                self.assertEqual(recovery['recovered_values'][0]['original_excerpt_location'], excerpt['location'])
                self.assertFalse(any(item['text'] == DOC_URL for entries in projected.values() for item in entries))
                text = self.render(draft, documents)
                self.assertIn('Offered operation (documented, not independently verified): ' + description, text)
                self.assertIn('required schema (exactly "CHECK_V1"); candidate (string). Optional: notes.', text)
                self.assertNotIn('The example deliberately contains a contradiction.', text)
                self.assertIn('illustrative examples, not general operation guarantees', text)
                self.assertNotIn('Prepare a source-attributed offer', text)
                self.assertNotIn('Propose a separate repair.', text)
                self.assertEqual(draft, before)
                self.assertEqual(documents[0]['text'], source)

    def test_oversized_concise_view_remains_complete_multipart_unicode_and_resumable(self):
        state = copy.deepcopy(self.state)
        state['draft']['offer']['limitations'] = [{'text': 'Material condition: ' + 'é漢字😀' * 2000, 'source_url': DOC_URL}]
        self.store.save(self.key, state)
        payload = self.workflow.handle('seller', 'session', 'buyer explanation')
        self.assertGreater(len(payload.encode()), REPLY_BYTES)
        manifest = json.loads(self.workflow.render_response('seller', 'session', payload, 'buyer explanation'))
        self.assertFalse(manifest['complete_payload'])
        parts = [json.loads(self.workflow.handle('seller', 'session', f"export part {manifest['export_id']} {index}")) for index in range(1, manifest['total_parts'] + 1)]
        self.assertEqual(reassemble(manifest, parts), payload)
        self.assertEqual(self.store.load(self.key), state)
        self.assertIn('unavailable', self.workflow.handle('other', 'session', f"export part {manifest['export_id']} 1"))

    def test_previous_alias_snapshots_keep_identity_boundaries_and_hashes(self):
        detailed = buyer_readable(self.state['draft']) + '\né漢字😀' * 1600
        previous = snapshot(detailed, self.state['draft']['revision'], 'buyer explanation')
        before = copy.deepcopy(previous)
        self.render()
        parts = [part(previous, index) for index in range(1, previous['manifest']['total_parts'] + 1)]
        self.assertEqual(reassemble(previous['manifest'], parts), detailed)
        self.assertEqual(previous, before)

    def test_finish_review_points_to_concise_command_and_stays_idempotent(self):
        card = self.workflow.handle('seller', 'session', 'review offer')
        selection = card_selection(json.loads(card.metadata['card_payload']), 'approve_cta')
        request = json.dumps({**selection, 'approved': True})
        reply = self.workflow.handle('seller', 'session', request)
        self.assertIn('Use buyer explanation for the concise human view', reply)
        self.assertIn('already finished', self.workflow.handle('seller', 'session', request))
        after = self.store.load(self.key)
        for field in ('draft', 'fields', 'documents', 'draft_documents', 'revision', 'restrictions'):
            self.assertEqual(after.get(field), self.state.get(field))
        self.workflow.conversation.interpret.assert_not_called()
