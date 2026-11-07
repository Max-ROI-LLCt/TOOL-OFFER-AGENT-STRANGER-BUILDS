import json
from unittest import TestCase
from unittest.mock import Mock, patch

from tool_offer_agent.documents import DocumentError
from tool_offer_agent.fahce import FahceClient, PENDING
from tool_offer_agent.workflow import Workflow
from tests.support import DOC_URL, INTAKE, TOOL_URL, FakeAuthorizedTransport, FakeFetcher, StoreTestMixin


class WorkflowTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = FakeFetcher()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher)

    def chat(self, text, sender="seller", session="conversation-1"):
        return self.workflow.handle(sender, session, text)

    def record(self):
        return json.loads(self.chat("export json"))

    def test_asks_only_missing_fields_and_retains_answers(self):
        reply = self.chat("customer: Accounting teams\npricing: free")
        self.assertIn("intake 2/7", reply)
        self.assertNotIn("Who is the intended customer", reply)
        self.assertEqual(self.fetcher.calls, [])
        self.chat(TOOL_URL)
        reply = self.chat(DOC_URL)
        self.assertIn("How should customers pay", reply)
        self.chat("none (free)")
        self.chat("public access, no key")
        reply = self.chat("POST /convert with CSV")
        self.assertIn("Convert CSV rows into JSON", reply)
        self.assertEqual(self.record()["draft"]["offer"]["pricing"], "free")

    def test_unlabelled_access_answer_with_embedded_url(self):
        self.chat(f"tool_url: {TOOL_URL}\ndocs: {DOC_URL}\ncustomer: Agent developers\npricing: USD 0.15\npayment: x402")
        answer = (
            "Public MCP discovery is available at https://fahce.kinganlogic.com/mcp "
            "without a pilot key. Paid determinations require no prior account or invitation: "
            "use an x402-v2-compatible client with a funded wallet."
        )
        reply = self.chat(answer)
        self.assertIn("intake 6/7", reply)
        state = self.store.load(self.store.key("seller", "conversation-1"))
        self.assertEqual(state["fields"]["access"], answer)
        self.assertEqual(state["fields"]["payment"], "x402")

    def test_unknown_identifier_field_is_still_rejected(self):
        reply = self.chat("unknown_field: value")
        self.assertIn("Unknown field", reply)
        self.assertIn("Intake 0/7", self.chat("status"))

    def test_complete_intake_exports_readable_and_json(self):
        reply = self.chat(INTAKE)
        self.assertIn("One proposed job", reply)
        record = self.record()
        self.assertFalse(record["draft_outdated"])
        self.assertEqual(record["draft"]["seller"]["source_urls"], [DOC_URL])
        self.assertIn("capabilities", record["draft"]["offer"])
        self.assertEqual(record["source_documents"][0]["source_url"], DOC_URL)
        self.assertIn("not authenticated", self.chat("export readable"))
        self.assertIn("FAHCE evaluation not requested", reply)

    def test_senders_and_sessions_are_both_isolated(self):
        self.chat(INTAKE)
        self.assertIn("No draft yet", self.chat("export", sender="other"))
        self.assertIn("No draft yet", self.chat("export", session="conversation-2"))
        self.chat("pricing: EUR 5 per job", sender="other")
        self.assertEqual(self.record()["draft"]["offer"]["pricing"], "USD 0.02 per invocation")

    def test_missing_session_cannot_fall_back(self):
        with self.assertRaises(ValueError):
            self.store.key("seller", "")
        self.assertIn("No shared fallback", self.chat(INTAKE, session=None))
        self.assertEqual(self.fetcher.calls, [])

    def test_draft_survives_workflow_restart(self):
        self.chat(INTAKE)
        restarted = Workflow(store=self.store, fetcher=FakeFetcher())
        self.assertEqual(json.loads(restarted.handle("seller", "conversation-1", "export")), self.record())

    def test_revision_saves_only_supplied_field_and_rebuild_is_explicit(self):
        self.chat(INTAKE)
        before = self.record()
        reply = self.chat("revise pricing: USD 1 per 100 rows")
        self.assertIn('Saved your pricing', reply)
        self.assertEqual(self.record()['draft'], before['draft'])
        self.chat('draft')
        after = self.record()
        self.assertGreater(after["draft"]["revision"], before["draft"]["revision"])
        self.assertEqual(after["draft"]["offer"]["pricing"], "USD 1 per 100 rows")
        self.assertEqual(before["draft"]["seller"], after["draft"]["seller"])
        self.assertEqual(len(self.fetcher.calls), 1)
        before_unlabelled = self.record()
        reply = self.chat("Please provide Part 1/4 only; there is no need to repeat the long documentation sections.")
        self.assertIn("No changes made", reply)
        self.assertEqual(self.record(), before_unlabelled)
        self.chat("job: Convert accounting exports to import-ready JSON")
        self.assertEqual(self.record()["draft"]["offer"]["job"], "Convert accounting exports to import-ready JSON")

    def test_unconfigured_check_has_exact_text_and_no_submission(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            self.assertEqual(self.chat("check"), PENDING)
            self.chat(INTAKE)
            before = self.record()["draft"]
            self.assertEqual(self.chat("check"), PENDING)
            self.assertEqual(self.record()["draft"], before)

    def test_doc_failure_preserves_previous_export_with_stale_marker(self):
        self.chat(INTAKE)
        before = self.record()["draft"]
        self.fetcher.fail = True
        reply = self.chat("docs: https://docs.example.com/new.json")
        self.assertIn("preserved", reply)
        self.assertNotIn("sensitive", reply)
        record = self.record()
        self.assertTrue(record["draft_outdated"])
        self.assertEqual(record["draft"], before)
        self.assertIn("PREVIOUS DRAFT", self.chat("export readable"))
        self.fetcher.fail = False
        self.chat("retry")
        self.assertFalse(self.record()["draft_outdated"])
        self.assertEqual(self.record()["draft"]["seller"]["source_urls"], ["https://docs.example.com/new.json"])

    def test_only_explicit_reextract_reprocesses_saved_documents(self):
        self.fetcher.text = 'Our API converts CSV records into JSON. Send CSV data in an HTTP request.'
        self.chat(INTAKE)
        before = self.record()
        extractor = Mock()
        extractor.extract.return_value = {key: [] for key in ('capabilities', 'inputs', 'outputs', 'limitations', 'commercial_terms')}
        self.workflow.extractor = extractor
        self.chat('draft')
        extractor.extract.assert_not_called()
        self.chat('retry')
        extractor.extract.assert_not_called()
        self.chat('reextract')
        extractor.extract.assert_called_once_with(before['source_documents'], job=None, invocation=before['draft']['offer']['invocation_instructions'])
        self.assertEqual(len(self.fetcher.calls), 1)
        self.assertGreater(self.record()['draft']['revision'], before['draft']['revision'])
        self.assertEqual(self.record()['draft']['offer']['job'], before['draft']['offer']['job'])

    def test_model_failure_preserves_draft_and_recovers(self):
        self.chat(INTAKE)
        before = self.record()["draft"]
        extractor = Mock()
        extractor.extract.side_effect = RuntimeError("sensitive-model-error")
        self.workflow.extractor = extractor
        self.assertNotIn("sensitive", self.chat("pricing: USD 1 per call"))
        self.assertEqual(self.record()["draft"], before)
        self.workflow.extractor = None
        self.chat("retry")
        self.assertEqual(self.record()["draft"]["offer"]["pricing"], "USD 1 per call")

    def test_extraction_error_code_preserves_draft_without_leaking_details(self):
        from tool_offer_agent.drafting import ExtractionError
        self.chat(INTAKE)
        before = self.record()['draft']
        extractor = Mock()
        extractor.extract.side_effect = ExtractionError('MODEL_TIMEOUT')
        self.workflow.extractor = extractor
        reply = self.chat('pricing: USD 2')
        self.assertIn('MODEL_TIMEOUT', reply)
        self.assertIn('Report this code', reply)
        self.assertEqual(self.record()['draft'], before)
        self.assertIn('draft limited', self.chat('retry'))
        self.assertIn('draft limited', self.chat('draft'))
        self.assertEqual(extractor.extract.call_count, 1)
        limited = self.chat('draft limited')
        self.assertIn('LIMITED deterministic extraction only', limited)
        record = self.record()['draft']
        self.assertEqual(record['extraction_mode'], 'deterministic_limited')
        self.assertEqual(record['offer']['pricing'], 'USD 2')
        self.assertEqual(extractor.extract.call_count, 1)
        self.assertEqual(before['offer']['pricing'], 'USD 0.02 per invocation')

    def test_all_exact_starter_prompts_are_safe_with_and_without_prior_draft(self):
        from tool_offer_agent.workflow import STARTER_PROMPTS
        self.assertEqual(len(STARTER_PROMPTS), 4)
        for prompt in STARTER_PROMPTS:
            reply = self.chat(prompt)
            self.assertNotIn('URL contains unsafe characters', reply)
            self.assertNotIn('Document extraction failed', reply)
        self.assertEqual(self.fetcher.calls, [])
        self.chat(INTAKE)
        before = self.record()
        for prompt in STARTER_PROMPTS:
            self.assertTrue(self.chat(prompt).strip())
        after = self.record()
        self.assertEqual(before['draft'], after['draft'])
        self.assertEqual(before['approved_offer'], after['approved_offer'])
        self.assertEqual(len(self.fetcher.calls), 1)

    def test_document_safety_failure_has_actionable_recovery(self):
        self.fetcher.fetch = Mock(side_effect=DocumentError("Documentation exceeds the size limit."))
        reply = self.chat(INTAKE)
        self.assertIn("size limit", reply)
        self.assertIn("revise docs:", reply)
        self.assertIn("Intake 7/7", self.chat("status"))

    def test_initial_fetch_failure_retains_intake(self):
        self.fetcher.fail = True
        self.chat(INTAKE)
        self.assertIn("Intake 7/7", self.chat("status"))
        self.fetcher.fail = False
        self.chat("retry")
        self.assertEqual(self.record()["draft"]["seller"]["tool_url"], TOOL_URL)

    def test_unsafe_input_is_atomic(self):
        self.chat(INTAKE)
        before = self.record()
        self.chat("pricing: USD 99\ndocs: http://127.0.0.1/secrets")
        self.assertEqual(self.record(), before)
        self.chat("api_key: sk-thisisatestsecretvalueonly")
        self.chat("private key: test key must not be accepted")
        self.chat("a" * 64)
        self.assertEqual(self.record(), before)
        self.assertNotIn("sk-thisisatestsecretvalueonly", self.store.load(self.store.key("seller", "conversation-1")).__repr__())

    def test_name_and_reset(self):
        self.workflow.name = "Custom Agent"
        self.assertIn("Custom Agent", self.chat("start"))
        self.chat(INTAKE)
        self.assertEqual(self.record()["agent_name"], "Custom Agent")
        self.chat("reset")
        self.assertIn("No draft yet", self.chat("export"))

    def test_doc_refresh_invalidates_check(self):
        self.workflow.fahce = FahceClient(FakeAuthorizedTransport())
        self.chat(INTAKE)
        self.chat("check")
        self.fetcher.text = self.fetcher.text.replace("1000 rows", "500 rows")
        self.chat("refresh docs")
        self.assertEqual(self.record()["fahce"]["status"], "not_requested")
        self.assertIn("500 rows", str(self.record()["draft"]["offer"]["limitations"]))

    def test_returned_check_is_exposed_and_revision_invalidates_it(self):
        transport = FakeAuthorizedTransport()
        self.workflow.fahce = FahceClient(transport)
        self.chat(INTAKE)
        reply = self.chat("check")
        self.assertIn("TEST FIXTURE ONLY", reply)
        self.assertIn("receipt_reference", reply)
        self.assertFalse(self.record()["fahce"]["result"]["verification"]["verified"])
        self.chat("check")
        self.chat("draft")
        self.chat("retry")
        self.chat("check")
        self.assertEqual(len(transport.calls), 1)
        self.chat("job: Convert one month's CSV ledger to JSON")
        self.assertEqual(self.record()["fahce"]["status"], "not_requested")
        self.chat("check")
        self.assertEqual(len(transport.calls), 2)
        self.assertNotEqual(transport.calls[0][2], transport.calls[1][2])
        self.assertNotEqual(transport.calls[0][1]["candidate_output"], transport.calls[1][1]["candidate_output"])

    def test_failed_paid_attempt_blocks_retries_even_after_revision_restart(self):
        transport = FakeAuthorizedTransport()
        transport.fail = True
        self.workflow.fahce = FahceClient(transport)
        self.chat(INTAKE)
        before = self.record()["draft"]
        reply = self.chat("check")
        self.assertIn("reconciliation", reply)
        self.assertNotIn("sensitive", reply)
        self.assertEqual(self.record()["draft"], before)
        self.chat("pricing: USD 1 per call")
        restarted = Workflow(store=self.store, fetcher=self.fetcher, fahce=FahceClient(transport))
        self.assertIn("no new payment", restarted.handle("seller", "conversation-1", "check"))
        self.assertIn("reconciliation", self.chat("reset"))
        self.assertEqual(len(transport.calls), 1)

    def test_received_invalid_response_is_not_a_success(self):
        transport = FakeAuthorizedTransport()
        transport.mutate = lambda body: body.update(schema="incorrect")
        self.workflow.fahce = FahceClient(transport)
        self.chat(INTAKE)
        self.assertIn("did not complete safely", self.chat("check"))
        self.assertNotIn("receipt_reference", self.record()["fahce"])
