"""Bounded synthetic regressions for the November 7 manual findings."""

import copy
import json
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from uagents_core.contrib.protocols.chat import MetadataContent, ChatAcknowledgement
from uagents_core.contrib.protocols.chat.cards import validate_card_payload, create_card_response_content
from uagents_core.types import DeliveryStatus

from tests.support import StoreTestMixin, FakeFetcher, INTAKE, DOC_URL
from tool_offer_agent.chat import create_text_chat, respond, bounded_send, incoming_text
from tool_offer_agent.conversation import retention_safe_reply, separate_instruction_fields
from tool_offer_agent.documents import Document, DocumentError, PublicDocumentFetcher
from tool_offer_agent.drafting import render_draft
from tool_offer_agent.readiness import assess, readiness_command
from tool_offer_agent.workflow import Workflow


class ControlledFetcher(FakeFetcher):
    def __init__(self, failures=()):
        super().__init__()
        self.failures = set(failures)

    def fetch(self, url):
        self.calls.append(url)
        if url in self.failures:
            raise DocumentError("Controlled fixture returned HTTP 404.")
        return Document(url, url, self.text, "application/json")


class LiveFindingsTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = ControlledFetcher()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher)
        self.sender, self.session = "synthetic-nov07", "manual-regression"

    def chat(self, text):
        return self.workflow.handle(self.sender, self.session, text)

    def state(self):
        return self.store.load(self.store.key(self.sender, self.session))

    def report(self):
        return assess(self.state(), self.sender, "local-correction-test")

    def test_natural_readiness_returns_same_assessment_without_model_or_mutation(self):
        self.chat("Try a fictional example")
        language = Mock()
        language.interpret.return_value = {"action": "reply", "reply": "I can assess that offer.", "updates": {}}
        self.workflow.conversation = language
        before = self.state()
        direct = self.chat("readiness")
        natural = self.chat("Assess this offer’s readiness. Explain what is missing and whether its fictional-example restriction prevents commercial use.")
        self.assertEqual(str(natural), str(direct))
        self.assertEqual(natural.metadata, direct.metadata)
        self.assertIn("Meaningful caveats", natural)
        self.assertIn("no commercial use", natural)
        self.assertEqual(self.state(), before)
        language.interpret.assert_not_called()

    def test_readiness_router_is_affirmative_and_not_a_field_parser(self):
        for text in ("Please check my offer's readiness", "Could you assess readiness?", "How ready is my draft?", "Is this offer ready for review?", "/readiness json"):
            with self.subTest(text=text):
                self.assertIsNotNone(readiness_command(text))
        for text in ("Don't assess readiness", "How do I assess readiness?", "What if we checked readiness?", "pricing: assess readiness", 'The docs say "assess readiness"', "Explain the readiness command"):
            with self.subTest(text=text):
                self.assertIsNone(readiness_command(text))

    def test_one_to_three_urls_and_mixed_results_are_all_attempted(self):
        urls = [DOC_URL, "https://docs.example.com/usage", "https://docs.example.com/payment"]
        for count in (1, 2, 3):
            for failed in (set(), {urls[0]}, {urls[count - 1]}, set(urls[:count])):
                with self.subTest(count=count, failed=failed):
                    self.session = str(count) + "-" + ",".join(sorted(failed))
                    self.fetcher.calls.clear()
                    self.fetcher.failures = failed
                    reply = self.chat("Please read docs: " + " ".join(urls[:count]))
                    state = self.state()
                    self.assertEqual(state['fields']['docs'], urls[:count])
                    self.assertEqual(self.fetcher.calls, urls[:count])
                    self.assertEqual([doc['requested_url'] for doc in state['documents']], [url for url in urls[:count] if url not in failed])
                    self.assertEqual([outcome['url'] for outcome in state['document_fetch_outcomes']], urls[:count])
                    for url in urls[:count]:
                        self.assertIn(url, reply)
                    if failed:
                        self.assertIn("fetch failed", reply)
                        self.assertEqual(len([item for item in self.report()['findings'] if item['code'] == 'DOCUMENT_FETCH_FAILED']), len(failed))

    def test_mixed_refresh_preserves_previous_text_and_saved_draft(self):
        second = "https://docs.example.com/usage"
        self.chat(INTAKE.replace("docs: " + DOC_URL, "docs: " + DOC_URL + " " + second))
        before = self.state()
        self.fetcher.failures = {DOC_URL}
        reply = self.chat("refresh docs")
        state = self.state()
        self.assertEqual(self.fetcher.calls[-2:], [DOC_URL, second])
        self.assertEqual(state['documents'], before['documents'])
        self.assertEqual(state['draft'], before['draft'])
        self.assertEqual(state['draft_documents'], before['draft_documents'])
        self.assertIn("previous text retained, not refreshed", reply)
        self.assertTrue(state['document_fetch_outcomes'][0]['retained_previous'])

    def test_multi_url_workflow_uses_real_http_fetcher_with_controlled_transport(self):
        from tests.test_documents import FakeConnection, FakeResponse, dns
        urls = ['https://docs.example.com/openapi.json', 'https://docs.example.com/missing', 'https://docs.example.com/usage']
        connections = [FakeConnection(FakeResponse(b'{"openapi":"3.0.0","paths":{}}', headers={'content-type': 'application/json'})),
                       FakeConnection(FakeResponse(status=404)),
                       FakeConnection(FakeResponse(b'POST /convert with a JSON body.'))]
        factory = Mock(side_effect=connections)
        self.workflow.fetcher = PublicDocumentFetcher(resolver=Mock(return_value=dns(['93.184.216.34'])), connection_factory=factory)
        reply = self.chat('Read docs: ' + ' '.join(urls))
        self.assertEqual(factory.call_count, 3)
        self.assertEqual([connection.requests[0][:2] for connection in connections], [('GET', '/openapi.json'), ('GET', '/missing'), ('GET', '/usage')])
        self.assertTrue(all(connection.closed for connection in connections))
        self.assertEqual([record['requested_url'] for record in self.state()['documents']], [urls[0], urls[2]])
        self.assertEqual(self.state()['documents'][1]['text'], 'POST /convert with a JSON body.')
        self.assertIn(urls[1], reply)
        self.assertIn('404', reply)

    def test_partial_read_can_build_incomplete_without_discarding_success(self):
        second = "https://docs.example.com/unavailable"
        self.fetcher.failures = {second}
        self.chat(INTAKE.replace("docs: " + DOC_URL, "docs: " + DOC_URL + " " + second))
        calls = list(self.fetcher.calls)
        self.chat("draft incomplete")
        state = self.state()
        self.assertEqual(self.fetcher.calls, calls)
        self.assertEqual([doc['requested_url'] for doc in state['draft_documents']], [DOC_URL])
        self.assertTrue(state['documentation_error'])
        self.assertIn('DOCUMENT_FETCH_FAILED', [item['code'] for item in self.report()['findings']])

    def test_one_to_three_urls_do_not_bypass_validation(self):
        for value in (DOC_URL + " http://127.0.0.1/", " ".join(DOC_URL + str(index) for index in range(4))):
            self.chat("docs: " + value)
            self.assertFalse(self.fetcher.calls)
            self.assertNotIn('docs', self.state()['fields'])

    def test_natural_comma_separated_urls_are_not_one_url(self):
        second = "https://docs.example.com/usage"
        self.chat("Please read docs: " + DOC_URL + "," + second)
        self.assertEqual(self.fetcher.calls, [DOC_URL, second])

    def test_review_shows_saved_values_and_separate_correction_and_cancel(self):
        self.chat(INTAKE)
        self.chat("revise pricing: USD 9 per month")
        before = self.state()
        review = self.chat("review intake")
        self.assertIn('USD 9 per month', review)
        for field, value in before['fields'].items():
            if isinstance(value, str):
                self.assertIn(value, review)
        payload = json.loads(review.metadata['card_payload'])
        validate_card_payload('review', payload)
        self.assertEqual(payload['reject_cta']['label'], 'Cancel review')
        form = self.chat(json.dumps(payload['approve_cta']['selection']))
        form_payload = json.loads(form.metadata['card_payload'])
        validate_card_payload('form', form_payload)
        response = self.chat(json.dumps({**form_payload['submit_cta']['selection'], 'field': 'pricing', 'value': 'USD 9 per month'}))
        self.assertIn('unchanged', response)
        self.assertEqual(self.state()['revision'], before['revision'])
        self.assertEqual(self.state()['draft'], before['draft'])
        review = self.chat('review intake')
        selection = json.loads(review.metadata['card_payload'])['reject_cta']['selection']
        self.assertIn('cancelled', self.chat(json.dumps({**selection, 'approved': False})))
        self.assertEqual(self.state()['fields'], before['fields'])
        self.assertEqual(self.state()['revision'], before['revision'])
        self.assertIn('No active card', self.chat('cancel review'))

    def test_rebuild_counter_and_review_apply_to_the_exact_draft(self):
        self.chat('Try a fictional example')
        original = copy.deepcopy(self.state())
        self.chat('finish review')
        self.assertIn('already finished', self.report()['next_step'])
        self.chat('revise pricing: USD 9 per month')
        self.assertEqual(self.state()['revision'], original['revision'] + 1)
        self.assertIn('rebuild', self.report()['next_step'])
        self.chat('draft limited')
        state = self.state()
        self.assertEqual(state['revision'], original['revision'] + 2)
        self.assertEqual(state['draft']['draft_version'], 2)
        self.assertEqual(state['offer_lineage'][0]['draft'], original['draft'])
        self.assertEqual(state['offer_lineage'][0]['source_documents'], original['draft_documents'])
        self.assertIn('superseded draft', self.report()['next_step'])
        self.chat('review offer')
        self.chat('finish review')
        self.assertIn('already finished', self.report()['next_step'])
        revision = self.state()['revision']
        self.chat('revise pricing: USD 9 per month')
        self.assertEqual(self.state()['revision'], revision)
        self.assertFalse(self.state()['outdated'])

    def test_draft_markdown_separates_sections_and_source_attribution(self):
        self.chat(INTAKE)
        state = self.state()
        rendered = render_draft(state['draft'], state['draft_documents'])
        for heading in ('Capabilities', 'Inputs', 'Outputs', 'Limitations', 'Pricing', 'Payment Instructions', 'Access Instructions', 'Invocation Instructions', 'Sources and authorization boundaries', 'Boundaries'):
            self.assertIn('\n\n## ' + heading, rendered)
        self.assertIn('\n  Source: ' + DOC_URL, rendered)
        self.assertIn('State revision advances', rendered)

    def test_combined_access_is_preserved_but_payment_is_not_invocation(self):
        language = Mock()
        combined = 'Customers obtain access after paying 0.15 USDC per request'
        language.interpret.return_value = {'action': 'update', 'reply': 'Those are access terms.', 'updates': {'access': combined, 'invocation': 'paying 0.15 USDC per request'}}
        self.workflow.conversation = language
        reply = self.chat(combined)
        self.assertEqual(self.state()['fields']['access'], combined)
        self.assertNotIn('invocation', self.state()['fields'])
        self.assertIn('which endpoint or MCP tool', reply)
        self.assertNotIn('payment', self.state()['fields'])

    def test_instruction_guard_preserves_explicit_request_and_other_fields(self):
        fields = {'access': 'Register an account', 'payment': 'Pay 0.15 USDC', 'invocation': 'POST /run with a JSON body after payment'}
        plan = {'action': 'update', 'reply': 'Intake details.', 'updates': fields}
        self.assertEqual(separate_instruction_fields(plan), plan)
        duplicate = {**plan, 'updates': {'access': 'Use the dashboard', 'invocation': 'Use the dashboard'}}
        self.assertEqual(separate_instruction_fields(duplicate)['updates'], {'access': 'Use the dashboard'})
        per_invocation = {**plan, 'updates': {'access': 'Pay USD 2 per invocation', 'invocation': 'USD 2 per invocation'}}
        self.assertEqual(separate_instruction_fields(per_invocation)['updates'], {'access': 'Pay USD 2 per invocation'})

    def test_combined_mcp_access_payment_bypasses_literal_invocation_shortcut(self):
        self.chat(INTAKE)
        state = self.state()
        state['fields'].pop('access')
        state['fields'].pop('invocation')
        state['awaiting'] = 'access'
        self.store.save(self.store.key(self.sender, self.session), state)
        combined = 'Users can use it as MCP after paying USD 2 per invocation'
        reply = self.chat(combined)
        self.assertEqual(self.state()['fields']['access'], combined)
        self.assertNotIn('invocation', self.state()['fields'])
        self.assertIn('invoke', reply)

    def test_blanket_secret_retention_promise_is_not_delivered(self):
        language = Mock()
        language.interpret.return_value = {'action': 'reply', 'reply': 'Please provide public docs. Secrets are not stored.', 'updates': {}}
        self.workflow.conversation = language
        reply = self.chat('Can I paste a password here?')
        self.assertNotIn('Secrets are not stored', reply)
        self.assertIn('Do not submit credentials', reply)
        self.assertIn('ASI or other platform', reply)
        self.assertEqual(retention_safe_reply('Pricing is not stored yet.'), 'Pricing is not stored yet.')


class ACPFindingsTests(StoreTestMixin, IsolatedAsyncioTestCase):
    async def test_metadata_only_selection_and_conflicting_identity(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        workflow.handle('synthetic', 'acp', INTAKE)
        review = workflow.handle('synthetic', 'acp', 'review intake')
        selection = json.loads(review.metadata['card_payload'])['approve_cta']['selection']
        message = create_text_chat('Accompanying UI text is not the action')
        message.content.append(create_card_response_content(card_id=UUID(review.metadata['card_id']), selection=selection))
        context = SimpleNamespace(session='acp', send=AsyncMock(), logger=Mock())
        await respond(context, 'synthetic', message, workflow)
        self.assertIn('complete new public value', context.send.call_args_list[-1].args[1].text())
        message.content.append(message.content[-1])
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            incoming_text(message)
        message.content = [create_card_response_content(card_id=UUID(review.metadata['card_id']), selection={**selection, 'card_id': 'f' * 32})]
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            incoming_text(message)
        message.content = [MetadataContent(type='metadata', metadata={'card_protocol_version': '1', 'selection': '{"action":"cancel","action":"reviewed"}'})]
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            incoming_text(message)

    async def test_metadata_only_cancellation_is_bound_and_preserves_state(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        workflow.handle('synthetic', 'acp', INTAKE)
        review = workflow.handle('synthetic', 'acp', 'review intake')
        before = self.store.load(self.store.key('synthetic', 'acp'))
        message = create_text_chat('')
        message.content = [create_card_response_content(card_id=UUID(review.metadata['card_id']), cancelled=True)]
        context = SimpleNamespace(session='acp', send=AsyncMock(), logger=Mock())
        await respond(context, 'synthetic', message, workflow)
        self.assertIsInstance(context.send.call_args_list[0].args[1], ChatAcknowledgement)
        self.assertEqual(context.send.call_args_list[0].args[1].acknowledged_msg_id, message.msg_id)
        self.assertIn('cancelled', context.send.call_args_list[-1].args[1].text())
        state = self.store.load(self.store.key('synthetic', 'acp'))
        self.assertEqual(state['fields'], before['fields'])
        self.assertEqual(state['draft'], before['draft'])
        self.assertEqual(state['revision'], before['revision'])
        self.assertNotIn('guided_card', state)

    async def test_sent_missing_and_failed_transport_never_imply_delivery(self):
        for status, expected in ((DeliveryStatus.SENT, 'transport_unconfirmed'), (None, 'transport_unconfirmed'), (DeliveryStatus.FAILED, 'transport_failed'), (DeliveryStatus.DELIVERED, 'transport_delivered')):
            context = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(status=status)), logger=Mock())
            self.assertEqual(await bounded_send(context, 'synthetic', create_text_chat('hello'), 'trace', 'reply'), expected)
            self.assertIn('ASI history/rendering not confirmed', context.logger.info.call_args.args[0])
