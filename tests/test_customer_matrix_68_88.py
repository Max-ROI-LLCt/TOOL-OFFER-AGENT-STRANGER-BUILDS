"""Failure-shape fixtures from founder summaries, not verbatim customer transcripts."""
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from tool_offer_agent.product_policy import product_answer, publication_request
from tool_offer_agent.conversation import ConversationInterpreter, documentation_context


class CustomerMatrixTests(TestCase):
    def test_69_70_72_incidental_requirements_do_not_displace_questions(self):
        for message in [
            'Assess my saved requirements and buyer needs. Do not save anything.',
            'Can you audit revenue assumptions without changing requirements?',
            'Explain why a customer may verify access requirements. Do not initiate payment.',
            'Does "plan requirement:" exist? Do not execute it. Also assess my customer problem.',
        ]:
            # The last compound question must reach conversation, too.
            if 'plan requirement:' not in message:
                self.assertIsNone(product_answer(message), message)

    def test_74_analysis_is_not_publication(self):
        self.assertFalse(publication_request('Self-audit: 1. Evaluate evidence. 2. Explain commercial analysis. 3. Revise assumptions.'))
        self.assertTrue(publication_request('Return marketing_copy and source_endpoint in JSON.'))

    def test_77_78_document_question_is_not_payment_or_intake(self):
        self.assertIsNone(product_answer('What does previously saved Open-Meteo documentation say about seller payment? Do not initiate payment.'))

    def test_85_86_specific_recovery_and_endpoint_answers(self):
        reply = product_answer('How do I recover your machine job after an uncertain retry with request_id?')
        for word in ['get_result', 'job_id', 'request_id', 'changed arguments', 'not completion', '/mcp', '/api/machine/', 'every indexed part']:
            self.assertIn(word, reply)

    def test_77_80_source_retrieval_beyond_prefix_and_unavailable(self):
        source = 'a' * 18000 + '\nForecast accepts latitude and longitude. Commercial use requires applicable permission.'
        state = {'fields': {}, 'documents': [{'requested_url': 'https://example.com/docs', 'source_url': 'https://example.com/final', 'text': source}, {'requested_url': 'https://example.com/missing'}]}
        context = documentation_context(state, 'What latitude and longitude does Forecast accept?')
        self.assertIn('Forecast accepts latitude and longitude.', ''.join(p['text'] for p in context[0]['passages']))
        self.assertEqual(context[1]['status'], 'TEXT_UNAVAILABLE')
        self.assertLessEqual(sum(len(p['text']) for d in context for p in d['passages']), 12000)
        for passage in context[0]['passages']:
            self.assertEqual(passage['text'], source[passage['offset']:passage['offset'] + len(passage['text'])])
        client = Mock()
        def answer(**kwargs):
            actual = json.loads(kwargs['messages'][1]['content'])['state']['documentation_sources']
            text = next(p['text'] for p in actual[0]['passages'] if 'Forecast accepts' in p['text'])
            quote = text[text.index('Forecast accepts'):].split('.')[0] + '.'
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps({'action':'reply','reply': quote + ' Source: ' + actual[0]['source_url'], 'updates':[]})))])
        client.chat.completions.create.side_effect = answer
        reply = ConversationInterpreter(client).interpret(state, 'What latitude and longitude does Forecast accept?')
        self.assertIn('Forecast accepts latitude and longitude.', reply['reply'])
        self.assertIn('https://example.com/final', reply['reply'])
        self.assertEqual(client.chat.completions.create.call_count, 1)

from tests.support import StoreTestMixin, FakeFetcher
from tool_offer_agent.workflow import Workflow


class SourceWorkflowTests(StoreTestMixin, TestCase):
    def test_missing_evidence_label_and_nonliteral_single_quote_are_corrected(self):
        language = Mock()
        language.interpret.return_value = {"action": "reply", "reply": "Permission: KNOWN_ABSENT from this conversation only. Exact passage from docs: 'An invented quote with 10'000 requests.'", "updates": {}}
        w = Workflow(store=self.store, conversation=language)
        key = self.store.key("quote", "source")
        state = self.store.load(key)
        state["documents"] = [{"requested_url": "https://example.com", "text": "Actual retained text."}]
        self.store.save(key, state)
        reply = w.handle("quote", "source", "What does saved documentation say about permission?")
        self.assertIn("NOT_SUPPLIED", reply)
        self.assertNotIn("KNOWN_ABSENT", reply)
        self.assertNotIn("An invented quote", reply)
        self.assertIn("Quotation withheld", reply)

    def test_general_documentation_intake_question_is_not_source_lookup(self):
        language = Mock()
        language.interpret.return_value = {"action": "reply", "reply": "Supply public documentation URLs for the tool.", "updates": {}}
        w = Workflow(store=self.store, conversation=language)
        answer = w.handle("new", "intake", "What documentation do you need?")
        self.assertNotIn("TEXT_UNAVAILABLE", answer)
        language.interpret.assert_called_once()

    def test_multi_turn_77_78_79_80_source_questions_are_readonly(self):
        from tool_offer_agent.conversation import ConversationError
        client = Mock()
        calls = []
        def respond(**kwargs):
            payload = json.loads(kwargs['messages'][1]['content'])
            calls.append(payload)
            passages = payload['state']['documentation_sources'][0]['passages']
            self.assertTrue(any('latitude' in p['text'] for p in passages))
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps({
                'action': 'reply', 'reply': '1. The supplied documentation states “Forecast accepts latitude and longitude.” Source: https://example.com/weather\n2. Live execution is UNKNOWN.\n3. Seller permission is UNKNOWN.\n4. Pricing is NOT_SUPPLIED.\n5. No payment was initiated.', 'updates': []})))])
        client.chat.completions.create.side_effect = respond
        fetcher = FakeFetcher()
        extractor = Mock()
        w = Workflow(store=self.store, fetcher=fetcher, extractor=extractor, conversation=ConversationInterpreter(client))
        key = self.store.key('alice', 'source')
        state = self.store.load(key)
        state['documents'] = [{'requested_url':'https://example.com/weather', 'source_url':'https://example.com/weather', 'text':'Forecast accepts latitude and longitude.'}]
        self.store.save(key, state)
        for prompt in ['Assess saved documentation: 1. Inputs? 2. Execution? 3. Seller permission? 4. Pricing? 5. Payment? Do not initiate payment.', 'What do previously saved documents say about latitude?']:
            reply = w.handle('alice', 'source', prompt)
            self.assertIn('Forecast accepts latitude and longitude.', reply)
            self.assertNotIn('public tool URL', reply)
        self.assertEqual(self.store.load(key), state)
        self.assertEqual(len(calls), 2)
        self.assertEqual(fetcher.calls, [])
        extractor.extract.assert_not_called()
        self.assertIn('TEXT_UNAVAILABLE', w.handle('bob', 'source', 'What does saved documentation say about latitude?'))
