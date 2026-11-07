from unittest import TestCase
from tool_offer_agent.drafting import extract

class LiveFeedbackTests(TestCase):
    def test_wrapped_capability_keeps_exact_complete_sentence(self):
        text = 'API Documentation\nThe API endpoint /v1/forecast accepts a geographical coordinate, a list of\nweather variables and responds with a JSON hourly forecast. More text.'
        facts = extract([{'source_url': 'https://example.com/docs', 'text': text}])
        quote = facts['capabilities'][0]['text']
        self.assertIn(quote, text)
        self.assertTrue(quote.endswith('forecast.'))
        self.assertIn('\nweather variables', quote)

    def test_variable_header_does_not_become_parameter(self):
        text = 'Parameter | Format | Required | Default | Description\nlatitude | Float | Yes | | Coordinate\nVariable | Valid time | Unit | Description\ntemperature_2m | Instant | C | Temperature'
        facts = extract([{'source_url': 'https://example.com/docs', 'text': text}])
        self.assertEqual(len(facts['inputs']), 1)
        self.assertNotIn('Variable', facts['inputs'][0]['text'])
