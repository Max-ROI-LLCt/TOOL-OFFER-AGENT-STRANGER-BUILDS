from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import tomllib

from prepare_agentverse_release import AGENT_ADDRESS, ROOT, package_digest, prepare
from build_hosted import MODULES
from hosted_custody import create_rollback


class PreparationTests(TestCase):
    def setUp(self):
        def synthetic_git_identity(command, **kwargs):
            self.assertEqual(command, ["git", "rev-parse", "HEAD"])
            return "SYNTHETIC_TEST_COMMIT_NOT_HISTORY\n"
        identity = patch("prepare_agentverse_release.subprocess.check_output", side_effect=synthetic_git_identity)
        identity.start()
        self.addCleanup(identity.stop)

    def test_stages_new_isolated_candidate_without_markdown_or_deployment(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            base = Path(directory)
            snapshot = base / "hosted"
            (snapshot / ".avctl").mkdir(parents=True)
            (snapshot / ".avctl" / "config.toml").write_bytes((ROOT / "agentverse_release.toml").read_bytes())
            (snapshot / "README.txt").write_bytes((ROOT / "AGENT-PROFILE.txt").read_bytes())
            (snapshot / ".env").write_text("TEST_ONLY_CANARY=not-a-credential\n")
            (snapshot / "__init__.py").write_text("\"\"\"Existing initializer.\"\"\"\n")
            (snapshot / "agent.py").write_text("old implementation")
            (snapshot / "pyproject.toml").write_text("old dependencies")
            custody = base / "custody"
            custody.mkdir(mode=0o700)
            create_rollback(snapshot, custody)
            stage = base / "candidate"
            result = prepare(snapshot, stage, custody=custody)
            self.assertEqual(result["mode"], "REVIEW_ONLY_NO_DEPLOY")
            self.assertEqual(result["release_sha256"], package_digest(stage))
            self.assertTrue(result["profile_body_preserved"])
            self.assertTrue(result["custody_archive_sha256"])
            self.assertEqual(result["files"]["agent.py"]["status"], "changed")
            self.assertEqual(result["files"]["commerce.py"]["status"], "new")
            self.assertFalse(list(stage.rglob("*.md")))
            self.assertFalse(list(stage.rglob(".env*")))
            self.assertEqual(stage.stat().st_mode & 0o777, 0o700)
            self.assertEqual(tomllib.loads((stage / ".avctl" / "config.toml").read_text())["agent"]["address"], AGENT_ADDRESS)
            self.assertEqual((stage / ".avctl" / "config.toml").read_bytes(), (snapshot / ".avctl" / "config.toml").read_bytes())
            staged_project = tomllib.loads((stage / "pyproject.toml").read_text())
            self.assertEqual(staged_project["project"]["readme"], "README.txt")
            self.assertEqual(staged_project["tool"]["setuptools"]["py-modules"], ["agent", "cli", *MODULES])
            self.assertNotIn("packages", staged_project["tool"]["setuptools"])
            with self.assertRaises(ValueError):
                prepare(snapshot, stage, custody=custody)
            (snapshot / "agent.py").write_text("unexpected hosted change")
            with self.assertRaisesRegex(ValueError, "changed since custody"):
                prepare(snapshot, base / "tampered", custody=custody)

    def test_refuses_different_hosted_agent(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            snapshot = Path(directory) / "hosted"
            (snapshot / ".avctl").mkdir(parents=True)
            (snapshot / ".avctl" / "config.toml").write_text('[agent]\naddress = "different"\n')
            with self.assertRaisesRegex(ValueError, "custody mismatch"):
                prepare(snapshot, Path(directory) / "candidate")

    def test_refuses_hosted_metadata_drift_before_staging(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            snapshot = Path(directory) / "hosted"
            (snapshot / ".avctl").mkdir(parents=True)
            original = (ROOT / "agentverse_release.toml").read_text()
            (snapshot / ".avctl" / "config.toml").write_text(original.replace('description = ', 'description = "newer hosted profile" # '))
            with self.assertRaisesRegex(ValueError, "Unreviewed Agentverse configuration"):
                prepare(snapshot, Path(directory) / "candidate")
            self.assertFalse((Path(directory) / "candidate").exists())

    def test_preserves_public_profile_when_pull_omits_metadata(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            snapshot = Path(directory) / "hosted"
            (snapshot / ".avctl").mkdir(parents=True)
            release = tomllib.loads((ROOT / "agentverse_release.toml").read_text())["agent"]
            (snapshot / ".avctl" / "config.toml").write_text(
                f'[agent]\naddress = "{AGENT_ADDRESS}"\ninclude = ""\nreadme_path = ""\ndescription = ""\n'
            )
            (snapshot / "README.txt").write_bytes((ROOT / "AGENT-PROFILE.txt").read_bytes())
            (snapshot / "__init__.py").write_text('"""Existing initializer."""\n')
            stage = Path(directory) / "candidate"
            prepare(snapshot, stage)
            staged = tomllib.loads((stage / ".avctl" / "config.toml").read_text())["agent"]
            self.assertEqual(staged["description"], release["description"])
            self.assertEqual(staged["readme_path"], "README.txt")
            self.assertEqual((stage / "README.txt").read_text(), (snapshot / "README.txt").read_text())
