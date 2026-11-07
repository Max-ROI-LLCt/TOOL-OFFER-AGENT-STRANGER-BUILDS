"""Wallet-approved FAHCE checkout bridge. No wallet keys or signing authority."""
import hashlib
import json
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit

from .fahce import canonical_json, fingerprint, machine_request
from .drafting import render_draft


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, redirect_url):
        return None


def checkout_request(draft, documents):
    request = machine_request(draft, documents)
    # The legacy purchase representation remains inspectable and unchanged.
    request["candidate_output"] = render_draft(draft)
    if len(canonical_json(request).encode()) > 524288:
        raise ValueError("FAHCE request exceeds its aggregate size limit.")
    return request


def free_preflight(draft, documents, *, transport=None):
    """Screen the exact checkout input without creating a checkout or authority."""
    machine = checkout_request(draft, documents)
    encoded = canonical_json({"operation": "diagnose", "request": machine}).encode()
    if len(encoded) > 524288:
        raise ValueError("FAHCE preflight wrapper exceeds its aggregate size limit.")
    request = Request("https://fahce.kinganlogic.com/api/v1/machine/preflight", data=encoded,
                      headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "ToolOfferAgent/0.2"}, method="POST")
    opener = transport or build_opener(NoRedirects()).open
    with opener(request, timeout=20) as response:
        result = json.loads(response.read(5000000))
    screen = result.get("capability_screen", {}) if isinstance(result, dict) else {}
    if (not isinstance(result, dict) or result.get("schema") != "FAHCE_MACHINE_PREFLIGHT_V1"
            or result.get("syntax_valid") is not True or result.get("engine_executed") is not False
            or result.get("payment_authority") is not False or not isinstance(screen, dict)
            or screen.get("semantic_status") not in {"NOT_ESTABLISHED", "SEMANTICALLY_UNSUPPORTED"}
            or screen.get("structural_status") not in {"STRUCTURALLY_INTERPRETABLE", "STRUCTURAL_LIMITATION"}
            or not isinstance(screen.get("candidate_limitations"), list) or not isinstance(screen.get("limitations"), list)):
        raise ValueError("Invalid non-executing preflight contract.")
    return {"request_sha256": fingerprint(machine), "candidate_output": machine["candidate_output"], "screen": screen}


class FahceCheckoutClient:
    def __init__(self, endpoint, token, transport=None):
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment or not token:
            raise ValueError("FAHCE checkout requires a fixed HTTPS origin and server-side credential.")
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.transport = transport or build_opener(NoRedirects()).open

    def _call(self, path, token, body=None):
        request = Request(self.endpoint + path,
                          data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                          headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "ToolOfferAgent/0.2", "Accept": "application/json"},
                          method="POST" if body is not None else "GET")
        try:
            with self.transport(request, timeout=20) as response:
                raw = response.read(5000000)
            result = json.loads(raw)
            if not isinstance(result, dict) or "error" in result:
                raise ValueError()
            return result
        except Exception:
            raise RuntimeError("FAHCE checkout is unavailable. Existing payment state is preserved; do not pay again.") from None

    def prepare(self, draft, documents, checkout_key):
        request = checkout_request(draft, documents)
        # Preserve the existing reviewed checkout contract. A structured preview is
        # separately inspectable via export representation, but free preflight
        # does not prove that the engine interprets its nested claims. Do not
        # silently switch payload formats or change existing purchase hashes.
        encoded = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > 524288:
            raise ValueError("FAHCE request exceeds its aggregate size limit.")
        request_hash = hashlib.sha256(encoded.encode()).hexdigest()
        result = self._call("/v1/checkouts", self.token,
                            {"request": request, "draftHash": fingerprint(draft), "checkoutKey": checkout_key})
        if (result.get("requestSha256") != request_hash or result.get("draftHash") != fingerprint(draft)
                or result.get("id") != checkout_key
                or result.get("url") != self.endpoint + "/checkout/" + checkout_key + "/#access=" + str(result.get("accessToken"))):
            raise RuntimeError("Checkout preparation binding mismatch. No payment requested.")
        return {**result, "draft_hash": fingerprint(draft)}

    def status(self, checkout):
        result = self._call("/checkout/" + checkout["id"] + "/api/status", checkout["accessToken"])
        revision = result.get("representationRevision")
        reviewed = (isinstance(revision, dict)
                    and revision.get("scope") == "BUYER_REVIEWED_REPRESENTATION"
                    and revision.get("evidenceUnchanged") is True
                    and isinstance(revision.get("acceptedAt"), str) and bool(revision["acceptedAt"])
                    and revision.get("sourceRequestSha256") == checkout["requestSha256"]
                    and revision.get("requestSha256") == result.get("requestSha256")
                    and isinstance(result.get("requestSha256"), str) and len(result["requestSha256"]) == 64
                    and all(character in "0123456789abcdef" for character in result["requestSha256"]))
        if (result.get("requestSha256") != checkout["requestSha256"] and not reviewed) or result.get("draftHash") != checkout["draft_hash"]:
            raise RuntimeError("Checkout result belongs to different input. Do not pay again.")
        return result
