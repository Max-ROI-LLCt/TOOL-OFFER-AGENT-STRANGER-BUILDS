import base64
import json
import os
from pathlib import Path
import time
from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory

from machine.agentverse_auth import access_token, cli_environment
from machine import release


class DeploymentAuthenticationTests(TestCase):
    def test_discovery_only_publish_changes_profile_without_uploading_or_restarting_agent(self):
        contract = release.read(release.ROOT / 'machine/contract.json')
        settings = release.read(release.ROOT / 'machine/public-profile.json')
        source = (release.ROOT / 'tool_offer_agent/machine_contract.py').read_text()
        baseline_profile = {**settings, 'readme': 'Earlier profile presentation'}
        desired_profile = {**settings, 'readme': (release.ROOT / 'AGENT-PROFILE.txt').read_text()}
        code = {'code': json.dumps([{'name': 'machine_contract.py', 'value': source}]), 'digest': 'unchanged-digest'}
        before = {'code': code, 'profile': {'profile': baseline_profile}}
        after = {'code': code, 'profile': {'profile': desired_profile}}
        with TemporaryDirectory() as directory:
            work = Path(directory)
            baseline = work / 'baseline'
            baseline.mkdir()
            (baseline / 'code.json').write_text(json.dumps(code))
            (baseline / 'profile.json').write_text(json.dumps({'profile': baseline_profile}))
            with patch.object(release, 'WORK', work), patch.object(release, 'BASELINE', baseline), \
                    patch.object(release, 'live', side_effect=[before, after]), patch.object(release, 'run') as command, \
                    patch.object(release, 'verify_deployed_agent') as verify_agent, patch.object(release, 'publish_site') as publish:
                release.publish_discovery()
            self.assertEqual(command.call_count, 1)
            self.assertEqual(command.call_args.args[0], [release.AVCTL, 'hosting', 'set', 'agent', 'readme', 'AGENT-PROFILE.txt', '-a', contract['agent_address']])
            verify_agent.assert_called_once()
            publish.assert_called_once()
            self.assertEqual(publish.call_args.args[0]['scope'], 'discovery_only')
            self.assertTrue(release.read(work / 'receipt.json')['agent_code_unchanged'])

    def setUp(self):
        environment = patch.dict(os.environ, {"AGENTVERSE_API_KEY": "", "AGENTVERSE_API_TOKEN": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def test_agent_only_deployment_preserves_website_and_reads_back_source(self):
        source = 'agent = None\n'
        address = release.read(release.ROOT / 'machine/contract.json')['agent_address']
        settings = {'description': 'Controlled test profile', 'starter_prompts': ['what do you do?']}
        profile = {**settings, 'readme': (release.ROOT / 'AGENT-PROFILE.txt').read_text()}
        manifest = {'scope': 'agent_only', 'baseline_digest': 'controlled-digest', 'source_hashes': {'agent.py': release.sha(source)},
                    'profile_settings': settings, 'release_id': 'controlled-release'}
        snapshot = {'code': {'code': json.dumps([{'name': 'agent.py', 'value': source}]), 'digest': 'controlled-digest'},
                    'profile': {'address': address, 'profile': profile},
                    'metadata': {'address': address, 'revision': 80, 'compiled': True, 'running': True}}
        with TemporaryDirectory() as directory:
            work = Path(directory)
            baseline = work / 'baseline'
            baseline.mkdir()
            for name in ('code', 'profile'):
                (baseline / (name + '.json')).write_text(json.dumps(snapshot[name]))
            with patch.object(release, 'WORK', work), patch.object(release, 'BASELINE', baseline), \
                    patch.object(release, 'verify', return_value=manifest), patch.object(release, 'live', return_value=snapshot), \
                    patch.object(release, 'profile_push_context', return_value=work), patch.object(release, 'run') as command, \
                    patch.object(release, 'publish_site') as publish, patch('builtins.print'):
                release.deploy(agent_only=True)
            publish.assert_not_called()
            self.assertEqual([call.args[0][2] for call in command.call_args_list], ['stop', 'push', 'run'])
            receipt = json.loads((work / 'receipt.json').read_text())
            self.assertFalse(receipt['website_deployed'])
            self.assertEqual(receipt['agent_code_digest'], 'controlled-digest')
            self.assertEqual(receipt['source_hashes'], manifest['source_hashes'])

    def test_agent_only_generation_preserves_unselected_source_and_gateway_release(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('machine', 'tool_offer_agent', 'baseline'):
                (root / name).mkdir()
            contract = {'origin': 'https://example.invalid', 'agent_address': 'controlled-existing-agent'}
            contract_source = 'CONTRACT = ' + repr(contract) + '\nRELEASE_ID = "existing-gateway-release"\n'
            baseline = {'agent.py': 'agent = None\n', 'preserved.py': 'VALUE = "retained live edit"\n',
                        'customer_recovery.py': 'MESSAGE = "before"\n', 'machine_contract.py': contract_source}
            (root / 'baseline/code.json').write_text(json.dumps({'code': json.dumps([
                {'name': name, 'value': text} for name, text in baseline.items()]), 'digest': 'baseline-digest'}))
            (root / 'baseline/metadata.json').write_text(json.dumps({'revision': 79}))
            (root / 'tool_offer_agent/machine_contract.py').write_text(contract_source)
            (root / 'tool_offer_agent/customer_recovery.py').write_text('MESSAGE = "after"\n')
            (root / 'machine/contract.json').write_text(json.dumps(contract))
            (root / 'machine/public-profile.txt').write_text('Try {{origin}}\n')
            (root / 'machine/public-profile.json').write_text(json.dumps({'description': 'Test', 'starter_prompts': ['start']}))
            with patch.object(release, 'ROOT', root), patch.object(release, 'WORK', root), \
                    patch.object(release, 'BASELINE', root / 'baseline'), patch.object(release, 'CANDIDATE', root / 'candidate'), \
                    patch('builtins.print'):
                manifest = release.generate(['customer_recovery'], agent_only=True)
                self.assertEqual(release.generate(['customer_recovery'], check=True, agent_only=True), manifest)
                self.assertEqual(manifest['changed_modules'], ['customer_recovery.py'])
                self.assertEqual(manifest['release_id'], 'existing-gateway-release')
                self.assertEqual((root / 'candidate/preserved.py').read_text(), baseline['preserved.py'])
                self.assertEqual((root / 'candidate/machine_contract.py').read_text(), contract_source)
                self.assertFalse((root / 'site').exists())
                (root / 'tool_offer_agent/machine_contract.py').write_text(contract_source + '\n')
                with self.assertRaisesRegex(ValueError, 'differs from live'):
                    release.generate(['customer_recovery'], agent_only=True)

    def test_agent_only_scope_cannot_publish_site_or_use_full_deploy(self):
        manifest = {'scope': 'agent_only'}
        with patch.object(release, 'verify', return_value=manifest), patch.object(release, 'live') as live:
            with self.assertRaisesRegex(ValueError, 'scope'):
                release.deploy()
            with self.assertRaisesRegex(ValueError, 'cannot publish'):
                release.publish_site(manifest)
            live.assert_not_called()

    def test_founders_key_name_takes_precedence_and_stays_private(self):
        with patch.dict(os.environ, {"AGENTVERSE_API_KEY": "controlled-key", "AGENTVERSE_API_TOKEN": "other-token"}):
            self.assertEqual(access_token(), "controlled-key")
            with cli_environment() as environment:
                self.assertNotIn("AGENTVERSE_API_KEY", environment)
                self.assertNotIn("AGENTVERSE_API_TOKEN", environment)
                saved = json.loads((Path(environment["HOME"]) / ".config/avctl/auth.json").read_text())
                self.assertEqual(saved["access_token"], "controlled-key")

    def test_secret_precedes_browser_login_without_persisting_or_exporting_it(self):
        with patch.dict(os.environ, {"AGENTVERSE_API_TOKEN": "controlled-personal-token"}):
            self.assertEqual(access_token(), "controlled-personal-token")
            with cli_environment() as environment:
                path = Path(environment["HOME"]) / ".config/avctl/auth.json"
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(path.read_text())["access_token"], "controlled-personal-token")
                self.assertNotIn("AGENTVERSE_API_TOKEN", environment)
                self.assertNotEqual(environment["HOME"], os.environ["HOME"])
            self.assertFalse(path.exists())

    def test_expired_jwt_fails_without_disclosing_it(self):
        claims = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) - 30}).encode()).decode().rstrip("=")
        token = "header." + claims + ".controlled-secret-signature"
        with patch.dict(os.environ, {"AGENTVERSE_API_TOKEN": token}):
            with self.assertRaisesRegex(ValueError, "has expired") as failure:
                with cli_environment():
                    self.fail("Expired token accepted")
            self.assertNotIn(token, str(failure.exception))

    def test_normal_cli_login_environment_is_preserved(self):
        with patch.dict(os.environ, {"AGENTVERSE_API_TOKEN": ""}):
            with cli_environment() as environment:
                self.assertEqual(environment["HOME"], os.environ["HOME"])

    def test_bearer_header_and_multiline_secrets_are_rejected(self):
        for token in ("Bearer controlled", "controlled\nsecret"):
            with patch.dict(os.environ, {"AGENTVERSE_API_TOKEN": token}):
                with self.assertRaisesRegex(ValueError, "raw personal token"):
                    access_token()
