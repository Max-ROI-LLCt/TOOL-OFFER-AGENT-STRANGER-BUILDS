"""Customer failure shapes; full historical acceptance inputs were not supplied."""
import json
import unittest
from tool_offer_agent.product_policy import publication_output

SOURCE = 'POST /v9/case-notes accepts note_key and case_ref. A successful response contains note_ref and state: queued.'

def request(source, extra=''):
    return 'Return one JSON object with marketing_copy, claims, publication_safe and source_endpoint. Draft a neutral description. ' + extra + ' "' + source + '"'

class SourceBindingTests(unittest.TestCase):
    def test_59_supplied_exact_documentation_is_populated(self):
        value = json.loads(publication_output('{"marketing_copy":"","claims":[],"publication_safe"}', {}, request(SOURCE)))
        self.assertEqual(value['source_endpoint'], 'POST /v9/case-notes')
        self.assertEqual(value['marketing_copy'], SOURCE)
        self.assertEqual(len(value['claims']), 2)
        self.assertFalse(value['publication_safe'])
        for claim in value['claims']:
            self.assertEqual(claim['assertion'], claim['exact_source_quote'])
            self.assertIn(claim['exact_source_quote'], SOURCE)
            self.assertEqual(claim['evidence_status'], 'SUPPORTED')

    def test_58_same_conversation_and_isolated_current_source(self):
        prior = publication_output('', {}, request(SOURCE))
        current = 'POST /v1/requests accepts request_key and case_ref. A successful response contains request_ref and state: queued.'
        message = request(current, 'Preserve timing conditions.')
        isolated = publication_output('', {}, message)
        same = publication_output(prior, {'documents': [{'text': SOURCE}], 'conversation': [{'role': 'assistant', 'content': prior}]}, message)
        self.assertEqual(isolated, same)
        self.assertNotIn('note_ref', same)
        self.assertEqual(json.loads(same)['marketing_copy'], current)

    def test_53_prose_and_pseudo_json_repaired(self):
        value = json.loads(publication_output('Here is {marketing_copy: draft}', {}, request(SOURCE)))
        self.assertTrue(value['claims'])

    def test_57_conditional_neutral_description_preserved(self):
        source = 'On successful response, POST /v1/tickets returns ticket_id and status: received.'
        value = json.loads(publication_output('', {}, request(source)))
        self.assertEqual(value['marketing_copy'], source)
        self.assertFalse(value['publication_safe'])

    def test_missing_support_explicit_failure(self):
        value = json.loads(publication_output('broken', {}, request('Unknown API.')))
        self.assertTrue(value['error']['message'])
        self.assertIsNone(value['source_endpoint'])
        self.assertFalse(value['publication_safe'])

    def test_leading_condition_cannot_be_removed(self):
        value = json.loads(publication_output('broken', {}, request('Only for admins, ' + SOURCE)))
        self.assertEqual(value['marketing_copy'], '')
        self.assertIn('error', value)

class RoutingIntegrationTests(unittest.TestCase):
    def test_native_workflow_current_source_avoids_provider_and_preserves_state(self):
        import tempfile
        from unittest.mock import Mock
        from tool_offer_agent.conversation import ConversationInterpreter
        from tool_offer_agent.storage import StateStore
        from tool_offer_agent.workflow import Workflow
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            workflow = Workflow(store=StateStore(directory + '/state.json'),
                                conversation=ConversationInterpreter(client))
            first = json.loads(workflow.handle('source-test', 'same', request(SOURCE)))
            new_source = SOURCE.replace('/v9/case-notes', '/v1/requests').replace('note_ref', 'request_ref')
            second = json.loads(workflow.handle('source-test', 'same', request(new_source)))
            isolated = json.loads(workflow.handle('source-test', 'isolated', request(new_source)))
            self.assertEqual(second, isolated)
            self.assertNotEqual(first['source_endpoint'], second['source_endpoint'])
            self.assertEqual(second['marketing_copy'], new_source)
            client.chat.completions.create.assert_not_called()
            state = workflow.store.load(workflow.store.key('source-test', 'same'))
            self.assertEqual(state['fields'], {})
            self.assertIsNone(state.get('approved_offer'))
            self.assertIsNone(state.get('fahce_checkout'))

if __name__ == '__main__':
    unittest.main()
