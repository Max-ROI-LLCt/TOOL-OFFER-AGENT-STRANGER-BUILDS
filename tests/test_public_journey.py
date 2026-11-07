from tests.support import card_selection
import copy
import html
import importlib.util
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import tomllib
from unittest import TestCase
from unittest.mock import Mock, patch

from tests.support import FakeFetcher, StoreTestMixin
from tool_offer_agent.guided_cards import valid_metadata
from tool_offer_agent.export_delivery import REPLY_BYTES, deliver, reassemble, retrieve
from tool_offer_agent.readiness import assess, human_summary
from tool_offer_agent.restrictions import capture, empty
from tool_offer_agent.workflow import STARTER_PROMPTS, Workflow


ROOT = Path(__file__).resolve().parents[1]


def local_module(name):
    specification = importlib.util.spec_from_file_location('public_journey_' + name, ROOT / 'machine' / (name + '.py'))
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


release = local_module('release')
SPEC = local_module('examples').SPEC


class PublicJourneyTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = FakeFetcher()
        self.fetcher.text = json.dumps(SPEC)
        self.planner = Mock()
        self.checkout = Mock()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher, conversation=self.planner, checkout=self.checkout)
        self.template = (ROOT / 'machine/public-profile.txt').read_text()
        self.settings = json.loads((ROOT / 'machine/public-profile.json').read_text())

    def ask(self, text):
        return self.workflow.handle('first-use-test', 'fresh-demo', text)

    def test_all_configured_starters_are_deterministic_non_authorizing(self):
        for index, prompt in enumerate(self.settings['starter_prompts']):
            with self.subTest(prompt=prompt):
                self.assertIn(prompt.casefold(), STARTER_PROMPTS)
                reply = self.workflow.handle('first-use-test', str(index), prompt)
                self.assertLess(len(reply.encode()), 6000)
                self.assertNotIn('TOOL_OFFER_EXPORT_MANIFEST', reply)
        self.planner.interpret.assert_not_called()
        self.assertFalse(self.checkout.mock_calls)
        self.assertEqual(self.fetcher.calls, [])

    def test_advertised_demo_and_correction_without_model_or_purchase(self):
        self.assertIn('Or paste your public tool URL here to get started.', self.ask(self.settings['starter_prompts'][0]))
        intake = re.search(r'```text\n(.*?)\n```', self.template, re.S).group(1).replace('{{origin}}', 'https://tooloffer.kinganlogic.com')
        self.assertTrue(intake.startswith('Demonstration only. No commercial use.\n'))
        homepage = (ROOT / 'site/public/index.html').read_text()
        published = html.unescape(re.search(r'<pre><code>(Demonstration only\..*?)</code></pre>', homepage, re.S).group(1))
        self.assertEqual(intake, published)
        self.assertIn('Read 1 documentation', self.ask(intake))
        self.assertIn('Saved your pricing', self.ask('revise pricing: USD 9 per month'))
        self.assertIn('Draft v1', self.ask('draft limited'))
        key = self.store.key('first-use-test', 'fresh-demo')
        saved = copy.deepcopy(self.store.load(key)['draft'])
        restrictions = copy.deepcopy(self.store.load(key)['restrictions'])
        self.assertTrue(restrictions['demonstration_only'])
        self.assertEqual(restrictions['commercial_authorization'], 'explicitly_restricted')
        self.assertEqual(restrictions['lifecycle'], 'current_product')
        self.assertEqual(saved['restrictions'], restrictions)
        concise = self.ask('buyer explanation')
        self.assertIn('Shipping form developers', concise)
        self.assertIn('normalize', concise)
        self.assertLess(len(concise.encode()), 6000)
        review = self.ask('review offer')
        self.assertTrue(valid_metadata(review.metadata))
        edit = card_selection(json.loads(review.metadata['card_payload']), 'reject_cta')
        form = self.ask(json.dumps({**edit, 'approved': False}))
        selection = json.loads(form.metadata['card_payload'])['submit_cta']['selection']
        acknowledgment = self.ask(json.dumps({**selection, 'approved': True, 'field': 'customer', 'value': 'Shipping form developers'}))
        self.assertIn('customer unchanged', acknowledgment)
        for command in ('readiness', 'readiness text', 'readiness json', 'export buyer readable', 'export buyer', 'export json'):
            with self.subTest(command=command):
                self.assertTrue(self.ask(command))
        self.assertEqual(self.store.load(key)['draft'], saved)
        self.assertEqual(self.store.load(key)['restrictions'], restrictions)
        self.planner.interpret.assert_not_called()
        self.assertFalse(self.checkout.mock_calls)

    def prepare_demo(self):
        self.ask(self.settings['starter_prompts'][0])
        intake = re.search(r'```text\n(.*?)\n```', self.template, re.S).group(1).replace('{{origin}}', 'https://tooloffer.kinganlogic.com')
        self.ask(intake)
        self.ask('revise pricing: USD 9 per month')
        self.ask('draft limited')
        return self.store.key('first-use-test', 'fresh-demo')

    def test_demo_restrictions_survive_changed_correction_rebuild_and_review_lifecycle(self):
        key = self.prepare_demo()
        before = self.store.load(key)
        original = copy.deepcopy(before['draft'])
        restrictions = copy.deepcopy(before['restrictions'])
        audit = self.ask('export json')
        manifest = json.loads(deliver(self.store, key, audit, before['revision'], 'json'))
        original_parts = [json.loads(retrieve(self.store, key, f"export part {manifest['export_id']} {index}")) for index in range(1, manifest['total_parts'] + 1)]
        form = self.ask('review intake')
        form = self.ask(json.dumps(json.loads(form.metadata['card_payload'])['approve_cta']['selection']))
        selection = json.loads(form.metadata['card_payload'])['submit_cta']['selection']
        customer = 'Small online retailers preparing parcel shipment data.'
        action = json.dumps({**selection, 'approved': True, 'field': 'customer', 'value': customer})
        self.assertIn('saved', self.ask(action))
        changed = self.store.load(key)
        self.assertEqual(changed['revision'], before['revision'] + 1)
        self.assertEqual(changed['draft'], original)
        self.assertTrue(changed['outdated'])
        self.assertEqual(changed['restrictions'], restrictions)
        self.ask(action)
        self.assertEqual(self.store.load(key)['revision'], changed['revision'])
        for command in ('buyer explanation', 'readiness'):
            reply = self.ask(command)
            self.assertIn('pending', reply.lower())
            self.assertLessEqual(len(reply.encode()), REPLY_BYTES)
        self.ask('draft limited')
        rebuilt = self.store.load(key)
        self.assertEqual(rebuilt['revision'], changed['revision'] + 1)
        self.assertEqual(rebuilt['draft']['revision'], rebuilt['revision'])
        self.assertEqual(rebuilt['draft']['draft_version'], original['draft_version'] + 1)
        self.assertEqual(rebuilt['draft']['restrictions'], restrictions)
        self.assertFalse(rebuilt['outdated'])
        explanation = self.ask('buyer explanation')
        self.assertNotIn('OUTDATED', explanation)
        self.assertIn(customer, explanation)
        summary = self.ask('readiness')
        self.assertIn(customer, summary)
        self.assertIn('Demonstration only', summary)
        self.assertIn('source-backed derived', summary)
        self.assertNotIn('permissions with the seller', summary)
        review = self.ask('review offer')
        self.assertIn('Demonstration only', review.metadata['card_payload'])
        finish = card_selection(json.loads(review.metadata['card_payload']), 'approve_cta')
        self.assertIn('cancelled', self.ask('cancel review'))
        self.assertIn('stale', self.ask(json.dumps({**finish, 'approved': True})))
        fresh = self.ask('review offer')
        finish = card_selection(json.loads(fresh.metadata['card_payload']), 'approve_cta')
        finished = self.ask(json.dumps({**finish, 'approved': True}))
        self.assertIn('review', finished.lower())
        self.assertIn(str(rebuilt['revision']), finished)
        after = self.store.load(key)
        self.assertEqual(after['draft'], rebuilt['draft'])
        self.assertEqual(after['restrictions'], restrictions)
        self.assertIsNone(after.get('approved_offer'))
        self.assertIsNone(after.get('fahce_checkout'))
        self.assertEqual(reassemble(manifest, original_parts), audit)
        final_parts = [json.loads(retrieve(self.store, key, f"export part {manifest['export_id']} {index}")) for index in range(1, manifest['total_parts'] + 1)]
        self.assertEqual(final_parts, original_parts)
        self.assertFalse(self.checkout.mock_calls)
        self.planner.interpret.assert_not_called()

    def test_json_examples_match_parser_and_message_string_contract(self):
        text = re.search(r'```json\n(.*?)\n```', self.template, re.S).group(1)
        expected = json.loads(text)
        self.ask(text)
        state = self.store.load(self.store.key('first-use-test', 'fresh-demo'))
        self.assertEqual(state['fields'], {name: value for name, value in expected.items() if name != 'schema'})
        self.assertIsNone(state['draft'])
        full = re.search(r'for example (\{"schema".*?\})\.', (ROOT / 'machine/guide.txt').read_text()).group(1)
        parsed = self.workflow._structured_intake(full)
        self.assertEqual(parsed['docs'], ['https://example.com/openapi.json'])
        self.workflow.handle('first-use-test', 'full-json', full)
        self.assertEqual(self.store.load(self.store.key('first-use-test', 'full-json'))['fields'], parsed)
        before = copy.deepcopy(state)
        for invalid in ('{"intake":' + text + '}', '{"customer":"one","customer":"two"}', '{"pricing":9}', '{"customer":""}', '```json\n' + text + '\n```'):
            self.ask(invalid)
            self.assertEqual(self.store.load(self.store.key('first-use-test', 'fresh-demo')), before)
        from jsonschema import ValidationError, validate
        contract = json.loads((ROOT / 'machine/contract.json').read_text())
        schema = next(tool['inputSchema']['properties']['message'] for tool in contract['tools'] if tool['name'] == 'send_message')
        validate(text, schema)
        with self.assertRaises(ValidationError):
            validate(expected, schema)

    def test_no_commercial_use_is_a_literal_restriction_not_a_url_heuristic(self):
        record = capture(empty(), 'No commercial use.', message_id='literal', timestamp='2026-11-05T00:00:00Z')
        self.assertEqual(record['commercial_authorization'], 'explicitly_restricted')
        self.assertFalse(record['demonstration_only'])
        self.assertEqual(record['sources'][0]['quote'], 'No commercial use.')
        self.assertEqual(record['sources'][0]['message_id'], 'literal')
        for text in ('https://parcel-example.invalid/', 'No commercial use?', 'What if this is demonstration only?'):
            self.assertEqual(capture(empty(), text), empty())
        self.assertEqual(capture(record, 'I own this product.'), record)
        self.assertIn('Saved your restrictions', self.ask('No commercial use.'))
        self.assertIn('blocked', self.ask('check').lower())
        self.assertFalse(self.checkout.mock_calls)

    def test_human_readiness_is_bounded_and_detailed_report_stays_complete(self):
        key = self.prepare_demo()
        state = self.store.load(key)
        state['fields']['customer'] = '顧客🌱' * 1500
        self.store.save(key, state)
        report = assess(state, 'first-use-test', 'test-release')
        summary = human_summary(report)
        self.assertLessEqual(len(summary.encode()), REPLY_BYTES)
        self.assertIn('full value in detailed report', summary)
        self.assertIn(state['fields']['customer'], report['human_readable'])
        self.assertIn('\n\n### Evidence boundaries\n\n', summary)
        self.assertIn('\n\n### Next action\n\n', summary)
        self.assertNotIn('TOOL_OFFER_EXPORT_MANIFEST', self.ask('readiness'))
        detail = json.loads(self.ask('readiness json'))
        self.assertEqual(detail['schema'], 'TOOL_OFFER_EXPORT_MANIFEST_V1')
        parts = [json.loads(retrieve(self.store, key, f"export part {detail['export_id']} {index}")) for index in range(1, detail['total_parts'] + 1)]
        rebuilt = json.loads(reassemble(detail, parts))
        self.assertIn(state['fields']['customer'], rebuilt['human_readable'])
        self.assertEqual(self.store.load(key), state)

    def test_demo_declared_before_first_url_is_not_reset_but_product_switch_is_scoped(self):
        key = self.prepare_demo()
        original = self.store.load(key)
        self.ask('tool_url: https://different.example.com/')
        changed = self.store.load(key)
        self.assertEqual(changed['restrictions'], empty())
        archived = changed['product_history'][-1]
        self.assertEqual(archived['restrictions']['lifecycle'], 'archived_product')
        self.assertTrue(archived['restrictions']['demonstration_only'])
        self.assertEqual(archived['draft'], original['draft'])
        self.assertEqual(changed['draft'], original['draft'])
        self.assertTrue(changed['outdated'])

    def test_profile_keeps_human_journey_separate_from_operator_reference(self):
        profile = release.profile_text(ROOT, json.loads((ROOT / 'machine/contract.json').read_text()))
        self.assertLess(len(profile), 14000)
        self.assertNotIn('{{machine_discovery}}', profile)
        intro = profile.split('## Optional paid')[0]
        self.assertIn('## Try it', intro[:1300])
        self.assertIn('| Send in chat | What you receive |', intro)
        self.assertNotIn('`check`', intro)
        self.assertNotIn('<details', profile)
        self.assertNotIn('Operator inference usage', profile)
        self.assertIn('category tags', profile)
        self.assertIn('![tag:innovationlab]', profile)
        self.assertIn('![tag:hackathon]', profile)
        self.assertLess(profile.index('![tag:innovationlab]'), profile.index('By Kingan Logic'))
        self.assertLess(profile.index('![tag:hackathon]'), profile.index('By Kingan Logic'))

    def test_profile_push_changes_only_explicit_public_metadata(self):
        baseline = {'description': 'old', 'starter_prompts': ['old'], 'readme': 'old', 'avatar_url': 'avatar', 'banner_url': 'banner'}
        manifest = {'profile_settings': self.settings}
        expected = {**baseline, **self.settings, 'readme': (ROOT / 'AGENT-PROFILE.txt').read_text()}
        self.assertTrue(release.profile_matches(expected, baseline, manifest))
        self.assertFalse(release.profile_matches({**expected, 'avatar_url': 'changed'}, baseline, manifest))
        with TemporaryDirectory() as directory, patch.object(release, 'WORK', Path(directory)), patch.object(release, 'CANDIDATE', Path(directory) / 'candidate'):
            release.CANDIDATE.mkdir()
            (release.CANDIDATE / 'agent.py').write_text('agent = None\n')
            context = release.profile_push_context(manifest, 'test-agent')
            config = tomllib.loads((context / '.avctl/config.toml').read_text())['agent']
            self.assertEqual(config['address'], 'test-agent')
            self.assertEqual(config['starter_prompts'], self.settings['starter_prompts'])
            self.assertEqual((context / 'AGENT-PROFILE.txt').read_text(), expected['readme'])
            self.assertEqual((context / 'agent.py').read_text(), 'agent = None\n')
            self.assertEqual(tomllib.loads((context / 'pyproject.toml').read_text())['project']['readme'], 'AGENT-PROFILE.txt')

    def test_metadata_sync_is_explicit_and_rejects_unrelated_drift(self):
        baseline = {'description': 'old', 'starter_prompts': ['old'], 'readme': 'old', 'avatar_url': 'avatar'}
        current = {**baseline, 'readme': (ROOT / 'AGENT-PROFILE.txt').read_text()}
        manifest = {'profile_settings': self.settings}
        with patch.object(release, 'run') as command:
            release.synchronize_profile_settings(current, baseline, manifest, 'test-agent', ROOT)
            self.assertEqual(command.call_count, 2)
            self.assertEqual(command.call_args_list[0].args[0][1:5], ['hosting', 'set', 'agent', 'description'])
            self.assertEqual(command.call_args_list[1].args[0][1:5], ['hosting', 'set', 'agent', 'starter-prompts'])
            command.reset_mock()
            with self.assertRaises(ValueError):
                release.synchronize_profile_settings({**current, 'avatar_url': 'changed'}, baseline, manifest, 'test-agent', ROOT)
            command.assert_not_called()
            with self.assertRaises(ValueError):
                release.synchronize_profile_settings({**current, 'description': 'concurrent change'}, baseline, manifest, 'test-agent', ROOT)
            command.assert_not_called()
