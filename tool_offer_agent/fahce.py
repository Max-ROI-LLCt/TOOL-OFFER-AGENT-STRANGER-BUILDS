"""FAHCE contract adapter, intentionally WITHOUT a payment implementation.

Only an owner-installed, server-side AuthorizedPaymentTransport may execute.
No wallet keys, static payment headers, or unauthenticated POST fallback exist.
"""

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol
from uuid import UUID

PENDING = "FAHCE check pending configuration"
ENDPOINT = "https://fahce.kinganlogic.com/api/v1/diagnose"
SCOPE = "FAHCE checks supplied evidence, not source authenticity, seller trust, publication, purchases, or external execution."


class ContractError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(value):
    """Local version binding, NOT an assertion about FAHCE's input hash algorithm."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def machine_request(draft, documents):
    evidence = []
    for i, document in enumerate(documents):
        label = document["source_url"]
        while utf16_length(label) > 160:
            label = label[:-1]
        evidence.append({"id": f"doc_{i + 1}", "kind": "document", "source_label": label, "text": document["text"]})
    request = {"schema": "FAHCE_MACHINE_REQUEST_V1", "candidate_output": canonical_json(draft), "evidence": evidence}
    if not 1 <= utf16_length(request["candidate_output"]) <= 200000 or len(evidence) > 12:
        raise ContractError("FAHCE request exceeds field limits.")
    if any(utf16_length(item["text"]) > 200000 for item in evidence):
        raise ContractError("FAHCE evidence exceeds field limits.")
    if len(canonical_json(request).encode("utf-8")) > 524288:
        raise ContractError("FAHCE request exceeds the 524288-byte aggregate limit.")
    return request


@dataclass(frozen=True)
class AuthorizedResponse:
    body: dict
    request_body_sha256: str
    bound_input_hash: str
    settlement_reference: str | None = None


class AuthorizedPaymentTransport(Protocol):
    """Trusted server-side boundary; NEVER supplied by chat or fetched documents.

    Implementations must obtain owner-approved wallet/provider, budgets, and
    acceptance of the current legal publication hash, perform documented x402-v2
    REST challenge/retry on the unchanged body, bind/verify the response to that
    exact request (including FAHCE input hashing and attestation), and retain
    recovery credentials and gateway PAYMENT-RESPONSE securely outside exports.
    request_body_sha256 identifies the exact canonical request sent;
    bound_input_hash is independently validated, not copied blindly from body.
    settlement_reference is a safe owner-facing reference only, never a token.
    Never automatically authorize a second payment after ambiguous delivery.
    This interface does not itself perform any of these operations.
    """

    def execute(self, endpoint: str, request: dict, *, idempotency_key: str) -> AuthorizedResponse: ...


def parse_response(response: AuthorizedResponse, request: dict, draft_hash: str):
    body = response.body
    required = {"schema", "operation", "request_id", "input_hash", "diagnosis", "repair", "verification", "billing", "receipt", "next_safe_action"}
    if not isinstance(body, dict) or not required.issubset(body):
        raise ContractError("Incomplete FAHCE response.")
    if body["schema"] != "FAHCE_MACHINE_RESPONSE_V1" or body["operation"] != "diagnose":
        raise ContractError("Unexpected FAHCE response contract or operation.")
    if response.request_body_sha256 != fingerprint(request):
        raise ContractError("Response is not bound to this request.")
    if not re.fullmatch(r"[a-f0-9]{64}", str(body["input_hash"])) or response.bound_input_hash != body["input_hash"]:
        raise ContractError("FAHCE input binding was not verified by the authorized transport.")
    receipt = body["receipt"]
    try:
        UUID(body["request_id"])
        if not isinstance(receipt, dict) or not {"case_id", "run_id", "input_hash", "result_hash", "hash_scheme", "provider", "model", "engine_version", "created_at", "response_hash_scheme", "response_hash", "payment_status", "payment_receipt", "settled_price_atomic_units"}.issubset(receipt):
            raise ValueError()
        if receipt["case_id"] != body["request_id"] or receipt["run_id"] != body["request_id"] or receipt["input_hash"] != body["input_hash"]:
            raise ValueError()
        if receipt["payment_status"] != "AUTHORIZED_PENDING_GATEWAY_SETTLEMENT" or receipt["payment_receipt"] is not None or receipt["settled_price_atomic_units"] is not None:
            raise ValueError()
        for key in ("result_hash", "response_hash"):
            if not re.fullmatch(r"[a-f0-9]{64}", receipt[key]):
                raise ValueError()
        diagnosis = body["diagnosis"]
        if not isinstance(diagnosis, dict) or not {"state", "claims", "contradictions", "missing_evidence", "missing_evidence_details", "claim_ceiling"}.issubset(diagnosis):
            raise ValueError()
        if diagnosis["state"] not in ("HOLD", "BLOCK", "QUARANTINE", "REPAIR_REQUIRED", "CLEAR_WITH_CEILING") or not isinstance(diagnosis["claim_ceiling"], str):
            raise ValueError()
        for field in ("claims", "contradictions", "missing_evidence", "missing_evidence_details"):
            if not isinstance(diagnosis[field], list):
                raise ValueError()
        for claim in diagnosis["claims"]:
            if not isinstance(claim, dict) or not {"id", "claim", "source", "support", "evidence_refs"}.issubset(claim):
                raise ValueError()
            if claim["support"] not in ("SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "UNVERIFIED") or not isinstance(claim["evidence_refs"], list):
                raise ValueError()
        verification = body["verification"]
        if type(verification["verified"]) is not bool or verification["external_execution_verified"] is not False or not isinstance(verification["scope"], str):
            raise ValueError()
        billing = body["billing"]
        if billing["determination_status"] not in ("DETERMINATION_COMPLETE", "DETERMINATION_COMPLETE_NEGATIVE"):
            raise ValueError()
        if type(billing["billable"]) is not bool or type(billing["free_retry"]) is not bool or "reason" not in billing:
            raise ValueError()
        if not isinstance(body["next_safe_action"]["action"], str) or not isinstance(body["next_safe_action"]["reason"], str):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ContractError("Invalid or incomplete FAHCE determination/receipt.") from None
    return {
        "status": "returned", "draft_hash": draft_hash,
        "request_hash": fingerprint(request),
        "receipt_reference": f"https://fahce.kinganlogic.com/api/v1/receipts/{body['request_id']}",
        "settlement_reference": response.settlement_reference,
        "settlement_status": "reference_returned" if response.settlement_reference else "not_confirmed",
        "result": body, "scope": SCOPE,
    }


class FahceClient:
    def __init__(self, transport: AuthorizedPaymentTransport | None = None):
        self.transport = transport

    @property
    def configured(self):
        return self.transport is not None

    def check(self, draft, documents, *, idempotency_key):
        if self.transport is None:
            return {"status": "pending_configuration", "message": PENDING, "draft_hash": fingerprint(draft)}
        request = machine_request(draft, documents)
        response = self.transport.execute(ENDPOINT, request, idempotency_key=idempotency_key)
        return parse_response(response, request, fingerprint(draft))
