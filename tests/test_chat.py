import importlib
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from tool_offer_agent.chat import create_agent, create_text_chat, respond, strip_routing_mentions
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage


async def execute_in_process(function, *args, **kwargs):
    return function(*args, **kwargs)


class ChatTests(IsolatedAsyncioTestCase):
    def setUp(self):
        threading_override = patch("tool_offer_agent.chat.asyncio.to_thread", new=execute_in_process)
        threading_override.start()
        self.addCleanup(threading_override.stop)

    async def test_ack_precedes_workflow_and_session_is_explicit(self):
        ctx = SimpleNamespace(session=uuid4(), send=AsyncMock())
        workflow = Mock()
        def handle(*args):
            self.assertIsInstance(ctx.send.call_args_list[0].args[1], ChatAcknowledgement)
            return "Draft preserved"
        workflow.handle.side_effect = handle
        msg = create_text_chat("hello")
        await respond(ctx, "seller", msg, workflow)
        workflow.handle.assert_called_once_with("seller", str(ctx.session), "hello")
        self.assertEqual(ctx.send.call_args_list[0].args[1].acknowledged_msg_id, msg.msg_id)
        self.assertIsInstance(ctx.send.call_args_list[1].args[1], ChatMessage)

    async def test_asi_mentions_are_removed_before_workflow(self):
        for target in ('tool-offer-builder', 'agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a'):
            for body in ('start', 'https://api.open-meteo.com/v1/forecast', 'access: No key required'):
                with self.subTest(target=target, body=body):
                    ctx = SimpleNamespace(session=uuid4(), send=AsyncMock())
                    workflow = Mock()
                    workflow.handle.return_value = 'Intake'
                    await respond(ctx, 'seller', create_text_chat('@' + target + ' ' + body), workflow)
                    workflow.handle.assert_called_once_with('seller', str(ctx.session), body)

    async def test_mentions_do_not_modify_evidence_or_other_handles(self):
        for text in ('Contact @tool-offer-builder for help', '@another-agent start', '@tool-offer-builder-other start', 'https://example.com/?q=@tool-offer-builder'):
            self.assertEqual(strip_routing_mentions(text), text)
        self.assertEqual(strip_routing_mentions('@tool-offer-builder'), '')

    async def test_failure_does_not_leak_exception(self):
        ctx = SimpleNamespace(session=uuid4(), send=AsyncMock())
        workflow = Mock()
        workflow.handle.side_effect = RuntimeError("private credentials")
        await respond(ctx, "seller", create_text_chat("draft"), workflow)
        self.assertNotIn("private credentials", ctx.send.call_args_list[-1].args[1].text())

    async def test_unprepared_large_reply_never_pushes_incomplete_parts(self):
        ctx = SimpleNamespace(session=uuid4(), send=AsyncMock())
        workflow = Mock()
        workflow.handle.return_value = '{"text":"' + "😀" * 10000 + '"}'
        await respond(ctx, "seller", create_text_chat("export"), workflow)
        self.assertEqual(ctx.send.call_count, 2)  # acknowledgement and one reply
        self.assertIn("no complete export was delivered", ctx.send.call_args_list[-1].args[1].text())


class ImportTests(TestCase):
    def test_hosted_nonspending_demo_is_fail_closed_without_custody_and_buyer(self):
        with patch.dict(os.environ, {"TOOL_OFFER_USE_MODEL": "0", "TOOL_OFFER_ENABLE_HOSTED_TEST_PAYMENTS": "1"}, clear=True), patch("tool_offer_agent.chat.Agent"):
            with self.assertRaisesRegex(RuntimeError, "custody URL, token"):
                create_agent(hosted=True)

    def test_hosted_demo_requires_allowed_buyer_and_existing_agent_recipient(self):
        from tool_offer_agent.workflow import Workflow
        buyer = "agent1" + "q" * 59
        address = "agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a"
        env = {"TOOL_OFFER_USE_MODEL": "0", "TOOL_OFFER_ENABLE_HOSTED_TEST_PAYMENTS": "1",
               "TOOL_OFFER_CUSTODY_URL": "https://custody.example.com", "TOOL_OFFER_CUSTODY_TOKEN": "test-only-secret", "TOOL_OFFER_DEMO_BUYER_ADDRESS": buyer}
        with patch.dict(os.environ, env, clear=True), patch("tool_offer_agent.chat.Agent") as agent_type, patch("tool_offer_agent.cloudflare_custody.CloudflareTransactionStore"):
            create_agent(hosted=True)
            self.assertEqual(agent_type.return_value.include.call_count, 3)
        restricted = Workflow(local_test=True, demo_buyer_address=buyer, demo_recipient=address)
        self.assertEqual(restricted.demo_buyer_address, buyer)
        self.assertEqual(restricted.demo_recipient, address)

    def test_hosted_agent_never_enables_local_test_payment_protocol(self):
        with patch.dict(os.environ, {"TOOL_OFFER_USE_MODEL": "0", "TOOL_OFFER_ENABLE_TEST_PAYMENTS": "1"}, clear=True), patch("tool_offer_agent.chat.Agent") as agent_type, patch("tool_offer_agent.chat.Workflow") as workflow:
            create_agent(hosted=True)
            self.assertFalse(workflow.call_args.kwargs["local_test"])
            self.assertEqual(agent_type.return_value.include.call_count, 2)

    def test_service_factory_registers_protocol_without_starting_service(self):
        with patch.dict(os.environ, {"TOOL_OFFER_AGENT_NAME": "Custom Offer Agent"}, clear=True), patch("tool_offer_agent.chat.Agent") as agent_type, patch("tool_offer_agent.chat.StateStore"):
            agent = create_agent()
            agent_type.assert_called_once_with(name="Custom Offer Agent")
            agent.include.assert_called_once()
            agent.run.assert_not_called()

    def test_hosted_factory_shares_personal_provider_for_both_inference_paths(self):
        env = {'ASI1_BASE_URL': 'https://exhausted.example/v1', 'ASI1_API_KEY': 'hosting-test-only', 'TOOL_OFFER_ASI_ONE_API_KEY': 'personal-test-only', 'TOOL_OFFER_CHAT_MODEL': 'ignored', 'TOOL_OFFER_EXTRACTION_MODEL': 'ignored'}
        with patch.dict(os.environ, env, clear=True), patch('tool_offer_agent.chat.Agent') as agent_type, patch('openai.OpenAI') as client, patch('tool_offer_agent.drafting.OpenAIQuoteExtractor') as extractor, patch('tool_offer_agent.chat.Workflow') as workflow:
            create_agent(hosted=True)
            client.assert_called_once_with(base_url='https://api.asi1.ai/v1', api_key=env['TOOL_OFFER_ASI_ONE_API_KEY'], max_retries=0)
            self.assertEqual(os.environ['ASI1_API_KEY'], 'hosting-test-only')
            self.assertIs(workflow.call_args.kwargs['conversation'].client, client.return_value)
            self.assertEqual(workflow.call_args.kwargs['conversation'].model, 'asi1')
            self.assertEqual(workflow.return_value.model_configuration['provider'], 'personal_asi_one')
            extractor.assert_called_once_with(client.return_value)
            self.assertIs(workflow.call_args.kwargs['extractor'], extractor.return_value)
            self.assertIs(workflow.call_args.kwargs['store'].storage, agent_type.return_value.storage)
            agent_type.return_value.run.assert_not_called()

    def test_personal_secret_missing_never_falls_back_to_hosting(self):
        for value in (None, '', '   '):
            env = {'ASI1_BASE_URL': 'https://exhausted.example/v1', 'ASI1_API_KEY': 'hosting-test-only'}
            if value is not None:
                env['TOOL_OFFER_ASI_ONE_API_KEY'] = value
            with self.subTest(value=value), patch.dict(os.environ, env, clear=True), patch('openai.OpenAI') as client:
                with self.assertRaisesRegex(RuntimeError, 'TOOL_OFFER_ASI_ONE_API_KEY'):
                    create_agent(hosted=True)
                client.assert_not_called()

    def test_hosted_model_extraction_can_be_disabled_without_credentials(self):
        with patch.dict(os.environ, {'TOOL_OFFER_USE_MODEL': '0'}, clear=True), patch('tool_offer_agent.chat.Agent'), patch('openai.OpenAI') as client, patch('tool_offer_agent.chat.Workflow') as workflow:
            create_agent(hosted=True)
            client.assert_not_called()
            self.assertIsNone(workflow.call_args.kwargs['extractor'])

    def test_agent_import_requires_no_credentials_and_starts_no_services(self):
        with patch.dict(os.environ, {}, clear=True), patch("uagents.Agent.run") as run:
            importlib.import_module("agent")
            run.assert_not_called()
