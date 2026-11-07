from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock

from tool_offer_agent.buyer_guidance import buyer_command
from tool_offer_agent.workflow import Workflow
from tests.support import FakeFetcher, INTAKE, StoreTestMixin
from tests.test_fahce_checkout import FakeCheckout


FOLLOW_UP = (
    "Your opening message offered two paths — buyer setup, and review-and-approval steps — "
    "and stated that guidance does not spend money. Every trigger attempt since has returned "
    "an identical notice about results being bound to the record they were produced against; "
    "the onboarding documentation itself has never arrived.\n\n"
    "I'm accepting that standing offer now. Please deliver the buyer setup documentation: "
    "the steps a requesting agent follows to help a user create a payment account and complete "
    "verification through the x402 bridge for tooloffer.kinganlogic.com.\n\n"
    "If this channel can't deliver it, either confirm the delivery path is erroring on your side "
    "and list your exact available commands verbatim so the right one can be triggered, or send "
    "the instructions through the authorized transport you mentioned. Text only — nothing here "
    "spends money or modifies a stored record."
)


class BuyerGuideDeliveryTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.conversation = Mock()
        self.conversation.interpret.side_effect = AssertionError("Guidance must not need inference")
        self.checkout = FakeCheckout()
        self.fetcher = FakeFetcher()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, checkout=self.checkout,
                                 conversation=self.conversation)

    def chat(self, message):
        return self.workflow.handle("native-agent", "buyer-guide", message)

    def test_bare_commands_already_work_on_revision46(self):
        for message in ("wallet", "purchase guide"):
            self.assertIn("buyer wallet guide", self.chat(message))
        self.conversation.interpret.assert_not_called()

    def test_send_wallet_and_send_purchase_guide_are_deterministic(self):
        for message in ("send wallet", "Send wallet.", "please send wallet", "send purchase guide"):
            with self.subTest(message=message):
                self.assertIn("buyer wallet guide", self.chat(message))
        self.conversation.interpret.assert_not_called()
        self.assertEqual(self.checkout.calls, [])

    def test_exact_long_m2m_follow_up_delivers_instructions(self):
        reply = self.chat(FOLLOW_UP)
        self.assertIn("buyer wallet guide", reply)
        self.assertIn("Connect wallet — no payment", reply)
        self.assertIn("not create or fund wallets", reply)
        self.assertIn("not payment approval", reply)
        self.conversation.interpret.assert_not_called()
        self.assertEqual(self.checkout.calls, [])
        self.assertEqual(self.fetcher.calls, [])

    def test_guidance_request_with_previous_fahce_context_is_not_revision_question(self):
        reply = self.chat("Your previous FAHCE reply mentioned revised drafts. Could you send the wallet setup instructions for https://tooloffer.kinganlogic.com?")
        self.assertIn("buyer wallet guide", reply)
        self.assertNotIn("No. A FAHCE evaluation", reply)
        self.conversation.interpret.assert_not_called()

    def test_negative_and_quoted_requests_are_not_commands(self):
        for message in (
            "Do not send wallet instructions.", "Please don't send the purchase guide.",
            "Could you not send wallet instructions?", "I don't want the wallet guide.",
            "Could you not send wallet setup instructions?", "Do not show the wallet setup guide.",
            'Why did it say "send wallet"?', 'The old instruction was "Please send wallet."',
            "docs: https://example.com/send-wallet", "```\nPlease send wallet\n```",
            "Please send a payment from my wallet.", "Please send wallet funds.",
        ):
            with self.subTest(message=message):
                self.assertIsNone(buyer_command(message))

    def test_existing_draft_approval_and_checkout_remain_unchanged(self):
        self.chat(INTAKE)
        self.chat("draft limited")
        key = self.store.key("native-agent", "buyer-guide")
        state = self.store.load(key)
        state["fahce_checkout"] = {"url": "https://checkout.example.com/private", "status": "complete"}
        self.store.save(key, state)
        before = deepcopy(self.store.load(key))
        reply = self.chat("Please provide the buyer setup documentation.")
        self.assertIn("existing purchase", reply)
        self.assertEqual(self.store.load(key), before)
        self.assertEqual(self.checkout.calls, [])
        self.conversation.interpret.assert_not_called()

    def test_real_revision_question_keeps_evaluation_boundary(self):
        reply = self.chat("If I revise my draft after a FAHCE evaluation, does the previous result apply?")
        self.assertIn("Any actual field revision invalidates", reply)
        self.conversation.interpret.assert_not_called()
