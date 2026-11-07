import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from tests.support import FakeFetcher, INTAKE, StoreTestMixin
from tool_offer_agent.chat import create_text_chat, respond
from tool_offer_agent.drafting import CATEGORIES, OpenAIQuoteExtractor, build_draft, pointer_value, select_excerpts, verified_derivation
from tool_offer_agent.export_delivery import reassemble
from tool_offer_agent.guided_cards import valid_metadata
from tool_offer_agent.offer_representation import buyer_offer
from tool_offer_agent.readiness import assess, machine_result
from tool_offer_agent.workflow import Workflow


class IntakeTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        self.fields = dict(line.split(': ', 1) for line in INTAKE.splitlines())

    def test_plain_and_json_equivalent(self):
        self.workflow.handle('plain', 'one', INTAKE)
        for docs in (self.fields['docs'], [self.fields['docs']]):
            fields = {**self.fields, 'docs': docs}
            self.workflow.handle('structured', str(type(docs)), json.dumps(fields))
            state = self.store.load(self.store.key('structured', str(type(docs))))
            self.assertEqual(state['fields'], self.store.load(self.store.key('plain', 'one'))['fields'])
            self.assertIsNotNone(state['draft'])

    def test_atomic_invalid_values_and_arbitrary_json(self):
        self.workflow.handle('seller', 'one', INTAKE)
        key = self.store.key('seller', 'one')
        before = self.store.load(key)
        for value in ({'customer': 'changed', 'docs': ['https://example.com', 'http://127.0.0.1']},
                      {'pricing': 0}, {'docs': []}, {'pricing': 'changed', 'unexpected': True},
                      {'openapi': '3.1.0', 'paths': {}}, {'schema': 'TOOL_OFFER_INTAKE_V1'},
                      {'schema': 'another', 'payment': 'changed'}):
            reply = self.workflow.handle('seller', 'one', json.dumps(value))
            self.assertIn('preserved', reply)
            self.assertEqual(self.store.load(key), before)
        self.workflow.handle('seller', 'one', '{"pricing":"first","pricing":"last"}')
        self.assertEqual(self.store.load(key), before)
        for quoted in ('```json\n{"customer":"example only"}\n```', '> {"customer":"example only"}'):
            self.workflow.handle('seller', 'one', quoted)
            self.assertEqual(self.store.load(key), before)

    def test_multiline_value_cannot_inject_field(self):
        self.workflow.handle('seller', 'one', json.dumps({'customer': 'Line one\npricing: invented'}))
        fields = self.store.load(self.store.key('seller', 'one'))['fields']
        self.assertEqual(fields['customer'], 'Line one\npricing: invented')
        self.assertNotIn('pricing', fields)

    def test_card_selection_and_cancellation(self):
        self.workflow.handle('seller', 'one', INTAKE)
        card = self.workflow.handle('seller', 'one', 'review intake')
        self.assertTrue(valid_metadata(card.metadata))
        card = self.workflow.handle('seller', 'one', json.dumps(json.loads(card.metadata['card_payload'])['approve_cta']['selection']))
        selection = json.loads(card.metadata['card_payload'])['submit_cta']['selection']
        selection.update(field='payment', value='Probably Stripe')
        self.workflow.handle('seller', 'one', json.dumps(selection))
        self.assertIn('already handled', self.workflow.handle('seller', 'one', json.dumps(selection)))
        self.workflow.handle('seller', 'one', 'review offer')
        self.workflow.handle('seller', 'one', 'cancel review')
        self.assertNotIn('guided_card', self.store.load(self.store.key('seller', 'one')))
        self.assertIn('stale', self.workflow.handle('different', 'one', json.dumps(selection)))


class LargeReviewTests(StoreTestMixin, IsolatedAsyncioTestCase):
    async def test_large_unicode_review_keeps_card_and_full_export(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        session = str(uuid4())
        workflow.handle('seller', session, INTAKE)
        key = self.store.key('seller', session)
        state = self.store.load(key)
        for category in ('capabilities', 'inputs', 'outputs'):
            state['draft']['offer'][category] = [{'text': '測定 📦 meaningful complete claim. ' * 160, 'source_url': 'https://example.com'} for _ in range(15)]
        self.store.save(key, state)
        context = SimpleNamespace(session=session, send=AsyncMock())
        await respond(context, 'seller', create_text_chat('@tool-offer-builder review offer'), workflow)
        message = context.send.call_args_list[-1].args[1]
        self.assertNotIn('bounded delivery budget', message.text())
        self.assertLessEqual(len(message.text().encode()), 6000)
        metadata = [part.metadata for part in message.content if part.type == 'metadata']
        self.assertEqual(len(metadata), 1)
        self.assertTrue(valid_metadata(metadata[0]))
        self.assertLess(len(message.model_dump_json().encode()), 16000)
        payload = workflow.handle('seller', session, 'export json')
        manifest = json.loads(workflow.render_response('seller', session, payload, 'export json'))
        parts = [json.loads(workflow.handle('seller', session, f"export part {manifest['export_id']} {index}")) for index in range(1, manifest['total_parts'] + 1)]
        self.assertEqual(reassemble(manifest, parts), payload)
        self.assertEqual(self.store.load(key)['draft'], state['draft'])


class ExtractionTests(TestCase):
    def test_interface_values_and_terms_precede_repeated_prose(self):
        spec = json.loads(Path('site/public/examples/parcel-openapi.json').read_text())
        spec['components'] = {'schemas': {'Unit': {'type': 'string', 'enum': ['cm', 'in']}}}
        spec['paths']['/normalize']['post']['requestBody']['content']['application/json']['schema']['properties']['unit'] = {'$ref': '#/components/schemas/Unit'}
        spec['security'] = [{'ApiKey': []}]
        spec['components']['securitySchemes'] = {'ApiKey': {'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key'}}
        documents = [{'source_url': 'https://example.com/spec.json', 'text': json.dumps(spec, indent=2)}]
        excerpts, coverage = select_excerpts(documents)
        pointers = {item.get('source_pointer') for item in excerpts}
        self.assertIn('/components/schemas/Unit/type', pointers)
        self.assertIn('/components/securitySchemes/ApiKey/name', pointers)
        self.assertIn('/paths/~1normalize/post/requestBody/content/application~1json/schema/properties/unit/$ref', pointers)
        self.assertIn('/paths/~1normalize/post/responses/200/content/application~1json/schema/properties/width_cm/type', pointers)
        self.assertIn('/x-limitations', pointers)
        self.assertIn('/x-commercial-terms', pointers)
        self.assertTrue(coverage['partial'])

    def test_pretty_compact_complete_values_and_source_mapping(self):
        spec = json.loads(Path('site/public/examples/parcel-openapi.json').read_text())
        spec['paths']['/normalize']['post']['description'] = 'Send width: 10, length: 20; preserve “units”, commas, and punctuation!'
        spec['paths']['/normalize']['post']['x-commercial-terms'] = 'A separate agreement is required; no settlement is implemented.'
        exports = []
        for text in (json.dumps(spec, indent=2, ensure_ascii=False), json.dumps(spec, separators=(',', ':'), ensure_ascii=False)):
            documents = [{'source_url': 'https://example.com/spec', 'text': text}]
            original = copy.deepcopy(documents)
            excerpts, coverage = select_excerpts(documents)
            self.assertTrue(coverage['partial'])
            for excerpt in excerpts:
                self.assertEqual(excerpt['text'], text[excerpt['start']:excerpt['end']])
                if 'source_pointer' in excerpt:
                    self.assertEqual(json.loads(excerpt['text']), pointer_value(spec, excerpt['source_pointer']))
            client = Mock()
            def complete(**kwargs):
                sent = json.loads(kwargs['messages'][1]['content'])
                selected = {category: [] for category in CATEGORIES}
                for item in sent['quote_catalogue']:
                    pointer = sent['untrusted_documents'][item['excerpt']].get('source_pointer', '')
                    category = 'commercial_terms' if 'commercial' in pointer else 'limitations' if 'limitations' in pointer else 'capabilities'
                    if len(selected[category]) < 4:
                        selected[category].append({'quote_id': item['id']})
                return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps(selected)))])
            client.chat.completions.create.side_effect = complete
            extractor = OpenAIQuoteExtractor(client)
            fields = dict(line.split(': ', 1) for line in INTAKE.splitlines())
            draft = build_draft(fields, documents, 1, extractor=extractor)
            self.assertEqual(client.chat.completions.create.call_count, 1)
            buyer = buyer_offer(draft)
            for category, entries in buyer['interface'].items():
                self.assertEqual(len(entries), len({(entry['text'], entry['source_url']) for entry in entries}))
                for entry in entries:
                    self.assertFalse(entry['text'].endswith(': {'))
                    if entry.get('derivation'):
                        self.assertTrue(verified_derivation(entry, text), entry)
            self.assertEqual(documents, original)
            self.assertIn('width: 10, length: 20;', json.dumps(buyer, ensure_ascii=False))
            exports.append(buyer['interface'])
        self.assertEqual(exports[0], exports[1])


class ReadinessSummaryTests(StoreTestMixin, TestCase):
    def test_inline_and_multipart_summary_match_report(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        workflow.handle('seller', 'one', INTAKE)
        key = self.store.key('seller', 'one')
        for large in (False, True):
            state = self.store.load(key)
            if large:
                state['fields']['customer'] = '📦 customer with constraints. ' * 180
                self.store.save(key, state)
            report = assess(state, 'seller', 'a' * 64)
            result = machine_result(self.store, 'seller', 'one', 'a' * 64)
            self.assertEqual(result['readiness']['summary'], {**{name: report[name] for name in ('status', 'scope', 'basis', 'authorization', 'next_step')}, 'finding_count': len(report['findings'])})
            self.assertNotIn('buyer_ready', result['readiness']['summary'])

    def test_same_snapshot_inline_and_multipart_have_identical_summary(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        workflow.handle('seller', 'one', INTAKE)
        with patch('tool_offer_agent.readiness.REPLY_BYTES', 1000000):
            inline = machine_result(self.store, 'seller', 'one', 'a' * 64)['readiness']
        with patch('tool_offer_agent.readiness.REPLY_BYTES', 1):
            multipart = machine_result(self.store, 'seller', 'one', 'a' * 64)['readiness']
        self.assertEqual(inline['delivery'], 'inline')
        self.assertEqual(multipart['delivery'], 'multipart')
        self.assertEqual(inline['summary'], multipart['summary'])
        self.assertEqual(inline['report_sha256'], multipart['report_sha256'])


class ContaminationTests(TestCase):
    def test_model_catalogue_cannot_select_json_syntax_as_input_facts(self):
        text = Path('site/public/examples/parcel-openapi.json').read_text()
        client = Mock()
        def complete(**kwargs):
            sent = json.loads(kwargs['messages'][1]['content'])
            selected = {category: [] for category in CATEGORIES}
            for item in sent['quote_catalogue']:
                if item['text'] in {'"length_cm": {', '"width_cm": {', '"length": 10,'}:
                    selected['inputs'].append({'quote_id': item['id']})
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps(selected)))])
        client.chat.completions.create.side_effect = complete
        fields = dict(line.split(': ', 1) for line in INTAKE.splitlines())
        draft = build_draft(fields, [{'source_url': 'https://example.com/spec.json', 'text': text}], 1, extractor=OpenAIQuoteExtractor(client))
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertFalse(any(item['text'] in {'"length_cm": {', '"width_cm": {', '"length": 10,'} for item in draft['offer']['inputs']))

    def test_legacy_model_fragments_are_not_buyer_facts(self):
        spec = {'openapi': '3.1.0', 'paths': {'/parcel': {'post': {'summary': 'Quote: width 10, length 20; supported.'}}},
                'x-commercial-terms': 'Seller agreement required: review first; do not transact.',
                'notes': {'unsupported_section': 'Returns evidence: a, b; context remains relevant.'}}
        text = json.dumps(spec, indent=2)
        source = 'https://example.com/spec.json'
        model_facts = {category: [] for category in CATEGORIES}
        model_facts['inputs'] = [{'text': '"width_cm": {', 'source_url': source}, {'text': '"length": 10,', 'source_url': source}]
        model_facts['commercial_terms'] = [{'text': spec['x-commercial-terms'], 'source_url': source}] * 2
        model_facts['capabilities'] = [{'text': spec['notes']['unsupported_section'], 'source_url': source}]
        fields = dict(line.split(': ', 1) for line in INTAKE.splitlines())
        draft = build_draft(fields, [{'source_url': source, 'text': text}], 1, model_facts=model_facts)
        self.assertEqual(draft['offer']['inputs'], [])
        self.assertEqual(len(draft['offer']['documented_commercial_terms']), 1)
        self.assertTrue(any(item['text'] == spec['notes']['unsupported_section'] for item in draft['offer']['capabilities']))
        excerpts, _ = select_excerpts([{'source_url': source, 'text': text}])
        self.assertTrue(any(item.get('source_pointer') == '/notes/unsupported_section' and item['narrative'] for item in excerpts))
