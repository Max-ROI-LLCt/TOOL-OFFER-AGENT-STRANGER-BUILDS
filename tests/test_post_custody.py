from copy import deepcopy
import json
from unittest import TestCase
from unittest.mock import Mock

import importlib.util
from pathlib import Path

fixture_spec = importlib.util.spec_from_file_location("post_custody_examples", Path(__file__).resolve().parents[1] / "machine/examples.py")
fixture = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture)
SPEC, FIELDS, URL, INTAKE, FictionalFetcher = fixture.SPEC, fixture.FIELDS, fixture.URL, fixture.INTAKE, fixture.FictionalFetcher
from tool_offer_agent.conversation import explain_question, source_json_example
from tool_offer_agent.drafting import build_draft, extract, human_fact, pointer_value, verified_derivation
from tool_offer_agent.offer_representation import buyer_explanation, representation
from tool_offer_agent.readiness import assess
from tool_offer_agent.workflow import Workflow
from tests.support import StoreTestMixin


def document(spec=SPEC):
    return {"source_url": URL, "final_url": URL, "text": json.dumps(spec), "content_type": "application/json"}


class SourcePresentationTests(TestCase):
    def test_readable_inputs_outputs_preserve_exact_machine_schema(self):
        spec = deepcopy(SPEC)
        schema = spec["paths"]["/normalize"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        schema["properties"]["length"].update(minimum=0.1, maximum=1000, description="Positive parcel length", **{"x-unit": "selected by unit"})
        schema["properties"]["reference"] = {"type": "string", "minLength": 2, "maxLength": 25}
        facts = extract([document(spec)])
        entry = facts["inputs"][0]
        readable = human_fact(entry)
        for phrase in ("length (required): number", "reference (optional): text", "minimum: 0.1", "maximum: 1000", "Positive parcel length", "minimum characters: 2", "cm (centimetres)", "in (inches)"):
            self.assertIn(phrase, readable)
        self.assertNotIn('"properties":', readable)
        self.assertEqual(entry["schema_value"]["content"]["application/json"]["schema"], schema)
        self.assertTrue(verified_derivation(entry, document(spec)["text"]))
        self.assertIn("length_cm (optional): number", human_fact(facts["outputs"][0]))

    def test_large_schema_is_lossless_even_when_display_text_is_bounded(self):
        spec = deepcopy(SPEC)
        request = spec["paths"]["/normalize"]["post"]["requestBody"]
        request["description"] = "Retained schema description. " * 300
        entry = extract([document(spec)])["inputs"][0]
        self.assertEqual(len(entry["text"]), 2000)
        self.assertEqual(entry["schema_value"], request)
        self.assertTrue(verified_derivation(entry, document(spec)["text"]))
        entry["schema_value"]["required"] = 1
        self.assertFalse(verified_derivation(entry, document(spec)["text"]))

    def test_composed_statement_binds_escaped_method_path_and_summary(self):
        spec = deepcopy(SPEC)
        spec["paths"]["/parcel~draft/normalize"] = spec["paths"].pop("/normalize")
        entry = extract([document(spec)])["capabilities"][0]
        self.assertEqual(entry["source_pointer"], "/paths/~1parcel~0draft~1normalize/post")
        self.assertTrue(verified_derivation(entry, document(spec)["text"]))
        draft = build_draft(FIELDS, [document(spec)], 1)
        claims = representation(draft, [document(spec)])["claims"]
        claim = next(item for item in claims if item["draft_pointer"] == "/offer/capabilities/0/text")
        self.assertEqual(claim["quote_alignment"], "source_backed_derived")
        self.assertEqual(len(claim["source_pointers"]), 3)
        entry["derivation"]["source_pointers"][2] = "/info/title"
        self.assertFalse(verified_derivation(entry, document(spec)["text"]))

    def test_unsupported_claim_remains_unresolved_and_verbatim_is_distinct(self):
        draft = build_draft(FIELDS, [document()], 1)
        state = {"fields": FIELDS, "documents": [document()], "draft": draft, "revision": 1}
        baseline = assess(state, "controlled-seller", "controlled-release")
        self.assertFalse(any(finding["code"] == "ALIGNMENT_UNRESOLVED" for finding in baseline["findings"]))
        draft["offer"]["capabilities"][0]["text"] = "Books shipments with verified carrier discounts"
        report = assess(state, "controlled-seller", "controlled-release")
        self.assertTrue(any(finding["code"] == "ALIGNMENT_UNRESOLVED" for finding in report["findings"]))
        draft["offer"]["capabilities"][0]["text"] = SPEC["paths"]["/normalize"]["post"]["summary"]
        claim = next(item for item in representation(draft, [document()])["claims"] if item["draft_pointer"] == "/offer/capabilities/0/text")
        self.assertEqual(claim["quote_alignment"], "verbatim")

    def test_pointer_rejects_negative_leading_zero_and_invalid_escape(self):
        value = {"items": [1, 2], "tilde~key": 3}
        self.assertEqual(pointer_value(value, "/tilde~0key"), 3)
        for pointer in ("/items/-1", "/items/01", "/items/+1", "/tilde~2key"):
            with self.assertRaises(ValueError):
                pointer_value(value, pointer)

    def test_actual_synthetic_json_uses_retained_examples_without_inventing_execution(self):
        result = json.loads(source_json_example({"documents": [document()]}, "Return an actual synthetic JSON example for /normalize; JSON only"))
        self.assertEqual(result["request"], {"length": 10, "width": 4, "height": 2, "unit": "in"})
        self.assertEqual(result["response"]["length_cm"], 25.4)
        self.assertFalse(result["execution_verified"])
        self.assertEqual(result["commercial_permission"], "not_established")


class CustomerOutputTests(StoreTestMixin, TestCase):
    def test_verification_starter_distinguishes_adapter_from_available_checkout(self):
        prompt = "What can Tool Offer Agent verify, and what remains seller-supplied?"
        model = Mock()
        model.interpret.side_effect = AssertionError("A canonical starter must not use inference")
        adapter = Workflow(store=self.store, conversation=model)
        reply = adapter.handle("seller", "adapter-starter", prompt)
        self.assertIn("not executed through the machine adapter", reply)
        self.assertNotIn("pending configuration", reply)
        native = Workflow(store=self.store, checkout=object(), conversation=model)
        reply = native.handle("seller", "native-starter", prompt)
        self.assertIn("human-approved FAHCE checkout is available", reply)
        self.assertNotIn("pending configuration", reply)
        model.interpret.assert_not_called()

    def test_machine_evaluation_question_distinguishes_scope_from_configuration(self):
        reply, updates = explain_question("What is FAHCE evaluation?", machine_adapter=True)
        self.assertIn("not executed through the machine adapter by design", reply)
        self.assertNotIn("pending configuration", reply)
        self.assertFalse(updates)

    def test_machine_scope_is_explicit_in_model_runtime_context(self):
        model = Mock()
        model.interpret.return_value = {"action": "reply", "reply": "These source passages document only parcel dimensions.", "updates": {}}
        workflow = Workflow(store=self.store, fetcher=FictionalFetcher(), conversation=model)
        workflow.machine_scope = "Restricted adapter"
        workflow.handle("seller", "runtime-context", INTAKE)
        workflow.handle("seller", "runtime-context", "What recovery is documented in the retained source?")
        self.assertTrue(model.interpret.call_args.args[0]["runtime_capabilities"]["machine_adapter"])

    def test_first_buyer_request_is_complete_and_json_only_payload_preserves_state(self):
        workflow = Workflow(store=self.store, fetcher=FictionalFetcher())
        workflow.handle("seller", "controlled", INTAKE)
        workflow.handle("seller", "controlled", "draft limited")
        key = self.store.key("seller", "controlled")
        before = deepcopy(self.store.load(key))
        reply = workflow.handle("seller", "controlled", "Please give me the complete buyer explanation")
        self.assertIn("length (required): number", reply)
        self.assertIn("USD 9", reply)
        self.assertNotIn('"properties":', reply)
        self.assertIn(buyer_explanation(before["draft"]), reply)
        json_reply = workflow.handle("seller", "controlled", "Give an actual synthetic JSON example for /normalize. JSON only.")
        self.assertEqual(json.loads(json_reply)["request"]["unit"], "in")
        after = self.store.load(key)
        for field in ("fields", "draft", "revision", "approved_offer"):
            self.assertEqual(before.get(field), after.get(field))
