import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from tests.support import StoreTestMixin
from tool_offer_agent.documents import Document, _TextParser
from tool_offer_agent.drafting import CATEGORIES, OpenAIQuoteExtractor
from tool_offer_agent.storage import StateStore
from tool_offer_agent.workflow import Workflow


PUBLIC_URL = "https://open-meteo.com/en/docs"
HTML_SAMPLE = """<h2>API Documentation</h2>
<p>The API endpoint /v1/forecast accepts a geographical coordinate, a list of weather variables and responds with a JSON hourly weather forecast for 7 days.</p>
<table><tr><th>Parameter</th><th>Format</th><th>Required</th><th>Default</th><th>Description</th></tr>
<tr><th>latitude, longitude</th><td>Floating point</td><td>Yes</td><td></td><td>Geographical WGS84 coordinates of the location.</td></tr>
<tr><th>hourly</th><td>String array</td><td>No</td><td></td><td>A list of weather variables which should be returned.</td></tr></table>
<h2>JSON Return Object</h2>
<table><tr><th>Parameter</th><th>Format</th><th>Description</th></tr>
<tr><th>latitude, longitude</th><td>Floating point</td><td>WGS84 of the center of the weather grid-cell used to generate this forecast.</td></tr>
<tr><th>hourly</th><td>Object</td><td>For every chosen hourly weather variable, the data is provided as a numeric array.</td></tr></table>"""


class OpenMeteoRegressionTests(StoreTestMixin, TestCase):
    def test_unverbatim_model_output_preserves_v17_without_repeated_model_spend(self):
        parser = _TextParser()
        parser.feed(HTML_SAMPLE)
        text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
        payload = {category: [] for category in CATEGORIES}
        payload["inputs"] = [{"text": "Open-Meteo independently verifies every location.", "source_url": PUBLIC_URL}]
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)), finish_reason="stop")]
        )
        workflow = Workflow(store=self.store, extractor=OpenAIQuoteExtractor(client))
        sender, session = "seller", "existing-v17"
        state_key = StateStore.key(sender, session)
        state = self.store.load(state_key)
        state.update(fields={"tool_url": "https://api.open-meteo.com/v1/forecast", "docs": [PUBLIC_URL],
                             "customer": "API integrators", "pricing": "undecided", "payment": "none",
                             "access": "public", "invocation": "GET /v1/forecast?latitude=<lat>&longitude=<lon>"},
                     revision=17, draft={"schema": "TOOL_OFFER_RECORD_V1", "revision": 17,
                                         "seller": {"source_urls": [PUBLIC_URL]}, "offer": {"pricing": "undecided"}},
                     documents=[{"requested_url": PUBLIC_URL, "source_url": PUBLIC_URL, "text": text, "media_type": "text/html"}])
        self.store.save(state_key, state)
        error = workflow.handle(sender, session, "pricing: USD 0.01 per call")
        self.assertIn("MODEL_UNGROUNDED_QUOTE", error)
        self.assertEqual(json.loads(workflow.handle(sender, session, "export json"))["draft"]["revision"], 17)
        self.assertIn("draft limited", workflow.handle(sender, session, "retry"))
        self.assertEqual(client.chat.completions.create.call_count, 1)
        limited = workflow.handle(sender, session, "draft limited")
        self.assertIn("LIMITED deterministic extraction only", limited)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        new_draft = json.loads(workflow.handle(sender, session, "export json"))["draft"]
        self.assertGreater(new_draft["revision"], 17)
        self.assertEqual(new_draft["extraction_mode"], "deterministic_limited")
        self.assertEqual(new_draft["offer"]["pricing"], "USD 0.01 per call")

    def test_v17_shaped_existing_session_stays_intact_until_explicit_refresh(self):
        parser = _TextParser()
        parser.feed(HTML_SAMPLE)
        text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
        fetcher = type("TestFetcher", (), {"fetch": lambda self, url: Document(url, url, text, "text/html")})()
        workflow = Workflow(store=self.store, fetcher=fetcher)
        sender, session = "seller", "existing-conversation"
        fields = {"tool_url": "https://api.open-meteo.com/v1/forecast", "docs": [PUBLIC_URL], "customer": "API integrators", "pricing": "undecided", "payment": "undecided", "access": "public", "invocation": "GET /v1/forecast?latitude=<latitude>&longitude=<longitude>&hourly=temperature_2m"}
        key = StateStore.key(sender, session)
        original = self.store.load(key)
        original.update(fields=fields, revision=17, draft={"schema": "TOOL_OFFER_RECORD_V1", "revision": 17, "seller": {"tool_url": fields["tool_url"], "source_urls": [PUBLIC_URL]}, "offer": {"job": "Weather forecast", "unknown_or_unextracted": ["inputs", "outputs"]}},
                        documents=[{"requested_url": PUBLIC_URL, "source_url": PUBLIC_URL, "text": "Previous v17 extraction", "media_type": "text/html"}])
        self.store.save(key, original)
        restarted = Workflow(store=StateStore(self.store.path), fetcher=fetcher)
        self.assertEqual(json.loads(restarted.handle(sender, session, "export json"))["draft"], original["draft"])
        self.assertIn("saved for review", restarted.handle(sender, session, "status"))
        self.assertEqual(self.store.load(key)["draft"], original["draft"])
        refreshed = restarted.handle(sender, session, "refresh docs")
        record = json.loads(restarted.handle(sender, session, "export json"))["draft"]
        self.assertIn("Draft v1", refreshed)
        self.assertIn("state revision 18", refreshed)
        self.assertEqual(record["revision"], 18)
        self.assertIn("Geographical WGS84", record["offer"]["inputs"][0]["text"])
        self.assertIn("weather grid-cell", record["offer"]["outputs"][0]["text"])
        self.assertTrue(record["deterministic_extraction"]["not_exhaustive"])
        self.assertEqual(record["offer"]["unknown_or_unextracted"], ["limitations", "commercial_terms"])
        self.assertEqual(record["seller"]["source_urls"], [PUBLIC_URL])
