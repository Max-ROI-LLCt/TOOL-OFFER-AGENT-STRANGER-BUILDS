"""A full future release must regenerate every mirror without identity drift."""

import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from build_hosted import build
from machine import discovery, release


class ReleaseSurfaceTests(TestCase):
    def test_full_generation_updates_contract_version_everywhere_and_is_repeatable(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("machine", "tool_offer_agent", "site/src", "site/public"):
                shutil.copytree(release.ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
            for name in ("README.md", "AGENT-PROFILE.txt", "AGENT-PROFILE.md", "agentverse_release.toml"):
                shutil.copyfile(release.ROOT / name, root / name)
            contract = json.loads((root / "machine/contract.json").read_text())
            contract["version"] = "1.4.8"
            (root / "machine/contract.json").write_text(json.dumps(contract, indent=2) + "\n")
            work = root / "data/test-release"
            baseline = work / "baseline"
            built = build(baseline / "source")
            entries = [{"name": path.name, "value": path.read_text()} for path in sorted(built.glob("*.py"))]
            (baseline / "code.json").write_text(json.dumps({"code": json.dumps(entries), "digest": "test-only-digest"}))
            (baseline / "metadata.json").write_text(json.dumps({"revision": 1}))
            with patch.object(release, "ROOT", root), patch.object(release, "WORK", work), \
                    patch.object(release, "BASELINE", baseline), patch.object(release, "CANDIDATE", work / "candidate"):
                generated = release.generate(("chat", "machine"))
                checked = release.generate(("chat", "machine"), check=True)
            self.assertEqual(generated, checked)
            self.assertGreater(discovery.check_surfaces(root, contract), 10)
            for name in ("manifest.json", "capabilities/machines", "discovery-surfaces.json"):
                document = json.loads((root / "site/public" / name).read_text())
                self.assertEqual(document["release_id"], generated["release_id"])
                self.assertEqual(document["version"], "1.4.8")
            self.assertIn(generated["release_id"], (root / "AGENT-PROFILE.txt").read_text())
