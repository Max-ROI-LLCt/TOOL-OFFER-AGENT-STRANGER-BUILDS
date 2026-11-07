"""Outside-customer regression. Network/model/payment are controlled fakes."""

import copy
import json
from unittest import TestCase
from unittest.mock import Mock
from uagents_core.contrib.protocols.chat.cards import FormCardPayload, CustomCardPayload

from tests.support import FakeFetcher, INTAKE, StoreTestMixin, DOC_URL
from tool_offer_agent.chat import create_readiness_chat
from tool_offer_agent.customer_recovery import DIRECTORY, REFERENCES
from tool_offer_agent.documents import Document, DocumentError
from tool_offer_agent.guided_cards import valid_metadata
from tool_offer_agent.readiness import assess
from tool_offer_agent.workflow import Workflow

MAGAZINE = "https://www.ticketlens.com/en/magazine"
CUSTOMER = "regular people are customers who would use agents"
INVOCATION = "Users can use it as MCP to their agent or any other AI harness tool"
TRANSCRIPT = [
    "hello", "Look into this https://mcp.ticketlens.com/", "You can refer this: " + DIRECTORY,
    CUSTOMER + ", you can retry reading the link I sent earlier", "undecided", "Probably stripe",
    INVOCATION, "Using the URL itself", "build the draft", "Try this " + MAGAZINE, "build the draft",
]


class TicketFetcher(FakeFetcher):
    error_class = DocumentError

    def fetch(self, url):
        if url == DIRECTORY:
            self.calls.append(url)
            raise self.error_class("Documentation server did not return HTTP 200 (received HTTP 403).")
        if url == MAGAZINE:
            self.calls.append(url)
            return Document(url, url, ("TicketLens Magazine. Find travel tips and tricks for destinations worldwide. " * 60)[:4500], "text/html")
        return super().fetch(url)


class TicketLensAcceptance(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = TicketFetcher()
        self.language = Mock()
        self.language.interpret.side_effect = AssertionError("Unexpected intake model call")
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, conversation=self.language)

    def chat(self, text, sender="outside-tester", session="ticketlens", **kwargs):
        return self.workflow.handle(sender, session, text, **kwargs)

    def state(self):
        return self.store.load(self.store.key("outside-tester", "ticketlens"))

    def test_exact_ticketlens_replay(self):
        replies = [self.chat(text) for text in TRANSCRIPT]
        self.assertIn("an offer a buyer can review", replies[0])
        self.assertIn("HTTP 403", replies[2])
        self.assertIn(DIRECTORY, replies[3])
        self.assertIn("HTTP 403", replies[3])
        self.assertEqual(self.fetcher.calls.count(DIRECTORY), 3)
        self.assertIn("pricing", replies[3])
        self.assertIn("Which specific group", replies[3])
        self.assertIn("tentative", replies[5])
        self.assertIn("saved it under invocation rather than access", replies[6])
        self.assertIn("evidence insufficient", replies[9])
        self.assertIn("INCOMPLETE DRAFT", replies[10])
        self.assertIn("Draft v1", replies[10])
        self.assertNotIn("Draft v10", replies[10])
        self.language.interpret.assert_not_called()
        state = self.state()
        self.assertEqual(state["fields"]["customer"], CUSTOMER)
        self.assertEqual(state["fields"]["invocation"], INVOCATION)
        self.assertEqual(state["fields"]["payment"], "Probably stripe")
        self.assertEqual(state["draft"]["offer"]["payment_status"], "tentative_seller_statement")
        for name in ("capabilities", "inputs", "outputs"):
            self.assertEqual(state["draft"]["offer"][name], [])
        self.assertEqual(assess(state, "outside-tester", "test")["status"], "needs_information")
        self.assertIn("INCOMPLETE DRAFT", self.chat("buyer explanation"))
        self.assertIn("evidence insufficient", self.chat("status"))
        self.assertIsNone(state.get("fahce_checkout"))
        self.assertEqual(self.workflow.export_record(state)["source_documents"][0]["source_url"], MAGAZINE)

    def test_valid_fictional_api_not_blocked_and_versions_separate(self):
        response = self.chat(INTAKE)
        state = self.state()
        self.assertIn("Draft v1", response)
        self.assertEqual(state["draft"]["documentation_evidence"]["status"], "documented_for_review")
        self.assertGreater(state["draft"]["revision"], 0)
        self.chat("revise pricing: USD 0.03 per invocation")
        self.assertEqual(self.state()['draft']['draft_version'], 1)
        self.assertTrue(self.state()['outdated'])
        self.chat('draft')
        state = self.state()
        self.assertEqual(state["draft"]["draft_version"], 2)
        self.assertEqual(state["draft"]["revision"], self.state()["revision"])
        self.assertIn("USD 0.03", self.chat("export readable"))

    def test_failed_replacement_preserves_good_documents_and_draft(self):
        self.chat(INTAKE)
        old = self.state()
        self.chat("docs: " + DIRECTORY)
        self.chat("customer: Auditors, please retry the previous documentation")
        self.assertEqual(self.state()["documents"], old["documents"])
        self.assertEqual(self.state()["draft"], old["draft"])
        self.assertTrue(self.state()["outdated"])

    def test_selected_replacement_archives_original_sources(self):
        self.chat(INTAKE)
        old = self.state()["documents"]
        self.chat("docs: " + MAGAZINE)
        self.assertEqual(self.state()["document_history"][-1]["documents"], old)

    def test_recovery_form_wire_and_direct_selection(self):
        self.chat("tool_url: https://mcp.ticketlens.com/")
        reply = self.chat("docs: " + DIRECTORY)
        self.assertTrue(valid_metadata(reply.metadata))
        self.assertEqual(create_readiness_chat(reply).content[-1].type, "metadata")
        payload = json.loads(reply.metadata["card_payload"])
        FormCardPayload.model_validate(payload)
        selection = payload["submit_cta"]["selection"]
        response = self.chat(json.dumps({**selection, "choice": "1"}))
        self.assertIn("Read 1", response)
        self.assertEqual(self.fetcher.calls[-1], REFERENCES[0])
        self.assertEqual(self.state()["fields"]["docs"], [REFERENCES[0]])

    def test_recovery_planner_prose_selects_only_current_candidates(self):
        self.chat("docs: " + DIRECTORY)
        self.chat("Please select source 2")
        self.assertEqual(self.fetcher.calls[-1], REFERENCES[1])
        self.language.interpret.assert_not_called()

    def test_selection_schema_session_staleness_and_injection(self):
        self.chat(INTAKE)
        reply = self.chat("review intake")
        reply = self.chat(json.dumps(json.loads(reply.metadata["card_payload"])["approve_cta"]["selection"]))
        selection = json.loads(reply.metadata["card_payload"])["submit_cta"]["selection"]
        before = copy.deepcopy(self.state()["fields"])
        for extra in ({"field": "pricing", "value": "free", "check": "yes"}, {"field": "pricing", "value": "free\npayment: none"}, {"field": "check", "value": "yes"}):
            response = self.chat(json.dumps({**selection, **extra}))
            self.assertEqual(self.state()["fields"], before)
        escaped = json.dumps({**selection, "field": "access", "value": "sk-" + "x" * 24}).replace("sk-", "\\u0073k-")
        self.assertIn("Nothing was saved", self.chat(escaped))
        self.assertEqual(self.state()["fields"], before)
        wrong = self.chat(json.dumps({**selection, "field": "pricing", "value": "free"}), session="another")
        self.assertIn("another conversation", wrong)
        self.chat("customer: Billing platform developers")
        stale = self.chat(json.dumps({**selection, "field": "pricing", "value": "free"}))
        self.assertIn("stale", stale)

    def test_offer_review_is_not_commercial_approval_or_checkout(self):
        self.chat(INTAKE)
        reply = self.chat("review offer")
        self.assertTrue(valid_metadata(reply.metadata))
        self.assertEqual(reply.metadata["card_kind"], "custom")
        CustomCardPayload.model_validate(json.loads(reply.metadata["card_payload"]))
        self.assertIn("Seller-stated payment", reply.metadata["card_payload"])
        result = self.chat("confirm review")
        self.assertIn("No commercial approval", result)
        self.assertIsNone(self.state().get("approved_offer"))
        self.assertIsNone(self.state().get("fahce_checkout"))

    def test_incomplete_draft_without_successful_document_read_is_exportable(self):
        self.chat(INTAKE.replace(DOC_URL, DIRECTORY))
        before = len(self.fetcher.calls)
        response = self.chat("draft incomplete")
        self.assertIn("INCOMPLETE DRAFT", response)
        self.assertEqual(len(self.fetcher.calls), before)
        self.assertIsNotNone(self.state()["draft"])
        self.assertIn("TOOL_OFFER_EXPORT_V1", self.chat("export json"))

    def test_general_article_labels_do_not_become_mcp_schemas_or_spend_model_quota(self):
        self.workflow.extractor = Mock(side_effect=AssertionError("Unnecessary extraction"))
        self.fetcher.fetch = lambda url: Document(url, url,
            "Capability: Plan a holiday\nInputs: favorite city\nOutputs: travel advice", "text/html")
        response = self.chat(INTAKE.replace(DOC_URL, MAGAZINE))
        self.assertIn("INCOMPLETE DRAFT", response)
        self.assertEqual(self.state()["draft"]["offer"]["inputs"], [])
        self.assertEqual(self.state()["draft"]["offer"]["outputs"], [])
        self.workflow.extractor.extract.assert_not_called()

    def test_natural_language_form_correction_is_bounded_and_model_free(self):
        self.chat(INTAKE)
        self.chat("review intake")
        result = self.chat("Please change pricing to USD 7 per month")
        self.assertIn("Saved your pricing", result)
        self.assertEqual(self.state()["fields"]["pricing"], "USD 7 per month")
        self.assertTrue(self.state()["outdated"])
        self.language.interpret.assert_not_called()

    def test_export_before_any_draft_keeps_intake_and_failure_provenance(self):
        self.chat("docs: " + DIRECTORY)
        exported = json.loads(self.chat("export json"))
        self.assertIsNone(exported["draft"])
        self.assertEqual(exported["pending_intake"]["docs"], [DIRECTORY])
        self.assertEqual(exported["document_attempts"][-1]["result"], "fetch_failed")

    def test_published_starter_expected_question_is_current_and_model_free(self):
        from pathlib import Path
        prompt = "Help me turn my API documentation into a commercial offer draft."
        response = self.chat(prompt)
        homepage = (Path(__file__).resolve().parents[1] / "site/public/index.html").read_text()
        self.assertIn(prompt, homepage)
        self.assertIn("Or paste your public tool URL here to get started.", response)
        self.assertIn("Start with my tool", response)
        self.assertIn("no Tool Offer Agent checkout required", homepage)
        self.language.interpret.assert_not_called()

    def test_hosted_gate_rejects_lazy_circular_imports(self):
        from build_hosted import validate_import_graph
        with self.assertRaisesRegex(ValueError, "circular local imports"):
            validate_import_graph({"workflow.py": "def handle():\n    from guided_cards import select\n", "guided_cards.py": "def select():\n    from workflow import handle\n"})
        validate_import_graph({"workflow.py": "def handle():\n    from guided_cards import select\n", "guided_cards.py": "def select(workflow):\n    return workflow.selection_contains_secret('public value')\n"})

    def test_retry_duplicate_message_does_not_repeat_fetch(self):
        self.chat("tool_url: https://mcp.ticketlens.com/")
        self.chat("docs: " + DIRECTORY)
        message = CUSTOMER + ", you can retry reading the link I sent earlier"
        self.chat(message, message_id="controlled-retry-1")
        before = len(self.fetcher.calls)
        self.chat(message, message_id="controlled-retry-1")
        self.assertEqual(len(self.fetcher.calls), before)
