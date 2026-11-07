"""Offline routing regressions reconstructed from the revision-45 incident report."""

from copy import deepcopy
import json
from unittest import TestCase
from unittest.mock import Mock

from tool_offer_agent.conversation import ConversationError, validate
from tool_offer_agent.listing_guidance import handle_listing_request
from tool_offer_agent.workflow import Workflow
from tests.support import FakeFetcher, INTAKE, StoreTestMixin


UNRELATED_MESSAGES = (
    "Explain the free customer experience, not a listing checklist.",
    "Give me a concise preview of Draft v6, not a listing checklist.",
    "What do you do for free? I don't want a checklist of websites to list on.",
    "What do you do for free? I don't want websites listed.",
    "I'm a new customer. What can you do for me for free, and how do I start?",
    "What is the best way to list my saved draft inputs?",
    "Please list the free features you provide.",
    "Explain what the listing checklist command does; don't run it.",
    "Do not show me a listing checklist.",
    "Don't give me a checklist.",
    "I don’t want a directory checklist.",
    "No listing checklist, please.",
    "Instead of a listing checklist, explain my offer.",
    "Without listing any websites, explain the free customer experience.",
    "Never recommend marketplaces or directories.",
    "Which directory stores my exports?",
    "What is VerifyMCP?",
    "Where is the checklist mentioned in Draft v6?",
    "Can you explain the word enlistment?",
    "Don't export listing; just explain what that command means.",
    "What does listing profile mcp mean?",
    "Show me a checklist of the facts missing from my draft.",
)


class ListingIntentRegressionTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.language = Mock()
        self.language.interpret.return_value = {
            "action": "reply", "reply": "A concise answer to your product question.", "updates": {},
        }
        self.fetcher = FakeFetcher()
        self.checkout = Mock()
        self.workflow = Workflow(
            store=self.store, fetcher=self.fetcher, conversation=self.language,
            checkout=self.checkout,
        )

    def state(self, session="existing"):
        return self.store.load(self.store.key("customer", session))

    def seed_draft_v6(self):
        self.workflow.handle("customer", "existing", INTAKE)
        state = self.state()
        state["revision"] = 6
        state["draft"]["revision"] = 6
        state["check"] = {"historical_result": "preserve"}
        state["fahce_checkout"] = {"id": "historical-checkout"}
        self.store.save(self.store.key("customer", "existing"), state)
        self.language.reset_mock()
        return deepcopy(state)

    def assert_conversation(self, message, session):
        before = self.state(session)
        self.language.reset_mock()
        reply = self.workflow.handle("customer", session, message)
        self.assertEqual(reply, "A concise answer to your product question.")
        self.language.interpret.assert_called_once()
        self.assertEqual(self.language.interpret.call_args.args[1], message)
        after = self.state(session)
        for field in ("fields", "documents", "draft", "revision", "check", "fahce_checkout", "restrictions"):
            self.assertEqual(after.get(field), before.get(field), field)
        self.assertFalse(after.get("listing_checklist", {}).get("viewed"))
        self.assertEqual(self.checkout.mock_calls, [])

    def test_existing_conversation_free_customer_experience(self):
        self.seed_draft_v6()
        self.assert_conversation(UNRELATED_MESSAGES[0], "existing")

    def test_existing_conversation_concise_draft_v6_preview(self):
        self.seed_draft_v6()
        self.assert_conversation(UNRELATED_MESSAGES[1], "existing")

    def test_fresh_conversation_free_experience_with_no_websites(self):
        for message in UNRELATED_MESSAGES[2:4]:
            with self.subTest(message=message):
                self.assert_conversation(message, message)
        self.assertEqual(self.fetcher.calls, [])

    def test_fresh_customer_onboarding(self):
        self.assert_conversation(UNRELATED_MESSAGES[4], "fresh-onboarding")
        self.assertEqual(self.fetcher.calls, [])

    def test_negative_instructions_and_incidental_mentions_are_conversational(self):
        for message in UNRELATED_MESSAGES[5:]:
            with self.subTest(message=message):
                self.assert_conversation(message, message)

    def test_routing_does_not_create_listing_state_for_unrelated_messages(self):
        for message in UNRELATED_MESSAGES:
            with self.subTest(message=message):
                state = {"fields": {}}
                self.assertIsNone(handle_listing_request(state, message))
                self.assertEqual(state, {"fields": {}})

    def test_bad_model_listing_actions_cannot_override_current_user_intent(self):
        self.seed_draft_v6()
        for action in ("listing checklist", "export listing"):
            for message in UNRELATED_MESSAGES[:5]:
                with self.subTest(action=action, message=message):
                    self.language.interpret.return_value = {
                        "action": action, "reply": "unrequested model listing output", "updates": {},
                    }
                    before = self.state()
                    self.language.reset_mock()
                    reply = self.workflow.handle("customer", "existing", message)
                    self.language.interpret.assert_called_once()
                    self.assertNotIn("Listing preparation checklist", reply)
                    self.assertNotIn("unrequested model listing output", reply)
                    self.assertIn("kept your offer unchanged", reply)
                    self.assertEqual(self.state()["draft"], before["draft"])
                    self.assertEqual(self.state()["fahce_checkout"], before["fahce_checkout"])
        self.assertEqual(self.checkout.mock_calls, [])

    def test_model_action_validation_requires_matching_listing_intent(self):
        for action in ("listing checklist", "export listing"):
            for message in UNRELATED_MESSAGES:
                with self.subTest(action=action, message=message):
                    with self.assertRaises(ConversationError):
                        validate({"action": action, "reply": "unused", "updates": {}}, message)

    def test_explicit_and_natural_listing_checklists_still_work(self):
        for command in (
            "listing checklist", "checklist", "Listing checklist!", "/listing checklist",
            "Where should I list my tool?", "Can I get a high-value checklist?",
            "Which channels should I promote this on?", "Help me get discovered",
            "Please show me a listing checklist.", "Recommend directories for my API.",
            "listing checklist for my MCP server",
        ):
            with self.subTest(command=command):
                reply = self.workflow.handle("customer", command, command)
                self.assertTrue(reply.startswith("Listing preparation checklist"))
        self.language.interpret.assert_not_called()
        self.assertEqual(self.checkout.mock_calls, [])
        self.assertEqual(self.fetcher.calls, [])

    def test_profiles_structured_checklist_and_export_commands_still_work(self):
        self.seed_draft_v6()
        for profile in ("mcp", "api", "agent", "unknown"):
            with self.subTest(profile=profile):
                reply = self.workflow.handle("customer", "existing", "listing profile " + profile)
                self.assertIn("Listing preparation checklist", reply)
                structured = json.loads(self.workflow.handle("customer", "existing", "listing checklist json"))
                self.assertEqual(structured["tool_type"], profile)
        exported = json.loads(self.workflow.handle("customer", "existing", "export listing"))
        self.assertIn("listing_checklist", exported)
        self.assertEqual(exported["distribution"]["status"], "not_published")
        self.language.interpret.assert_not_called()
        self.assertEqual(self.checkout.mock_calls, [])

    def test_question_cannot_be_treated_as_pending_consent(self):
        self.seed_draft_v6()
        self.assert_conversation("Yes, but what do you do for free? No checklist please.", "existing")
        self.assert_conversation("yes", "existing")

    def test_direct_acceptance_still_requires_a_pending_offer(self):
        self.seed_draft_v6()
        reply = self.workflow.handle("customer", "existing", "yes please")
        self.assertIn("Listing preparation checklist", reply)
        self.language.interpret.assert_not_called()
        self.assert_conversation("yes please", "unrelated-session")
