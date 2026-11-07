"""Evidence-bound commercial transitions without wallet or settlement authority."""

from dataclasses import asdict, dataclass
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
import json
import re
import threading
from uuid import uuid4


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


class Stage(str, Enum):
    OFFER_DISCOVERED = "OFFER_DISCOVERED"
    EVIDENCE_REVIEWED = "EVIDENCE_REVIEWED"
    SELLER_OFFER_APPROVED = "SELLER_OFFER_APPROVED"
    BUYER_APPROVAL_REQUIRED = "BUYER_APPROVAL_REQUIRED"
    BUYER_APPROVED = "BUYER_APPROVED"
    PAYMENT_REQUESTED = "PAYMENT_REQUESTED"
    PAYMENT_COMMITTED = "PAYMENT_COMMITTED"
    EXECUTION_OBSERVED = "EXECUTION_OBSERVED"
    DELIVERY_EVIDENCED = "DELIVERY_EVIDENCED"
    SETTLEMENT_VERIFIED = "SETTLEMENT_VERIFIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNSUPPORTED = "UNSUPPORTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"


NEXT = {
    Stage.OFFER_DISCOVERED: (Stage.EVIDENCE_REVIEWED,),
    Stage.EVIDENCE_REVIEWED: (Stage.SELLER_OFFER_APPROVED, Stage.REJECTED),
    Stage.SELLER_OFFER_APPROVED: (Stage.BUYER_APPROVAL_REQUIRED, Stage.CANCELLED),
    Stage.BUYER_APPROVAL_REQUIRED: (Stage.BUYER_APPROVED, Stage.UNSUPPORTED, Stage.REJECTED, Stage.CANCELLED, Stage.EXPIRED),
    Stage.BUYER_APPROVED: (Stage.PAYMENT_REQUESTED, Stage.CANCELLED, Stage.EXPIRED),
    Stage.PAYMENT_REQUESTED: (Stage.PAYMENT_COMMITTED, Stage.REJECTED, Stage.CANCELLED, Stage.EXPIRED, Stage.PENDING_RECONCILIATION),
    Stage.PAYMENT_COMMITTED: (Stage.EXECUTION_OBSERVED, Stage.CANCELLED, Stage.FAILED, Stage.PENDING_RECONCILIATION),
    Stage.EXECUTION_OBSERVED: (Stage.DELIVERY_EVIDENCED, Stage.FAILED, Stage.PENDING_RECONCILIATION),
    Stage.DELIVERY_EVIDENCED: (Stage.SETTLEMENT_VERIFIED, Stage.PENDING_RECONCILIATION),
    Stage.PENDING_RECONCILIATION: (Stage.SETTLEMENT_VERIFIED, Stage.FAILED, Stage.CANCELLED),
}


class TransitionError(ValueError):
    pass


@dataclass(frozen=True)
class PaymentTerms:
    method: str
    currency: str
    amount: str
    network: str
    recipient: str
    verification_method: str
    funding_requirement: str
    authorization: str
    deadline: str

    def __post_init__(self):
        try:
            amount = Decimal(self.amount)
        except InvalidOperation:
            raise ValueError("Amount must be a positive exact decimal string.") from None
        if not amount.is_finite() or amount <= 0 or not re.fullmatch(r"\d+(?:\.\d+)?", self.amount):
            raise ValueError("Amount must be a positive exact decimal string.")
        if not self.currency or not self.recipient or not self.deadline:
            raise ValueError("Currency, recipient and deadline are required.")
        try:
            due = datetime.fromisoformat(self.deadline.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Deadline must be a timezone-aware ISO timestamp.") from None
        if due.tzinfo is None:
            raise ValueError("Deadline must have a timezone.")


RAILS = {
    "stripe": ("fiat", "Stripe Checkout session verification", "Provider account, Checkout session and buyer payment authorization"),
    "skyfire": ("USDC", "Skyfire provider verification", "Provider access and funded authorized buyer account"),
    "fet_direct": ("FET", "Independent chain transaction confirmation", "Correct network, funded wallet and buyer signature"),
    "x402": ("USDC", "x402 gateway plus independent settlement verification", "x402 v2 client, exact network/recipient, funded wallet and buyer signature"),
    "test_only": ("TEST", "No financial verification: local protocol exercise", "No wallet; controlled local test only"),
}


def select_rail(terms, *, local_test=False):
    capability = RAILS.get(terms.method)
    if capability is None:
        return {"status": Stage.UNSUPPORTED.value, "reason": "Unknown payment method; no substitution permitted.", "required": "Document and independently verify the exact rail."}
    if terms.method == "test_only" and local_test and terms.currency == "TEST" and terms.network == "local":
        return {"status": "TEST_ONLY", "terms": asdict(terms), "settlement": "not_applicable"}
    return {"status": Stage.UNSUPPORTED.value, "terms": asdict(terms), "reason": "Protocol vocabulary does not establish payment capability or buyer funding.", "required": capability[2] + "; " + capability[1]}


def request_intent_digest(record):
    return digest({"protocol": "AgentPaymentProtocol", "message": "RequestPayment", "reference": record["id"],
                   "recipient": record["payment_terms"]["recipient"], "terms": record["payment_terms"]})


class TransactionJournal:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def _key(self, transaction_id):
        return self.store.key("tool-offer-commercial-v1", transaction_id)

    def read(self, transaction_id):
        return self.store.load(self._key(transaction_id)).get("commercial_transaction")

    def bind_buyer(self, buyer, transaction_id):
        with self.lock:
            index = self.store.key("tool-offer-commercial-buyer-v1", buyer)
            previous = self.store.load(index).get("pending_commercial_transaction")
            if previous and previous != transaction_id:
                record = self.read(previous)
                if record and record["stage"] in (
                    Stage.BUYER_APPROVED.value, Stage.PAYMENT_REQUESTED.value, Stage.PAYMENT_COMMITTED.value,
                    Stage.EXECUTION_OBSERVED.value, Stage.DELIVERY_EVIDENCED.value, Stage.PENDING_RECONCILIATION.value,
                ):
                    raise TransitionError("Another unresolved request to this buyer exists.")
            previous_state = {"pending_commercial_transaction": previous} if previous else None
            updated = {"pending_commercial_transaction": transaction_id}
            if hasattr(self.store, "compare_and_swap"):
                if not self.store.compare_and_swap(index, previous_state, updated):
                    raise TransitionError("Concurrent buyer request; inspect pending status before proceeding.")
            else:
                self.store.save(index, updated)

    def pending_for_buyer(self, buyer):
        index = self.store.key("tool-offer-commercial-buyer-v1", buyer)
        return self.store.load(index).get("pending_commercial_transaction")

    def create(self, draft, documents, seller, buyer, operation, terms, *, transaction_id=None, at=None,
               fahce_status="NOT_CONFIGURED", fahce_reference=None):
        if not draft or not operation or not seller or not buyer:
            raise TransitionError("Current offer, operation, seller and buyer are required.")
        if fahce_status not in ("NOT_CONFIGURED", "UNAVAILABLE", "UNSUPPORTED", "INCOMPLETE", "PENDING_RECONCILIATION", "RETURNED_WITH_EVIDENCE", "INDEPENDENTLY_VERIFIED"):
            raise TransitionError("Unsupported FAHCE status.")
        if fahce_status == "INDEPENDENTLY_VERIFIED":
            raise TransitionError("Independent FAHCE verification is not configured.")
        transaction_id = transaction_id or str(uuid4())
        with self.lock:
            if self.read(transaction_id):
                raise TransitionError("Transaction identity already exists.")
            record = {
                "schema": "TOOL_OFFER_TRANSACTION_V1", "id": transaction_id,
                "offer_version": draft["revision"], "offer_hash": digest(draft),
                "source_hash": digest(documents), "source_urls": draft["seller"]["source_urls"],
                "seller": seller, "buyer": buyer, "operation": operation,
                "payment_terms": asdict(terms), "stage": Stage.OFFER_DISCOVERED.value,
                "authorization": "not_granted", "payment": "not_committed",
                "execution": "not_observed", "delivery": "not_evidenced", "settlement": "not_verified",
                "fahce": fahce_status, "fahce_reference": fahce_reference, "events": [],
            }
            record["events"].append(self._event(record, Stage.OFFER_DISCOVERED, seller["id"], "discovery:" + transaction_id, [record["offer_hash"], record["source_hash"]], at))
            if hasattr(self.store, "compare_and_swap"):
                if not self.store.compare_and_swap(self._key(transaction_id), None, {"commercial_transaction": record}):
                    raise TransitionError("Transaction identity already exists.")
            else:
                self.store.save(self._key(transaction_id), {"commercial_transaction": record})
            return record

    @staticmethod
    def _event(record, stage, actor, idempotency_key, evidence, at):
        previous = record["events"][-1]["hash"] if record["events"] else None
        event = {
            "transaction_id": record["id"], "offer_version": record["offer_version"],
            "offer_hash": record["offer_hash"], "source_hash": record["source_hash"],
            "seller": record["seller"], "buyer": record["buyer"], "operation": record["operation"],
            "payment_terms": record["payment_terms"], "stage": stage.value,
            "authorization": record["authorization"], "payment": record["payment"],
            "execution": record["execution"], "delivery": record["delivery"], "settlement": record["settlement"],
            "fahce": record["fahce"], "fahce_reference": record["fahce_reference"],
            "actor": actor, "idempotency_key": idempotency_key,
            "evidence": evidence, "time": at or datetime.now(timezone.utc).isoformat(),
            "unresolved": [] if stage == Stage.SETTLEMENT_VERIFIED else ["Independent settlement evidence", "Seller claims unverified"],
            "next_permitted": [value.value for value in NEXT.get(stage, ())], "previous_hash": previous,
        }
        event["hash"] = digest(event)
        return event

    def transition(self, transaction_id, stage, actor, idempotency_key, evidence=(), *, at=None):
        stage = Stage(stage)
        with self.lock:
            record = self.read(transaction_id)
            if not record:
                raise TransitionError("Unknown transaction.")
            if any(event["idempotency_key"] == idempotency_key for event in record["events"]):
                raise TransitionError("Duplicate transition; no external action repeated.")
            if stage not in NEXT.get(Stage(record["stage"]), ()):
                raise TransitionError("Out-of-order or terminal transition.")
            expected = record["buyer"]["id"] if stage in (Stage.BUYER_APPROVED, Stage.PAYMENT_COMMITTED, Stage.REJECTED) else record["seller"]["id"]
            if stage == Stage.SETTLEMENT_VERIFIED:
                raise TransitionError("Independent settlement verifier is not configured.")
            if actor != expected:
                raise TransitionError("Actor is not authorized for this transition.")
            if stage in (Stage.BUYER_APPROVED, Stage.PAYMENT_REQUESTED, Stage.PAYMENT_COMMITTED):
                deadline = datetime.fromisoformat(record["payment_terms"]["deadline"].replace("Z", "+00:00"))
                if datetime.now(timezone.utc) >= deadline:
                    raise TransitionError("Authorization deadline has expired.")
            if stage in (Stage.PAYMENT_COMMITTED, Stage.EXECUTION_OBSERVED, Stage.DELIVERY_EVIDENCED, Stage.SETTLEMENT_VERIFIED) and not evidence:
                raise TransitionError("Independent evidence reference required; no inferred outcome.")
            before = deepcopy(record)
            record["stage"] = stage.value
            if stage == Stage.BUYER_APPROVED:
                record["authorization"] = "buyer_approved_exact_terms"
            if stage == Stage.PAYMENT_COMMITTED:
                record["payment"] = "test_commit_not_settled" if record["payment_terms"]["method"] == "test_only" else "committed_not_verified"
            if stage == Stage.EXECUTION_OBSERVED:
                record["execution"] = "observed_not_attested"
            if stage == Stage.DELIVERY_EVIDENCED:
                record["delivery"] = "evidenced_not_settled"
            if stage == Stage.SETTLEMENT_VERIFIED:
                record["settlement"] = "independent_evidence_recorded"
            record["events"].append(self._event(record, stage, actor, idempotency_key, list(evidence), at))
            if hasattr(self.store, "compare_and_swap"):
                if not self.store.compare_and_swap(self._key(transaction_id), {"commercial_transaction": before}, {"commercial_transaction": record}):
                    raise TransitionError("Concurrent transition; inspect transaction status before proceeding.")
            else:
                self.store.save(self._key(transaction_id), {"commercial_transaction": record})
            return record


def receipt(record):
    body = {"schema": "TOOL_OFFER_TEST_RECEIPT_V1", "transaction_id": record["id"], "offer_hash": record["offer_hash"],
            "source_hash": record["source_hash"], "last_event_hash": record["events"][-1]["hash"],
            "stage": record["stage"], "settlement": record["settlement"],
            "verification_boundary": "Local hash-chain integrity only; no signature, payment proof, or seller attestation."}
    return {**body, "receipt_hash": digest(body)}


def verify_receipt(record, candidate_receipt):
    if not record.get("events"):
        return {"local_integrity": False, "independent_verification": False, "unverified_claims": ["Event chain missing"]}
    previous = None
    for event in record["events"]:
        event_body = {key: value for key, value in event.items() if key != "hash"}
        if event["previous_hash"] != previous or digest(event_body) != event["hash"]:
            return {"local_integrity": False, "independent_verification": False, "unverified_claims": ["Event chain changed"]}
        previous = event["hash"]
    last = record["events"][-1]
    bound = ("transaction_id", "offer_version", "offer_hash", "source_hash", "seller", "buyer", "operation", "payment_terms", "stage", "authorization", "payment", "execution", "delivery", "settlement", "fahce", "fahce_reference")
    valid = all(last[field] == (record["id"] if field == "transaction_id" else record[field]) for field in bound if field != "offer_version")
    valid = valid and last["offer_version"] == record["offer_version"] and receipt(record) == candidate_receipt
    return {"local_integrity": valid, "independent_verification": False,
            "unverified_claims": ["Seller capability", "Buyer identity provenance", "Payment settlement", "Independent execution"]}
