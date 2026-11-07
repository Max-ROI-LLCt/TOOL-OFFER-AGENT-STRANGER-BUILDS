from pathlib import Path
from tempfile import TemporaryDirectory
import tomllib
from unittest import TestCase

from hosted_custody import create_rollback, stage_rollback, verify_rollback
from prepare_agentverse_release import ROOT


class CustodyTests(TestCase):
    def test_source_only_backup_is_verifiable_and_immutable(self):
        with TemporaryDirectory() as folder:
            snapshot = Path(folder) / "snapshot"
            destination = Path(folder) / "custody"
            snapshot.mkdir()
            destination.mkdir(mode=0o700)
            (snapshot / ".avctl").mkdir()
            (snapshot / ".avctl/config.toml").write_bytes((ROOT / "agentverse_release.toml").read_bytes())
            (snapshot / "README.txt").write_text("Preserved hosted profile")
            (snapshot / "__init__.py").write_text("original initializer")
            (snapshot / "agent.py").write_text("original hosted code")
            (snapshot / "pyproject.toml").write_text("original dependencies")
            (snapshot / ".env").write_text("SECRET_CANARY=must-not-copy")
            manifest = create_rollback(snapshot, destination)
            self.assertEqual(manifest, verify_rollback(destination))
            self.assertNotIn(".env", manifest["files"])
            with self.assertRaisesRegex(ValueError, "never overwrite"):
                create_rollback(snapshot, destination)
            with (destination / "existing-agent-source.tar").open("ab") as archive:
                archive.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "checksum"):
                verify_rollback(destination)

    def test_rejects_wrong_agent(self):
        with TemporaryDirectory() as folder:
            snapshot = Path(folder)
            (snapshot / ".avctl").mkdir()
            (snapshot / ".avctl/config.toml").write_text('[agent]\naddress="wrong"\n')
            with self.assertRaisesRegex(ValueError, "identity"):
                create_rollback(snapshot, snapshot)

    def test_stages_existing_agent_rollback_without_markdown_or_secrets(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            snapshot = base / "snapshot"
            custody = base / "custody"
            stage = base / "restored"
            (snapshot / ".avctl").mkdir(parents=True)
            custody.mkdir(mode=0o700)
            (snapshot / ".avctl/config.toml").write_text(
                (ROOT / "agentverse_release.toml").read_text().replace('readme_path = "README.txt"', 'readme_path = ""')
            )
            (snapshot / "README.txt").write_text("Existing profile")
            (snapshot / "__init__.py").write_text('"""Initializer."""\n')
            (snapshot / "agent.py").write_text("original = True\n")
            (snapshot / "pyproject.toml").write_text('[project]\nname = "my-agent"\nreadme = "README.md"\n')
            (snapshot / ".env").write_text("SECRET_CANARY=must-not-copy")
            manifest = create_rollback(snapshot, custody)
            result = stage_rollback(custody, stage)
            self.assertEqual(result["mode"], "ROLLBACK_STAGED_NO_DEPLOY")
            self.assertEqual(result["source_archive_sha256"], manifest["archive_sha256"])
            self.assertTrue(result["source_files_preserved"])
            self.assertEqual((stage / "agent.py").read_bytes(), (snapshot / "agent.py").read_bytes())
            self.assertEqual((stage / "README.txt").read_bytes(), (snapshot / "README.txt").read_bytes())
            self.assertEqual((stage / ".avctl/config.toml").read_bytes(), (ROOT / "agentverse_release.toml").read_bytes())
            self.assertEqual("README.txt", tomllib.loads((stage / "pyproject.toml").read_text())["project"]["readme"])
            self.assertFalse(list(stage.rglob("*.md")))
            self.assertFalse(list(stage.rglob(".env*")))
            self.assertEqual(stage.stat().st_mode & 0o777, 0o700)
            with self.assertRaisesRegex(ValueError, "new isolated"):
                stage_rollback(custody, stage)
