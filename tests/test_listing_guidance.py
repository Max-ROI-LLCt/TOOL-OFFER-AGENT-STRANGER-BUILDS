from copy import deepcopy
from datetime import date
import json
from unittest import TestCase
from unittest.mock import Mock

from tool_offer_agent.listing_guidance import DESTINATIONS, OFFER, build_checklist
from tool_offer_agent.workflow import Workflow
from tests.support import FakeFetcher, INTAKE, StoreTestMixin


class ListingGuidanceTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = FakeFetcher()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher)

    def chat(self, message, sender="seller", session="one"):
        return self.workflow.handle(sender, session, message)

    def state(self):
        return self.store.load(self.store.key("seller", "one"))

    def test_once_offered_and_accepted_across_restart_without_changing_offer(self):
        reply = self.chat(INTAKE)
        self.assertIn(OFFER, reply)
        before = deepcopy(self.state())
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher)
        checklist = self.chat("Yes please!")
        self.assertTrue(checklist.startswith("Listing preparation checklist"))
        self.assertIn("OpenAPI REST documentation", checklist)
        after = self.state()
        for key in ("draft", "fields", "revision", "check"):
            self.assertEqual(before[key], after[key])
        self.assertNotIn(OFFER, self.chat("draft"))
        self.assertEqual(len(self.fetcher.calls), 1)

    def test_decline_is_persisted_and_does_not_nag(self):
        self.chat(INTAKE)
        self.assertIn("No problem", self.chat("not now"))
        self.chat("pricing: $25")
        self.assertNotIn(OFFER, self.chat("draft limited"))
        self.assertTrue(self.state()["listing_checklist"]["declined"])
        self.assertIn("Listing preparation checklist", self.chat("checklist"))

    def test_bare_yes_is_not_global_or_cross_session_acceptance(self):
        self.chat(INTAKE)
        self.assertNotIn("Listing preparation checklist", self.chat("yes", session="other"))
        self.assertNotIn("Listing preparation checklist", self.chat("yes", sender="other"))
        self.chat("status")
        self.assertIn("Listing preparation checklist", self.chat("yes"))

    def test_natural_request_and_profile_work_without_language_model(self):
        for question in ("Where should I list my tool?", "Can I get a high-value checklist?", "Which channels should I promote this on?"):
            self.assertIn("Listing preparation checklist", self.chat(question))
        self.assertEqual(self.fetcher.calls, [])
        self.chat("listing profile api")
        plan = json.loads(self.chat("listing checklist json"))
        self.assertEqual(plan["tool_type"], "api")
        self.assertEqual(plan["destinations"][0]["id"], "openapi")
        self.assertNotIn("verifymcp", [item["id"] for item in plan["destinations"]])
        self.assertEqual(plan["publication_status"], "not_verified")

    def test_mcp_priority_and_dependency_are_both_explicit(self):
        self.chat("listing checklist for my MCP server")
        plan = json.loads(self.chat("listing checklist json"))
        self.assertEqual(plan["destinations"][0]["id"], "verifymcp")
        self.assertEqual(plan["destinations"][0]["depends_on"], ["mcp_registry"])
        self.assertEqual(plan["tool_type_basis"], "seller_declared")
        self.assertIn("official MCP Registry", " ".join(plan["execution_order"]))

    def test_agent_profile_does_not_pretend_to_be_mcp(self):
        self.chat("listing profile agent")
        plan = json.loads(self.chat("listing checklist json"))
        self.assertEqual(plan["destinations"][0]["id"], "agentverse")
        self.assertNotIn("mcp_registry", [item["id"] for item in plan["destinations"]])

    def test_bazaar_is_always_conditional_and_smithery_excluded(self):
        self.chat("listing profile api")
        self.chat("payment: x402 on Base")
        plan = json.loads(self.chat("listing checklist json"))
        bazaar = next(item for item in plan["destinations"] if item["id"] == "bazaar")
        self.assertEqual(bazaar["applicability"], "conditional_x402_eligibility")
        self.assertNotIn("smithery", [item["id"] for item in plan["destinations"]])
        self.assertEqual(plan["excluded"][0]["id"], "smithery")
        self.assertEqual(plan["status"], "preparation_only")
        self.assertTrue(all(item["status"] in {"preparation_only", "recheck_required"} for item in plan["destinations"]))

    def test_export_binds_guidance_and_keeps_selection_unpublished(self):
        self.chat(INTAKE)
        self.chat("distribution select VerifyMCP, Glama")
        self.workflow.conversation = Mock()
        self.chat("Actually change the price to $25.")
        record = json.loads(self.chat("export listing"))
        self.assertEqual(record["distribution"]["selected_destinations"], ["VerifyMCP", "Glama"])
        self.assertEqual(record["distribution"]["status"], "not_published")
        self.assertEqual(record["listing_checklist"]["offer_revision"], self.state()["revision"])
        self.assertTrue(record["listing_checklist"]["draft_outdated"])
        self.assertNotIn(OFFER, self.chat("export readable"))

    def test_listing_named_in_field_value_is_saved_as_intake(self):
        self.chat("access: See VerifyMCP or Bazaar for public docs?")
        self.assertEqual(self.state()["fields"]["access"], "See VerifyMCP or Bazaar for public docs?")

    def test_invalid_profile_does_not_change_the_saved_profile(self):
        self.chat("listing profile api")
        self.assertIn("Choose listing profile", self.chat("listing profile unicorn"))
        self.assertEqual(self.state()["listing_profile"], "api")

    def test_model_can_choose_prepared_guidance_without_inventing_links(self):
        language = Mock()
        language.interpret.return_value = {"action": "listing checklist", "reply": "unused invented directories", "updates": {}}
        workflow = Workflow(store=self.store, fetcher=self.fetcher, conversation=language)
        reply = workflow.handle("seller", "one", "Help me get discovered")
        self.assertIn("VerifyMCP", reply)
        self.assertNotIn("invented directories", reply)

    def test_knowledge_expiry_and_generated_plans_do_not_mutate_catalog(self):
        first = build_checklist({"fields": {}, "listing_profile": "mcp"}, today=date(2026, 10, 31))
        self.assertFalse(first["knowledge_expired"])
        first["destinations"][0]["name"] = "tampered"
        expired = build_checklist({"fields": {}}, today=date(2026, 12, 1))
        self.assertTrue(expired["knowledge_expired"])
        self.assertTrue(all(item["status"] == "recheck_required" for item in expired["destinations"]))
        self.assertEqual(DESTINATIONS[0]["name"], "OpenAPI REST documentation")
        self.assertTrue(all(item["sources"] and item["last_checked"] for item in expired["destinations"]))
