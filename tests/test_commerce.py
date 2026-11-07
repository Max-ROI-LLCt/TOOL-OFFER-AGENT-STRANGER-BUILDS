import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest import TestCase

from tests.support import FakeAuthorizedTransport, FakeFetcher, INTAKE, StoreTestMixin
from tool_offer_agent.commerce import PaymentTerms, Stage, TransitionError, receipt, verify_receipt
from tool_offer_agent.fahce import FahceClient
from tool_offer_agent.protocol_payment import payment_request
from tool_offer_agent.storage import StateStore
from tool_offer_agent.workflow import Workflow


class CommercialWorkflowTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = FakeFetcher()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, local_test=True)
        self.seller = "agent1seller"
        self.buyer = "agent1buyer"
        self.deadline = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()

    def seller_chat(self, message):
        return self.workflow.handle(self.seller, "seller-session", message)

    def open(self, method="test_only", currency="TEST", network="local", recipient="agent1seller"):
        self.seller_chat(INTAKE)
        self.assertIn("Seller offer approved", self.seller_chat("offer approve"))
        response = self.seller_chat(
            f"transaction open buyer={self.buyer} method={method} currency={currency} amount=2.50 "
            f"network={network} recipient={recipient} deadline={self.deadline}"
        )
        return json.loads(response)

    def approve(self, transaction_id):
        return self.workflow.handle(
            self.buyer, "buyer-session",
            f"transaction approve {transaction_id} test_only TEST 2.50 local agent1seller {self.deadline}",
        )

    def test_seller_approval_exact_buyer_authorization_and_restart(self):
        opened = self.open()
        transaction_id = opened["transaction_id"]
        self.assertEqual(opened["rail_decision"]["status"], "TEST_ONLY")
        self.assertEqual(self.workflow.commerce.read(transaction_id)["stage"], Stage.BUYER_APPROVAL_REQUIRED.value)
        self.assertIn("unauthorized", self.workflow.handle("agent1stranger", "another", f"transaction status {transaction_id}"))
        self.assertIn("must repeat", self.workflow.handle(self.buyer, "buyer-session", f"transaction approve {transaction_id} test_only USDC 2.50 local agent1seller {self.deadline}"))
        self.assertIn("buyer", self.seller_chat(f"transaction send {transaction_id}").lower())
        self.assertIn("approved", self.approve(transaction_id))
        self.assertIn("queued", self.seller_chat(f"transaction send {transaction_id}"))
        before = deepcopy(self.workflow.commerce.read(transaction_id))
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, local_test=True)
        self.assertEqual(before, self.workflow.commerce.read(transaction_id))
        self.assertIn("Buyer must approve", self.seller_chat(f"transaction send {transaction_id}"))
        self.assertIn("unresolved", self.seller_chat("reset"))
        recorded = json.loads(self.seller_chat(f"transaction status {transaction_id}"))
        self.assertTrue(recorded["local_verification"]["local_integrity"])
        self.assertFalse(recorded["local_verification"]["independent_verification"])
        self.assertEqual(recorded["record"]["payment"], "not_committed")
        self.assertEqual(recorded["record"]["settlement"], "not_verified")
        self.assertEqual(json.loads(self.seller_chat("export json"))["commercial_transaction_ids"], [transaction_id])

    def test_asi_text_demo_and_summary_expose_truthful_status(self):
        self.assertIn("Open-Meteo", self.seller_chat("demo"))
        opened = self.open()
        transaction_id = opened["transaction_id"]
        self.assertIn("Seller-approved offer hash", self.seller_chat("status"))
        summary = self.seller_chat("transaction summary " + transaction_id)
        self.assertIn("BUYER_APPROVAL_REQUIRED", summary)
        self.assertIn("not_verified", summary)
        self.assertIn("NOT_CONFIGURED", summary)
        self.assertIn("independently verified: False", summary)

    def test_seller_approval_is_idempotent_and_linked_to_transaction(self):
        self.seller_chat(INTAKE)
        first = json.loads(self.seller_chat("export json"))["draft"]
        self.assertIn("approved", self.seller_chat("offer approve"))
        before = json.loads(self.seller_chat("export json"))["approved_offer"]
        self.assertIn("no duplicate", self.seller_chat("offer approve"))
        self.assertEqual(before, json.loads(self.seller_chat("export json"))["approved_offer"])
        opened = self.seller_chat(f"transaction open buyer={self.buyer} method=test_only currency=TEST amount=2.50 network=local recipient=agent1seller deadline={self.deadline}")
        record = self.workflow.commerce.read(json.loads(opened)["transaction_id"])
        approved_event = next(event for event in record["events"] if event["stage"] == Stage.SELLER_OFFER_APPROVED.value)
        self.assertIn(before["idempotency_key"], approved_event["evidence"])
        self.assertEqual(record["offer_version"], first["revision"])

    def test_unsupported_x402_never_substitutes_asset_network_or_recipient(self):
        opened = self.open("x402", "USDC", "base", "0xSeller")
        record = self.workflow.commerce.read(opened["transaction_id"])
        self.assertEqual(opened["rail_decision"]["status"], Stage.UNSUPPORTED.value)
        self.assertIn("no buyer approval", opened["next"])
        self.assertEqual(record["stage"], Stage.UNSUPPORTED.value)
        self.assertEqual(tuple(record["payment_terms"][field] for field in ("method", "currency", "network", "recipient")), ("x402", "USDC", "base", "0xSeller"))
        self.assertEqual(record["fahce"], "NOT_CONFIGURED")
        self.assertIn("pending", self.seller_chat("check").lower())
        self.assertIn("refused", self.seller_chat(f"transaction send {record['id']}"))

    def test_duplicate_commit_out_of_order_and_receipt_tamper(self):
        transaction_id = self.open()["transaction_id"]
        journal = self.workflow.commerce
        with self.assertRaises(TransitionError):
            journal.transition(transaction_id, Stage.PAYMENT_COMMITTED, self.buyer, "premature", ["test"])
        self.approve(transaction_id)
        self.seller_chat(f"transaction send {transaction_id}")
        journal.transition(transaction_id, Stage.PAYMENT_COMMITTED, self.buyer, "test-commit", ["TEST_ONLY:id"])
        record = journal.read(transaction_id)
        self.assertEqual(record["payment"], "test_commit_not_settled")
        with self.assertRaises(TransitionError):
            journal.transition(transaction_id, Stage.PAYMENT_COMMITTED, self.buyer, "test-commit", ["TEST_ONLY:id"])
        with self.assertRaises(TransitionError):
            journal.transition(transaction_id, Stage.SETTLEMENT_VERIFIED, self.seller, "false-proof", ["seller says yes"])
        self.assertTrue(verify_receipt(record, receipt(record))["local_integrity"])
        altered = deepcopy(record)
        altered["events"][0]["evidence"] = ["changed"]
        self.assertFalse(verify_receipt(altered, receipt(record))["local_integrity"])
        altered_receipt = receipt(record)
        altered_receipt["settlement"] = "verified"
        self.assertFalse(verify_receipt(record, altered_receipt)["local_integrity"])
        altered = deepcopy(record)
        altered["buyer"]["id"] = "agent1stranger"
        self.assertFalse(verify_receipt(altered, receipt(altered))["local_integrity"])

    def test_concurrent_local_requests_only_one_is_recorded(self):
        transaction_id = self.open()["transaction_id"]
        self.approve(transaction_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: self.seller_chat(f"transaction send {transaction_id}"), range(2)))
        self.assertEqual(sum("queued" in outcome for outcome in outcomes), 1)
        self.assertEqual(self.workflow.commerce.read(transaction_id)["stage"], Stage.PAYMENT_REQUESTED.value)

    def test_uncertain_buyer_request_prevents_ambiguous_rebinding(self):
        first = self.open()["transaction_id"]
        self.approve(first)
        self.assertIn("queued", self.seller_chat(f"transaction send {first}"))
        self.workflow.commerce.transition(first, Stage.PENDING_RECONCILIATION, self.seller, "uncertain:" + first, ["Outcome unknown"])
        second = self.open()["transaction_id"]
        self.approve(second)
        self.assertIn("Another unresolved request", self.seller_chat(f"transaction send {second}"))
        self.assertEqual(self.workflow.commerce.pending_for_buyer(self.buyer), first)

    def test_independent_store_instances_cannot_commit_duplicate_request(self):
        transaction_id = self.open()["transaction_id"]
        self.approve(transaction_id)
        other = Workflow(store=StateStore(self.store.path), fetcher=FakeFetcher(), local_test=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(
                lambda workflow: workflow.handle(self.seller, "seller-session", f"transaction send {transaction_id}"),
                (self.workflow, other),
            ))
        self.assertEqual(sum("queued" in outcome for outcome in outcomes), 1)
        self.assertEqual(self.workflow.commerce.read(transaction_id)["stage"], Stage.PAYMENT_REQUESTED.value)

    def test_expired_authorization_is_not_approved(self):
        transaction_id = self.open()["transaction_id"]
        record = self.workflow.commerce.read(transaction_id)
        record["payment_terms"]["deadline"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.workflow.commerce.store.save(self.workflow.commerce._key(transaction_id), {"commercial_transaction": record})
        self.assertIn("expired", self.workflow.handle(
            self.buyer, "buyer-session", f"transaction approve {transaction_id} test_only TEST 2.50 local agent1seller {record['payment_terms']['deadline']}"
        ))

    def test_expired_request_cannot_be_dispatched_after_persisting_it(self):
        transaction_id = self.open()["transaction_id"]
        self.approve(transaction_id)
        self.assertIn("queued", self.seller_chat(f"transaction send {transaction_id}"))
        record = self.workflow.commerce.read(transaction_id)
        record["payment_terms"]["deadline"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(TransitionError, "expired before external dispatch"):
            payment_request(record)

    def test_fahce_fixture_is_linked_without_claiming_independent_verification(self):
        fixture_transport = FakeAuthorizedTransport()
        self.workflow.fahce = FahceClient(fixture_transport)
        self.seller_chat(INTAKE)
        self.assertIn("FAHCE returned result", self.seller_chat("check"))
        opened = self.open()
        record = self.workflow.commerce.read(opened["transaction_id"])
        self.assertEqual(record["fahce"], "RETURNED_WITH_EVIDENCE")
        self.assertEqual(record["settlement"], "not_verified")
        self.assertEqual(record["fahce_reference"], json.loads(self.seller_chat("export json"))["fahce"]["receipt_reference"])
        self.assertFalse(verify_receipt(record, receipt(record))["independent_verification"])
        self.assertEqual(len(fixture_transport.calls), 1)

    def test_fahce_incomplete_does_not_block_offer(self):
        self.workflow.fahce = FahceClient(FakeAuthorizedTransport())
        opened = self.open()
        record = self.workflow.commerce.read(opened["transaction_id"])
        self.assertEqual(record["fahce"], "INCOMPLETE")
        self.assertIsNone(record["fahce_reference"])


class RailValidationTests(TestCase):
    def test_invalid_amount_and_naive_deadline_rejected(self):
        for amount, deadline in (("NaN", "2027-01-01T00:00:00+00:00"), ("0", "2027-01-01T00:00:00+00:00"), ("1", "2027-01-01T00:00:00")):
            with self.assertRaises(ValueError):
                PaymentTerms("test_only", "TEST", amount, "local", "seller", "none", "none", "none", deadline)
