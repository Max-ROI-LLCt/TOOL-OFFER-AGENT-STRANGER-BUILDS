"""Controlled fixtures only; no independent-client or ASI UI rendering claim."""

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from jsonschema import validate
from uagents_core.identity import Identity
from uagents_core.contrib.protocols.chat import MetadataContent

from tests.support import StoreTestMixin
from tool_offer_agent.chat import create_readiness_chat, create_text_chat, respond
from tool_offer_agent.export_delivery import reassemble, retrieve
from tool_offer_agent.machine import MachineRequest, MachineService
from tool_offer_agent.machine_contract import CONTRACT
from tool_offer_agent.readiness import ReadinessReport, ReadinessText, assess, digest, encoded, machine_result, native_reply
from tool_offer_agent.readiness_cards import card_metadata, valid_metadata
from tool_offer_agent.restrictions import empty
from tool_offer_agent.workflow import Workflow


def fixture():
    source = "https://example.com/guide"
    return {"fields": {"tool_url": "https://example.com/api", "docs": source, "customer": "Developers", "pricing": "Fully free", "payment": "None", "access": "Public demo; no account", "invocation": "GET /tickets/{id}"},
            "documents": [{"source_url": source, "text": "Return the caller's authorized ticket status. This demo is fully free."}],
            "draft": {"revision": 2, "offer": {"capabilities": [{"text": "Return the caller's authorized ticket status.", "source_url": source}], "pricing": "Fully free", "unknown_or_unextracted": []}},
            "revision": 2, "outdated": False, "restrictions": empty(), "check": None}


class ReadinessTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.sender = "controlled-client"
        self.session = str(uuid4())
        self.key = self.store.key(self.sender, self.session)
        self.state = fixture()
        self.store.save(self.key, self.state)

    def test_pure_report_schema_facts_and_complete_text(self):
        before = copy.deepcopy(self.state)
        report = assess(self.state, self.sender, "test-release")
        validate(report, ReadinessReport.schema())
        self.assertEqual(self.state, before)
        self.assertEqual(report["status"], "needs_information")
        self.assertTrue(any(item["code"] == "DOCUMENTATION_INSUFFICIENT" for item in report["findings"]))
        self.assertEqual(report["facts"][0]["basis"], "verbatim_quote")
        self.assertEqual(report["facts"][0]["evidence_refs"], ["doc_1"])
        self.assertIn("https://example.com/guide", report["human_readable"])
        self.assertIn("Fully free", report["human_readable"])
        self.assertIn("\nSources:\n", report["human_readable"])
        self.assertFalse(report["authorization"]["independently_verified"])

    def test_snapshot_binds_every_assessed_input_and_release(self):
        original = assess(self.state, self.sender, "release")["basis"]["snapshot_sha256"]
        for name, value in [("fields", {"pricing": "undecided"}), ("documents", []), ("restrictions", {**empty(), "demonstration_only": True}), ("planning", {"mode": "prelaunch", "items": []}), ("outdated", True), ("approved_offer", {"hash": "old", "by": "different"})]:
            with self.subTest(name=name):
                changed = {**self.state, name: value}
                self.assertNotEqual(assess(changed, self.sender, "release")["basis"]["snapshot_sha256"], original)
        self.assertNotEqual(assess(self.state, self.sender, "new-release")["basis"]["snapshot_sha256"], original)

    def test_prelaunch_no_url_preserves_proposals_and_fiction(self):
        self.state.update(fields={}, documents=[], draft=None, planning={"mode": "prelaunch", "items": [
            {"id": "R1", "kind": "requirement", "text": "Only authorized tickets", "status": "proposed"},
            {"id": "D1", "kind": "decision", "text": "Select a plan", "status": "unresolved"},
            {"id": "F1", "kind": "exercise", "text": "Fictional tenant interview", "status": "fictional"},
            {"id": "T1", "kind": "test", "text": "Other tenants denied", "status": "not_executed", "requirement_id": "R1"}]})
        report = assess(self.state, self.sender, "release")
        self.assertEqual(report["status"], "prelaunch")
        self.assertIn("no public URL is required", report["next_step"])
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["planning"][2]["status"], "fictional")
        self.assertIn("not executed", report["human_readable"])

    def test_free_demo_is_not_seller_authorization(self):
        self.state["restrictions"].update(demonstration_only=True, third_party_non_ownership=True)
        report = assess(self.state, self.sender, "release")
        self.assertEqual(report["authorization"]["commercial"], "explicitly_restricted")
        self.assertEqual(next(item["value"] for item in report["facts"] if item["pointer"] == "/fields/payment"), "None")
        self.assertIn("Fully free", report["human_readable"])

    def test_approval_stale_and_identity_unverified(self):
        self.state["approved_offer"] = {"hash": digest(self.state["draft"]), "by": self.sender}
        report = assess(self.state, self.sender, "release")
        self.assertEqual(report["authorization"]["seller_approval"], "current_sender_bound")
        self.assertEqual(report["authorization"]["commercial"], "not_established")
        self.state["outdated"] = True
        report = assess(self.state, self.sender, "release")
        self.assertEqual(report["status"], "needs_revision")
        self.assertEqual(report["authorization"]["seller_approval"], "stale_or_different_sender")

    def test_unaligned_claim_is_not_falsely_supported_or_contradicted(self):
        self.state["draft"]["offer"]["capabilities"][0]["text"] = "Inspect ANY ticket and resell the service"
        self.state["draft"]["model_extraction"] = {"coverage": "partial", "selected_characters": 100}
        self.state["draft"]["offer"]["unknown_or_unextracted"] = ["limitations"]
        report = assess(self.state, self.sender, "release")
        self.assertEqual(report["facts"][0]["basis"], "derived_schema_or_unaligned")
        self.assertIn("ALIGNMENT_UNRESOLVED", [item["code"] for item in report["findings"]])
        self.assertIn("EXTRACTION_INCOMPLETE", [item["code"] for item in report["findings"]])
        self.assertIn("claim_truth_or_general_semantic_entailment", report["not_assessed"])

    def test_absent_and_undecided_are_distinct(self):
        self.state["fields"].pop("payment")
        self.state["fields"]["pricing"] = "undecided"
        findings = assess(self.state, self.sender, "release")["findings"]
        self.assertEqual(next(item["code"] for item in findings if item["pointer"] == "/fields/pricing"), "INTAKE_UNDECIDED")
        self.assertEqual(next(item["code"] for item in findings if item["pointer"] == "/fields/payment"), "INTAKE_MISSING")

    def test_long_report_complete_resumable_isolated_and_state_immutable(self):
        self.state["documents"][0]["text"] += "\n" + "Long source 🌱\n" * 1100
        self.state["draft"]["offer"]["capabilities"].append({"text": self.state["documents"][0]["text"], "source_url": self.state["documents"][0]["source_url"]})
        self.store.save(self.key, self.state)
        result = machine_result(self.store, self.sender, self.session, "release")
        self.assertEqual(result["readiness"]["delivery"], "multipart")
        manifest = result["readiness"]["manifest"]
        parts = [json.loads(retrieve(self.store, self.key, f"export part {manifest['export_id']} {index}")) for index in range(1, manifest["total_parts"] + 1)]
        with self.assertRaises(ValueError):
            reassemble(manifest, parts[:-1])
        raw = reassemble(manifest, list(reversed(parts)))
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), result["readiness"]["report_sha256"])
        self.assertIn("Long source 🌱\n" * 1100, json.loads(raw)["human_readable"])
        self.assertEqual(self.store.load(self.key), self.state)
        other = self.store.key("simulated-other-client", self.session)
        self.assertIn("unavailable", retrieve(self.store, other, f"export part {manifest['export_id']} 1"))

    def test_snapshot_overflow_never_silently_truncates(self):
        with patch("tool_offer_agent.readiness.MAX_EXPORT_BYTES", 12):
            with self.assertRaisesRegex(ValueError, "snapshot_too_large"):
                assess(self.state, self.sender, "release")

    def test_native_replay_returns_original_snapshot_without_mutating_offer(self):
        first = native_reply(self.store, self.sender, self.session, "release", "readiness", "request-one")
        self.state["fields"]["pricing"] = "undecided"
        self.store.save(self.key, self.state)
        again = native_reply(self.store, self.sender, self.session, "release", "readiness", "request-one")
        self.assertEqual(first, again)
        self.assertEqual(first.metadata, again.metadata)
        self.assertEqual(self.store.load(self.key), self.state)
        self.assertIn("different arguments", native_reply(self.store, self.sender, self.session, "release", "readiness json", "request-one"))

    def test_cards_metadata_only_no_actions_and_field_accuracy(self):
        report = assess(self.state, self.sender, "release")
        metadata = card_metadata(report)
        self.assertTrue(valid_metadata(metadata))
        payload = json.loads(metadata["card_payload"])
        text = encoded(payload)
        self.assertIn(report["basis"]["snapshot_sha256"], text)
        self.assertIn("https://example.com/guide", text)
        self.assertIn("caller's authorized ticket", text)
        self.assertNotIn('"action"', text)
        self.assertNotIn('"selection"', text)
        self.assertEqual(metadata["is_terminal"], "true")

    def test_invalid_card_and_explicit_text_mode_keep_complete_text(self):
        for metadata in [None, {"card_kind": "bogus"}, {**card_metadata(assess(self.state, self.sender, "release")), "card_payload": '{"root":{"type":"button","action":{"selection":{"approve":true}}}}'}]:
            message = create_readiness_chat(ReadinessText("Complete\nreadiness fallback", metadata))
            self.assertEqual(message.text(), "Complete\nreadiness fallback")
            self.assertEqual(len(message.content), 1)
        with patch("tool_offer_agent.readiness_cards.card_metadata", side_effect=RuntimeError("invalid presentation")):
            reply = native_reply(self.store, self.sender, self.session, "release", "readiness")
            self.assertIsNone(reply.metadata)
            self.assertIn("Offer readiness:", reply)
        self.assertIsNone(native_reply(self.store, self.sender, self.session, "release", "readiness text").metadata)

    def test_native_chat_attaches_card_without_any_execution_dependency(self):
        denied = Mock(side_effect=AssertionError("Forbidden dependency"))
        workflow = Workflow(store=self.store, fetcher=denied, extractor=denied, conversation=denied, fahce=denied, checkout=denied)
        ctx = SimpleNamespace(session=self.session, send=AsyncMock())
        asyncio.run(respond(ctx, self.sender, create_text_chat("readiness"), workflow))
        reply = ctx.send.call_args_list[-1].args[1]
        self.assertTrue(any(isinstance(content, MetadataContent) for content in reply.content))
        self.assertIn("Offer readiness:", reply.text())
        self.assertEqual(self.store.load(self.key), self.state)
        self.assertEqual(denied.mock_calls, [])

    def test_machine_signed_boundary_replay_and_simulated_other_client(self):
        identity = Identity.from_seed("offline-readiness-gateway", 0)
        denied = Mock(side_effect=AssertionError("Forbidden dependency"))
        service = MachineService(Workflow(store=self.store, fetcher=denied, extractor=denied, conversation=denied, checkout=denied, fahce=denied), CONTRACT, "release", identity.address, clock=lambda: 1000)
        actor = "machine:controlled-one"
        actor_key = self.store.key(actor, self.session)
        self.store.save(actor_key, self.state)
        data = {"principal": "controlled-one", "session_id": self.session, "request_id": str(uuid4()), "release_id": "release", "issued_at": 1000, "transport_sender": identity.address, "operation": "assess_offer_readiness", "arguments": {}}
        def execute(value):
            body = encoded(value)
            return service.execute(MachineRequest(body=body, authorization=identity.sign_digest(hashlib.sha256(body.encode()).digest())), identity.address)
        first = execute(data)
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["model_attempts"], 0)
        self.assertEqual(self.store.load(actor_key), self.state)
        self.state["outdated"] = True
        self.store.save(actor_key, self.state)
        self.assertEqual(execute(data), first)
        self.assertEqual(execute({**data, "operation": "get_status"})["error"], "idempotency_conflict")
        other = execute({**data, "principal": "controlled-two"})
        self.assertNotEqual(first["readiness"]["snapshot_sha256"], other["readiness"]["snapshot_sha256"])
        self.assertNotIn("example.com/guide", other["text"])
        self.assertEqual(denied.mock_calls, [])
