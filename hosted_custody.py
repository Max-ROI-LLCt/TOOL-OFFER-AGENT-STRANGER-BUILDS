"""Back up and verify existing hosted source without contacting Agentverse or reading secrets."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile
import tomllib

from prepare_agentverse_release import AGENT_ADDRESS, LEGACY_DESCRIPTION, ROOT, package_digest


REQUIRED = {"README.txt", ".avctl/config.toml", "__init__.py", "agent.py", "pyproject.toml"}


def source_files(snapshot):
    snapshot = Path(snapshot).resolve()
    config = tomllib.loads((snapshot / ".avctl/config.toml").read_text(encoding="utf-8"))
    if config.get("agent", {}).get("address") != AGENT_ADDRESS:
        raise ValueError("Hosted identity does not match the existing agent.")
    names = REQUIRED | {path.name for path in snapshot.glob("*.py")}
    if not all((snapshot / name).is_file() and not (snapshot / name).is_symlink() for name in names):
        raise ValueError("Hosted source incomplete or contains a symlink.")
    if any(name.endswith(".md") or name.startswith(".env") for name in names):
        raise ValueError("Markdown and environment files must never enter custody.")
    return {name: (snapshot / name).read_bytes() for name in sorted(names)}


def create_rollback(snapshot, directory):
    directory = Path(directory)
    source = source_files(snapshot)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Create a private, existing custody directory first.")
    if directory.stat().st_mode & 0o077:
        raise ValueError("Custody directory must be accessible only to its owner (0700).")
    archive_path = directory / "existing-agent-source.tar"
    manifest_path = directory / "existing-agent-source.json"
    if archive_path.exists() or manifest_path.exists():
        raise ValueError("Custody files already exist; never overwrite a rollback.")
    with archive_path.open("xb") as output, tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in source.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o600
            member.mtime = 0
            archive.addfile(member, io.BytesIO(content))
    archive_path.chmod(0o600)
    manifest = {
        "mode": "EXISTING_AGENT_SOURCE_ONLY_NO_SECRETS_NO_SESSION_DATA",
        "agent_address": AGENT_ADDRESS,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": {name: sha256(content).hexdigest() for name, content in source.items()},
        "archive_sha256": sha256(archive_path.read_bytes()).hexdigest(),
        "rollback_requires": "Founder-authorized existing-agent update; preserve hosted storage and verify source first",
    }
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2, sort_keys=True)
    manifest_path.chmod(0o600)
    verify_rollback(directory)
    return manifest


def verify_rollback(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "existing-agent-source.json").read_text(encoding="utf-8"))
    archive_path = directory / "existing-agent-source.tar"
    if manifest["agent_address"] != AGENT_ADDRESS or sha256(archive_path.read_bytes()).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Rollback identity or archive checksum mismatch.")
    with tarfile.open(archive_path, "r") as archive:
        members = archive.getmembers()
        if any(not member.isfile() or member.name not in manifest["files"] or member.name.endswith(".md") or member.name.startswith(".env") for member in members):
            raise ValueError("Unexpected rollback member.")
        if len(members) != len(manifest["files"]) or {member.name for member in members} != set(manifest["files"]):
            raise ValueError("Missing or duplicate rollback member.")
        for member in members:
            if sha256(archive.extractfile(member).read()).hexdigest() != manifest["files"][member.name]:
                raise ValueError("Rollback source checksum mismatch.")
    return manifest


def stage_rollback(directory, destination):
    """Reconstruct the exact saved source in a fresh, non-deployed directory."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Rollback must be staged in a new isolated location.")
    manifest = verify_rollback(directory)
    with tarfile.open(Path(directory) / "existing-agent-source.tar", "r") as archive:
        source = {member.name: archive.extractfile(member).read() for member in archive.getmembers()}
    saved_config = tomllib.loads(source[".avctl/config.toml"].decode("utf-8"))
    pinned = (ROOT / "agentverse_release.toml").read_bytes()
    release_config = tomllib.loads(pinned.decode("utf-8"))
    saved_agent, release_agent = saved_config["agent"], release_config["agent"]
    if (set(saved_config) != {"agent"} or set(saved_agent) != set(release_agent)
            or saved_agent["address"] != release_agent["address"]
            or saved_agent["include"] != release_agent["include"]
            or saved_agent["description"] not in ("", LEGACY_DESCRIPTION, release_agent["description"])
            or saved_agent["readme_path"] not in ("", "README.txt")):
        raise ValueError("Rollback profile differs from the pinned existing agent.")
    project = source["pyproject.toml"].decode("utf-8")
    readme = tomllib.loads(project)["project"]["readme"]
    if readme not in ("README.md", "README.txt"):
        raise ValueError("Rollback project references an unexpected README.")
    source["pyproject.toml"] = project.replace('readme = "README.md"', 'readme = "README.txt"').encode("utf-8")
    source[".avctl/config.toml"] = pinned
    destination.mkdir(mode=0o700, parents=True)
    for name, content in source.items():
        path = destination / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
    return {
        "mode": "ROLLBACK_STAGED_NO_DEPLOY",
        "agent_address": AGENT_ADDRESS,
        "source_archive_sha256": manifest["archive_sha256"],
        "stage": str(destination),
        "stage_sha256": package_digest(destination),
        "source_files_preserved": all(
            sha256((destination / name).read_bytes()).hexdigest() == checksum
            for name, checksum in manifest["files"].items()
            if name not in {"pyproject.toml", ".avctl/config.toml"}
        ),
        "metadata_changes": ["pyproject.toml: README.txt", ".avctl/config.toml: pinned public profile"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", help="Existing isolated hosted snapshot, required when creating custody")
    parser.add_argument("--directory", required=True)
    parser.add_argument("--stage-rollback", help="Fresh isolated output path; never deploys")
    arguments = parser.parse_args()
    if not arguments.stage_rollback and not arguments.snapshot:
        parser.error("--snapshot is required when creating custody")
    result = stage_rollback(arguments.directory, arguments.stage_rollback) if arguments.stage_rollback else create_rollback(arguments.snapshot, arguments.directory)
    print(json.dumps(result, indent=2))
