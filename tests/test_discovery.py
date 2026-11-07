"""Canonical discovery regression tests; no network, model or payment calls."""

import copy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from machine import discovery
from machine.surfaces import machine_manifest, release_identity


ROOT = Path(__file__).resolve().parents[1]


class DiscoveryTests(TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "machine/contract.json").read_text())

    def test_all_current_surfaces_match_canonical_contract(self):
        self.assertGreater(discovery.check_surfaces(ROOT, self.contract), 10)
        self.assertEqual(json.loads((ROOT / "site/public/manifest.json").read_text()), machine_manifest(self.contract, release_identity(ROOT, self.contract)))

    def test_changed_capability_cannot_pass_without_propagation(self):
        changed = copy.deepcopy(self.contract)
        changed["capabilities"].append("A deliberately unsynchronized test capability.")
        with self.assertRaisesRegex(ValueError, "Stale discovery mirrors"):
            discovery.check_surfaces(ROOT, changed)

    def test_invocation_identity_and_payment_boundaries_fail_closed(self):
        for field in ("mcp", "rest", "agentverse"):
            changed = copy.deepcopy(self.contract)
            key = {"mcp": "url", "rest": "url_template", "agentverse": "address"}[field]
            changed["invocation"][field][key] = "wrong"
            with self.assertRaisesRegex(ValueError, "Conflicting invocation"):
                discovery.validate_contract(changed)
        for field in ("optional", "separate_from_drafting", "buyer_authorization_required", "machine_adapter_supported"):
            changed = copy.deepcopy(self.contract)
            changed["payments"]["evaluation"][field] = not changed["payments"]["evaluation"][field]
            with self.assertRaisesRegex(ValueError, "buyer-authorized"):
                discovery.validate_contract(changed)

    def test_generation_is_idempotent_and_preserves_authored_content(self):
        original = "# Existing guide\n\nKeep this worked example.\n"
        section = discovery.markdown_section(self.contract)
        once = discovery.replace_section(original, section)
        self.assertEqual(discovery.replace_section(once, section), once)
        self.assertIn("Keep this worked example.", once)
        with self.assertRaisesRegex(ValueError, "Ambiguous discovery"):
            discovery.replace_section(once + discovery.START, section)

    def test_scanner_rejects_critical_stale_strings_but_preserves_history(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence").mkdir()
            stale = "No content " + "found"
            (root / "evidence/history.txt").write_text(stale)
            (root / "README.md").write_text("Current guide")
            self.assertEqual(discovery.stale_strings(root), 1)
            (root / "README.md").write_text(stale)
            with self.assertRaisesRegex(ValueError, "Critical stale discovery"):
                discovery.stale_strings(root)

    def test_public_readback_requires_exact_profile_description_and_manifest(self):
        def response(body):
            stream = io.BytesIO(body)
            stream.status = 200
            stream.headers = {"Content-Type": "application/json; charset=utf-8"}
            return stream

        manifest = (ROOT / "site/public/manifest.json").read_bytes()
        profile = {"address": self.contract["agent_address"], "name": self.contract["name"],
                   "short_description": self.contract["short_description"], "readme": discovery.profile_text(ROOT, self.contract)}
        with patch.object(discovery.urllib.request, "urlopen", side_effect=[response(manifest), response(json.dumps(profile).encode())]) as requests, \
                patch.object(discovery, "verify_public_assets", return_value={"passed": True}) as assets:
            receipt = discovery.verify_live(ROOT, self.contract)
            assets.assert_called_once_with(ROOT)
            self.assertTrue(receipt["public_surfaces"]["passed"])
            self.assertTrue(receipt["public_profile_matches"])
            self.assertFalse(receipt["authentication_used"])
            self.assertTrue(all("Authorization" not in call.args[0].headers for call in requests.call_args_list))
        profile["short_description"] = "An old public description"
        with patch.object(discovery.urllib.request, "urlopen", side_effect=[response(manifest), response(json.dumps(profile).encode())]):
            with self.assertRaisesRegex(ValueError, "profile identity differs"):
                discovery.verify_live(ROOT, self.contract)
        with patch.object(discovery.urllib.request, "urlopen", return_value=response(b"{}")):
            with self.assertRaisesRegex(ValueError, "differs from the generated source bytes"):
                discovery.verify_live(ROOT, self.contract)
