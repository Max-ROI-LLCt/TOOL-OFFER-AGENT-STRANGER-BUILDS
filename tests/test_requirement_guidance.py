"""T065–T067 command accuracy and T064 provenance preservation.

Prompts are deterministic failure-shape fixtures; full customer transcripts were
not supplied. Test fetch/model boundaries use fakes and do not prove a live fetch.
"""
import copy
import json
from unittest import TestCase
from unittest.mock import Mock

from tool_offer_agent.conversation import SYSTEM
from tool_offer_agent.drafting import OpenAIQuoteExtractor
from tool_offer_agent.product_policy import PLAN_HELP, planning_command
from tool_offer_agent.workflow import Workflow
from tests.support import DOC_URL, INTAKE, FakeFetcher, StoreTestMixin
from tests.test_extraction_cache import model_client


QUESTIONS = [
    'I am nontechnical. What exact command saves a proposed requirement? Explain without saving anything.',
    'You told me to use save requirement: and avoid plan requirement:. Verify both prefixes against the executor.',
    'Self-audit: is save requirement: documented or execution-verified? Is plan requirement: supported?',
]


class RequirementGuidanceTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.language = Mock()
        self.language.interpret.return_value = {'action': 'reply', 'reply': 'Conversation text only.', 'updates': {}}
        self.fetcher = FakeFetcher()
        self.w = Workflow(store=self.store, conversation=self.language, fetcher=self.fetcher)

    def chat(self, text):
        return self.w.handle('guidance', 'one', text)

    def state(self):
        return self.store.load(self.store.key('guidance', 'one'))

    def test_first_time_guidance_is_readonly_and_deterministic(self):
        before = copy.deepcopy(self.state())
        reply = self.chat(QUESTIONS[0])
        self.assertIn('mode prelaunch\nplan requirement:', reply)
        self.assertIn('saves nothing', reply)
        self.assertEqual(before, self.state())
        self.language.interpret.assert_not_called()

    def test_accepted_command_persists_numbering_and_exact_text_across_restart(self):
        self.assertIn('mode prelaunch', self.chat('plan requirement: First requirement.'))
        self.assertNotIn('planning', self.state())
        self.chat('mode prelaunch')
        self.assertIn('Saved R1 as proposed', self.chat('plan requirement: First requirement.'))
        self.w = Workflow(store=self.store)
        self.assertIn('Saved R2 as proposed', self.chat('PLAN REQUIREMENT: Second requirement.'))
        items = json.loads(self.chat('export plan'))['items']
        self.assertEqual([(i['id'], i['text'], i['status']) for i in items],
                         [('R1', 'First requirement.', 'proposed'), ('R2', 'Second requirement.', 'proposed')])
        self.assertEqual(items[0]['source_quote'], 'First requirement.')
        self.assertEqual(items[0]['origin'], 'explicit_current_user_command')

    def test_unsupported_save_prefix_never_reaches_model_or_mutates(self):
        for mode in [False, True]:
            if mode:
                self.chat('mode prelaunch')
            before = copy.deepcopy(self.state())
            reply = self.chat('save requirement: Do not lose this text.')
            self.assertIn('Unsupported command', reply)
            self.assertIn('Nothing saved', reply)
            self.assertIn('plan requirement:', reply)
            self.assertEqual(before, self.state())
        self.language.interpret.assert_not_called()

    def test_self_audit_uses_parser_contract_not_prior_assistant_claims(self):
        state = self.state()
        state['conversation'] = [{'role': 'assistant', 'content': 'Use save requirement:; avoid plan requirement:.'}]
        self.store.save(self.store.key('guidance', 'one'), state)
        before = copy.deepcopy(self.state())
        for question in QUESTIONS[1:]:
            reply = self.chat(question)
            self.assertIn('save requirement: is unsupported', reply)
            self.assertIn('executor recognizes that exact prefix', reply)
            self.assertIn('not that a requirement was saved', reply)
            self.assertEqual(before, self.state())
        self.language.interpret.assert_not_called()

    def test_questions_preserve_all_existing_planning_items_and_statuses(self):
        self.chat('mode prelaunch')
        for command in ['plan requirement: Keep sources.', 'plan decision: Review owner.',
                        'plan test R1: Verify sources.', 'plan exercise: Fictional report.']:
            self.chat(command)
        before = copy.deepcopy(self.state())
        for question in QUESTIONS:
            self.chat(question)
            self.assertEqual(before, self.state())
        self.assertIn('no duplicate', self.chat('plan requirement: Keep sources.'))
        self.assertEqual(before['planning'], self.state()['planning'])
        self.assertEqual([i['status'] for i in before['planning']['items']],
                         ['proposed', 'unresolved', 'not_executed', 'fictional'])

    def test_raw_parser_recognizes_only_plan_prefix(self):
        state = {'planning': {'mode': 'prelaunch', 'items': []}}
        before = copy.deepcopy(state)
        self.assertIsNone(planning_command(state, 'save requirement: First.'))
        self.assertEqual(before, state)
        self.assertIn('Saved R1 as proposed', planning_command(state, 'plan requirement: First.'))
        for command in ['plan requirement:', 'plan requirement R1: Invalid reference.', '/plan requirement: Slash not accepted.']:
            before = copy.deepcopy(state)
            planning_command(state, command)
            self.assertEqual(before, state)

    def test_model_instructions_include_actual_command_help(self):
        self.assertIn(PLAN_HELP, SYSTEM)
        self.assertIn('save requirement: is not an alias', SYSTEM)

    def test_requirement_content_is_not_mistaken_for_guidance(self):
        self.chat('mode prelaunch')
        reply = self.chat('plan requirement: How should we save requirement commands?')
        self.assertIn('Saved R1 as proposed', reply)
        self.assertEqual(self.state()['planning']['items'][0]['text'], 'How should we save requirement commands?')

    def test_t064_pasted_text_is_not_fetch_or_extraction_proof(self):
        self.chat('Pasted documentation quotation: Inputs: CSV. Outputs: JSON.')
        self.assertEqual(self.fetcher.calls, [])
        self.assertEqual(self.state()['documents'], [])
        self.assertIsNone(self.state().get('extraction_cache'))
        self.assertIn('0/0 supplied page(s) read', self.chat('status'))

    def test_t064_saved_url_failure_read_and_extraction_are_distinct(self):
        self.fetcher.fail = True
        self.assertIn('Documentation unavailable', self.chat('docs: ' + DOC_URL))
        self.assertEqual(self.state()['fields']['docs'], [DOC_URL])
        self.assertEqual(self.state()['documents'], [])
        self.assertIn('0/1 supplied page(s) read', self.chat('status'))
        self.fetcher.fail = False
        self.assertIn('Read 1 documentation', self.chat('retry'))
        self.assertIn('1/1 supplied page(s) read', self.chat('status'))
        self.assertIsNone(self.state().get('extraction_cache'))
        self.w.extractor = OpenAIQuoteExtractor(model_client())
        self.chat(INTAKE)
        self.chat('draft')
        self.assertTrue(self.state().get('extraction_cache'))
        self.assertIn('One successful extraction saved', self.chat('status'))
