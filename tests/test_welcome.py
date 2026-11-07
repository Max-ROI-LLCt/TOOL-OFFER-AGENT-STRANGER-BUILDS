import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from tests.support import FakeFetcher, INTAKE, StoreTestMixin, TOOL_URL, DOC_URL, card_selection
from tool_offer_agent.chat import create_text_chat, respond
from tool_offer_agent.customer_recovery import INTRO
from tool_offer_agent.guided_cards import valid_metadata
from tool_offer_agent.parcel_fixture import FIELDS, SPEC, RESTRICTION
from tool_offer_agent.workflow import Workflow
from uagents_core.contrib.protocols.chat import ChatAcknowledgement
from uagents_core.contrib.protocols.chat.cards import CustomCardPayload


class WelcomeTests(StoreTestMixin, IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.session = str(uuid4())
        self.sender = 'synthetic-welcome-test'
        self.fetcher = FakeFetcher()
        self.planner = Mock()
        self.planner.interpret.side_effect = AssertionError('Welcome must not call the interpreter')
        self.extractor = Mock()
        self.extractor.extract.side_effect = AssertionError('Welcome must not call model extraction')
        self.checkout = Mock()
        self.fahce = Mock()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, conversation=self.planner,
                                 extractor=self.extractor, checkout=self.checkout, fahce=self.fahce)
        self.addCleanup(self.assert_no_paid_calls)

    def assert_no_paid_calls(self):
        self.planner.interpret.assert_not_called()
        self.assertFalse(self.extractor.mock_calls)
        self.assertFalse(self.checkout.mock_calls)
        self.assertFalse(self.fahce.mock_calls)

    def state(self):
        return self.store.load(self.store.key(self.sender, self.session))

    async def send(self, text, *, message=None, session=None, sender=None):
        context = SimpleNamespace(session=session or self.session, send=AsyncMock())
        message = message or create_text_chat('@tool-offer-builder ' + text)
        await respond(context, sender or self.sender, message, self.workflow)
        self.assertIsInstance(context.send.call_args_list[0].args[1], ChatAcknowledgement)
        self.assertEqual(context.send.call_count, 2)
        reply = context.send.call_args_list[-1].args[1]
        self.assertNotIn('Local processing is unavailable', reply.text())
        self.assertNotIn('TOOL_OFFER_EXPORT_MANIFEST', reply.text())
        return reply

    def payload(self, reply):
        metadata = next(item.metadata for item in reply.content if item.type == 'metadata')
        self.assertTrue(valid_metadata(metadata))
        self.assertEqual(metadata['card_kind'], 'custom')
        self.assertLess(len(metadata['card_payload'].encode()), 8000)
        payload = json.loads(metadata['card_payload'])
        CustomCardPayload.model_validate(payload)
        return payload

    def buttons(self, reply):
        return {child['label']: child['action']['selection'] for child in self.payload(reply)['root']['children']
                if child['type'] == 'button'}

    async def test_exact_question_emits_concise_text_and_native_metadata(self):
        reply = await self.send('what do you do?')
        self.assertTrue(reply.text().startswith(INTRO))
        self.assertEqual(reply.text().count(INTRO), 1)
        self.assertNotIn(INTRO, json.dumps(self.payload(reply)))
        self.assertEqual(list(self.buttons(reply)), ['Start with my tool', 'Try a fictional example'])
        self.assertIn('Or paste your public tool URL here to get started.', reply.text())
        self.assertLess(len(reply.text().encode()), 500)
        self.assertNotIn('interpreter', reply.text())
        self.assertNotIn('…', json.dumps(self.payload(reply)))
        self.assertEqual(self.fetcher.calls, [])

    async def test_profile_starters_use_same_welcome_and_keep_other_starters(self):
        settings = json.loads((Path(__file__).resolve().parents[1] / 'machine/public-profile.json').read_text())
        for prompt in settings['starter_prompts'][:2]:
            reply = await self.send(prompt)
            self.assertEqual(list(self.buttons(reply)), ['Start with my tool', 'Try a fictional example'])
        for prompt in settings['starter_prompts'][2:]:
            self.assertTrue((await self.send(prompt)).text())

    async def test_first_click_asks_url_then_direct_url_advances(self):
        selection = self.buttons(await self.send('what do you do?'))['Start with my tool']
        reply = await self.send(json.dumps(selection))
        self.assertEqual(reply.text(), 'What is the public API or MCP URL? (No credentials or private/local URLs.)')
        self.assertEqual(self.state()['awaiting'], 'tool_url')
        reply = await self.send(TOOL_URL)
        self.assertEqual(self.state()['fields']['tool_url'], TOOL_URL)
        self.assertEqual(self.state()['awaiting'], 'docs')
        self.assertIn('documentation URL', reply.text())
        self.assertNotIn(INTRO, reply.text())

    async def test_direct_url_without_welcome_or_click(self):
        reply = await self.send(TOOL_URL)
        self.assertEqual(self.state()['fields']['tool_url'], TOOL_URL)
        self.assertEqual(self.state()['awaiting'], 'docs')
        self.assertIn('documentation URL', reply.text())

    async def test_same_message_fields_and_urls_use_existing_intake(self):
        for prefix in ('what do you do?', 'Start with my tool', 'Try a fictional example'):
            self.session = str(uuid4())
            reply = await self.send(prefix + '\ntool_url: ' + TOOL_URL + '\ncustomer: App builders')
            self.assertEqual(self.state()['fields'], {'tool_url': TOOL_URL, 'customer': 'App builders'})
            self.assertIn('documentation URL', reply.text())
            self.assertNotIn('fictional', json.dumps(self.state()['fields']))
        self.session = str(uuid4())
        await self.send('Start with my tool ' + TOOL_URL)
        self.assertEqual(self.state()['awaiting'], 'docs')
        self.session = str(uuid4())
        await self.send('what do you do? ' + TOOL_URL + '\ncustomer: App builders')
        self.assertEqual(self.state()['fields'], {'tool_url': TOOL_URL, 'customer': 'App builders'})
        self.session = str(uuid4())
        await self.send('Start with my tool tool_url: ' + TOOL_URL)
        self.assertEqual(self.state()['awaiting'], 'docs')
        self.session = str(uuid4())
        await self.send('what do you do?\n' + INTAKE)
        self.assertIsNotNone(self.state()['draft'])
        self.assertEqual(self.fetcher.calls, [DOC_URL])

    async def test_plain_chat_fallback_when_metadata_unavailable(self):
        with patch('tool_offer_agent.guided_cards.valid_metadata', return_value=False):
            reply = await self.send('what do you do?')
        self.assertEqual([item.type for item in reply.content], ['text'])
        self.assertIn('Start with my tool', reply.text())
        self.assertIn('Try a fictional example', reply.text())
        await self.send('Start with my tool')
        self.assertEqual(self.state()['awaiting'], 'tool_url')
        await self.send(TOOL_URL)
        self.assertEqual(self.state()['awaiting'], 'docs')

    async def test_unrecognized_welcome_suffix_does_not_become_an_intake_value(self):
        await self.send('tool_url: ' + TOOL_URL + '\ndocs: ' + DOC_URL)
        before = self.state()
        reply = await self.send('what do you do? Can you explain your role?')
        self.assertIn('No intake values changed', reply.text())
        self.assertEqual(self.state(), before)

    async def test_demo_click_restrictions_persist_before_draft_and_through_review(self):
        selection = self.buttons(await self.send('what do you do?'))['Try a fictional example']
        original = self.workflow._build

        def inspect_before_build(state, *args, **kwargs):
            persisted = self.state()
            self.assertIsNone(persisted['draft'])
            self.assertTrue(persisted['restrictions']['demonstration_only'])
            self.assertEqual(persisted['restrictions']['commercial_authorization'], 'explicitly_restricted')
            self.assertEqual(' '.join(source['quote'] for source in persisted['restrictions']['sources']), RESTRICTION)
            self.assertEqual(json.loads(persisted['documents'][0]['text']), SPEC)
            self.assertTrue(kwargs['limited'])
            return original(state, *args, **kwargs)

        with patch.object(self.workflow, '_build', side_effect=inspect_before_build):
            reply = await self.send(json.dumps(selection))
        self.assertIn(RESTRICTION, reply.text())
        self.assertIn('not a fetched or running service', reply.text())
        draft = copy.deepcopy(self.state()['draft'])
        self.assertEqual(draft['restrictions'], self.state()['restrictions'])
        self.assertEqual(self.state()['fields']['pricing'], FIELDS['pricing'])
        self.assertEqual(self.state()['fields']['access'], FIELDS['access'])
        finish = card_selection(self.payload(reply), 'approve_cta')
        self.assertIn('Review finished', (await self.send(json.dumps({**finish, 'approved': True}))).text())
        self.assertEqual(self.state()['draft'], draft)
        self.assertIn('blocked by saved restrictions', (await self.send('check')).text())
        self.assertIn('blocked by saved restrictions', (await self.send('offer approve')).text())
        self.assertEqual(self.fetcher.calls, [])

    async def test_typed_demo_and_existing_draft_never_replace_work(self):
        await self.send('Try a fictional example')
        saved = copy.deepcopy(self.state()['draft'])
        reply = await self.send('what do you do?')
        self.assertEqual(list(self.buttons(reply)), ['Review current draft', 'Review intake'])
        await self.send(json.dumps(self.buttons(reply)['Review current draft']))
        self.assertEqual(self.state()['draft'], saved)
        self.assertIn('not replaced', (await self.send('Try a fictional example')).text())
        self.assertEqual(self.state()['draft'], saved)

    async def test_existing_partial_intake_continues_missing_field_without_demo(self):
        await self.send('tool_url: ' + TOOL_URL + '\ncustomer: Builders')
        reply = await self.send('what do you do?')
        choices = self.buttons(reply)
        self.assertEqual(list(choices), ['Continue intake', 'Review intake'])
        self.assertIn('documentation URL', (await self.send(json.dumps(choices['Continue intake']))).text())
        saved = copy.deepcopy(self.state()['fields'])
        await self.send('Try a fictional example')
        self.assertEqual(self.state()['fields'], saved)
        self.assertIsNone(self.state()['draft'])

    async def test_duplicates_stale_and_cross_session_actions_cannot_overwrite(self):
        selection = self.buttons(await self.send('what do you do?'))['Try a fictional example']
        before = self.state()
        for session, sender in ((str(uuid4()), self.sender), (self.session, 'another-sender')):
            self.assertIn('stale', (await self.send(json.dumps(selection), session=session, sender=sender)).text())
        self.assertEqual(self.state(), before)
        message = create_text_chat(json.dumps(selection))
        first = await self.send('', message=message)
        after = copy.deepcopy(self.state())
        repeated = await self.send('', message=message)
        self.assertEqual(first.text(), repeated.text())
        self.assertEqual(self.state(), after)
        self.assertIn('already handled', (await self.send(json.dumps(selection))).text())
        self.assertEqual(self.state()['draft_count'], 1)
        await self.send('revise pricing: Fictional USD 8 per month')
        saved = copy.deepcopy(self.state())
        self.assertIn('stale', (await self.send(json.dumps(selection))).text())
        self.assertEqual(self.state(), saved)
        reply = await self.send('what do you do?')
        self.assertEqual(list(self.buttons(reply)), ['Review current draft', 'Build a limited draft'])
        self.assertEqual(self.state()['draft'], saved['draft'])

    async def test_superseded_cards_invalid_actions_and_old_messages(self):
        first = self.buttons(await self.send('what do you do?'))['Try a fictional example']
        second = self.buttons(await self.send('what do you do?'))['Start with my tool']
        before = self.state()
        self.assertIn('stale', (await self.send(json.dumps(first))).text())
        for invalid in ({**second, 'action': 'welcome_build'}, {**second, 'pricing': 'USD 1'},
                        {**second, 'approved': 'true'}):
            self.assertIn('Invalid card selection', (await self.send(json.dumps(invalid))).text())
        self.assertEqual(self.state(), before)
        old = create_text_chat(json.dumps(second))
        old.timestamp = old.timestamp.replace(year=2020)
        self.assertIn('older', (await self.send('', message=old)).text())
        self.assertEqual(self.state(), before)
        await self.send(TOOL_URL)
        self.assertIn('stale', (await self.send(json.dumps(second))).text())

    async def test_existing_nonfictional_draft_and_greetings(self):
        self.workflow.extractor = None
        await self.send(INTAKE)
        saved = copy.deepcopy(self.state()['draft'])
        for greeting in ('what do you do?', 'hi', 'hello', 'start'):
            reply = await self.send(greeting)
            self.assertIn('Review current draft', self.buttons(reply))
            self.assertNotIn('Try a fictional example', reply.text())
        await self.send('Try a fictional example')
        self.assertEqual(self.state()['draft'], saved)
        self.assertFalse(self.state().get('restrictions', {}).get('demonstration_only'))
