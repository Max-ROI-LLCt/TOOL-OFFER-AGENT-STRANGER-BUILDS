from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock

from tool_offer_agent.buyer_guidance import buyer_command
from tool_offer_agent.workflow import Workflow
from tests.support import FakeFetcher, INTAKE, StoreTestMixin
from tests.test_fahce_checkout import FakeCheckout


class BuyerGuidanceTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.checkout = FakeCheckout()
        self.conversation = Mock()
        self.conversation.interpret.side_effect = AssertionError("Buyer commands must not need a model")
        self.workflow = Workflow(store=self.store, fetcher=FakeFetcher(), checkout=self.checkout, conversation=self.conversation)

    def chat(self, message, sender="buyer", session="new-user"):
        return self.workflow.handle(sender, session, message)

    def test_setup_questions_do_not_become_intake_or_create_checkout(self):
        for message in ("wallet", "/wallet", "Set up my buying wallet", "How do I connect my wallet?", "purchase guide", "How do I buy a FAHCE check?"):
            with self.subTest(message=message):
                reply = self.chat(message)
                self.assertIn("by Kingan Logic", reply)
                self.assertIn("Connect wallet — no payment", reply)
                self.assertIn("not payment approval", reply)
                self.assertIn("operator help", reply)
                self.assertIn("United States", reply)
                self.assertIn("authenticated US relay", reply)
                self.assertIn("UK-origin server requests", reply)
                self.assertIn("Relay location does not change buyer eligibility", reply)
        self.assertEqual(self.store.load(self.store.key("buyer", "new-user"))["fields"], {})
        self.assertEqual(self.checkout.calls, [])
        self.conversation.interpret.assert_not_called()

    def test_wallet_address_is_neither_an_intake_value_nor_model_history(self):
        self.chat("tool_url: https://api.example.com/")
        before = self.store.load(self.store.key("buyer", "new-user"))
        for prefix in ("", "wallet: ", "my buying wallet address is "):
            reply = self.chat(prefix + "0x" + "12" * 20)
            self.assertIn("address alone cannot authorize", reply)
        self.assertEqual(before, self.store.load(self.store.key("buyer", "new-user")))
        self.assertEqual(self.checkout.calls, [])

    def test_status_does_not_prepare_a_purchase_when_none_exists(self):
        for message in ("purchase status", "refresh purchase status", "get my FAHCE result"):
            self.assertIn("Nothing was prepared or purchased", self.chat(message))
        self.assertEqual(self.checkout.calls, [])

    def test_fresh_customer_prepares_once_and_existing_setup_preserves_purchase(self):
        self.chat(INTAKE)
        self.chat("draft limited")
        self.assertIn("0.15 USDC", self.chat("prepare checkout"))
        before = deepcopy(self.store.load(self.store.key("buyer", "new-user")))
        reply = self.chat("wallet")
        self.assertIn("existing private checkout", reply)
        self.assertIn("Do not start a second payment", reply)
        self.assertNotIn("choose Pay now", reply)
        after = self.store.load(self.store.key("buyer", "new-user"))
        for field in ("fields", "draft", "revision", "fahce_checkout"):
            self.assertEqual(before[field], after[field])
        self.checkout.phase = "response_received"
        self.assertIn("FAHCE returned result", self.chat("purchase status"))
        self.assertIn("FAHCE returned result", self.chat("get my FAHCE result"))
        self.assertEqual(len(self.checkout.calls), 1)

    def test_guidance_never_leaks_another_conversations_checkout(self):
        self.chat(INTAKE)
        self.chat("draft limited")
        self.chat("check")
        for sender, session in (("other", "new-user"), ("buyer", "other-session")):
            reply = self.chat("wallet", sender, session)
            self.assertNotIn("private-checkout-capability", reply)
            self.assertNotIn("existing purchase", reply)
        self.assertEqual(len(self.checkout.calls), 1)

    def test_unconfigured_wallet_guidance_never_offers_a_live_checkout(self):
        self.workflow.checkout = None
        reply = self.chat("wallet")
        self.assertIn("not configured", reply)
        self.assertNotIn("choose Pay now", reply)

    def test_embedded_instructions_are_not_buyer_commands(self):
        for message in ("docs: https://example.com/wallet", "payment: connect my wallet", "Do not prepare checkout", "What if I prepare checkout?", "wallet\npricing: USD 10"):
            self.assertIsNone(buyer_command(message))

    def test_pending_legacy_payment_does_not_offer_another_checkout(self):
        key = self.store.key("buyer", "new-user")
        state = self.store.load(key)
        state["pending_payment"] = {"id": "test-only"}
        self.store.save(key, state)
        self.assertIn("No new checkout or payment", self.chat("wallet"))
        self.assertEqual(self.checkout.calls, [])

    def test_model_receives_actual_bridge_configuration_not_legacy_transport_flag(self):
        self.conversation.interpret.side_effect = None
        self.conversation.interpret.return_value = {"action": "wallet", "reply": "Buyer guide", "updates": {}}
        self.assertIn("Connect wallet — no payment", self.chat("I need some guidance for a purchase"))
        context = self.conversation.interpret.call_args.args[0]
        self.assertEqual(context["runtime_capabilities"], {"machine_adapter": False, "wallet_checkout_configured": True,
            "direct_evaluation_configured": False, "existing_wallet_checkout": False, "automatic_spending": False})
        self.assertNotIn("runtime_capabilities", self.store.load(self.store.key("buyer", "new-user")))
        self.workflow.checkout = None
        self.assertIn("not configured", self.chat("I need some guidance for a purchase"))
        self.assertFalse(self.conversation.interpret.call_args.args[0]["runtime_capabilities"]["wallet_checkout_configured"])

    def test_capability_question_does_not_deny_the_configured_wallet_bridge(self):
        reply = self.chat("Can you help me pay for a FAHCE evaluation?")
        self.assertIn("transport is configured", reply)
        self.assertIn("Drafting is free", reply)
        self.assertIn("purchase guide", reply)
        self.assertIn("separate buyer-authorized", reply)
        self.assertIn("private checkout", reply)
        self.assertNotIn("pending configuration", reply)
        self.conversation.interpret.assert_not_called()
