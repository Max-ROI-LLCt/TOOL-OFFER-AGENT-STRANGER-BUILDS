"""The pre-release gate must fail closed without changing a hosted agent."""

from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from hosted_custody import create_rollback
from prepare_agentverse_release import AGENT_ADDRESS, APPROVED_DESCRIPTION, ROOT, package_digest
from verify_agentverse_live import verify_live


class LiveReleaseGuardTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.snapshot = base / "snapshot"
        self.snapshot.mkdir()
        (self.snapshot / ".avctl").mkdir()
        (self.snapshot / ".avctl/config.toml").write_bytes((ROOT / "agentverse_release.toml").read_bytes())
        (self.snapshot / "README.txt").write_text("Original profile guide")
        (self.snapshot / "agent.py").write_text("original = True\n")
        (self.snapshot / "__init__.py").write_text("init = True\n")
        (self.snapshot / "pyproject.toml").write_text("[project]\nname = 'agent'\n")
        self.custody = base / "custody"
        self.custody.mkdir(mode=0o700)
        create_rollback(self.snapshot, self.custody)
        self.candidate = base / "candidate"
        self.candidate.mkdir()
        (self.candidate / ".avctl").mkdir()
        (self.candidate / ".avctl/config.toml").write_bytes((ROOT / "agentverse_release.toml").read_bytes())
        (self.candidate / "agent.py").write_text("replacement = True\n")
        self.digest = package_digest(self.candidate)
        self.code = [
            {"name": "agent.py", "value": "original = True\n"},
            {"name": "__init__.py", "value": "init = True\n"},
            {"name": ".env", "value": "NEVER_EXPOSE_A_VALUE=test-only"},
        ]

    def opener(self, request, timeout):
        address_path = f"/v2/hosting/{AGENT_ADDRESS}"
        if request.full_url.endswith("/v2/agents"):
            payload = [{"address": AGENT_ADDRESS}]
        elif request.full_url.startswith("https://agentverse.ai" + address_path + "/code?"):
            payload = {"digest": "test-digest", "code": json.dumps(self.code)}
        elif request.full_url.startswith("https://agentverse.ai" + address_path + "/secrets?"):
            payload = {"secrets": [{"name": "TEST_ONLY", "secret": "NEVER_EXPOSE_A_VALUE"}]}
        elif request.full_url.startswith("https://agentverse.ai" + address_path + "?"):
            payload = {"address": AGENT_ADDRESS, "running": True, "compiled": True, "code_digest": "test-digest"}
        else:
            payload = {"address": AGENT_ADDRESS, "profile": {"description": APPROVED_DESCRIPTION, "readme": "Original profile guide"}}
        return BytesIO(json.dumps(payload).encode())

    def test_validates_live_python_guide_and_secret_names_without_values(self):
        result = verify_live(self.custody, self.candidate, self.digest, token="test-only", opener=self.opener)
        self.assertTrue(result["hosted_python_and_guide_match_rollback"])
        self.assertEqual(result["hosted_secret_names"], ["TEST_ONLY"])
        self.assertNotIn("NEVER_EXPOSE_A_VALUE", json.dumps(result))

    def test_rejects_changed_live_source_without_replacing_rollback(self):
        self.code[0]["value"] = "changed = True\n"
        with self.assertRaisesRegex(ValueError, "source changed"):
            verify_live(self.custody, self.candidate, self.digest, token="test-only", opener=self.opener)

    def test_rejects_changed_candidate_before_network_request(self):
        (self.candidate / "agent.py").write_text("changed = True\n")
        with self.assertRaisesRegex(ValueError, "Candidate changed"):
            verify_live(self.custody, self.candidate, self.digest, token="test-only", opener=self.opener)
