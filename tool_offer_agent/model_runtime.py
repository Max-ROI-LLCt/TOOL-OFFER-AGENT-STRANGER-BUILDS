"""ASI client diagnostics and bounded transient recovery; never logs provider text."""

import threading
from uuid import uuid4
import logging
import time
import base64
import json
import os
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from urllib.parse import urlsplit

TRACE = threading.local()


class SpendingError(RuntimeError):
    """No inference may proceed without a durable, evidenced reservation."""


class SpendingGuard:
    # Native and machine handlers share this ledger, including extraction calls.
    # Hosted operation requires a single writer; this is not a distributed lock.
    lock = threading.Lock()
    key = "operator_inference_spending_v1"

    def __init__(self, store, policy=None, clock=time.time):
        self.store, self.clock = store, clock
        self.policy = policy

    def configuration(self):
        try:
            p = self.policy
            if not isinstance(p, dict) or p.get("model") != "asi1" or p.get("single_writer") is not True:
                raise ValueError()
            if not isinstance(p.get("owner_actors", []), list) or any(not isinstance(actor, str) or not actor.startswith(("machine:", "native:")) for actor in p.get("owner_actors", [])):
                raise ValueError()
            if not isinstance(p.get("billing_bound_evidence"), str) or not p["billing_bound_evidence"].strip():
                raise ValueError()
            expires = datetime.fromisoformat(p["valid_until"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires.timestamp() <= self.clock():
                raise ValueError()
            cap = Decimal(str(p["daily_usd"]))
            reserve = Decimal(0)
            for kind in ("prompt", "completion", "reasoning"):
                tokens = p["max_billed_" + kind + "_tokens"]
                rate = Decimal(str(p[kind + "_usd_per_million"]))
                if type(tokens) is not int or tokens < 1 or not rate.is_finite() or rate <= 0:
                    raise ValueError()
                reserve += tokens * rate  # USD * 1,000,000; round UP to microdollars.
            if not cap.is_finite() or cap <= 0:
                raise ValueError()
            return p, int((cap * 1000000).to_integral_value(rounding=ROUND_FLOOR)), int(reserve.to_integral_value(rounding=ROUND_CEILING))
        except (ValueError, KeyError, TypeError, InvalidOperation, AttributeError):
            raise SpendingError("SPENDING_EVIDENCE_UNAVAILABLE") from None

    def reserve(self, model):
        p, cap, amount = self.configuration()
        if model != p["model"]:
            raise SpendingError("SPENDING_MODEL_UNPRICED")
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        with self.lock:
            ledger = self.store.load(self.key).get("spending", {})
            if ledger.get("blocked"):
                raise SpendingError("SPENDING_RECONCILIATION_REQUIRED")
            if ledger.get("day") != day:
                ledger = {"day": day, "reserved_micro_usd": 0}
            owner = getattr(TRACE, "spending_actor", None) in p.get("owner_actors", [])
            if not owner and ledger["reserved_micro_usd"] + amount > cap:
                raise SpendingError("SPENDING_DAILY_LIMIT")
            if owner:
                ledger["owner_reserved_micro_usd"] = ledger.get("owner_reserved_micro_usd", 0) + amount
            else:
                ledger["reserved_micro_usd"] += amount
            self.store.save(self.key, {"spending": ledger})
            if self.store.load(self.key).get("spending") != ledger:
                raise SpendingError("SPENDING_STORAGE_UNAVAILABLE")
        return amount

    def verify_usage(self, response):
        p, _, _ = self.configuration()
        usage = getattr(response, "usage", None)
        values = {"prompt": getattr(usage, "prompt_tokens", None),
                  "completion": getattr(usage, "completion_tokens", None),
                  "reasoning": getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None)}
        if values["reasoning"] is None:
            values["reasoning"] = getattr(usage, "reasoning_tokens", None)
        if (getattr(response, "model", None) != p["model"] or
                any(type(v) is not int or v < 0 or v > p["max_billed_" + k + "_tokens"] for k, v in values.items())):
            with self.lock:
                ledger = self.store.load(self.key).get("spending", {})
                ledger["blocked"] = True
                self.store.save(self.key, {"spending": ledger})
            raise SpendingError("SPENDING_USAGE_UNVERIFIABLE")
        # Reservations are never refunded, including cache discounts, errors,
        # timeouts and lost replies. Reasoning is conservatively priced separately.


def configure_spending(client, store):
    from .machine_contract import CONTRACT
    if CONTRACT.get("spending_policy", {}).get("mode") == "call_limits_only":
        # Explicit owner policy: abuse controls remain in the gateway and traced
        # attempt budget. No dollar ceiling or pricing-evidence gate is applied.
        client._tool_offer_spending_guard = None
        client._tool_offer_spending_mode = "call_limits_only"
        return
    try:
        policy = json.loads(os.environ["TOOL_OFFER_SPENDING_POLICY"]) if "TOOL_OFFER_SPENDING_POLICY" in os.environ else CONTRACT.get("spending_policy")
        if not isinstance(policy, dict) or Decimal(str(policy.get("daily_usd"))) != Decimal(str(CONTRACT.get("spending_policy", {}).get("daily_usd"))):
            policy = None
        elif re.fullmatch(r"agent1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{59}", os.getenv("TOOL_OFFER_OWNER_EXPORT_ADDRESS", "")):
            # Reuse the existing authenticated owner boundary; never infer an
            # exemption from a display name, message or client-supplied field.
            policy = {**policy, "owner_actors": [*policy.get("owner_actors", []), "native:" + os.environ["TOOL_OFFER_OWNER_EXPORT_ADDRESS"]]}
    except (ValueError, InvalidOperation):
        policy = None
    client._tool_offer_spending_guard = SpendingGuard(store, policy)

def traced(function, *args, spending_actor=None, **kwargs):
    TRACE.events = []
    TRACE.remaining = 2
    TRACE.deadline = time.monotonic() + 60
    TRACE.spending_actor = spending_actor
    try:
        return function(*args, **kwargs), TRACE.events
    finally:
        TRACE.events = None
        TRACE.remaining = None
        TRACE.deadline = None
        TRACE.spending_actor = None

def event(value):
    events = getattr(TRACE, "events", None)
    if isinstance(events, list):
        events.append(value)

LOGGER = logging.getLogger("tool_offer_model")
RETRYABLE = {429, 500, 502, 503, 504}
HARD_QUOTA = {"insufficient_quota", "quota_exceeded", "account_blocked"}
SAFE_CODES = {"invalid_api_key", "invalid_token", "token_expired", "authentication_error",
              "permission_error", "permission_denied", "insufficient_quota", "quota_exceeded",
              "rate_limit_exceeded", "account_blocked", "model_not_found", "unknown_parameter"}


def error_metadata(error):
    status = getattr(error, "status_code", None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    body = getattr(error, "body", None)
    detail = body.get("error", body) if isinstance(body, dict) else {}
    code = detail.get("code") if isinstance(detail, dict) else None
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    content_type = headers.get("content-type", "") if hasattr(headers, "get") else ""
    kind = "json" if isinstance(content_type, str) and "json" in content_type else "html" if isinstance(content_type, str) and "html" in content_type else "other"
    # Classify known failure explanations without ever retaining their text.
    detail_text = str(detail.get("message", "")).casefold() if isinstance(detail, dict) else ""
    reason = next((label for token, label in (
        ("expired", "expired_credential"), ("quota", "quota_or_billing"),
        ("permission", "permission_denied"), ("invalid api key", "invalid_credential"),
        ("invalid token", "invalid_credential"), ("api key", "credential_rejected")) if token in detail_text), "unclassified")
    if isinstance(code, str) and code in HARD_QUOTA:
        reason = "quota_or_billing"
    return {"http_status": status, "provider_code": code if isinstance(code, str) and code in SAFE_CODES else "unavailable", "response_kind": kind, "reason": reason}


def completion(client, **kwargs):
    """Retry one explicit transient rejection; never retry auth, timeouts or parsing."""
    request_id = uuid4().hex
    for attempt in range(2):
        started = time.monotonic()
        remaining = getattr(TRACE, "remaining", None)
        deadline = getattr(TRACE, "deadline", None)
        if remaining is not None:
            if remaining <= 0 or deadline - started < 1:
                raise RuntimeError("Inference operation budget exhausted; no request sent.")
            TRACE.remaining -= 1
            kwargs["timeout"] = min(kwargs.get("timeout", 25), deadline - started)
        guard = vars(client).get("_tool_offer_spending_guard")
        # Real provider clients cannot bypass configuration. Test fakes can be
        # used without a guard; they never contact the provider.
        if guard is None and type(client).__module__.startswith("openai") and vars(client).get("_tool_offer_spending_mode") != "call_limits_only":
            raise SpendingError("SPENDING_EVIDENCE_UNAVAILABLE")
        sent = False
        safe = {}
        try:
            reserved = guard.reserve(kwargs.get("model")) if guard else None
            sent = True
            response = client.chat.completions.create(**kwargs)
            # Retain only allowlisted response metadata, never provider text/headers.
            usage = getattr(response, "usage", None)
            safe = {"outcome": "completion_received", "requested_model": "asi1" if kwargs.get("model") == "asi1" else "other",
                    "response_model": "asi1" if getattr(response, "model", None) == "asi1" else "other_or_unavailable"}
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(usage, name, None)
                if type(value) is int and value >= 0:
                    safe[name] = value
            safe.update(request_id=request_id, attempt=attempt + 1, elapsed_ms=int((time.monotonic() - started) * 1000))
            provider_id = getattr(response, "_request_id", None) or getattr(response, "id", None)
            if isinstance(provider_id, str) and 1 <= len(provider_id) <= 256:
                safe["provider_request_id_sha256"] = hashlib.sha256(provider_id.encode()).hexdigest()
            for group, field, label in (("prompt_tokens_details", "cached_tokens", "cached_tokens"), ("completion_tokens_details", "reasoning_tokens", "reasoning_tokens")):
                value = getattr(getattr(usage, group, None), field, None)
                if type(value) is int and value >= 0:
                    safe[label] = value
            if "reasoning_tokens" not in safe:
                value = getattr(usage, "reasoning_tokens", None)
                if type(value) is int and value >= 0:
                    safe["reasoning_tokens"] = value
            choices = getattr(response, "choices", None)
            finish = getattr(choices[0], "finish_reason", None) if isinstance(choices, list) and choices else None
            safe["finish_reason"] = finish if finish in {"stop", "length", "content_filter", "tool_calls"} else "unavailable"
            if guard:
                safe["reserved_micro_usd"] = reserved
                guard.verify_usage(response)
            event(dict(safe))
            client._tool_offer_latest_provider_status = safe
            return response
        except SpendingError:
            event({**safe, "outcome": "spending_blocked", "request_id": request_id, "attempt": attempt + 1, "request_sent": sent})
            raise
        except Exception as error:
            safe = error_metadata(error)
            event({**safe, "outcome": "api_timeout" if type(error).__name__ in {"APITimeoutError", "TimeoutError"} else "api_failure",
                   "request_id": request_id, "attempt": attempt + 1, "elapsed_ms": int((time.monotonic() - started) * 1000)})
            LOGGER.warning("ASI inference failure: http_status=%s provider_code=%s response_kind=%s reason=%s attempt=%s",
                           safe["http_status"], safe["provider_code"], safe["response_kind"], safe["reason"], attempt + 1)
            if attempt or safe["provider_code"] in HARD_QUOTA or safe["http_status"] not in RETRYABLE:
                raise
            # Keep the entire hosted invocation below its 90-second budget.
            time.sleep(0.5)


def client_configuration(base_url, api_key):
    parsed = urlsplit(base_url)
    # The hosting platform may inject an internal HTTP proxy. Preserve that
    # server-owned route rather than substituting the public ASI endpoint.
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not isinstance(api_key, str) or not api_key.strip()):
        raise RuntimeError("ASI provider requires a server-configured HTTP(S) endpoint and credential.")
    expiry = "not_jwt_or_unavailable"
    if len(api_key.split(".")) == 3:
        try:
            payload = api_key.split(".")[1]
            data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if type(data.get("exp")) in (int, float):
                expiry = "expired_claim" if data["exp"] <= time.time() else "future_claim"
        except (ValueError, TypeError, UnicodeError):
            pass
    LOGGER.warning("ASI inference configuration: scheme=%s host=%s credential_present=true bearer_prefix=%s jwt_expiry=%s",
                   parsed.scheme, parsed.hostname, api_key.lower().startswith("bearer "), expiry)
    return {"scheme": parsed.scheme, "host": parsed.hostname, "credential_present": True,
            "bearer_prefix": api_key.lower().startswith("bearer "), "jwt_expiry": expiry}

