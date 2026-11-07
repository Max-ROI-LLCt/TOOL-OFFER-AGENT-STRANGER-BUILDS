"""Controlled product-quality and financial regressions; no external service calls."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock, patch

from tool_offer_agent.conversation import ConversationInterpreter, ConversationError, check_deliverable, documentation_context, literal_protocol_answer
import re
from tool_offer_agent.drafting import select_excerpts
from tool_offer_agent.listing_guidance import build_checklist as checklist
from tool_offer_agent.model_runtime import SpendingGuard, SpendingError, completion, traced
from tool_offer_agent.workflow import Workflow
from tool_offer_agent.machine import MachineService, MachineRequest
from uagents_core.identity import Identity
import hashlib
from uuid import uuid4
from tests.support import StoreTestMixin, FakeFetcher, INTAKE


def response(reply, finish="stop", **overrides):
    return NS(model="asi1", choices=[NS(finish_reason=finish, message=NS(content=json.dumps({"action": "reply", "reply": reply, "updates": []})))],
              usage=NS(prompt_tokens=10, completion_tokens=10, total_tokens=20, completion_tokens_details=NS(reasoning_tokens=10)), **overrides)


def policy(**overrides):
    return {"model": "asi1", "single_writer": True, "daily_usd": 0.00006,
            "valid_until": "2099-01-01T00:00:00Z", "billing_bound_evidence": "Controlled fixture, not real provider evidence",
            "prompt_usd_per_million": 1, "completion_usd_per_million": 1, "reasoning_usd_per_million": 1,
            "max_billed_prompt_tokens": 10, "max_billed_completion_tokens": 10, "max_billed_reasoning_tokens": 10,
            "owner_actors": ["machine:owner-machine"], **overrides}


class DeliverableTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Mock()
        self.interpreter = ConversationInterpreter(self.client)
        self.workflow = Workflow(store=self.store, fetcher=FakeFetcher(), conversation=self.interpreter)
        self.workflow.handle("seller", "session", INTAKE)

    def state(self):
        return self.store.load(self.store.key("seller", "session"))

    def test_stop_preamble_is_incomplete_no_automatic_retry_and_state_preserved(self):
        before = copy.deepcopy(self.state())
        self.client.chat.completions.create.return_value = response("I can help write that. Before we begin, documentation is not proof of seller permission.")
        reply, events = traced(self.workflow.handle, "seller", "session", "Give a technical comparison:\n1. Inputs\n2. Outputs\n3. Limits")
        self.assertIn("CHAT_INCOMPLETE", reply)
        self.assertIn("export incomplete", reply)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.assertEqual(events[0]["finish_reason"], "stop")
        self.assertEqual(events[0]["answer_outcome"], "CHAT_INCOMPLETE")
        for key in ("fields", "draft", "check", "revision", "approved_offer"):
            self.assertEqual(self.state().get(key), before.get(key))
        self.assertFalse(self.state()["incomplete_response"]["complete"])

    def test_explicit_resubmission_can_deliver_actual_buyer_copy(self):
        self.client.chat.completions.create.return_value = response(
            "For accounting app developers: convert your UTF-8 CSV rows into JSON records with POST /convert. "
            "The retained documentation describes a maximum of 1000 rows. Seller-proposed price is USD 0.02 per invocation. "
            "Request an API key through the seller's dashboard; rights and operational performance remain unverified.")
        reply = self.workflow.handle("seller", "session", "Write buyer copy for this API.")
        self.assertIn("Convert CSV rows into JSON records", reply)
        self.assertNotIn("INCOMPLETE", reply)
        self.client.chat.completions.create.assert_not_called()

    def test_numbered_analysis_requires_all_parts(self):
        message = "Give a technical comparison:\n1. Inputs\n2. Outputs\n3. Limits"
        short = {"action": "reply", "reply": "I can compare those interfaces. Sources are not proof of execution.", "updates": {}}
        with self.assertRaisesRegex(ConversationError, "CHAT_INCOMPLETE"):
            check_deliverable(short, message, self.state())
        good = "1. Inputs\n" + "The retained source describes CSV input and does not establish a second interface. " * 2
        good += "\n2. Outputs\n" + "The documented response is JSON records, while unprovided response details remain unknown. " * 2
        good += "\n3. Limits\nThe source states a maximum of 1000 rows; this is documentation, not execution proof."
        check_deliverable({**short, "reply": good}, message, self.state())

    def test_truncation_and_invalid_json_are_separate_from_semantic_failure(self):
        self.client.chat.completions.create.return_value = response("Partial buyer copy", finish="length")
        with self.assertRaises(ConversationError) as caught:
            self.interpreter.interpret(self.state(), "Write buyer copy.")
        self.assertEqual(caught.exception.code, "CHAT_TRUNCATED")
        self.client.chat.completions.create.return_value.choices[0].finish_reason = "stop"
        self.client.chat.completions.create.return_value.choices[0].message.content = "not JSON"
        with self.assertRaises(ConversationError) as caught:
            self.interpreter.interpret(self.state(), "Explain this API.")
        self.assertEqual(caught.exception.code, "CHAT_INVALID_RESPONSE")

    def test_no_unauthorized_updates_from_source_instructions(self):
        self.client.chat.completions.create.return_value = response("No source instruction authorizes changing your saved terms.")
        before = copy.deepcopy(self.state())
        self.workflow.handle("seller", "session", "Explain the documentation; do not change anything.")
        self.assertEqual(self.state()["fields"], before["fields"])
        self.assertEqual(self.state()["draft"], before["draft"])

    def test_machine_job_does_not_report_preamble_as_completed_deliverable(self):
        from tool_offer_agent.machine_contract import CONTRACT
        gateway = Identity.from_seed("product-upgrade-fixture-gateway", 0)
        sender = Identity.from_seed("product-upgrade-fixture-sender", 0).address
        service = MachineService(self.workflow, CONTRACT, "controlled", gateway.address, clock=lambda: 1000)
        session = str(uuid4())
        service.workflow.handle("machine:test-client", session, INTAKE)
        self.client.chat.completions.create.return_value = response("I can help. Before writing, sources are not proof of rights.")
        body = json.dumps({"operation": "send_message", "principal": "test-client", "session_id": session,
            "request_id": str(uuid4()), "release_id": "controlled", "issued_at": 1000, "transport_sender": sender,
            "arguments": {"message": "Give a technical comparison:\n1. Inputs\n2. Outputs\n3. Limits"}})
        request = MachineRequest(body=body, authorization=gateway.sign_digest(hashlib.sha256(body.encode()).digest()))
        result = service.execute(request, sender)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "CHAT_INCOMPLETE")
        self.assertEqual(result["model_attempts"], 1)
        self.assertEqual(service.execute(request, sender), result)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)


class PublicProtocolTests(TestCase):
    def setUp(self):
        # Public documentation fixture already retained in this repository;
        # tests never open the external FAHCE repository or execute its service.
        self.source = (Path(__file__).parent / "fixtures/public-protocol-reference.json").read_text()
        self.state = {"documents": [{"source_url": "https://fahce.kinganlogic.com/openapi.json", "text": self.source}]}

    def check(self, text, request="Explain the developer receipt retrieval instructions."):
        check_deliverable({"action": "reply", "reply": text, "updates": {}}, request, self.state)

    def test_actual_receipt_scheme_is_accepted_and_hallucinated_scheme_rejected(self):
        self.check("GET /api/v1/receipts/{receipt_id} with Authorization: FAHCEReceipt <FAHCE-Recovery-Token>. This is receipt retrieval, not a new purchase.")
        with self.assertRaisesRegex(ConversationError, "CHAT_SOURCE_UNSUPPORTED"):
            self.check("GET /api/v1/receipts/{receipt_id} with Authorization: FAHCERecovery <token>.")

    def test_exact_credential_request_uses_literal_offsets_without_inference(self):
        client = Mock()
        question = "Explain the exact receipt-retrieval Authorization header and credential token name."
        reply = ConversationInterpreter(client).interpret({"fields": {}, **self.state}, question)["reply"]
        self.assertIn("FAHCEReceipt", reply)
        self.assertIn("FAHCE-Recovery-Token", reply)
        self.assertIn("gateway-signed PAYMENT-CONTEXT", reply)
        self.assertNotIn("gateway-signed PAYMENT-SIGNATURE", reply)
        passages = re.findall(r'text\[(\d+):(\d+)\]:\n```json\n(.*?)\n```', reply, re.S)
        self.assertGreaterEqual(len(passages), 4)
        for start, end, passage in passages:
            self.assertEqual(self.source[int(start):int(end)], passage)
        client.chat.completions.create.assert_not_called()

    def test_credential_extraction_has_no_guessed_service_specific_facts(self):
        source = json.loads(self.source)
        source["components"]["securitySchemes"]["receiptAccess"]["description"] = "ArchiveReceipt <ARCHIVE_READ_TOKEN>. Scoped only to this receipt."
        source["paths"]["/api/v1/receipts/{receipt_id}"]["get"]["description"] = "Retrieve one stored archive receipt."
        reply = literal_protocol_answer({"documents": [{"source_url": "https://example.invalid/openapi.json", "text": json.dumps(source)}]}, "Give the exact receipt Authorization header and token name.")
        self.assertIn("ArchiveReceipt <ARCHIVE_READ_TOKEN>", reply)
        self.assertNotIn("FAHCEReceipt", reply)

    def test_negative_attestation_clause_does_not_select_another_endpoint(self):
        source = json.loads(self.source)
        source["paths"]["/api/v1/attestation-policy"] = {"get": {"description": "A different read resource.", "security": [{"receiptAccess": []}]}}
        question = "Explain the exact receipt-retrieval Authorization header. Do not claim current attestation or execution."
        reply = literal_protocol_answer({"documents": [{"source_url": "https://example.invalid/openapi.json", "text": json.dumps(source)}]}, question)
        self.assertIn("GET /api/v1/receipts/{receipt_id}", reply)

    def test_end_of_document_security_names_are_retrieved_literally(self):
        retained = documentation_context(self.state, "Explain the complete developer receipt integration workflow.")
        passages = retained[0]["passages"]
        self.assertTrue(any("FAHCEReceipt" in p["text"] and "FAHCE-Recovery-Token" in p["text"] for p in passages))
        for passage in passages:
            self.assertEqual(passage["text"], self.source[passage["offset"]:passage["offset"] + len(passage["text"])])

    def test_complete_flow_requires_credential_names_and_402(self):
        request = "Explain the complete developer integration workflow and receipt retrieval."
        good = "First receive HTTP 402. Separately approve payment, retry with PAYMENT-SIGNATURE. Retain FAHCE-Recovery-Token; retrieve the receipt with Authorization: FAHCEReceipt <FAHCE-Recovery-Token>. Documentation establishes no current execution or settlement."
        self.check(good, request)
        for missing in ("402", "PAYMENT-SIGNATURE", "FAHCE-Recovery-Token"):
            with self.subTest(missing=missing), self.assertRaisesRegex(ConversationError, "CHAT_SOURCE_UNSUPPORTED"):
                self.check(good.replace(missing, "[omitted]"), request)

    def test_docs_do_not_prove_settlement_attestation_or_execution(self):
        for claim in ("Payment has settled.", "Attestation is verified.", "Execution is verified."):
            with self.subTest(claim=claim), self.assertRaisesRegex(ConversationError, "CHAT_SOURCE_UNSUPPORTED"):
                self.check(claim)


class SpendingTests(StoreTestMixin, TestCase):
    def client(self, configuration=None):
        client = Mock()
        client._tool_offer_spending_guard = SpendingGuard(self.store, configuration or policy())
        client.chat.completions.create.return_value = response("A fixture.")
        return client

    def test_missing_or_expired_evidence_sends_no_request(self):
        for p in (None, policy(valid_until="2000-01-01T00:00:00Z"), policy(billing_bound_evidence=None), policy(reasoning_usd_per_million=None)):
            client = self.client()
            client._tool_offer_spending_guard = SpendingGuard(self.store, p)
            with self.assertRaises(SpendingError):
                completion(client, model="asi1")
            client.chat.completions.create.assert_not_called()

    def test_real_sdk_cannot_bypass_the_guard(self):
        import httpx
        from openai import OpenAI
        transport = Mock(return_value=httpx.Response(200, json={}))
        with httpx.Client(transport=httpx.MockTransport(transport)) as http:
            client = OpenAI(api_key="controlled-test-only", http_client=http, max_retries=0)
            with self.assertRaisesRegex(SpendingError, "EVIDENCE_UNAVAILABLE"):
                completion(client, model="asi1")
        transport.assert_not_called()

    def test_explicit_call_only_policy_allows_inference_without_a_dollar_gate(self):
        from tool_offer_agent.model_runtime import configure_spending
        client = Mock()
        client.chat.completions.create.return_value = response("A complete controlled answer.")
        configure_spending(client, self.store)
        self.assertEqual(vars(client)["_tool_offer_spending_mode"], "call_limits_only")
        self.assertIsNone(vars(client)["_tool_offer_spending_guard"])
        completion(client, model="asi1")
        client.chat.completions.create.assert_called_once()
        self.assertNotIn("spending", self.store.load(SpendingGuard.key))

    def test_deployment_blocks_before_any_hosted_mutation_without_billing_evidence(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("controlled_release_guard", Path(__file__).parents[1] / "machine/release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with patch.object(release, "verify", return_value={}), patch.object(release, "read", return_value={"spending_policy": None}), patch.object(release, "run") as run, patch.object(release, "live") as live:
            with self.assertRaisesRegex(SpendingError, "EVIDENCE_UNAVAILABLE"):
                release.deploy()
            run.assert_not_called()
            live.assert_not_called()

    def test_all_calls_including_extraction_share_durable_budget(self):
        a, b = self.client(), self.client()
        completion(a, model="asi1"); completion(b, model="asi1")
        restarted = self.client()
        with self.assertRaisesRegex(SpendingError, "DAILY_LIMIT"):
            completion(restarted, model="asi1")
        restarted.chat.completions.create.assert_not_called()
        self.assertEqual(self.store.load(SpendingGuard.key)["spending"]["reserved_micro_usd"], 60)

    def test_owner_is_explicit_and_separate_from_external_pool(self):
        client = self.client()
        for _ in range(4):
            traced(lambda: completion(client, model="asi1"), spending_actor="machine:owner-machine")
        ledger = self.store.load(SpendingGuard.key)["spending"]
        self.assertEqual(ledger["reserved_micro_usd"], 0)
        self.assertEqual(ledger["owner_reserved_micro_usd"], 120)
        completion(client, model="asi1")

    def test_missing_usage_latches_across_utc_reset(self):
        client = self.client()
        client.chat.completions.create.return_value.usage.completion_tokens_details = None
        with self.assertRaisesRegex(SpendingError, "USAGE_UNVERIFIABLE"):
            completion(client, model="asi1")
        client._tool_offer_spending_guard.clock = lambda: 1900000000
        with self.assertRaisesRegex(SpendingError, "RECONCILIATION"):
            completion(client, model="asi1")
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_unknown_outcome_holds_reservation_and_never_retries(self):
        client = self.client()
        client.chat.completions.create.side_effect = TimeoutError()
        for _ in range(2):
            with self.assertRaises(TimeoutError):
                completion(client, model="asi1")
        with self.assertRaises(SpendingError):
            completion(client, model="asi1")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_concurrent_reservations_and_utc_reset(self):
        client = self.client()
        guard = client._tool_offer_spending_guard
        guard.clock = lambda: 1793664000
        def reserve(_):
            try: return guard.reserve("asi1")
            except SpendingError: return None
        with ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(sum(x is not None for x in executor.map(reserve, range(8))), 2)
        guard.clock = lambda: 1793750400
        self.assertEqual(guard.reserve("asi1"), 30)

    def test_reasoning_overrun_and_provider_model_change_fail_closed(self):
        for mutate in (lambda r: setattr(r.usage.completion_tokens_details, "reasoning_tokens", 11), lambda r: setattr(r, "model", "other")):
            self.store.delete(SpendingGuard.key)
            client = self.client(); mutate(client.chat.completions.create.return_value)
            with self.assertRaisesRegex(SpendingError, "USAGE_UNVERIFIABLE"):
                completion(client, model="asi1")


class CoverageTests(TestCase):
    def test_long_sources_keep_material_limits_literal_offsets(self):
        text = ("Search response input output search parameters.\n" * 250 +
                "Material limitation: unavailable for medical decisions.\n" + "Generic text.\n" * 200)
        docs = [{"source_url": "https://example.invalid/docs", "text": text}]
        excerpts, coverage = select_excerpts(docs, job="search response")
        self.assertTrue(any("unavailable for medical" in e["text"] for e in excerpts))
        self.assertTrue(coverage["partial"])
        for e in excerpts:
            self.assertEqual(e["text"], text[e["start"]:e["end"]])
        passages = documentation_context({"documents": docs}, "Explain search response and limitations")[0]["passages"]
        self.assertTrue(any("unavailable for medical" in p["text"] for p in passages))
        for p in passages:
            self.assertEqual(p["text"], text[p["offset"]:p["offset"] + len(p["text"])])

    def test_bazaar_unavailability_without_blanket_product_refusal(self):
        state = {"listing_profile": "api", "fields": {"payment": "x402", "access": "Our service is not available on Bazaar."}}
        plan = checklist(state)
        bazaar = next(d for d in plan["destinations"] if d["id"] == "bazaar")
        self.assertEqual(bazaar["eligibility_state"], "seller_unavailable")
        self.assertIn("No submission recommended", bazaar["route"])
        self.assertTrue(any(d["id"] == "openapi" for d in plan["destinations"]))
        state["fields"]["access"] = "Owner-approved key"
        state["conversation"] = [{"role": "user", "content": "Is our service unavailable on Bazaar?"}]
        bazaar = next(d for d in checklist(state)["destinations"] if d["id"] == "bazaar")
        self.assertEqual(bazaar["eligibility_state"], "conditional_unverified")
