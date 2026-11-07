from tests.support import card_selection
import copy
import json
from unittest import TestCase
from unittest.mock import Mock

from tests.support import DOC_URL, INTAKE, FakeFetcher, StoreTestMixin
from tests.test_card_client_acceptance import business_state
from tool_offer_agent.guided_cards import FIELDS, valid_metadata
from tool_offer_agent.workflow import Workflow


class NativeCorrectionTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = FakeFetcher()
        self.workflow = Workflow(store=self.store, fetcher=self.fetcher)
        self.workflow.handle('seller', 'session', INTAKE)
        self.key = self.store.key('seller', 'session')
        self.original = self.store.load(self.key)
        self.workflow.conversation = Mock()

    def ask(self, text, **kwargs):
        return self.workflow.handle('seller', 'session', text, **kwargs)

    def form(self):
        reply = self.ask('review intake')
        self.assertTrue(valid_metadata(reply.metadata))
        self.assertIn(self.store.load(self.key)['fields']['customer'], reply)
        reply = self.ask(json.dumps(json.loads(reply.metadata['card_payload'])['approve_cta']['selection']))
        self.assertTrue(valid_metadata(reply.metadata))
        return json.loads(reply.metadata['card_payload'])['submit_cta']['selection']

    def submit(self, selection, field='customer', value=None, **extra):
        return self.ask(json.dumps({**selection, 'field': field, 'value': value if value is not None else self.original['fields']['customer'], 'approved': True, **extra}))

    def test_actual_native_shape_unchanged_and_repeat(self):
        selection = self.form()
        before = business_state(self.store.load(self.key))
        fetch_count = len(self.fetcher.calls)
        reply = self.submit(selection)
        self.assertIn('customer unchanged', reply)
        self.assertIn('revision 1', reply)
        self.assertNotIn('travel planners', reply)
        self.assertEqual(before, business_state(self.store.load(self.key)))
        self.assertEqual(fetch_count, len(self.fetcher.calls))
        self.assertIn('already handled', self.submit(selection))
        self.assertIn('stale', self.ask(json.dumps({**selection, 'action': 'reviewed', 'approved': True})))
        self.assertIn('stale', self.submit(selection, value='Different customer'))
        self.workflow.conversation.interpret.assert_not_called()

    def test_all_supported_fields_are_atomic_and_single_field(self):
        values = {'customer': 'New operators', 'job': 'Explain conversion errors', 'pricing': 'USD 4 per call',
                  'payment': 'Probably an invoice', 'access': 'Use a seller-issued key', 'invocation': 'POST /convert',
                  'docs': 'https://docs.example.com/replacement.json', 'tool_url': 'https://api.example.com/v2', 'seller_name': 'Example seller'}
        self.assertEqual(set(values), set(FIELDS))
        for field, value in values.items():
            with self.subTest(field=field):
                self.store.save(self.key, copy.deepcopy(self.original))
                selection = self.form()
                reply = self.submit(selection, field, value)
                after = self.store.load(self.key)
                self.assertIn('Saved your ' + field, reply)
                self.assertIn('revision 2', reply)
                self.assertEqual(after['revision'], self.original['revision'] + 1)
                expected = {**self.original['fields'], field: [value] if field == 'docs' else value}
                self.assertEqual(after['fields'], expected)
                self.assertEqual(after['draft'], self.original['draft'])
                self.assertTrue(after['outdated'])
                self.assertFalse(after.get('approved_offer'))
                self.assertEqual(after.get('commercial_transactions'), self.original.get('commercial_transactions'))
                self.assertLess(len(reply.encode()), 1000)

    def test_invalid_submissions_get_bound_recovery_without_partial_update(self):
        for extra in ({'approved': 'true'}, {'approved': False}, {'approved': 1}, {'field': 'checkout'},
                      {'value': ''}, {'value': '   '}, {'value': 'ok\npricing: free'}, {'value': 7},
                      {'field': 'docs', 'value': 'https://docs.example.com/good http://127.0.0.1/private'},
                      {'value': 'valid', 'purchase': True}):
            with self.subTest(extra=extra):
                selection = self.form()
                before = business_state(self.store.load(self.key))
                reply = self.submit(selection, **extra)
                self.assertTrue(valid_metadata(reply.metadata))
                self.assertIn('review intake', reply)
                self.assertEqual(before, business_state(self.store.load(self.key)))
                fresh = json.loads(reply.metadata['card_payload'])['submit_cta']['selection']
                self.assertNotEqual(fresh['card_id'], selection['card_id'])
                self.assertIn('stale', self.submit(selection))
                self.assertIn('unchanged', self.submit(fresh))

    def test_duplicate_json_keys_and_cross_session_cannot_consume_card(self):
        selection = self.form()
        before = self.store.load(self.key)
        payload = json.dumps({**selection, 'field': 'customer', 'value': 'new', 'approved': True})
        duplicate = payload[:-1] + ',"field":"payment"}'
        self.assertIn('Invalid card selection JSON', self.ask(duplicate))
        self.assertIn('stale', self.workflow.handle('other', 'session', payload))
        self.assertEqual(self.store.load(self.key), before)
        self.assertIn('unchanged', self.submit(selection))

    def test_cross_origin_tool_change_requires_separate_product_intake(self):
        selection = self.form()
        before = business_state(self.store.load(self.key))
        reply = self.submit(selection, 'tool_url', 'https://another.example.com/')
        self.assertIn('different origin', reply)
        self.assertTrue(valid_metadata(reply.metadata))
        self.assertEqual(before, business_state(self.store.load(self.key)))
        self.assertIn('different origin', self.ask('revise tool_url: https://another.example.com/'))
        self.assertEqual(before, business_state(self.store.load(self.key)))

    def test_plain_fallback_unchanged_changed_unicode_and_payment_ack_are_inline(self):
        before = business_state(self.store.load(self.key))
        reply = self.ask('revise customer: ' + self.original['fields']['customer'])
        self.assertIn('unchanged', reply)
        self.assertEqual(before, business_state(self.store.load(self.key)))
        for field, value in [('customer', 'é漢字😀' * 1000), ('payment', 'Probably ' + 'é漢字😀' * 1000)]:
            reply = self.ask('revise ' + field + ': ' + value)
            self.assertIn('Saved your ' + field, reply)
            self.assertLess(len(reply.encode()), 1000)
            self.assertEqual(self.workflow.render_response('seller', 'session', reply, 'response'), reply)
            self.assertEqual(self.store.load(self.key)['fields'][field], value)

    def test_full_cycle_planner_and_cancellation(self):
        review = self.ask('review offer')
        edit = card_selection(json.loads(review.metadata['card_payload']), 'reject_cta')
        form = self.ask(json.dumps({**edit, 'approved': False}))
        selection = json.loads(form.metadata['card_payload'])['submit_cta']['selection']
        self.assertIn('Saved your customer', self.ask('Please change customer to Different operators'))
        self.assertEqual(self.store.load(self.key)['fields']['customer'], 'Different operators')
        explanation = self.ask('buyer explanation')
        self.assertIn('OUTDATED', explanation)
        self.assertIn('customer: Different operators', explanation)
        self.ask('review offer')
        self.assertIn('cancelled', self.ask('cancel review'))
        self.assertIn('review offer for a fresh review', self.submit(selection))
        review = self.ask('review offer')
        finish = {**card_selection(json.loads(review.metadata['card_payload']), 'approve_cta'), 'approved': True}
        before = business_state(self.store.load(self.key))
        acknowledgment = self.ask(json.dumps(finish))
        self.assertIn('Review finished for saved draft revision 1', acknowledgment)
        self.assertIn('pending intake revision 2', acknowledgment)
        self.assertIn('already finished', self.ask('Finish review (no approval or purchase)'))
        self.assertEqual(before, business_state(self.store.load(self.key)))

    def test_docs_noop_does_not_fetch_and_native_recovery_shape_is_supported(self):
        selection = self.form()
        calls = list(self.fetcher.calls)
        self.assertIn('docs unchanged', self.submit(selection, 'docs', DOC_URL))
        self.assertEqual(calls, self.fetcher.calls)
        recovery = self.ask('recovery form')
        selection = json.loads(recovery.metadata['card_payload'])['submit_cta']['selection']
        before = business_state(self.store.load(self.key))
        self.assertIn('Continuing in plain chat', self.ask(json.dumps({**selection, 'choice': 'continue', 'approved': True})))
        self.assertEqual(before, business_state(self.store.load(self.key)))
