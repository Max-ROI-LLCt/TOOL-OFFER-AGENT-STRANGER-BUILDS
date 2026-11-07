"""Bounded selection and durable cache regressions; mocked models only."""

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from tool_offer_agent.drafting import (
    CATEGORIES, ExtractionError, MAX_EXCERPT_CHARS, MAX_REQUEST_CHARS,
    OpenAIQuoteExtractor, select_excerpts,
)
from tool_offer_agent.storage import AgentStateStore, StateStore
from tool_offer_agent.workflow import Workflow
from tests.support import DOC_URL, INTAKE, FakeFetcher, StoreTestMixin


def model_client(payload=None):
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=json.dumps(
            payload if payload is not None else {key: [] for key in CATEGORIES})))])
    return client


class ExcerptTests(TestCase):
    def test_aggregate_bound_determinism_and_contiguous_context(self):
        heading = "## Ledger conversion\n"
        quote = "Only available for ledger CSV records."
        docs = [{"source_url": DOC_URL + str(i), "text": (
            "Background information without task details.\n" * 300
            + heading + quote + "\nInputs: ledger CSV\nOutputs: JSON\n"
            + "More background.\n" * 300)} for i in range(3)]
        selected, coverage = select_excerpts(docs, job="ledger conversion", invocation="POST /ledger")
        self.assertEqual((selected, coverage), select_excerpts(docs, job="ledger conversion", invocation="POST /ledger"))
        self.assertLessEqual(sum(len(item["text"]) for item in selected), MAX_EXCERPT_CHARS)
        self.assertEqual(len({item["source_url"] for item in selected}), 3)
        self.assertTrue(coverage["partial"])
        for item in selected:
            doc = next(doc for doc in docs if doc["source_url"] == item["source_url"])
            self.assertEqual(item["text"], doc["text"][item["start"]:item["end"]])
        for doc in docs:
            self.assertTrue(any(heading + quote in item["text"] for item in selected if item["source_url"] == doc["source_url"]))
        self.assertEqual(coverage["supplied_chars"], sum(item["supplied_chars"] for item in coverage["documents"]))

    def test_full_small_sources_and_task_relevance(self):
        docs = [{"source_url": DOC_URL, "text": "Heading\nInputs: CSV\nOutputs: JSON"}]
        selected, coverage = select_excerpts(docs)
        self.assertEqual(selected[0]["text"], docs[0]["text"])
        self.assertFalse(coverage["partial"])
        text = "Neutral introduction.\n" * 500 + "## Ledger\nLedger conversion takes CSV.\n" + "Neutral tail.\n" * 500
        selected, _ = select_excerpts([{"source_url": DOC_URL, "text": text}], job="ledger conversion")
        self.assertTrue(any("## Ledger\nLedger conversion" in item["text"] for item in selected))

    def test_quote_in_full_document_but_not_sent_is_rejected(self):
        text = "".join(f"Unrelated section {i:04d} contains detail number {i:04d}.\n" for i in range(700))
        docs = [{"source_url": DOC_URL, "text": text}]
        selected, _ = select_excerpts(docs)
        omitted = next(line for line in text.splitlines() if not any(line in item["text"] for item in selected))
        payload = {key: [] for key in CATEGORIES}
        payload["inputs"] = [{"source_url": DOC_URL, "text": omitted}]
        client = model_client(payload)
        with self.assertRaisesRegex(ExtractionError, "MODEL_QUOTE_OUTSIDE_EXCERPTS"):
            OpenAIQuoteExtractor(client).extract(docs)
        sent = json.loads(client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(sent["untrusted_documents"], selected)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_scope_cannot_cross_excerpt_boundaries_and_location_is_absolute(self):
        docs = [{"source_url": DOC_URL, "text": "Heading\nquote\n" * 2000}]
        excerpts = [{"source_url": DOC_URL, "start": 0, "end": 7, "text": "Heading"},
                    {"source_url": DOC_URL, "start": 22, "end": 27, "text": "quote"}]
        payload = {key: [] for key in CATEGORIES}
        payload["inputs"] = [{"source_url": DOC_URL, "text": "quote", "scope": "Heading"}]
        with patch("tool_offer_agent.drafting.select_excerpts", return_value=(excerpts, {})):
            with self.assertRaisesRegex(ExtractionError, "MODEL_UNGROUNDED_SCOPE"):
                OpenAIQuoteExtractor(model_client(payload)).extract(docs)
            payload["inputs"][0].pop("scope")
            result = OpenAIQuoteExtractor(model_client(payload)).extract(docs)
            self.assertEqual(result["inputs"][0]["location"], "text[22:27]")

    def test_framed_request_and_hints_are_bounded_before_model_call(self):
        docs = [{"source_url": DOC_URL, "text": "CSV input\n" * 1000}]
        client = model_client()
        extractor = OpenAIQuoteExtractor(client)
        extractor.extract(docs, job="ledger " * 800, invocation="POST /ledger " * 400)
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertLessEqual(len(json.dumps(messages, ensure_ascii=False)), MAX_REQUEST_CHARS)
        payload = json.loads(messages[1]["content"])
        self.assertLessEqual(len(payload["proposed_job"]), 600)
        self.assertTrue(extractor.coverage(docs, job="j" * 601)["hints_truncated"])
        client.reset_mock()
        with self.assertRaisesRegex(ExtractionError, "MODEL_INPUT_BUDGET_EXCEEDED"):
            extractor.extract([{"source_url": "https://example.com/" + "a" * (MAX_REQUEST_CHARS + 100), "text": "CSV"}])
        client.chat.completions.create.assert_not_called()

    def test_extra_entry_fields_and_excess_quotes_rejected(self):
        for entries in ([{"source_url": DOC_URL, "text": "CSV", "verified": True}],
                        [{"source_url": DOC_URL, "text": "CSV"}] * 2):
            payload = {key: [] for key in CATEGORIES}
            payload["inputs"] = entries
            with self.assertRaises(ExtractionError):
                OpenAIQuoteExtractor(model_client(payload)).extract([{"source_url": DOC_URL, "text": "CSV"}])


class CacheTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = model_client()
        self.fetcher = FakeFetcher()
        self.fetcher.text = "This conversion tool accepts CSV and returns JSON.\n" * 300
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, extractor=OpenAIQuoteExtractor(self.client))

    def chat(self, text, sender="seller", session="one"):
        return self.workflow.handle(sender, session, text)

    def state(self):
        return self.store.load(self.store.key("seller", "one"))

    def test_unrelated_revisions_reuse_and_preserve_seller_fields(self):
        self.chat(INTAKE)
        for field, value in (("pricing", "EUR 3 per call"), ("payment", "invoice"), ("access", "public"),
                             ("seller_name", "Ledger seller"), ("customer", "Ledger teams")):
            self.chat(f"{field}: {value}")
            self.assertEqual(self.state()["fields"][field], value)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.assertEqual(self.state()["draft"]["offer"]["pricing"], "EUR 3 per call")
        self.assertEqual(set(self.state()["extraction_cache"]), {"key", "facts", "coverage"})

    def test_context_model_policy_and_content_invalidate(self):
        self.chat(INTAKE)
        for text in ("job: Ledger conversion", "invocation: POST /ledger with CSV", "docs: https://docs.example.com/new"):
            previous = self.state()["extraction_cache"]["key"]
            self.chat(text)
            self.assertNotEqual(previous, self.state()["extraction_cache"]["key"])
        self.assertEqual(self.client.chat.completions.create.call_count, 4)
        self.chat("refresh docs")
        self.assertEqual(self.client.chat.completions.create.call_count, 4)
        self.fetcher.text += "New documented restriction."
        self.chat("refresh docs")
        self.assertEqual(self.client.chat.completions.create.call_count, 5)
        self.workflow.extractor.model = "other-model"
        self.chat("retry")
        self.assertEqual(self.client.chat.completions.create.call_count, 5)
        self.chat("reextract")
        self.assertEqual(self.client.chat.completions.create.call_count, 6)
        with patch("tool_offer_agent.drafting.EXTRACTION_POLICY", "new-policy"):
            self.chat("retry")
            self.assertEqual(self.client.chat.completions.create.call_count, 6)
            self.chat("reextract")
            self.assertEqual(self.client.chat.completions.create.call_count, 7)
        self.assertIsInstance(self.state()["extraction_cache"], dict)

    def test_sqlite_restart_and_session_sender_isolation(self):
        self.chat(INTAKE)
        self.workflow = Workflow(store=StateStore(self.store.path), fetcher=self.fetcher, extractor=OpenAIQuoteExtractor(self.client))
        self.chat("pricing: USD 4 per call")
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.chat(INTAKE, sender="other")
        self.chat(INTAKE, session="other")
        self.assertEqual(self.client.chat.completions.create.call_count, 3)

    def test_platform_restart_and_session_sender_isolation(self):
        values = {}
        storage = Mock()
        storage.get.side_effect = values.get
        storage.set.side_effect = values.__setitem__
        for command in (INTAKE, "pricing: USD 9 per call"):
            self.workflow = Workflow(store=AgentStateStore(storage), fetcher=self.fetcher, extractor=OpenAIQuoteExtractor(self.client))
            self.chat(command)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.chat(INTAKE, sender="other")
        self.chat(INTAKE, session="other")
        self.assertEqual(self.client.chat.completions.create.call_count, 3)
        self.assertEqual(len(values), 3)

    def test_exports_status_draft_retry_do_not_reextract_incomplete_success(self):
        self.chat(INTAKE)
        before = self.state()["draft"]
        for command in ("status", "export json", "export readable", "draft", "retry", "retry"):
            self.chat(command)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.assertEqual(self.state()["draft"], before)
        self.assertIn("reextract", self.chat("retry"))
        exported = json.loads(self.chat("export json"))
        self.assertEqual(exported["source_documents"][0]["text"], self.fetcher.text)
        self.assertTrue(exported["draft"]["model_extraction"]["partial"])
        self.assertIn("PARTIAL", self.chat("status"))
        self.assertIn("PARTIAL", self.chat("export readable"))
        self.chat("reextract")
        self.assertEqual(self.client.chat.completions.create.call_count, 2)
        self.assertEqual(len(self.fetcher.calls), 1)
        self.chat("retry")
        self.assertEqual(self.client.chat.completions.create.call_count, 2)

    def test_scoped_success_survives_cache_without_overriding_user_job(self):
        self.fetcher.text = "Ledger conversion\nOnly available for CSV.\n"
        payload = {key: [{"source_url": DOC_URL, "text": "Ledger conversion"}] for key in CATEGORIES}
        payload["limitations"] = [{"source_url": DOC_URL, "text": "Only available for CSV.", "scope": "Ledger conversion"}]
        self.client.chat.completions.create.return_value.choices[0].message.content = json.dumps(payload)
        self.chat(INTAKE + "\njob: Convert my ledger")
        original = self.state()["draft"]["offer"]
        self.assertEqual(original["unknown_or_unextracted"], [])
        self.chat("payment: invoice later")
        self.chat("retry")
        after = self.state()["draft"]["offer"]
        self.assertEqual(after["job"], "Convert my ledger")
        self.assertEqual(after["limitations"], original["limitations"])
        self.assertEqual(after["limitations"][0]["scope"], "Ledger conversion")
        self.assertEqual(self.client.chat.completions.create.call_count, 1)

    def test_initial_truncation_or_permission_failure_never_populates_cache(self):
        self.client.chat.completions.create.return_value.choices[0].finish_reason = "length"
        self.assertIn("MODEL_OUTPUT_TRUNCATED", self.chat(INTAKE))
        self.assertNotIn("extraction_cache", self.state())
        self.assertIsNone(self.state()["draft"])
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        permission_error = type("PermissionDeniedError", (Exception,), {})
        self.client.chat.completions.create.side_effect = permission_error("private details")
        self.assertIn("MODEL_OUTPUT_TRUNCATED", self.chat("retry"))
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.assertIn("MODEL_PERMISSION", self.chat("reextract"))
        self.assertNotIn("extraction_cache", self.state())
        self.assertEqual(self.client.chat.completions.create.call_count, 2)
        self.chat("export json")
        self.chat("status")
        self.assertEqual(self.client.chat.completions.create.call_count, 2)

    def test_errors_are_not_cached_and_previous_draft_survives(self):
        self.chat(INTAKE)
        before = self.state()["draft"]
        self.client.chat.completions.create.side_effect = TimeoutError("private details")
        self.assertIn("MODEL_TIMEOUT", self.chat("reextract"))
        self.assertEqual(self.state()["draft"], before)
        self.assertNotIn("extraction_cache", self.state())
        self.assertTrue(self.state()["outdated"])
        self.chat("export json")
        self.assertEqual(self.client.chat.completions.create.call_count, 2)
        self.chat("retry")
        self.assertEqual(self.client.chat.completions.create.call_count, 2)
        self.chat("reextract")
        self.assertEqual(self.client.chat.completions.create.call_count, 3)
        self.assertNotIn("extraction_cache", self.state())
        self.client.chat.completions.create.side_effect = None
        self.chat("reextract")
        self.assertIn("extraction_cache", self.state())
        self.assertFalse(self.state()["outdated"])

    def test_revisions_clear_stale_check_but_never_pending_payment(self):
        self.chat(INTAKE)
        state = self.state()
        state["check"] = {"draft_hash": "old"}
        state["pending_payment"] = {"idempotency_key": "unresolved"}
        self.store.save(self.store.key("seller", "one"), state)
        self.chat("pricing: USD 5 per call")
        self.assertIsNone(self.state()["check"])
        self.assertEqual(self.state()["pending_payment"], state["pending_payment"])
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.chat("reextract")
        self.assertEqual(self.state()["pending_payment"], state["pending_payment"])
        self.assertIn("reconciliation", self.chat("reset"))

    def test_reset_removes_only_this_sessions_cache(self):
        self.chat(INTAKE)
        self.chat(INTAKE, session="other")
        self.chat("reset")
        self.assertNotIn("extraction_cache", self.state())
        other = self.store.load(self.store.key("seller", "other"))
        self.assertIn("extraction_cache", other)
