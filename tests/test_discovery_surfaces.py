"""Discovery-only regressions: prevent split versions without changing product logic."""

import copy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest import TestCase

from machine import discovery, surfaces


ROOT = Path(__file__).resolve().parents[1]


class SurfaceTests(TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "machine/contract.json").read_text())
        self.release = surfaces.release_identity(ROOT, self.contract)

    def test_machine_manifests_add_identity_and_pointers_without_mutating_contract(self):
        before = copy.deepcopy(self.contract)
        manifest = surfaces.machine_manifest(self.contract, self.release)
        self.assertEqual(self.contract, before)
        self.assertEqual(manifest["version"], self.contract["version"])
        self.assertEqual(manifest["release_id"], self.release)
        self.assertEqual(manifest["access"]["oauth"]["details"], self.contract["origin"] + "/machine/#access")
        self.assertEqual(manifest["access"]["oauth"]["openapi"], self.contract["origin"] + "/openapi.json")
        for field in ("tools", "limits", "authentication", "quota_accounting", "payments"):
            self.assertEqual(manifest[field], self.contract[field])

    def test_stamps_are_idempotent_for_all_pages_and_profiles(self):
        for source, is_html in [("<html><head>\n<title>Keep</title></head><body>Keep</body></html>\n", True),
                                ("# Keep\n\nKeep these instructions.\n", False)]:
            with self.subTest(html=is_html):
                stamped = surfaces.stamp_text(source, "1.4.7", self.release, html=is_html)
                self.assertEqual(surfaces.stamp_text(stamped, "1.4.7", self.release, html=is_html), stamped)
                newer = surfaces.stamp_text(stamped, "1.4.8", "f" * 64, html=is_html)
                self.assertNotIn(self.release, newer)
                self.assertNotIn("1.4.7", newer)
                self.assertIn("Keep", newer)
                self.assertEqual(newer.count(surfaces.STAMP_START), 1)

    def test_inventory_covers_every_asset_and_alias_not_just_named_pages(self):
        inventory = json.loads((ROOT / "site/public" / surfaces.INVENTORY).read_text())
        self.assertEqual({item["file"] for item in inventory["surfaces"] if "file" in item}, set(surfaces.public_files(ROOT)))
        paths = [item["path"] for item in inventory["surfaces"]]
        self.assertEqual(len(paths), len(set(paths)))
        for path in ("/instructions.txt", "/404", "/robots.txt", "/sitemap.xml", "/.well-known/owners.json", "/mcp/.well-known/owners.json"):
            self.assertIn(path, paths)
        self.assertFalse(any("agent-card" in path or path == "/.well-known/agent.json" for path in paths))

    def test_new_pages_and_asset_edits_block_deployment_until_synced(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "site/public", root / "site/public")
            (root / "site/src").mkdir()
            shutil.copyfile(ROOT / "site/src/discovery-routes.json", root / "site/src/discovery-routes.json")
            new_page = root / "site/public/new-guide.html"
            new_page.write_text("<html><head></head><body>New guide</body></html>")
            with self.assertRaisesRegex(ValueError, "Stale discovery mirrors"):
                discovery.write_or_check(surfaces.surface_outputs(root, self.contract, self.release), check=True)
            discovery.write_or_check(surfaces.surface_outputs(root, self.contract, self.release))
            discovery.write_or_check(surfaces.surface_outputs(root, self.contract, self.release), check=True)
            self.assertIn(self.release, new_page.read_text())
            (root / "site/public/styles.css").write_text("body { color: white; }")
            with self.assertRaisesRegex(ValueError, "discovery-surfaces.json"):
                discovery.write_or_check(surfaces.surface_outputs(root, self.contract, self.release), check=True)

    def test_split_versions_and_missing_ids_are_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "site/public", root / "site/public")
            (root / "site/src").mkdir()
            shutil.copyfile(ROOT / "site/src/discovery-routes.json", root / "site/src/discovery-routes.json")
            for name, field, value in [("manifest.json", "release_id", None), ("capabilities/machines", "version", "1.4.6"),
                                       ("openapi.json", "x-release-id", "0" * 64)]:
                path = root / "site/public" / name
                original = path.read_text()
                document = json.loads(original)
                document.pop(field) if value is None else document.update({field: value})
                path.write_text(json.dumps(document))
                with self.assertRaisesRegex(ValueError, "Stale discovery mirrors"):
                    discovery.write_or_check(surfaces.surface_outputs(root, self.contract, self.release), check=True)
                path.write_text(original)

    def test_sync_refuses_to_disguise_an_unreleased_contract_change(self):
        changed = {**self.contract, "version": "9.9.9"}
        with self.assertRaisesRegex(ValueError, "generate a full release"):
            surfaces.release_identity(ROOT, changed)

    def test_raw_wrangler_deployment_also_runs_the_guard(self):
        for name in ("wrangler.jsonc", "wrangler.production.jsonc"):
            configuration = json.loads((ROOT / "site" / name).read_text())
            self.assertEqual(configuration["build"]["command"], "python3 ../machine/discovery.py check")
