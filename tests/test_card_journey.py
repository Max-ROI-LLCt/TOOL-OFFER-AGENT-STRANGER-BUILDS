"""Isolated ACP replays of synthetic and sanitized retained browser structures."""

import copy
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from tests.support import StoreTestMixin, card_selection
from tool_offer_agent.chat import create_text_chat, respond
from tool_offer_agent.export_delivery import REPLY_BYTES, reassemble
from tool_offer_agent.guided_cards import valid_metadata
from tool_offer_agent.machine_contract import CONTRACT
from tool_offer_agent.storage import StateStore
from tool_offer_agent.workflow import Workflow


CUSTOMER = 'Independent shipping-form developers'


class CardJourneyTests(StoreTestMixin, IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.sender = 'synthetic-card-journey'
        self.session = str(uuid4())
        self.services = {name: Mock() for name in ('fetcher', 'extractor', 'conversation', 'checkout', 'fahce')}
        self.workflow = Workflow(store=self.store, **self.services)
        self.addCleanup(self.no_external_calls)

    def no_external_calls(self):
        for service in self.services.values():
            self.assertFalse(service.mock_calls)

    def state(self):
        return self.store.load(self.store.key(self.sender, self.session))

    async def send(self, text, *, sender=None, session=None, message=None):
        context = SimpleNamespace(session=session or self.session, send=AsyncMock())
        await respond(context, sender or self.sender,
                      message or create_text_chat('@tool-offer-builder ' + text), self.workflow)
        reply = context.send.call_args_list[-1].args[1]
        self.assertLessEqual(len(reply.text().encode('utf-8')), REPLY_BYTES)
        self.assertNotIn('Local processing is unavailable', reply.text())
        return reply

    def payload(self, reply):
        metadata = next(item.metadata for item in reply.content if item.type == 'metadata')
        self.assertTrue(valid_metadata(metadata))
        return json.loads(metadata['card_payload'])

    async def card(self, origin):
        self.session = str(uuid4())
        welcome = self.payload(await self.send('what do you do?'))
        selection = welcome['root']['children'][-1]['action']['selection']
        automatic = await self.send(json.dumps(selection))
        return automatic if origin == 'automatic' else await self.send('review offer')

    async def select(self, reply, action, **extra):
        selection = card_selection(self.payload(reply), action)
        return await self.send(json.dumps({**selection, **extra}))

    async def complete(self, reply):
        text = reply.text()
        value = json.loads(text) if text.startswith('{') else {}
        if value.get('schema') != 'TOOL_OFFER_EXPORT_MANIFEST_V1':
            return text, None
        parts = [json.loads((await self.send(f"export part {value['export_id']} {index}")).text())
                 for index in range(1, value['total_parts'] + 1)]
        return reassemble(value, parts), value

    async def test_both_origins_both_buttons_with_synthetic_transport_flags(self):
        for origin in ('automatic', 'typed_review'):
            for action in ('approve_cta', 'reject_cta'):
                variants = ({}, {'approved': True}) if action == 'approve_cta' else ({}, {'approved': False}, {'approved': True})
                for extra in variants:
                    with self.subTest(origin=origin, action=action, extra=extra):
                        card = await self.card(origin)
                        before = self.state()
                        result = await self.select(card, action, **extra)
                        if action == 'reject_cta':
                            self.assertEqual(self.payload(result)['title'], 'Correct one intake value')
                            self.assertEqual(self.state()['fields'], before['fields'])
                            self.assertEqual(self.state()['draft'], before['draft'])
                        else:
                            self.assertIn('Review finished for saved draft revision 1', result.text())
                            self.assertIn('No commercial approval, checkout, publication or payment', result.text())
                        self.assertFalse(self.state().get('approved_offer'))
                        self.assertFalse(self.state().get('commercial_transactions'))

    async def test_retained_browser_action_structure_with_routing_mention(self):
        async def routed(selection):
            text = '@' + CONTRACT['agent_address'] + ' ' + json.dumps(selection, separators=(',', ':'))
            return await self.send('', message=create_text_chat(text))

        for origin in ('automatic', 'typed_review'):
            with self.subTest(origin=origin):
                card = await self.card(origin)
                original = copy.deepcopy(self.state())
                issued = card_selection(self.payload(card), 'reject_cta')
                form = await routed({'action': 'edit', 'card_id': issued['card_id'], 'approved': True})
                self.assertEqual(self.payload(form)['title'], 'Correct one intake value')
                self.assertEqual(self.state()['fields'], original['fields'])
                correction = self.payload(form)['submit_cta']['selection']
                saved = await routed({'field': 'customer', 'value': CUSTOMER, 'action': 'correct',
                                      'card_id': correction['card_id'], 'approved': True})
                self.assertIn('Saved your customer', saved.text())
                self.assertEqual(self.state()['fields'], {**original['fields'], 'customer': CUSTOMER})
                self.assertEqual(self.state()['draft'], original['draft'])
                self.assertEqual(self.state()['documents'], original['documents'])
                self.assertEqual(self.state()['restrictions'], original['restrictions'])
                card = await self.card(origin)
                issued = card_selection(self.payload(card), 'approve_cta')
                finished = await routed({'action': 'reviewed', 'card_id': issued['card_id'], 'approved': True})
                self.assertIn('Review finished for saved draft revision 1', finished.text())
                self.assertFalse(self.state().get('approved_offer'))
                self.assertFalse(self.state().get('commercial_transactions'))

    async def test_button_correction_stale_views_rebuild_exports_and_reopen(self):
        card = await self.card('automatic')
        initial = copy.deepcopy(self.state())
        original_json, original_manifest = await self.complete(await self.send('export json'))
        self.assertIsNotNone(original_manifest)
        form = await self.select(card, 'reject_cta', approved=True)
        selection = self.payload(form)['submit_cta']['selection']
        message = create_text_chat(json.dumps({**selection, 'field': 'customer', 'value': CUSTOMER, 'approved': True}))
        saved = await self.send('', message=message)
        self.assertIn('Saved your customer', saved.text())
        self.assertIn('draft limited', saved.text())
        self.assertEqual((await self.send('', message=message)).text(), saved.text())
        corrected = self.state()
        self.assertEqual(corrected['fields'], {**initial['fields'], 'customer': CUSTOMER})
        self.assertEqual(corrected['revision'], 2)
        self.assertEqual(corrected['draft'], initial['draft'])
        self.assertEqual(corrected['documents'], initial['documents'])
        self.assertEqual(corrected['restrictions'], initial['restrictions'])
        self.assertTrue(corrected['outdated'])
        review = await self.send('review offer')
        self.assertIn('saved draft revision 1', review.text().lower())
        self.assertIn('intake revision 2', review.text())
        self.assertIn('draft limited', review.text())
        finished = await self.select(review, 'approve_cta', approved=True)
        self.assertIn('pending intake revision 2', finished.text())
        readiness, _ = await self.complete(await self.send('readiness'))
        self.assertIn('needs revision', readiness)
        self.assertIn(CUSTOMER, readiness)
        detailed, _ = await self.complete(await self.send('readiness text'))
        report, _ = await self.complete(await self.send('readiness json'))
        self.assertIn(json.loads(report)['basis']['snapshot_sha256'], detailed)
        self.assertIn('Assessed intake revision: 2', detailed)
        self.assertIn('Saved draft revision: 1', detailed)
        self.assertNotIn('Draft revision: 2', detailed)
        self.assertIn('\n\nSnapshot:', detailed)
        self.assertIn('draft limited', detailed)
        old_buyer, _ = await self.complete(await self.send('export buyer readable'))
        self.assertTrue(old_buyer.startswith('## Detailed buyer-readable offer'))
        self.assertIn('For: Shipping form developers', old_buyer)
        self.assertNotIn(CUSTOMER, old_buyer)
        self.assertIn('draft limited', old_buyer)
        explanation = await self.send('buyer explanation')
        self.assertIn('intake revision 2', explanation.text())
        self.assertIn('draft limited', explanation.text())
        self.assertIn('\n\n### Inputs\n\n', old_buyer)
        self.assertIn('\n\n### Outputs\n\n', old_buyer)
        self.assertIn('[source: ', old_buyer)
        pending_json, _ = await self.complete(await self.send('export json'))
        self.assertEqual(json.loads(pending_json)['draft'], json.loads(original_json)['draft'])
        self.assertEqual(json.loads(pending_json)['pending_intake']['customer'], CUSTOMER)
        await self.send('draft limited')
        rebuilt = copy.deepcopy(self.state())
        self.assertEqual(rebuilt['draft']['revision'], 3)
        self.assertEqual(rebuilt['draft']['draft_version'], 2)
        self.assertEqual(rebuilt['draft']['seller']['intended_customer'], CUSTOMER)
        self.assertTrue(rebuilt['restrictions']['demonstration_only'])
        self.assertFalse(rebuilt['outdated'])
        for command in ('review offer', 'buyer explanation', 'readiness', 'readiness text', 'export buyer readable'):
            text, _ = await self.complete(await self.send(command))
            self.assertIn(CUSTOMER, text if command != 'review offer' else json.dumps(self.payload(await self.send(command))))
            self.assertNotIn('OUTDATED', text)
        audit_text, manifest = await self.complete(await self.send('export json'))
        self.assertIsNotNone(manifest)
        audit = json.loads(audit_text)
        self.assertEqual(audit['draft']['seller']['intended_customer'], CUSTOMER)
        self.assertEqual(audit['draft']['revision'], 3)
        self.assertTrue(audit['restrictions']['demonstration_only'])
        self.assertIsNone(audit['pending_intake'])
        self.store = StateStore(self.store.path)
        self.workflow = Workflow(store=self.store, **self.services)
        self.assertEqual(self.state()['draft'], rebuilt['draft'])
        self.assertIn(CUSTOMER, (await self.send('buyer explanation')).text())
        retained_parts = [json.loads((await self.send(f"export part {original_manifest['export_id']} {index}")).text())
                          for index in range(1, original_manifest['total_parts'] + 1)]
        self.assertEqual(reassemble(original_manifest, retained_parts), original_json)
        self.assertFalse(self.state().get('approved_offer'))
        self.assertFalse(self.state().get('commercial_transactions'))

    async def test_identical_button_value_and_typed_correction_are_separate(self):
        card = await self.card('typed_review')
        form = await self.select(card, 'reject_cta', approved=True)
        before = self.state()
        selection = {**self.payload(form)['submit_cta']['selection'], 'field': 'customer',
                     'value': before['fields']['customer'], 'approved': True}
        result = await self.send(json.dumps(selection))
        self.assertIn('customer unchanged', result.text())
        self.assertEqual(self.state()['revision'], before['revision'])
        self.assertEqual(self.state()['draft'], before['draft'])
        self.assertIn('already handled', (await self.send(json.dumps(selection))).text())
        await self.card('automatic')
        before = self.state()
        typed = await self.send('revise customer: ' + CUSTOMER)
        self.assertIn('Saved your customer', typed.text())
        self.assertEqual(self.state()['fields'], {**before['fields'], 'customer': CUSTOMER})
        self.assertEqual(self.state()['draft'], before['draft'])

    async def test_invalid_stale_cross_session_and_cross_sender_are_non_mutating(self):
        card = await self.card('automatic')
        selection = card_selection(self.payload(card), 'reject_cta')
        before = self.state()
        for extra in ({'approved': 'true'}, {'approved': 1}, {'purchase': True}, {'field': 'customer'}, {'action': 'correct'}):
            result = await self.send(json.dumps({**selection, **extra}))
            self.assertIn('Invalid card selection', result.text())
            self.assertEqual(self.state(), before)
        payload = json.dumps({**selection, 'approved': True})
        for arguments in ({'session': str(uuid4())}, {'sender': 'different-synthetic-sender'}):
            self.assertIn('stale', (await self.send(payload, **arguments)).text())
            self.assertEqual(self.state(), before)
        duplicate = payload[:-1] + ',"approved":true}'
        self.assertIn('Invalid card selection JSON', (await self.send(duplicate)).text())
        self.assertEqual(self.state(), before)
        await self.send('review offer')
        fresh = self.state()
        self.assertIn('stale', (await self.send(payload)).text())
        self.assertEqual(self.state(), fresh)
        await self.send('revise customer: ' + CUSTOMER)
        revised = self.state()
        self.assertIn('stale', (await self.send(payload)).text())
        self.assertEqual(self.state(), revised)

    async def test_live_acceptance_script_against_local_acp(self):
        from tests.live_card_journey import exercise

        async def ask(session, question, expected=None, card_kind=None):
            reply = await self.send(question, session=session)
            metadata = [item.metadata for item in reply.content if item.type == 'metadata']
            if expected:
                self.assertIn(expected, reply.text())
            if card_kind:
                self.assertEqual(metadata[0]['card_kind'], card_kind)
                self.assertTrue(valid_metadata(metadata[0]))
            return reply.text(), metadata

        async def stored(session):
            return self.store.load(self.store.key(self.sender, str(session)))

        receipt = {}
        await exercise(ask, stored, receipt)
        self.assertTrue(receipt['passed'])
        self.assertEqual(len(receipt['card_journey']['action_cases']), 4)
