import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from machine.discovery import authored_outputs, generated_outputs, markdown_section, stale_strings
from tool_offer_agent.readiness import digest


ROOT = Path(__file__).resolve().parents[1]


class PresentationAccuracyTests(TestCase):
    def test_aliases_reject_in_source_and_large_companion_bundle(self):
        for alias in ('Top' + 'her', 'Logan ' + 'Pattern Engine'):
            with TemporaryDirectory() as directory:
                root = Path(directory) / 'ToolOfferAgent'
                root.mkdir()
                (root / 'README.md').write_text('Tool Offer Agent')
                companion = root.parent / 'wallet-approval/public'
                companion.mkdir(parents=True)
                bundle = companion / 'app.js'
                bundle.write_text(' ' * 1_000_000 + alias)
                with self.assertRaisesRegex(ValueError, 'Critical stale'):
                    stale_strings(root)

    def test_historical_documents_are_not_generation_targets(self):
        contract = json.loads((ROOT / 'machine/contract.json').read_text())
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('Current documentation')
            history = root / 'CONTINUE-POST-CUSTODY.txt'
            history.write_text('Historical snapshot: do not restamp')
            self.assertNotIn(history, authored_outputs(root, contract))

    def test_real_intake_and_demo_are_distinct_and_registry_is_published(self):
        profile = (ROOT / 'machine/public-profile.txt').read_text()
        self.assertLess(profile.index('### Start with my tool'), profile.index('### Try a fictional example'))
        self.assertIn('actual service information', profile)
        self.assertIn('Demonstration only. No commercial use.', profile)
        guide = (ROOT / 'machine/guide.txt').read_text()
        publication = json.loads((ROOT / 'machine/registry-publication.json').read_text())
        self.assertIn(publication['publishedAt'], guide)
        self.assertIn('version ' + publication['version'], markdown_section(json.loads((ROOT / 'machine/contract.json').read_text())))
        self.assertIn('com.kinganlogic/tool-offer-agent', guide)
        self.assertNotIn('preparation is not publication', guide)

    def test_record_hash_is_not_source_text_hash(self):
        document = {'source_url': 'https://example.invalid/docs', 'text': 'Synthetic café documentation'}
        expected = hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        self.assertEqual(digest(document), expected)
        self.assertNotEqual(digest(document), hashlib.sha256(document['text'].encode('utf-8')).hexdigest())

    def test_registry_candidate_follows_contract_without_claiming_publication(self):
        contract = json.loads((ROOT / 'machine/contract.json').read_text())
        outputs = generated_outputs(ROOT, contract, 'Tool Offer Agent')
        candidate = json.loads(outputs[ROOT / 'machine/registry-server.json'])
        self.assertEqual(candidate['version'], contract['version'])
        self.assertEqual(candidate['name'], 'com.kinganlogic/tool-offer-agent')
        self.assertEqual(candidate['remotes'][0]['url'], contract['invocation']['mcp']['url'])
        self.assertNotIn('_meta', candidate)

    def test_completed_registry_publication_matches_preserved_server_bytes(self):
        publication = json.loads((ROOT / 'machine/registry-publication.json').read_text())
        server_bytes = (ROOT / 'machine/registry-server.json').read_bytes()
        server = json.loads(server_bytes)
        self.assertEqual(publication['published_source']['registry_server_sha256'], hashlib.sha256(server_bytes).hexdigest())
        self.assertEqual((publication['name'], publication['version'], publication['endpoint']),
                         (server['name'], server['version'], server['remotes'][0]['url']))
        self.assertEqual(publication['status'], 'active')
        self.assertIs(publication['isLatest'], True)
        self.assertIn('Owner-supplied', publication['evidence_origin'])

    def test_protocol_addresses_are_code_not_navigation(self):
        contract = json.loads((ROOT / 'machine/contract.json').read_text())
        section = markdown_section(contract)
        self.assertIn('`POST ' + contract['invocation']['rest']['url_template'] + '`', section)
        self.assertIn('`' + contract['invocation']['mcp']['url'] + '`', section)
        self.assertIn(contract['origin'] + '/machine/', section)
