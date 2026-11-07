"""Optional Cloudflare custody for commercial records, not conversation sessions."""

import json
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .storage import StateStore


class CustodyUnavailable(RuntimeError):
    pass


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, redirect_url):
        return None


class CloudflareTransactionStore:
    def __init__(self, endpoint, token, *, allow_local_http=False, transport=None):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "https" and not (allow_local_http and parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"))
                or not parsed.netloc or parsed.path != "/v1/state" or parsed.query or parsed.fragment):
            raise ValueError("Custody endpoint must be an HTTPS /v1/state URL (or explicitly allowed local loopback).")
        if not token:
            raise ValueError("Custody bearer token is required.")
        self.endpoint = endpoint
        self.token = token
        self.transport = transport or build_opener(_NoRedirects()).open

    key = staticmethod(StateStore.key)

    def _request(self, operation, key, **data):
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("Invalid custody key.")
        body = json.dumps({"operation": operation, "key": key, **data}, ensure_ascii=False).encode("utf-8")
        request = Request(self.endpoint, data=body, headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}, method="POST")
        try:
            with self.transport(request, timeout=10) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise ValueError("Invalid custody response.")
            return result
        except Exception:
            raise CustodyUnavailable("Commercial custody outcome unknown; reconcile before attempting another external action.") from None

    def load(self, key):
        result = self._request("load", key)
        if "state" not in result or result["state"] is not None and not isinstance(result["state"], dict):
            raise CustodyUnavailable("Invalid commercial custody state; no external action permitted.")
        return result["state"] or {}

    def compare_and_swap(self, key, before, after):
        result = self._request("compare_and_swap", key, before=before, after=after)
        if type(result.get("swapped")) is not bool:
            raise CustodyUnavailable("Commercial custody acknowledgement missing; reconcile before proceeding.")
        return result["swapped"]
