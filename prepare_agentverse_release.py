"""Stage an auditable existing-agent update without invoking AVCTL mutations."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib

from build_hosted import MODULES, build


ROOT = Path(__file__).resolve().parent
CONTRACT = json.loads((ROOT / "machine/contract.json").read_text())
AGENT_ADDRESS = CONTRACT["agent_address"]
APPROVED_DESCRIPTION = CONTRACT["short_description"]
LEGACY_DESCRIPTION = APPROVED_DESCRIPTION


def digest(path):
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def package_digest(directory):
    package = sha256()
    for file in sorted(path for path in directory.rglob("*") if path.is_file()):
        package.update(file.relative_to(directory).as_posix().encode("utf-8"))
        package.update(b"\0")
        package.update(file.read_bytes())
    return package.hexdigest()


def prepare(snapshot, destination, custody=None):
    snapshot, destination = Path(snapshot).resolve(), Path(destination).resolve()
    if snapshot == destination or destination.exists():
        raise ValueError("Stage into a new isolated location, never over an existing checkout or snapshot.")
    config = ROOT / ".avctl" / "config.toml"
    release_config = ROOT / "agentverse_release.toml"
    staged_config = release_config.read_text(encoding="utf-8")
    local_config = tomllib.loads(config.read_text(encoding="utf-8")) if config.exists() else None
    release_agent = tomllib.loads(staged_config).get("agent", {})
    hosted_config = tomllib.loads((snapshot / ".avctl" / "config.toml").read_text(encoding="utf-8"))
    if (release_agent.get("address") != AGENT_ADDRESS or hosted_config.get("agent", {}).get("address") != AGENT_ADDRESS
            or local_config is not None and local_config.get("agent", {}).get("address") != AGENT_ADDRESS):
        raise ValueError("Address custody mismatch; no release staged.")
    hosted_agent = hosted_config["agent"]
    if (set(tomllib.loads(staged_config)) != {"agent"}
            or set(release_agent) != {"address", "description", "include", "readme_path"}
            or set(hosted_agent) != set(release_agent)
            or release_agent["readme_path"] != "README.txt"
            or release_agent["description"] != APPROVED_DESCRIPTION
            or release_agent["include"] != hosted_agent["include"]
            or hosted_agent["description"] not in ("", LEGACY_DESCRIPTION, APPROVED_DESCRIPTION)
            or hosted_agent["readme_path"] not in ("", release_agent["readme_path"])
            or local_config is None or local_config["agent"].get("description") not in (LEGACY_DESCRIPTION, APPROVED_DESCRIPTION)):
        raise ValueError("Unreviewed Agentverse configuration; no release staged.")
    if not (snapshot / "README.txt").is_file() or not (snapshot / "__init__.py").is_file():
        raise ValueError("Isolated hosted snapshot must preserve profile text and the hosted initializer.")
    if (snapshot / "README.txt").read_text() != (ROOT / "AGENT-PROFILE.txt").read_text():
        raise ValueError("Snapshot profile is not the canonical current profile; use machine/release.py for a synchronized release.")
    if {file.name for file in snapshot.glob("*.py")} - {"agent.py", "cli.py", "__init__.py", *(name + ".py" for name in MODULES)}:
        raise ValueError("Unrecognized hosted Python files; review them before staging.")
    custody_digest = None
    if custody:
        from hosted_custody import verify_rollback
        rollback = verify_rollback(custody)
        for name, checksum in rollback["files"].items():
            if not (snapshot / name).is_file() or sha256((snapshot / name).read_bytes()).hexdigest() != checksum:
                raise ValueError("Hosted source changed since custody backup; re-review before staging.")
        custody_digest = rollback["archive_sha256"]

    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package_layout = 'packages = ["tool_offer_agent"]\npy-modules = ["agent"]'
    if project.count('readme = "README.md"') != 1 or project.count(package_layout) != 1:
        raise ValueError("Unexpected project metadata or package layout.")
    hosted_modules = '["agent", "cli", ' + ', '.join('"' + name + '"' for name in MODULES) + ']'
    staged_project = project.replace('readme = "README.md"', 'readme = "README.txt"').replace(package_layout, 'py-modules = ' + hosted_modules)
    destination.mkdir(mode=0o700, parents=True)
    build(destination)
    (destination / "README.txt").write_bytes((snapshot / "README.txt").read_bytes())
    (destination / "__init__.py").write_bytes((snapshot / "__init__.py").read_bytes())
    (destination / "pyproject.toml").write_text(staged_project, encoding="utf-8")
    (destination / ".avctl").mkdir()
    (destination / ".avctl" / "config.toml").write_text(staged_config, encoding="utf-8")
    changes = {file.name: {"hosted_sha256": digest(snapshot / file.name) if (snapshot / file.name).exists() else None,
                           "staged_sha256": digest(file)}
               for file in sorted(destination.glob("*.py"))}
    for item in changes.values():
        item["status"] = "unchanged" if item["hosted_sha256"] == item["staged_sha256"] else "changed" if item["hosted_sha256"] else "new"
    return {
        "mode": "REVIEW_ONLY_NO_DEPLOY", "agent_address": AGENT_ADDRESS,
        "source_checkout": str(ROOT), "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "snapshot": str(snapshot), "stage": str(destination), "release_sha256": package_digest(destination),
        "custody_archive_sha256": custody_digest,
        "profile_body_preserved": digest(destination / "README.txt") == digest(snapshot / "README.txt"),
        "files": changes,
        "release_blockers": ["Founder release authorization", "Final predeployment hosted-source re-pull and diff approval",
                             "Production custody endpoint and secret-name availability review"] + ([] if custody_digest else ["Verified source rollback archive"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Isolated reviewed AVCTL hosted pull; README already converted to README.txt")
    parser.add_argument("--custody", help="Private verified source-only rollback directory for this exact snapshot")
    arguments = parser.parse_args()
    stage = Path(tempfile.mkdtemp(prefix="tool-offer-release-"))
    stage.rmdir()
    print(json.dumps(prepare(arguments.snapshot, stage, custody=arguments.custody), indent=2))
