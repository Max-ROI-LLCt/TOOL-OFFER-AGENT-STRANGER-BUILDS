import copy
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from tool_offer_agent.buyer_guidance import buyer_command
from tool_offer_agent.conversation import ConversationError, ConversationInterpreter, validate
from tool_offer_agent.workflow import Workflow
from tool_offer_agent.product_policy import output_risk
from tests.support import StoreTestMixin, FakeFetcher, INTAKE


class ConsolidatedRepairTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.language = Mock()
        self.language.interpret.return_value = {"action": "reply", "reply": "This is a proposed design, not an implemented API.", "updates": {}}
        self.workflow = Workflow(store=self.store, fetcher=FakeFetcher(), conversation=self.language)

    def chat(self, message, session="repair"):
        return self.workflow.handle("seller", session, message)

    def state(self):
        return self.store.load(self.store.key("seller", "repair"))

    def test_native_machine_contract_is_documented_not_introspection(self):
        response = self.chat("Explain the actual deployed MCP/REST interface, credentials and session isolation.")
        for expected in ("/mcp", "/api/machine/", "identity-bound", "separate", "not a live"):
            self.assertIn(expected, response)
        self.language.interpret.assert_not_called()

    def test_bare_transaction_commands_are_safe_and_consistent(self):
        for command in ("transaction summary", "transaction status"):
            response = self.chat(command)
            self.assertNotIn("Unknown commercial command", response)
            self.assertIn("No seller-side transaction", response)
            self.assertIn("purchase status", response)

    def test_seller_payment_question_is_not_fahce_revision(self):
        response = self.chat("How can my customers pay my seller subscription, rather than the previous FAHCE flow?")
        self.assertNotIn("No. A FAHCE evaluation is bound", response)
        self.assertIn("seller", response.casefold())

    def test_fictional_payment_audit_is_not_wallet_setup(self):
        message = "In this fictional payment-evidence audit, does a wallet approval prove delivery? Do not onboard me."
        self.assertIsNone(buyer_command(message))
        self.chat(message)
        self.language.interpret.assert_called_once()

    def test_complete_formatted_document_can_exceed_old_limit(self):
        text = "Product brief\n\n" + "- Proposed requirement, not implemented.\n" * 60
        result = validate({"action": "reply", "reply": text, "updates": {}}, "Give me a complete brief with line breaks.")
        self.assertEqual(result["reply"], text)

    def test_length_finish_is_never_complete(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="length", message=SimpleNamespace(content='{"action":"reply","reply":"unfinished'))])
        with self.assertRaises(ConversationError):
            ConversationInterpreter(client).interpret({"fields": {}}, "A complete offer, please.")
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_model_cannot_select_wallet_from_an_audit(self):
        with self.assertRaises(ConversationError):
            validate({"action": "wallet", "reply": "Wallet setup.", "updates": {}}, "Audit this fictional payment evidence.")

    def test_no_url_exercise_does_not_demand_url_or_save_model_facts(self):
        self.language.interpret.return_value = {"action": "update", "reply": "Proposed pricing only.", "updates": {"pricing": "$29"}}
        response = self.chat("Hypothetical pricing exercise: $29. I have no endpoint; do not change my intake.")
        self.assertNotIn("public API or MCP URL", response)
        self.assertNotIn("pricing", self.state()["fields"])

    def test_prelaunch_requirements_are_explicit_isolated_and_not_intake(self):
        before = copy.deepcopy(self.state())
        self.assertIn("pre-launch", self.chat("mode prelaunch").lower())
        self.chat("plan requirement: Only authenticated tenants can inspect their own tickets.")
        self.chat("plan decision: Monthly quota remains undecided.")
        self.chat("plan test R1: Another tenant cannot read this ticket.")
        state = self.state()
        self.assertEqual(state["fields"], before["fields"])
        self.assertEqual(state["revision"], before["revision"])
        self.assertEqual(len(state["planning"]["items"]), 3)
        self.assertEqual(state["planning"]["items"][2]["requirement_id"], "R1")
        self.assertNotIn("own tickets", self.chat("plan status", session="other"))
        self.assertNotIn("public API or MCP URL", self.chat("start"))
        self.assertIn("evidence", self.chat("draft limited"))

    def test_plan_fiction_is_separate_and_cannot_authorize_offer(self):
        self.chat("mode prelaunch")
        self.chat("plan exercise: Fictional participant Alice likes the proposed API.")
        response = self.chat("offer approve")
        self.assertIn("pre-launch", response)
        self.assertIsNone(self.state().get("approved_offer"))
        self.assertIn("fictional", self.chat("export plan").casefold())

    def test_plan_capacity_rejects_without_losing_existing_items(self):
        self.chat("mode prelaunch")
        for index in range(24):
            self.chat(f"plan requirement: Explicit requirement {index}.")
        before = self.state()["planning"]
        self.assertIn("limit", self.chat("plan requirement: One too many."))
        self.assertEqual(self.state()["planning"], before)

    def test_plan_test_must_reference_existing_requirement(self):
        self.chat("mode prelaunch")
        self.assertIn("existing requirement", self.chat("plan test R99: It should work."))
        self.assertEqual(self.state()["planning"]["items"], [])

    def test_prior_listing_repairs_and_legitimate_commands(self):
        for question in ("Explain the free customer experience.", "Give a concise preview of Draft v6.",
                         "What do you do for free? I do not want websites listed.", "I am a new customer. How do I start?",
                         "Do not give me a listing checklist."):
            with self.subTest(question=question):
                response = self.chat(question)
                self.assertNotIn("VerifyMCP", response)
        self.assertIn("api", self.chat("listing profile api").lower())
        self.assertIn("destinations", self.chat("listing checklist json"))
        self.chat(INTAKE)
        self.chat("draft limited")
        self.assertIn("destinations", self.chat("export listing"))

    def test_seller_rails_are_not_operational_billing(self):
        response = self.chat("payment options")
        data = json.loads(response)
        self.assertEqual(data["operational"], [])
        self.assertEqual(len(data["methods"]), 5)

    def test_stripe_and_metered_terms_do_not_create_billing_or_invent_rates(self):
        before = copy.deepcopy(self.state())
        response = self.chat("How do I handle billing for my customers with seller-managed Stripe at $29 plus metered overages? The overage rate is undecided.")
        self.assertIn("$29 + max(0, usage", response)
        self.assertIn("explicitly supplied overage price", response)
        self.assertIn("unprovided units, rates and terms remain undecided", response)
        self.assertIn("I do not create a Stripe account, charge your customers", response)
        self.assertEqual(self.state()["fields"], before["fields"])
        self.assertIsNone(self.state().get("approved_offer"))
        self.language.interpret.assert_not_called()

    def test_affiliate_or_paid_wrapper_permission_is_not_resale_authority(self):
        response = self.chat("Can my seller payment plan rely on affiliate or paid-wrapper permission as resale authorization?")
        self.assertIn("does not establish resale rights", response)
        self.assertIsNone(self.state().get("approved_offer"))
        self.assertEqual(json.loads(self.chat("payment options"))["operational"], [])

    def test_free_offer_keeps_attribution_and_authorization_boundaries(self):
        self.chat(INTAKE)
        self.chat("pricing: fully free; no paid tiers\npayment: none; no payment step")
        self.chat("draft limited")
        result = json.loads(self.chat("export json"))
        self.assertIn("fully free", json.dumps(result))
        self.assertIn("no payment step", json.dumps(result))
        self.assertIn("source", json.dumps(result))
        self.assertIsNone(self.state().get("approved_offer"))

    def test_final_output_rejects_known_claim_expansions(self):
        cases = [
            ("Contact help@example.com from the report.", "Extract contact details."),
            ("Customers can inspect any ticket.", "Describe GET /tickets/{id}."),
            ("Public documentation grants ordinary usage rights.", "Can I use this?"),
            ("The standard plan includes human review.", "Documentation conflicts about review."),
            ("Contact Alice for an interview.", "Alice is a fictional participant."),
            ("Upload real tenant reports for this experiment.", "Plan a test."),
        ]
        for reply, message in cases:
            with self.subTest(reply=reply):
                self.assertIsNotNone(output_risk(reply, {}, message))

    def test_safe_corrections_and_grounded_contacts_are_not_rejected(self):
        self.assertIsNone(output_risk("Contact help@example.com.", {}, "The supplied contact is help@example.com."))
        self.assertIsNone(output_risk("Do not claim customers can inspect every tenant's ticket.", {}, "Review scope."))
        self.assertIsNone(output_risk("Use synthetic reports; real reports need permission and redaction.", {}, "Plan a test."))

    def test_truncated_partial_is_labeled_and_retrievable(self):
        error = ConversationError("incomplete response")
        error.partial = "Partial document\n\nEnds before"
        self.language.interpret.side_effect = error
        response = self.chat("Write a complete brief.")
        self.assertIn("INCOMPLETE", response)
        retained = json.loads(self.chat("export incomplete"))
        self.assertFalse(retained["complete"])
        self.assertEqual(retained["text"], error.partial)
