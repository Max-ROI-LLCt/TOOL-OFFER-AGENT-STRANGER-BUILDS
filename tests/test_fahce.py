from dataclasses import asdict, replace
import json
from unittest import TestCase

from jsonschema import Draft202012Validator, FormatChecker

from tool_offer_agent.drafting import build_draft
from tool_offer_agent.fahce import ContractError, ENDPOINT, FahceClient, PENDING, fingerprint, machine_request, parse_response
from tests.support import DOC_URL, FIXTURES, FakeAuthorizedTransport, FakeFetcher


class FahceTests(TestCase):
    def setUp(self):
        self.spec = json.loads((FIXTURES / "openapi.json").read_text(encoding="utf-8"))
        self.documents = [asdict(FakeFetcher().fetch(DOC_URL))]
        fields = {"tool_url": "https://api.example.com/", "customer": "Test customers", "pricing": "free", "payment": "none", "access": "public", "invocation": "POST /convert"}
        self.draft = build_draft(fields, self.documents, 1)
        self.request = machine_request(self.draft, self.documents)
        self.transport = FakeAuthorizedTransport()

    def test_request_matches_downloaded_real_openapi_contract(self):
        schema = self.spec["components"]["schemas"]["MachineRequest"]
        Draft202012Validator(schema).validate(self.request)
        self.assertEqual(set(self.request), {"schema", "candidate_output", "evidence"})
        self.assertEqual(set(self.request["evidence"][0]), {"id", "kind", "source_label", "text"})
        self.assertEqual(json.loads(self.request["candidate_output"]), self.draft)
        post = self.spec["paths"]["/api/v1/diagnose"]["post"]
        self.assertEqual(post["requestBody"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/MachineRequest")
        self.assertIn("PAYMENT-REQUIRED", post["responses"]["402"]["headers"])
        self.assertIn("FAHCE-Terms-Accepted", [p["name"] for p in post["parameters"]])

    def test_discovery_snapshot_requires_x402_rest_not_paid_mcp(self):
        discovery = json.loads((FIXTURES / "machines.json").read_text(encoding="utf-8"))
        self.assertEqual(discovery["payment"]["protocol"], "x402-v2")
        self.assertEqual(discovery["mcp"]["quickstart"]["scope"], "FREE_DISCOVERY_ONLY_NO_PAID_EXECUTION")
        self.assertEqual(discovery["mcp"]["paid_execution"], "REST_ONLY_WALLET_X402_NO_PILOT_KEY")

    def test_test_only_response_matches_real_response_schema(self):
        response = self.transport.execute(ENDPOINT, self.request, idempotency_key="test-only-key")
        Draft202012Validator(self.spec["components"]["schemas"]["MachineResponse"], format_checker=FormatChecker()).validate(response.body)
        result = parse_response(response, self.request, fingerprint(self.draft))
        self.assertEqual(result["result"], response.body)
        self.assertIn(response.body["request_id"], result["receipt_reference"])
        self.assertEqual(result["settlement_status"], "not_confirmed")
        self.assertIsNone(result["settlement_reference"])
        self.assertFalse(result["result"]["verification"]["verified"])

    def test_unconfigured_transport_never_posts(self):
        client = FahceClient()
        self.assertFalse(client.configured)
        result = client.check(self.draft, self.documents, idempotency_key="test-only-key")
        self.assertEqual(result["message"], PENDING)
        self.assertNotIn("result", result)
        self.assertNotIn("receipt_reference", result)

    def test_mismatched_request_hash_and_input_hash_rejected(self):
        response = self.transport.execute(ENDPOINT, self.request, idempotency_key="test-only-key")
        for invalid in (replace(response, request_body_sha256="0" * 64), replace(response, bound_input_hash="0" * 64)):
            with self.assertRaises(ContractError):
                parse_response(invalid, self.request, fingerprint(self.draft))

    def test_wrong_receipt_operation_and_incomplete_response_rejected(self):
        mutations = [lambda b: b.update(operation="repair"), lambda b: b["receipt"].update(case_id="different"), lambda b: b["receipt"].update(input_hash="0" * 64), lambda b: b.pop("diagnosis"), lambda b: b["verification"].update(verified="true"), lambda b: b["receipt"].update(payment_status="PILOT_KEY_NO_PAYMENT"), lambda b: b["billing"].update(determination_status="DETERMINATION_NOT_PRODUCED")]
        for mutation in mutations:
            response = self.transport.execute(ENDPOINT, self.request, idempotency_key="test-only-key")
            mutation(response.body)
            with self.assertRaises(ContractError):
                parse_response(response, self.request, fingerprint(self.draft))

    def test_field_and_aggregate_limits_include_utf16_and_escaping(self):
        for draft, docs in (({"job": "😀" * 100001}, []), ({"job": "small"}, self.documents * 13), ({"job": "small"}, [{**self.documents[0], "text": "x" * 200001}]), ({"job": "small"}, [{**self.documents[0], "text": "\n" * 150000}] * 2)):
            with self.assertRaises(ContractError):
                machine_request(draft, docs)

    def test_source_labels_are_bounded_without_losing_export_sources(self):
        self.documents[0]["source_url"] = "https://docs.example.com/" + "a" * 200
        request = machine_request(self.draft, self.documents)
        self.assertLessEqual(len(request["evidence"][0]["source_label"]), 160)
        self.assertGreater(len(self.documents[0]["source_url"]), 160)
