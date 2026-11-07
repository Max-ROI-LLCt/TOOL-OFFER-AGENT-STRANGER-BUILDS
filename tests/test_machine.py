"""Offline restricted-adapter tests; fake models and no paid transports."""

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from uagents_core.identity import Identity
from tool_offer_agent.machine import MachineRequest, MachineService, include_machine
from tool_offer_agent.machine_contract import CONTRACT
from tool_offer_agent.workflow import Workflow
from tests.support import StoreTestMixin, FakeFetcher, INTAKE
from tests.test_listing_intent_regression import UNRELATED_MESSAGES


class MachineTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.key = Identity.from_seed('offline-tool-offer-gateway-test', 0)
        self.sender = Identity.from_seed('offline-ephemeral-test', 0).address
        self.language = Mock()
        self.language.interpret.return_value = {'action': 'reply', 'reply': 'Your free product answer.', 'updates': {}}
        self.checkout = Mock()
        self.paid = Mock()
        workflow = Workflow(store=self.store, fetcher=FakeFetcher(), conversation=self.language, checkout=self.checkout, fahce=self.paid)
        self.service = MachineService(workflow, CONTRACT, 'release-test', self.key.address, clock=lambda: 1000)
        self.session = str(uuid4())

    def request(self, operation='get_status', arguments=None, **overrides):
        data = {'principal': 'client-one', 'session_id': self.session, 'request_id': str(uuid4()),
                'release_id': 'release-test', 'issued_at': 1000, 'transport_sender': self.sender,
                'operation': operation, 'arguments': arguments or {}}
        data.update(overrides)
        body = json.dumps(data)
        return MachineRequest(body=body, authorization=self.key.sign_digest(hashlib.sha256(body.encode()).digest()))

    def call(self, operation='get_status', arguments=None, **overrides):
        return self.service.execute(self.request(operation, arguments, **overrides), self.sender)

    def test_hosted_handler_signs_with_context_not_agent_wrapper(self):
        identity = Identity.from_seed('offline-tool-offer-hosted-response', 0)
        for representation in [SimpleNamespace(sign_digest=identity.sign_digest), SimpleNamespace(identity=identity)]:
            with self.subTest(representation=tuple(vars(representation))):
                hosted_agent = Mock(spec_set=['include'])
                context = SimpleNamespace(agent=representation, send=AsyncMock())
                with patch('tool_offer_agent.machine.MachineService', return_value=self.service):
                    include_machine(hosted_agent, self.service.workflow)
                protocol = hosted_agent.include.call_args.args[0]
                handler = next(iter(protocol.signed_message_handlers.values()))
                request = self.request(operation='capabilities')
                asyncio.run(handler(context, self.sender, request))
                context.send.assert_awaited_once()
                destination, response = context.send.call_args.args
                self.assertEqual(destination, self.sender)
                self.assertTrue(Identity.verify_digest(identity.address, hashlib.sha256(response.body.encode()).digest(), response.signature))
                self.assertEqual(json.loads(response.body)['status'], 'complete')
                self.language.interpret.assert_not_called()

    def test_missing_context_signer_fails_before_operation(self):
        hosted_agent = Mock(spec_set=['include'])
        context = SimpleNamespace(agent=SimpleNamespace(), send=AsyncMock())
        with patch('tool_offer_agent.machine.MachineService', return_value=self.service):
            include_machine(hosted_agent, self.service.workflow)
        protocol = hosted_agent.include.call_args.args[0]
        handler = next(iter(protocol.signed_message_handlers.values()))
        with patch.object(self.service, 'execute', return_value={'status': 'complete'}) as execute:
            with self.assertRaises(AttributeError):
                asyncio.run(handler(context, self.sender, self.request()))
            execute.assert_not_called()
        context.send.assert_not_awaited()

    def test_no_paid_dependencies_inherited(self):
        self.assertIsNone(self.service.workflow.checkout)
        self.assertIsNot(self.service.workflow.fahce, self.paid)
        for command in ['check', '/check', 'CHECK', 'preflight', 'offer approve', 'transaction open', 'transaction approve', 'transaction send', 'payment options', 'publish', 'purchase status', 'reset']:
            with self.subTest(command=command):
                result = self.call('send_message', {'message': command})
                self.assertIn('Unavailable through the free machine adapter', result['text'])
        self.checkout.assert_not_called()
        self.assertFalse(self.checkout.mock_calls)
        self.assertFalse(self.paid.mock_calls)
        self.language.interpret.assert_not_called()

    def test_model_planned_commerce_is_also_denied(self):
        self.language.interpret.return_value = {'action': 'check', 'reply': '', 'updates': {}}
        result = self.call('send_message', {'message': 'Please buy the evaluation for this offer.'})
        self.assertNotEqual(result['status'], 'uncertain')
        self.assertFalse(self.checkout.mock_calls)
        self.assertFalse(self.paid.mock_calls)

    def test_all_incident_and_negative_inputs_remain_conversational(self):
        for text in UNRELATED_MESSAGES:
            with self.subTest(text=text):
                self.language.reset_mock()
                result = self.call('send_message', {'message': text})
                self.assertEqual(result['text'], 'Your free product answer.')
                self.language.interpret.assert_called_once()

    def test_existing_draft_v6_and_restrictions_preserved(self):
        workflow = self.service.workflow
        actor = 'machine:client-one'
        workflow.handle(actor, self.session, INTAKE)
        state_key = self.store.key(actor, self.session)
        state = self.store.load(state_key)
        state['revision'] = 6
        state['draft']['revision'] = 6
        state['check'] = {'historical': 'preserved'}
        state['fahce_checkout'] = {'historical': 'never reuse'}
        self.store.save(state_key, state)
        before = copy.deepcopy(state)
        self.call('send_message', {'message': 'Give me a concise preview of Draft v6, not a listing checklist.'})
        after = self.store.load(state_key)
        for field in ['draft', 'check', 'fahce_checkout', 'revision']:
            self.assertEqual(after[field], before[field])

    def test_listing_commands_still_work_without_model(self):
        for command in ['listing checklist', 'listing checklist json', 'listing profile api', 'listing profile mcp', 'listing profile agent', 'export listing']:
            with self.subTest(command=command):
                result = self.call('send_message', {'message': command})
                self.assertEqual(result['status'], 'complete')
                self.assertNotEqual(result['text'], 'Your free product answer.')
        self.language.interpret.assert_not_called()

    def test_deterministic_operations_never_infer(self):
        for operation, arguments in [('get_status', {}), ('export_offer', {'format': 'json'}), ('export_offer', {'format': 'buyer'}),
                                     ('get_export_part', {'export_id': 'a' * 64, 'index': 1})]:
            result = self.call(operation, arguments)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['model_attempts'], 0)
        self.language.interpret.assert_not_called()

    def test_bad_key_and_tampering_rejected_before_work(self):
        request = self.request()
        request.body = request.body.replace('client-one', 'client-two')
        with self.assertRaises(Exception):
            self.service.execute(request, self.sender)
        with self.assertRaises(ValueError):
            self.service.execute(self.request(transport_sender='other'), self.sender)
        self.language.interpret.assert_not_called()

    def test_stale_release_and_request_rejected(self):
        self.assertEqual(self.call(release_id='stale')['error'], 'release_mismatch')
        with self.assertRaises(ValueError):
            self.call(issued_at=1)
        self.language.interpret.assert_not_called()

    def test_replay_and_status_recovery_never_repeat_inference(self):
        request_id = str(uuid4())
        first = self.call('send_message', {'message': 'What is free?'}, request_id=request_id)
        second = self.call('send_message', {'message': 'What is free?'}, request_id=request_id)
        recovered = self.call('result', request_id=request_id)
        self.assertEqual(first, second)
        self.assertEqual(first, recovered)
        self.language.interpret.assert_called_once()
        conflict = self.call('send_message', {'message': 'Do something else'}, request_id=request_id)
        self.assertEqual(conflict['error'], 'idempotency_conflict')

    def test_sessions_and_clients_are_isolated(self):
        self.service.workflow.handle('machine:client-one', self.session, 'tool_url: https://example.com/')
        self.assertIn('example.com', self.call()['text'])
        self.assertNotIn('example.com', self.call(principal='client-two')['text'])
        self.assertNotIn('example.com', self.call(session_id=str(uuid4()))['text'])

    def test_resumable_exports_use_existing_session_store(self):
        text = json.dumps({'large': 'source-attributed ' * 2000})
        manifest = json.loads(self.service.workflow.render_response('machine:client-one', self.session, text, 'export json'))
        result = self.call('get_export_part', {'export_id': manifest['export_id'], 'index': 1})
        part = json.loads(result['text'])
        self.assertEqual(part['export_id'], manifest['export_id'])
        self.assertEqual(part['index'], 1)
        other = self.call('get_export_part', {'export_id': manifest['export_id'], 'index': 1}, principal='client-two')
        self.assertIn('unavailable', other['text'].lower())

    def test_unknown_operations_and_additional_arguments_rejected(self):
        for operation, arguments in [('pay', {}), ('export_offer', {'format': 'json', 'principal': 'owner'}), ('get_status', {'url': 'https://fahce.kinganlogic.com/'})]:
            with self.assertRaises(ValueError):
                self.call(operation, arguments)
