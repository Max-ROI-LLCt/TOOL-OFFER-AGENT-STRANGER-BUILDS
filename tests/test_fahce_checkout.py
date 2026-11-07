import json
from unittest import TestCase

from tool_offer_agent.fahce import fingerprint
from tool_offer_agent.workflow import Workflow
from tests.support import INTAKE, FakeFetcher, StoreTestMixin


class FakeCheckout:
    def __init__(self):
        self.calls = []
        self.phase = "ready"

    def prepare(self, draft, documents, key):
        self.calls.append(key)
        return {"id": key, "draft_hash": fingerprint(draft), "requestSha256": "a" * 64,
                "accessToken": "private-checkout-capability", "url": "https://checkout.example/checkout/#access=private-checkout-capability"}

    def status(self, checkout):
        result = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures/diagnose_response.test-only.json").read_text())
        return {"phase": self.phase, "result": result, "receiptProof": {"verified": True}, "gatewayReportsSuccess": False,
                "requestSha256": checkout["requestSha256"],
                "preflight": {"status": "NO_KNOWN_BLOCKER", "requestSha256": checkout["requestSha256"],
                              "candidateBlockers": 0, "evidenceBlockers": 0}}


class WalletCheckoutTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.checkout = FakeCheckout()
        self.workflow = Workflow(store=self.store, fetcher=FakeFetcher(), checkout=self.checkout)

    def chat(self, message, sender="seller", session="checkout-test"):
        return self.workflow.handle(sender, session, message)

    def test_requires_current_draft_and_reuses_prepared_checkout(self):
        self.assertIn("current draft", self.chat("check"))
        self.chat(INTAKE)
        first = self.chat("check")
        self.assertIn("0.15 USDC", first)
        self.assertEqual(first, self.chat("check"))
        self.assertEqual(len(self.checkout.calls), 1)

    def test_retrieves_actual_result_without_claiming_settlement(self):
        self.chat(INTAKE)
        self.chat("check")
        self.checkout.phase = "response_received"
        reply = self.chat("check")
        self.assertIn("FAHCE returned result", reply)
        record = json.loads(self.chat("export json"))
        self.assertEqual(record["fahce"]["settlement_status"], "not_confirmed")
        self.assertFalse(record["fahce"]["result"]["verification"]["verified"])
        self.assertNotIn("private-checkout-capability", json.dumps(record))
        self.assertEqual(len(self.checkout.calls), 1)

    def test_revision_does_not_attach_old_result_or_start_another_purchase(self):
        self.chat(INTAKE)
        self.chat("check")
        self.chat("revise pricing: USD 9 per month")
        self.chat("draft limited")
        self.assertIn("draft changed", self.chat("check"))
        self.assertEqual(len(self.checkout.calls), 1)

    def test_ambiguous_delivery_does_not_prepare_second_purchase(self):
        self.chat(INTAKE)
        self.chat("check")
        self.checkout.phase = "unresolved"
        self.assertIn("Do not approve another payment", self.chat("check"))
        self.assertEqual(len(self.checkout.calls), 1)

    def test_unsupported_input_does_not_invite_payment_or_replace_checkout(self):
        self.chat(INTAKE)
        self.checkout.phase = "input_blocked"
        reply = self.chat("check")
        self.assertIn("free input check", reply)
        self.assertIn("No new wallet signature or payment", reply)
        self.assertNotIn("approve with your own", reply)
        self.assertNotIn("0.15 USDC", reply)
        self.assertIn("Open existing FAHCE checkout", reply)
        self.assertEqual(reply, self.chat("check"))
        self.assertEqual(len(self.checkout.calls), 1)

    def test_different_senders_get_separate_checkouts(self):
        for sender in ("first", "second"):
            self.chat(INTAKE, sender)
            self.chat("check", sender)
        self.assertEqual(len(set(self.checkout.calls)), 2)

    def test_unknown_or_in_progress_phase_never_invites_payment(self):
        self.chat(INTAKE)
        for phase in ("requesting_challenge", "future_phase", "", None):
            with self.subTest(phase=phase):
                self.checkout.phase = phase
                reply = self.chat("check")
                self.assertNotIn("0.15 USDC", reply)
                self.assertNotIn("approve with your own", reply)
                self.assertIn("Do not approve another payment", reply)
        self.assertEqual(len(self.checkout.calls), 1)

    def test_payment_invitation_requires_clear_hash_bound_preflight(self):
        self.chat(INTAKE)
        original_status = self.checkout.status
        for preflight in (None, {}, {"status": "UNAVAILABLE"}, {"status": "INPUT_UNSUPPORTED"},
                          {"status": "NO_KNOWN_BLOCKER", "requestSha256": "b" * 64},
                          {"status": "NO_KNOWN_BLOCKER", "requestSha256": "a" * 64,
                           "candidateBlockers": 1, "evidenceBlockers": 0},
                          {"status": "NO_KNOWN_BLOCKER", "requestSha256": "a" * 64,
                           "candidateBlockers": 0, "evidenceBlockers": None}):
            with self.subTest(preflight=preflight):
                self.checkout.status = lambda checkout: {**original_status(checkout), "preflight": preflight}
                reply = self.chat("check")
                self.assertNotIn("0.15 USDC", reply)
                self.assertNotIn("approve with your own", reply)
                self.assertIn("free input check", reply)
        self.assertEqual(len(self.checkout.calls), 1)

    def test_input_blocked_explains_formatting_without_telling_user_to_repair_provider(self):
        self.chat(INTAKE)
        self.checkout.phase = "input_blocked"
        original_status = self.checkout.status
        self.checkout.status = lambda checkout: {**original_status(checkout), "preflight": {
            "status": "INPUT_UNSUPPORTED", "candidateBlockers": 12, "evidenceBlockers": 0}}
        reply = self.chat("check")
        self.assertIn("12 offer-format blocker(s)", reply)
        self.assertIn("0 source-evidence blocker(s)", reply)
        self.assertIn("Refreshing alone does not rewrite", reply)
        self.assertNotIn("Azure", reply)

    def test_unavailable_preflight_does_not_blame_offer_or_invent_blocker_counts(self):
        self.chat(INTAKE)
        self.checkout.phase = "input_blocked"
        original_status = self.checkout.status
        self.checkout.status = lambda checkout: {**original_status(checkout), "preflight": {"status": "UNAVAILABLE"}}
        reply = self.chat("check")
        self.assertIn("unavailable", reply)
        self.assertNotIn("offer-format blocker(s)", reply)
        self.assertNotIn("0.15 USDC", reply)

    def test_pending_input_review_uses_same_checkout_without_inviting_payment(self):
        self.chat(INTAKE)
        self.chat("check")
        self.checkout.phase = "input_review"
        reply = self.chat("check")
        self.assertIn("Use revised input", reply)
        self.assertIn("does not sign or pay", reply)
        self.assertNotIn("0.15 USDC", reply)
        self.assertEqual(len(self.checkout.calls), 1)

    def test_reviewed_result_exports_actual_submitted_hash_and_original_binding(self):
        self.chat(INTAKE)
        self.chat("check")
        original_status = self.checkout.status
        self.checkout.phase = "response_received"
        revision = {"scope": "BUYER_REVIEWED_REPRESENTATION", "sourceRequestSha256": "a" * 64, "requestSha256": "d" * 64}
        self.checkout.status = lambda checkout: {**original_status(checkout), "requestSha256": "d" * 64, "representationRevision": revision}
        self.chat("check")
        exported = json.loads(self.chat("export json"))["fahce"]
        self.assertEqual(exported["request_hash"], "d" * 64)
        self.assertEqual(exported["source_request_hash"], "a" * 64)
        self.assertEqual(exported["reviewed_representation"], revision)


class ReviewedRepresentationTests(TestCase):
    def setUp(self):
        from tool_offer_agent.fahce_checkout import FahceCheckoutClient
        self.client = FahceCheckoutClient("https://checkout.example", "test-only-owner-token")
        self.checkout = {"id": "a" * 64, "accessToken": "test-only-capability", "requestSha256": "b" * 64, "draft_hash": "c" * 64}
        self.revision = {"scope": "BUYER_REVIEWED_REPRESENTATION", "evidenceUnchanged": True,
                         "acceptedAt": "2026-11-01T02:00:00Z", "sourceRequestSha256": "b" * 64, "requestSha256": "d" * 64}
        self.result = {"requestSha256": "d" * 64, "draftHash": "c" * 64, "representationRevision": self.revision}
        self.client._call = lambda *args: self.result

    def test_accepts_only_bound_reviewed_representation(self):
        self.assertEqual(self.client.status(self.checkout)["requestSha256"], "d" * 64)
        for field, value in [("scope", "UNREVIEWED"), ("evidenceUnchanged", False), ("acceptedAt", None),
                             ("sourceRequestSha256", "e" * 64), ("requestSha256", "e" * 64)]:
            with self.subTest(field=field):
                self.result["representationRevision"] = {**self.revision, field: value}
                with self.assertRaises(RuntimeError):
                    self.client.status(self.checkout)
        self.result["representationRevision"] = self.revision
        self.result["draftHash"] = "e" * 64
        with self.assertRaises(RuntimeError):
            self.client.status(self.checkout)

    def test_rejects_changed_request_without_review(self):
        self.result.pop("representationRevision")
        with self.assertRaises(RuntimeError):
            self.client.status(self.checkout)
