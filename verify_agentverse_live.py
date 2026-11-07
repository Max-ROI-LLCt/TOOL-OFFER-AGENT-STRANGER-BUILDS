"""Read-only custody gate for the existing Agentverse hosted agent."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import tarfile
import tomllib
import urllib.request

from hosted_custody import verify_rollback
from prepare_agentverse_release import AGENT_ADDRESS, APPROVED_DESCRIPTION, package_digest


def verify_live(custody, candidate, expected_candidate_sha256, *, token=None, opener=None):
    manifest = verify_rollback(custody)
    candidate = Path(candidate)
    candidate_sha256 = package_digest(candidate)
    if candidate_sha256 != expected_candidate_sha256:
        raise ValueError("Candidate changed; do not deploy.")
    config = tomllib.loads((candidate / ".avctl/config.toml").read_text(encoding="utf-8"))
    if config.get("agent", {}).get("address") != AGENT_ADDRESS:
        raise ValueError("Candidate identity changed; do not deploy.")
    if any(path.name.endswith(".md") or path.name.startswith(".env") for path in candidate.rglob("*") if path.is_file()):
        raise ValueError("Unexpected Markdown or environment file in candidate.")
    if token is None:
        token = json.loads((Path.home() / ".config/avctl/auth.json").read_text(encoding="utf-8"))["access_token"]
    open_request = opener or urllib.request.urlopen

    def fetch(path):
        request = urllib.request.Request(
            "https://agentverse.ai" + path,
            headers={"Authorization": "Bearer " + token, "User-Agent": "avctl/0.1.18", "Accept": "application/json"},
        )
        with open_request(request, timeout=20) as response:
            return json.load(response)

    agents = fetch("/v2/agents")
    if not isinstance(agents, list) or not any(agent.get("address") == AGENT_ADDRESS for agent in agents):
        raise ValueError("Authenticated account cannot list the existing agent.")
    metadata = fetch(f"/v2/hosting/{AGENT_ADDRESS}?no_cache=true")
    code = fetch(f"/v2/hosting/{AGENT_ADDRESS}/code?no_cache=true")
    profile = fetch(f"/v2/agents/{AGENT_ADDRESS}")
    secrets = fetch(f"/v2/hosting/{AGENT_ADDRESS}/secrets?no_cache=true")
    if (metadata.get("address") != AGENT_ADDRESS or not metadata.get("running")
            or not metadata.get("compiled") or metadata.get("code_digest") != code.get("digest")
            or profile.get("address") != AGENT_ADDRESS):
        raise ValueError("Live identity, runtime, or source digest changed during inspection.")
    if profile.get("profile", {}).get("description") != APPROVED_DESCRIPTION:
        raise ValueError("The existing agent description drifted.")

    python_files = {}
    for file in json.loads(code["code"]):
        name = file.get("name")
        if not isinstance(name, str) or not name.endswith(".py"):
            continue
        if "/" in name or "\\" in name or name in python_files or not isinstance(file.get("value"), str):
            raise ValueError("Unexpected hosted Python source entry.")
        python_files[name] = file["value"].encode("utf-8").replace(b"\r\n", b"\n")
    with tarfile.open(Path(custody) / "existing-agent-source.tar", "r") as archive:
        archive_python = {
            member.name: sha256(archive.extractfile(member).read().replace(b"\r\n", b"\n")).hexdigest()
            for member in archive.getmembers() if member.name.endswith(".py")
        }
    if set(python_files) != set(archive_python):
        raise ValueError("Hosted Python file list changed since rollback custody.")
    if any(sha256(content).hexdigest() != archive_python[name] for name, content in python_files.items()):
        raise ValueError("Hosted Python source changed since rollback custody.")
    if sha256(profile.get("profile", {}).get("readme", "").encode("utf-8")).hexdigest() != manifest["files"]["README.txt"]:
        raise ValueError("Hosted profile guide changed since rollback custody.")
    names = sorted(item["name"] for item in secrets.get("secrets", []) if isinstance(item.get("name"), str))
    return {
        "mode": "READ_ONLY_NO_DEPLOY", "agent_address": AGENT_ADDRESS,
        "hosted_digest": code["digest"], "hosted_revision": metadata.get("revision"),
        "hosted_python_and_guide_match_rollback": True, "candidate_sha256": candidate_sha256,
        "uncompared_hosted_entries": [".env", "pyproject.toml", ".avctl/config.toml"],
        "source_archive_sha256": manifest["archive_sha256"], "hosted_secret_names": names,
        "platform_injected_asi1_configuration_requires_hosted_acceptance": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--custody", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    arguments = parser.parse_args()
    print(json.dumps(verify_live(arguments.custody, arguments.candidate, arguments.expected_candidate_sha256), indent=2))
