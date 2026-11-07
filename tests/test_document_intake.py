from unittest import TestCase
from unittest.mock import Mock

from tool_offer_agent.conversation import ConversationError
from tool_offer_agent.documents import DocumentError
from tool_offer_agent.workflow import Workflow
from tests.support import DOC_URL, TOOL_URL, FakeFetcher, StoreTestMixin


class DocumentIntakeTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = FakeFetcher()
        self.language = Mock()
        self.language.interpret.side_effect = ConversationError("provider unavailable")
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, conversation=self.language)

    def chat(self, text):
        return self.workflow.handle("docs-test", "one", text)

    def state(self):
        return self.store.load(self.store.key("docs-test", "one"))

    def test_bare_docs_link_is_read_before_other_intake_without_model(self):
        self.chat("tool_url: " + TOOL_URL)
        reply = self.chat(DOC_URL)
        self.assertEqual(self.state()["fields"]["docs"], [DOC_URL])
        self.assertEqual(self.fetcher.calls, [DOC_URL])
        self.assertIn("Read 1 documentation", reply)
        self.assertEqual(self.state()["documents"][0]["text"], self.fetcher.text)
        self.assertIsNone(self.state()["draft"])
        self.language.interpret.assert_not_called()

    def test_first_docs_link_is_not_mistaken_for_tool_endpoint(self):
        reply = self.chat(DOC_URL)
        self.assertNotIn("tool_url", self.state()["fields"])
        self.assertEqual(self.state()["fields"]["docs"], [DOC_URL])
        self.assertIn("public API", reply)

    def test_markdown_and_natural_docs_link_need_no_model(self):
        reply = self.chat("Please read my [docs](" + DOC_URL + ").")
        self.assertIn("Read 1 documentation", reply)
        self.assertEqual(self.state()["fields"]["docs"], [DOC_URL])
        self.language.interpret.assert_not_called()

    def test_explicit_markdown_documentation_field(self):
        reply = self.chat("docs: [API documentation](" + DOC_URL + ")")
        self.assertIn("Read 1 documentation", reply)
        self.assertEqual(self.fetcher.calls, [DOC_URL])

    def test_angle_wrapped_link(self):
        reply = self.chat("<" + DOC_URL + ">")
        self.assertIn("Read 1 documentation", reply)
        self.assertEqual(self.fetcher.calls, [DOC_URL])

    def test_comma_in_document_url_query_is_preserved(self):
        url = DOC_URL + "?fields=inputs,outputs"
        self.chat("docs: " + url)
        self.assertEqual(self.fetcher.calls, [url])
        self.assertEqual(self.state()["fields"]["docs"], [url])

    def test_comma_separated_document_urls_remain_supported(self):
        second = "https://docs.example.com/pricing"
        self.chat("docs: " + DOC_URL + "," + second)
        self.assertEqual(self.fetcher.calls, [DOC_URL, second])

    def test_repeated_link_reports_cached_read_without_refetch_or_revision(self):
        self.chat(DOC_URL)
        revision = self.state()["revision"]
        reply = self.chat(DOC_URL)
        self.assertIn("already read", reply)
        self.assertEqual(self.fetcher.calls, [DOC_URL])
        self.assertEqual(self.state()["revision"], revision)

    def test_failed_read_is_explicit_and_retry_works_before_intake_completes(self):
        original_fetch = self.fetcher.fetch
        self.fetcher.fetch = Mock(side_effect=DocumentError("Documentation request timed out."))
        reply = self.chat("docs: " + DOC_URL)
        self.assertIn("Documentation unavailable", reply)
        self.assertIn("retry", reply)
        self.assertEqual(self.state()["documents"], [])
        self.assertEqual(self.state()["fields"]["docs"], [DOC_URL])
        self.fetcher.fetch = original_fetch
        self.assertIn("Read 1 documentation", self.chat("retry"))
        self.assertIsNone(self.state()["error"])

    def test_refresh_docs_works_before_intake_completes(self):
        self.chat(DOC_URL)
        self.assertIn("Read 1 documentation", self.chat("refresh docs"))
        self.assertEqual(self.fetcher.calls, [DOC_URL, DOC_URL])

    def test_private_link_is_not_fetched(self):
        reply = self.chat("docs: http://127.0.0.1/docs")
        self.assertIn("public", reply.lower())
        self.assertEqual(self.fetcher.calls, [])
        self.assertNotIn("docs", self.state()["fields"])

    def test_hypothetical_does_not_fetch_or_save_link(self):
        self.language.interpret.side_effect = None
        self.language.interpret.return_value = {"action": "reply", "reply": "We can discuss that.", "updates": {}}
        self.chat("What if we used " + DOC_URL + "?")
        self.assertEqual(self.fetcher.calls, [])
        self.assertEqual(self.state()["fields"], {})

    def test_tool_endpoint_answer_also_does_not_depend_on_model(self):
        self.chat(TOOL_URL)
        self.assertEqual(self.state()["fields"]["tool_url"], TOOL_URL)
        self.assertEqual(self.fetcher.calls, [])
        self.language.interpret.assert_not_called()

    def test_model_extracted_docs_are_read_not_just_saved(self):
        self.language.interpret.side_effect = None
        self.language.interpret.return_value = {"action": "update", "reply": "Documentation supplied.", "updates": {"docs": DOC_URL}}
        reply = self.chat("Our service manual is at " + DOC_URL)
        self.assertIn("Read 1 documentation", reply)
        self.assertEqual(self.fetcher.calls, [DOC_URL])
