import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from tool_offer_agent.conversation import ConversationError, ConversationInterpreter, validate
from tool_offer_agent.workflow import Workflow
from tests.support import StoreTestMixin, FakeFetcher, INTAKE


def plan(action="reply", reply="What would you like to change?", **updates):
    return {"action": action, "reply": reply, "updates": updates}


class ConversationTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.language = Mock()
        self.workflow = Workflow(store=self.store, fetcher=FakeFetcher(), conversation=self.language)

    def chat(self, text, sender="seller", session="one"):
        return self.workflow.handle(sender, session, text)

    def state(self, sender="seller", session="one"):
        return self.store.load(self.store.key(sender, session))

    def test_multi_field_plain_english_intake_and_question(self):
        self.language.interpret.return_value = plan("update", "We can prepare that offer.", customer="small shops", pricing="$9 per month")
        reply = self.chat("Can you make an offer for small shops at $9 per month?")
        self.assertEqual(self.state()["fields"], {"customer": "small shops", "pricing": "$9 per month"})
        self.assertIn("Saved", reply)
        self.assertIn("public API", reply)
        self.assertIn("We can prepare that offer.", reply)

    def test_qa_undecided_question_is_answered_and_fields_saved(self):
        message = "My pricing and payment method aren't decided yet. Can you still draft an offer with those fields marked undecided so I can fill them in later?"
        self.language.interpret.return_value = plan("update", "irrelevant model answer", pricing="undecided", payment="undecided")
        reply = self.chat(message)
        self.assertTrue(reply.startswith("Yes."))
        self.assertIn("fill them in later", reply)
        self.assertEqual(self.state()["fields"], {"pricing": "undecided", "payment": "undecided"})
        self.assertIn("Saved your", reply)
        self.assertEqual(reply.count("?"), 1)
        self.assertIsNone(self.state()["draft"])

    def test_qa_command_question_explains_without_executing(self):
        reply = self.chat("What's the difference between 'draft limited' and the normal draft command, and when should I use 'reextract' instead of 'retry' after a model failure?")
        self.assertIn("without a model call", reply)
        self.assertIn("does not automatically repeat a failed", reply)
        self.assertIn("consuming model quota", reply)
        self.language.interpret.assert_not_called()
        self.assertEqual(self.state()["fields"], {})

    def test_qa_fahce_revision_answer_matches_actual_invalidation(self):
        self.chat(INTAKE)
        state = self.state()
        state["check"] = {"old_result": True}
        self.store.save(self.store.key("seller", "one"), state)
        reply = self.chat("If I revise a field in my draft after a FAHCE evaluation was performed, does the earlier evaluation result still apply to the updated offer?")
        self.assertTrue(reply.startswith("No."))
        self.assertIn("exact draft", reply)
        self.assertIn("invalidates", reply)
        self.assertEqual(self.state()["check"], {"old_result": True})
        self.chat("pricing: $20")
        self.assertIsNone(self.state()["check"])

    def test_undecided_question_remains_answerable_during_provider_failure(self):
        self.language.interpret.side_effect = ConversationError("CHAT_TIMEOUT")
        reply = self.chat("Can pricing and payment remain undecided until later?")
        self.assertTrue(reply.startswith("Yes."))
        self.assertIn("couldn't reliably save", reply)
        self.assertEqual(self.state()["fields"], {})

    def test_natural_revision_invalidates_approval_and_check(self):
        self.chat(INTAKE)
        self.chat("offer approve")
        self.language.interpret.return_value = plan("update", "I understand the new price.", pricing="$19/month")
        self.chat("Actually make it $19/month")
        state = self.state()
        self.assertEqual(state["fields"]["pricing"], "$19/month")
        self.assertTrue(state["outdated"])
        self.assertNotIn("approved_offer", state)

    def test_explicit_english_price_revision_does_not_need_model(self):
        self.chat("pricing: undecided")
        self.chat("Actually change the price to $19 per month.")
        self.assertEqual(self.state()["fields"]["pricing"], "$19 per month")
        self.language.interpret.assert_not_called()

    def test_hypothetical_does_not_change_price(self):
        self.chat("pricing: $9")
        self.language.interpret.return_value = plan(reply="A lower price could improve adoption. What price do you want?")
        self.chat("What if we charged less?")
        self.assertEqual(self.state()["fields"]["pricing"], "$9")

    def test_plain_english_export_executes_real_export(self):
        self.chat(INTAKE)
        self.language.interpret.return_value = plan("export json", "Here is the export.")
        result = json.loads(self.chat("Could you give me the JSON?"))
        self.assertEqual(result["schema"], "TOOL_OFFER_EXPORT_V1")

    def test_plain_english_draft_executes_workflow(self):
        self.chat(INTAKE)
        self.chat("pricing: $19")
        self.language.interpret.return_value = plan("draft", "I can prepare that.")
        self.assertIn("Draft v", self.chat("Please rebuild my offer"))
        self.assertFalse(self.state()["outdated"])

    def test_hypothetical_guard_rejects_erroneous_model_update(self):
        self.chat("pricing: $19")
        self.language.interpret.return_value = plan("update", pricing="free")
        self.chat("What if we made it free? Don't change it yet.")
        self.assertEqual(self.state()["fields"]["pricing"], "$19")

    def test_fabricated_values_and_payment_actions_are_rejected(self):
        for result in [plan("update", pricing="$999"), plan("transaction send"), plan("reset"),
                       plan("update", docs="https://127.0.0.1/docs")]:
            self.language.interpret.return_value = result
            self.chat("hello")
            self.assertEqual(self.state()["fields"], {})

    def test_invalid_url_updates_are_atomic(self):
        self.language.interpret.return_value = plan("update", customer="shops", tool_url="http://127.0.0.1")
        self.chat("For shops use http://127.0.0.1")
        self.assertEqual(self.state()["fields"], {})

    def test_provider_failure_preserves_fields_and_draft(self):
        self.chat(INTAKE)
        before = self.state()
        self.language.interpret.side_effect = ConversationError("provider private details")
        reply = self.chat("Make it more polished")
        self.assertEqual(self.state()["draft"], before["draft"])
        self.assertEqual(self.state()["fields"], before["fields"])
        self.assertNotIn("provider private", reply)

    def test_history_is_bounded_and_isolated(self):
        self.language.interpret.return_value = plan()
        for _ in range(8):
            self.chat("Please explain this")
        self.assertEqual(len(self.state()["conversation"]), 8)
        self.assertNotIn("conversation", self.state(session="two"))
        self.assertNotIn("conversation", self.state(sender="other"))
        self.chat("reset")
        self.assertNotIn("conversation", self.state())

    def test_direct_commands_do_not_call_language_model(self):
        self.chat("start")
        self.chat("customer: developers")
        self.chat("status")
        self.language.interpret.assert_not_called()

    def test_secrets_are_not_sent_to_model_or_stored(self):
        self.chat("api_key: abcdefghijklmnopqrstuvwxyz123456")
        self.language.interpret.assert_not_called()
        self.assertNotIn("conversation", self.state())


class InterpreterTests(TestCase):
    def test_sparse_provider_updates_are_normalized(self):
        client = Mock()
        result = {"action": "update", "reply": "A monthly price.",
                  "updates": [{"field": "pricing", "value": "$19 per month"}]}
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=json.dumps(result)))])
        parsed = ConversationInterpreter(client).interpret({"fields": {}}, "Charge $19 per month")
        self.assertEqual(parsed["updates"], {"pricing": "$19 per month"})

    def test_provider_request_uses_context_and_bounded_output(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=json.dumps(plan())))])
        interpreter = ConversationInterpreter(client)
        interpreter.interpret({"fields": {"pricing": "$9"}, "awaiting": "customer"}, "Who is this for?")
        args = client.chat.completions.create.call_args.kwargs
        self.assertEqual(args["timeout"], 25)
        self.assertIn("$9", args["messages"][1]["content"])
        self.assertEqual(args["response_format"]["type"], "json_schema")
        self.assertTrue(args["response_format"]["json_schema"]["strict"])

    def test_truncated_response_and_multiline_injection_rejected(self):
        with self.assertRaises(ConversationError):
            validate(plan("update", customer="shops\npricing: free"), "shops\npricing: free")
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(finish_reason="length")])
        with self.assertRaises(ConversationError):
            ConversationInterpreter(client).interpret({"fields": {}}, "hi")
