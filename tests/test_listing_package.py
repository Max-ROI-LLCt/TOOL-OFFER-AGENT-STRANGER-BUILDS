import json
from unittest import TestCase
from tests.support import StoreTestMixin, FakeFetcher, INTAKE
from tool_offer_agent.workflow import Workflow


class ListingTests(StoreTestMixin, TestCase):
    def test_listing_binds_offer_and_does_not_publish(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        workflow.handle('seller', 'session', INTAKE)
        package = json.loads(workflow.handle('seller', 'session', 'export listing'))
        self.assertEqual(package['distribution']['status'], 'not_published')
        self.assertEqual(len(package['offer_sha256']), 64)
        self.assertEqual(package['independent_evaluation']['status'], 'not_requested')
        self.assertIn('No draft yet', workflow.handle('other', 'session', 'export listing'))

    def test_question_preserves_intake(self):
        workflow = Workflow(store=self.store)
        workflow.handle('seller', 'session', 'Can you help me prepare an offer?')
        self.assertEqual(self.store.load(self.store.key('seller', 'session'))['fields'], {})

    def test_distribution_and_lineage_survive_restart(self):
        workflow = Workflow(store=self.store, fetcher=FakeFetcher())
        workflow.handle('seller', 'session', INTAKE)
        original = json.loads(workflow.handle('seller', 'session', 'export listing'))
        workflow.handle('seller', 'session', 'distribution select Agentverse, Direct buyer')
        workflow.handle('seller', 'session', 'revise pricing: USD 5 per call')
        workflow.handle('seller', 'session', 'draft limited')
        restored = Workflow(store=self.store, fetcher=FakeFetcher())
        package = json.loads(restored.handle('seller', 'session', 'export listing'))
        self.assertEqual(package['distribution']['selected_destinations'], ['Agentverse', 'Direct buyer'])
        self.assertEqual(package['distribution']['status'], 'not_published')
        self.assertEqual(package['lineage'][0]['sha256'], original['offer_sha256'])
        self.assertEqual(package['lineage'][-1]['successor_sha256'], package['offer_sha256'])
