"""Local test fakes only. No network, model requests, or paid executions."""

import json
from pathlib import Path
from uuid import uuid4

from tool_offer_agent.documents import Document
from tool_offer_agent.fahce import AuthorizedResponse, fingerprint
from tool_offer_agent.storage import StateStore

FIXTURES = Path(__file__).parent / "fixtures"
DOC_URL = "https://docs.example.com/openapi.json"
TOOL_URL = "https://api.example.com/"
SPEC = {
    "openapi": "3.1.0", "info": {"title": "Test-only conversion tool", "version": "1"},
    "paths": {"/convert": {"post": {"summary": "Convert CSV rows into JSON records", "requestBody": {"content": {"text/csv": {"schema": {"type": "string"}}}}, "responses": {"200": {"description": "JSON records"}}}}},
    "x-limitations": "UTF-8 CSV only; maximum 1000 rows.", "x-pricing": "USD 0.02 per invocation",
}
INTAKE = f"tool_url: {TOOL_URL}\ndocs: {DOC_URL}\ncustomer: Accounting app developers\npricing: USD 0.02 per invocation\npayment: Use the seller's public billing page\naccess: Obtain an API key through the public dashboard; never paste it here\ninvocation: POST /convert with CSV body and Authorization: Bearer <API_KEY>"


def card_selection(payload, cta):
    if cta in payload:
        return payload[cta]['selection']
    action = {'approve_cta': 'reviewed', 'reject_cta': 'edit'}[cta]
    return next(child['action']['selection'] for child in payload['root']['children']
                if child['type'] == 'button' and child['action']['selection']['action'] == action)


class FakeFetcher:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.text = json.dumps(SPEC)

    def fetch(self, url):
        self.calls.append(url)
        if self.fail:
            raise RuntimeError("sensitive-error-detail")
        return Document(url, url, self.text, "application/json")


class StoreTestMixin:
    def setUp(self):
        super().setUp()
        directory = Path("tests") / ".state"
        directory.mkdir(exist_ok=True)
        path = directory / f"{uuid4().hex}.sqlite3"
        self.store = StateStore(path)
        self.addCleanup(self._cleanup_dir, directory)
        self.addCleanup(lambda: path.unlink(missing_ok=True))

    @staticmethod
    def _cleanup_dir(directory):
        # Another test may still own a database in this project-local directory.
        try:
            directory.rmdir()
        except OSError:
            pass


class FakeAuthorizedTransport:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.mutate = None

    def execute(self, endpoint, request, *, idempotency_key):
        self.calls.append((endpoint, request, idempotency_key))
        if self.fail:
            raise RuntimeError("sensitive-payment-error")
        body = json.loads((FIXTURES / "diagnose_response.test-only.json").read_text(encoding="utf-8"))
        if self.mutate:
            self.mutate(body)
        return AuthorizedResponse(body=body, request_body_sha256=fingerprint(request), bound_input_hash="a" * 64)
