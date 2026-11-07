from copy import deepcopy
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from tool_offer_agent.buyer_guidance import buyer_command
from tool_offer_agent.chat import create_text_chat, respond
from tool_offer_agent.conversation import ConversationError, ConversationInterpreter
from tool_offer_agent.workflow import Workflow
from tests.support import FakeFetcher, INTAKE, StoreTestMixin
from tests.test_chat import execute_in_process


QUESTIONS = (
    "Can I connect my wallet before I have an offer?",
    "I use Coinbase Wallet and want to understand the process before I prepare an offer. "
    "Can I connect my wallet now, and does connecting it give the agent permission to buy anything? "
    "I am only asking for instructions; do not create a checkout or ask me to sign.",
    "Could I set up Coinbase Wallet before drafting?",
    "Will connecting my wallet allow automatic purchases?",
    "Please help me understand wallet connection before purchasing.",
)


def rejected_client(status):
    client = Mock()
    error = RuntimeError("private provider response must not escape")
    error.status_code = status
    client.chat.completions.create.side_effect = error
    return client


class WalletInformationTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = rejected_client(403)
        self.checkout = Mock()
        self.fetcher = FakeFetcher()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, checkout=self.checkout,
                                 conversation=ConversationInterpreter(self.client))

    def chat(self, message):
        return self.workflow.handle("buyer", "wallet-information", message)

    def state(self):
        return self.store.load(self.store.key("buyer", "wallet-information"))

    def test_provider_auth_origin_remains_fail_closed(self):
        for status in (401, 403):
            with self.subTest(status=status):
                interpreter = ConversationInterpreter(rejected_client(status))
                with self.assertRaisesRegex(ConversationError, "^CHAT_AUTH$"):
                    interpreter.interpret(self.state(), QUESTIONS[0])
        reply = self.chat("Please improve this description")
        self.assertIn("CHAT_AUTH", reply)
        self.assertNotIn("private provider response", reply)
        self.checkout.assert_not_called()
        self.assertEqual(self.checkout.mock_calls, [])

    def test_short_and_long_information_questions_never_call_provider_or_purchase(self):
        for message in QUESTIONS + ("wallet", "/wallet", "wallet setup", "purchase guide", "How do I connect my wallet?"):
            with self.subTest(message=message):
                reply = self.chat(message)
                self.assertIn("Wallet guidance is available before you have an offer", reply)
                self.assertIn("actual connection happens only inside an eligible private checkout", reply)
                self.assertNotIn("CHAT_AUTH", reply)
                self.assertNotIn("What is the public URL", reply)
        self.client.chat.completions.create.assert_not_called()
        self.assertEqual(self.checkout.mock_calls, [])
        self.assertEqual(self.fetcher.calls, [])
        self.assertEqual(self.state()["fields"], {})
        self.assertIsNone(self.state().get("fahce_checkout"))

    def test_all_business_state_is_preserved_including_completed_purchase(self):
        self.chat(INTAKE)
        key = self.store.key("buyer", "wallet-information")
        state = self.state()
        state.update({"awaiting": "pricing", "approved_offer": {"test_only": True},
                      "check": {"test_only_completed_receipt": "preserve"},
                      "fahce_checkout": {"url": "https://checkout.example/checkout/test#access=test-only", "phase": "response_received"}})
        self.store.save(key, state)
        before = deepcopy(state)
        for question in QUESTIONS:
            self.assertIn("existing purchase", self.chat(question))
        after = self.state()
        before.pop("conversation", None)
        after.pop("conversation", None)
        self.assertEqual(before, after)
        self.assertEqual(self.checkout.mock_calls, [])
        self.client.chat.completions.create.assert_not_called()

    def test_information_does_not_inherit_another_session(self):
        key = self.store.key("buyer", "wallet-information")
        state = self.state()
        state["fahce_checkout"] = {"url": "https://checkout.example/checkout/test#access=other-private-capability"}
        self.store.save(key, state)
        for sender, session in (("another", "wallet-information"), ("buyer", "another")):
            reply = self.workflow.handle(sender, session, QUESTIONS[0])
            self.assertNotIn("other-private-capability", reply)
        self.assertEqual(self.checkout.mock_calls, [])

    def test_informational_matching_cannot_authorize_payment_or_consume_intake(self):
        for text in ("Pay now from my wallet", "Buy a check with my wallet", "Sign with my wallet",
                     "Connect my wallet and pay now", "Do not prepare checkout", "What if I prepare checkout?",
                     "payment: Can I connect my wallet before I have an offer?",
                     "wallet\npricing: USD 10", "docs: https://example.com/wallet",
                     "Can I connect my wallet?\nrevise pricing: USD 10",
                     '```text\nCan I connect my wallet?\n```'):
            with self.subTest(text=text):
                self.assertIsNone(buyer_command(text))
        self.assertEqual(buyer_command("prepare checkout"), "check")
        self.assertEqual(buyer_command("purchase status"), "purchase status")
        for question in QUESTIONS:
            self.assertEqual(buyer_command(question), "wallet")
        self.client.chat.completions.create.side_effect = None
        self.client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content='{"action":"check","reply":"Pay","updates":[]}'))])
        self.assertIn("CHAT_ACTION", self.chat("Pay now from my wallet"))
        self.assertEqual(self.checkout.mock_calls, [])

    def test_guidance_keeps_unconfigured_and_pending_states_truthful(self):
        self.workflow.checkout = None
        self.assertIn("not configured", self.chat(QUESTIONS[0]))
        self.workflow.checkout = self.checkout
        key = self.store.key("buyer", "wallet-information")
        state = self.state()
        state["pending_payment"] = {"id": "test-only"}
        self.store.save(key, state)
        self.assertIn("No new checkout or payment", self.chat(QUESTIONS[1]))
        self.assertEqual(self.checkout.mock_calls, [])

    def test_identity_secret_and_size_guards_still_precede_information_routing(self):
        before = self.state()
        for sender, session in (("", "wallet-information"), ("buyer", None)):
            reply = self.workflow.handle(sender, session, QUESTIONS[0])
            self.assertIn("sender and conversation/session ID are required", reply)
        self.assertIn("Do not send credentials", self.chat(QUESTIONS[0] + " private_key: " + "a" * 64))
        self.assertIn("Message too large", self.chat(QUESTIONS[0] + " " * 16000))
        self.assertEqual(before, self.state())
        self.client.chat.completions.create.assert_not_called()
        self.assertEqual(self.checkout.mock_calls, [])


class WalletProtocolTests(StoreTestMixin, IsolatedAsyncioTestCase):
    async def test_actual_chat_handler_preserves_session_and_answers_without_provider(self):
        client = rejected_client(403)
        checkout = Mock()
        workflow = Workflow(store=self.store, fetcher=FakeFetcher(), checkout=checkout,
                            conversation=ConversationInterpreter(client))
        ctx = SimpleNamespace(session=uuid4(), send=AsyncMock())
        with patch("tool_offer_agent.chat.asyncio.to_thread", new=execute_in_process):
            for question in QUESTIONS[:2]:
                await respond(ctx, "buyer", create_text_chat("@tool-offer-builder " + question), workflow)
                self.assertIn("Wallet guidance is available", ctx.send.call_args_list[-1].args[1].text())
        self.assertEqual(self.store.load(self.store.key("buyer", str(ctx.session)))["fields"], {})
        client.chat.completions.create.assert_not_called()
        self.assertEqual(checkout.mock_calls, [])
