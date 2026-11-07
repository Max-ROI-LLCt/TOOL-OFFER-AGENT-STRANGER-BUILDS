"""Generate and verify discovery mirrors without credentials or network access."""

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import tomllib
import urllib.request
import subprocess
from tempfile import TemporaryDirectory

try:
    from .surfaces import machine_manifest, release_identity, stamp_text, surface_outputs
except ImportError:
    from surfaces import machine_manifest, release_identity, stamp_text, surface_outputs


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PUBLICATION = json.loads((ROOT / "machine/registry-publication.json").read_text())
START = "<!-- tool-offer-discovery:start -->"
END = "<!-- tool-offer-discovery:end -->"
EXCLUDED_DIRECTORIES = {".git", ".venv", "node_modules", "data", "state", ".state", "evidence", ".agentverse-custody", "__pycache__", ".wrangler", "hosted_build"}


def encoded(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def validate_contract(contract):
    origin = contract["origin"]
    address = contract["agent_address"]
    if contract["machine_readable_profile"] != origin + "/manifest.json":
        raise ValueError("The canonical machine profile must be /manifest.json on the configured origin")
    if not origin.startswith("https://") or not contract["capabilities"] or not contract["does_not_do"]:
        raise ValueError("HTTPS origin, capabilities and exclusions are required")
    invocation = contract["invocation"]
    expected = {
        "agent_address": (invocation["agentverse"]["address"], address),
        "json_profile_url": (contract["json_profile_url"], f"https://agentverse.ai/v1/agents/{address}/profile"),
        "mcp_url": (invocation["mcp"]["url"], origin + "/mcp"),
        "rest_url": (invocation["rest"]["url_template"], origin + "/api/machine/{tool_name}"),
        "openapi_url": (invocation["rest"]["openapi_url"], origin + "/openapi.json"),
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ValueError("Conflicting invocation identity: " + field)
    payment = contract["payments"]
    if payment["drafting"]["price"] != "0" or payment["drafting"]["wallet_required"]:
        raise ValueError("Drafting must remain free without a wallet")
    evaluation = payment["evaluation"]
    if not all(evaluation[field] for field in ("optional", "separate_from_drafting", "buyer_authorization_required")) or evaluation["machine_adapter_supported"]:
        raise ValueError("Paid evaluation must remain separate and buyer-authorized, outside MCP/REST")
    if contract["machine_readable_profile"] not in contract["short_description"]:
        raise ValueError("The public description must advertise the machine-readable profile")


def markdown_section(contract):
    validate_contract(contract)
    invocation = contract["invocation"]
    return "\n".join([
        START, "## For machines", "",
        f"Machine-readable profile (canonical): {contract['machine_readable_profile']}", "",
        "This manifest is the authority for capabilities, invocation and payment boundaries. Read it first; no Agentverse page rendering or ASI:One login is required for discovery.", "",
        "### Capabilities", *["- " + item for item in contract["capabilities"]], "",
        "### Boundaries", *["- " + item for item in contract["does_not_do"]], "",
        f"MCP protocol endpoint (POST, not a webpage): `{invocation['mcp']['url']}`",
        f"Human machine-access documentation: {contract['origin']}/machine/",
        "Browser GET returns 405 (no standalone SSE stream). /mcp/ supports the same protocol without redirecting POST bodies.",
        f"REST request template (not a webpage): `POST {invocation['rest']['url_template']}`",
        f"Native Agentverse address: `{contract['agent_address']}` ({invocation['agentverse']['protocol']}).",
        f"Public Agentverse JSON profile: {contract['json_profile_url']}",
        "Calls require identity-bound credentials; discovery is public. " + invocation["result_handling"], "",
        "### Registry publication",
        f"Published in the official MCP Registry as `{REGISTRY_PUBLICATION['name']}`: version {REGISTRY_PUBLICATION['version']} at {REGISTRY_PUBLICATION['publishedAt']}, active/latest at the verified post-publication readback. The endpoint is {REGISTRY_PUBLICATION['endpoint']}. Publication is complete; no reenrollment or republication is required. Later local source corrections are not thereby deployed. Publication does not establish search indexing, adoption, execution certification or hackathon acceptance.", "",
        contract["payments"]["drafting"]["terms"],
        contract["payments"]["evaluation"]["terms"], END,
    ])


def html_section(contract):
    invocation = contract["invocation"]
    url = html.escape(contract["machine_readable_profile"], quote=True)
    capabilities = "".join("<li>" + html.escape(item) + "</li>" for item in contract["capabilities"])
    boundaries = "".join("<li>" + html.escape(item) + "</li>" for item in contract["does_not_do"])
    return (START + '\n<section id="for-machines" aria-labelledby="for-machines-title">'
            '<h2 id="for-machines-title">For machines</h2>'
            f'<p>Start with the <a href="{url}" type="application/json">canonical machine-readable profile</a>. '
            'No Agentverse page rendering or ASI:One login is required for discovery.</p>'
            '<h3>Capabilities</h3><ul>' + capabilities + '</ul><h3>Boundaries</h3><ul>' + boundaries + '</ul>'
            '<p><a href="/machine/">Machine access documentation</a> · '
            f'<a href="{html.escape(invocation["rest"]["openapi_url"], quote=True)}">REST API</a></p>'
            '<p>MCP protocol endpoint: <code>/mcp</code> (POST, not a webpage). '
            'Browser GET returns 405; standalone SSE is not offered. <code>/mcp/</code> accepts the same protocol.</p>'
            '<p>Published in the official MCP Registry as <code>com.kinganlogic/tool-offer-agent</code>: '
            f'version {REGISTRY_PUBLICATION["version"]}, published {REGISTRY_PUBLICATION["publishedAt"]}; active/latest at the verified post-publication readback. Registry publication is not runtime certification, '
            'guaranteed indexing, adoption or hackathon acceptance.</p>'
            '<p>' + html.escape(contract["payments"]["drafting"]["terms"]) + ' '
            + html.escape(contract["payments"]["evaluation"]["terms"]) + '</p></section>\n' + END)


def replace_section(text, section):
    if START in text or END in text:
        if text.count(START) != 1 or text.count(END) != 1:
            raise ValueError("Ambiguous discovery section; repair duplicate or incomplete markers")
        return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda unused: section, text, flags=re.S)
    if "</main>" in text:
        return text.replace("</main>", section + "\n</main>", 1)
    if "</body>" in text:
        return text.replace("</body>", section + "\n</body>", 1)
    first, separator, rest = text.partition("\n\n")
    return first + "\n\n" + section + "\n\n" + rest if separator else text + "\n\n" + section + "\n"


def profile_text(root, contract, release=None):
    template = (root / "machine/public-profile.txt").read_text()
    profile = (template.strip().replace("{{origin}}", contract["origin"])
            .replace("{{agent_address}}", contract["agent_address"])
            .replace("{{machine_discovery}}", markdown_section(contract)) + "\n")
    return stamp_text(profile, contract["version"], release or release_identity(root, contract))


def document_paths(root):
    paths = {root / name for name in ("README.md", "DISCOVERY.md", "machine/README.md", "machine/guide.txt")
             if (root / name).is_file()}
    excluded = {"AGENT-PROFILE.md", "AGENT-PROFILE.txt", "machine/public-profile.txt", "machine/guide.md", "REVIEW-REPORT.txt", "constraints-validated.txt", "requirements.txt"}
    return sorted(path for path in paths if path.relative_to(root).as_posix() not in excluded)


def authored_outputs(root, contract):
    outputs = {path: replace_section(path.read_text(), markdown_section(contract)) for path in document_paths(root)}
    landing = root / "site/public/index.html"
    if landing.exists():
        outputs[landing] = replace_section(landing.read_text(), html_section(contract))
    return outputs


def generated_outputs(root, contract, profile, release=None):
    validate_contract(contract)
    release = release or release_identity(root, contract)
    outputs = {
        root / "machine/registry-server.json": encoded({
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "com.kinganlogic/tool-offer-agent",
            "description": "Source-attributed API/MCP offer drafting, revision, readiness assessment and export.",
            "title": "Tool Offer Agent",
            "version": contract["version"],
            "remotes": [{"type": "streamable-http", "url": contract["invocation"]["mcp"]["url"]}],
        }),
        root / "site/public/manifest.json": encoded(machine_manifest(contract, release)),
        root / "AGENT-PROFILE.txt": profile,
        root / "AGENT-PROFILE.md": profile,
    }
    settings_path = root / "machine/public-profile.json"
    settings = json.loads(settings_path.read_text())
    outputs[settings_path] = encoded({**settings, "description": contract["short_description"]})
    for name in (".avctl/config.toml", "agentverse_release.toml"):
        path = root / name
        if path.exists():
            configuration = tomllib.loads(path.read_text())
            agent = configuration["agent"]
            agent.update(address=contract["agent_address"], description=contract["short_description"])
            if name == ".avctl/config.toml":
                agent.update(readme_path="AGENT-PROFILE.txt", starter_prompts=settings["starter_prompts"])
            outputs[path] = "[agent]\n" + "\n".join(key + " = " + json.dumps(value) for key, value in agent.items()) + "\n"
    guide = root / "machine/guide.txt"
    if guide.exists():
        outputs[root / "machine/guide.md"] = guide.read_text()
    return outputs


def write_or_check(outputs, check=False):
    stale = []
    for path, content in outputs.items():
        if check:
            if not path.is_file() or path.read_text() != content:
                stale.append(str(path))
        elif not path.is_file() or path.read_text() != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print("Updated", path)
    if stale:
        raise ValueError("Stale discovery mirrors:\n" + "\n".join(stale))


def stale_strings(root):
    forbidden = [r"\bTop" + r"her\b", r"Logan " + r"Pattern Engine", r"tool[o]{2}ffer\.kinganlogic\.com", r"tooloo" + r"fer\.kinganlogic\.com",
                 r"No content " + r"found", r"Paid FAHCE execution remains " + r"unconfigured",
                 r"Send wallet for " + r"buyer setup", r"Discovery: " + r"https://[^\s]+/capabilities/machines"]
    issues = []
    paths = document_paths(root)
    paths += [path for path in (root / "site/public").rglob("*") if path.is_file() and path.suffix in {".md", ".txt", ".html", ".json"}]
    paths += [root / name for name in ("AGENT-PROFILE.txt", "AGENT-PROFILE.md", "machine/public-profile.txt", "machine/public-profile.json", ".avctl/config.toml", "agentverse_release.toml") if (root / name).is_file()]
    for directory in ("tool_offer_agent", "machine", "site/src", "wallet-approval", "bridge"):
        paths += [path for path in (root / directory).rglob("*") if path.is_file()
                  and path.suffix in {".py", ".mjs", ".js", ".json", ".toml", ".html", ".md", ".txt"}
                  and not EXCLUDED_DIRECTORIES.intersection(path.relative_to(root).parts)]
    companion = root.parent / "wallet-approval"
    if companion.exists():
        paths += [path for path in companion.rglob("*") if path.is_file()
                  and path.suffix in {".mjs", ".js", ".html", ".json"}
                  and not EXCLUDED_DIRECTORIES.intersection(path.relative_to(companion).parts)]
    for path in sorted(set(paths)):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if any(re.search(pattern, line, flags=re.I) for pattern in forbidden):
                issues.append(f"{path}:{number}")
    if issues:
        raise ValueError("Critical stale discovery strings:\n" + "\n".join(issues))
    return len(set(paths))


def check_surfaces(root, contract):
    write_or_check(authored_outputs(root, contract), check=True)
    profile = profile_text(root, contract)
    write_or_check(generated_outputs(root, contract, profile), check=True)
    write_or_check(surface_outputs(root, contract, release_identity(root, contract)), check=True)
    generated = json.loads((root / "site/src/generated.json").read_text())
    if generated["contract"] != contract:
        raise ValueError("Gateway contract is stale; regenerate the full release")
    capabilities = json.loads((root / "site/public/capabilities/machines").read_text())
    for field, value in machine_manifest(contract, release_identity(root, contract)).items():
        if capabilities.get(field) != value:
            raise ValueError("Capabilities endpoint is stale: " + field)
    openapi = json.loads((root / "site/public/openapi.json").read_text())
    if openapi.get("x-machine-readable-profile") != contract["machine_readable_profile"] or openapi.get("x-capabilities") != contract["capabilities"]:
        raise ValueError("OpenAPI discovery metadata is stale")
    if set(openapi["paths"]).intersection("/api/machine/" + tool["name"] for tool in contract["tools"]) != {"/api/machine/" + tool["name"] for tool in contract["tools"]}:
        raise ValueError("OpenAPI is missing a canonical tool")
    for name in ("site/public/machine/index.html", "site/public/examples/index.html", "site/public/instructions.txt", "site/public/instructions.md", "site/public/llms.txt"):
        text = (root / name).read_text()
        if contract["machine_readable_profile"] not in text or any(item not in html.unescape(text) for item in contract["capabilities"]):
            raise ValueError("Missing canonical capabilities or machine URL: " + name)
    if (root / "site/public/instructions.txt").read_bytes() != (root / "site/public/instructions.md").read_bytes():
        raise ValueError("Markdown/text instructions diverged")
    for name in ("fictional-seller.json", "quickstart.json"):
        sample = json.loads((root / "site/public/examples" / name).read_text())
        if sample.get("machine_readable_profile") != contract["machine_readable_profile"] or sample.get("capabilities") != contract["capabilities"]:
            raise ValueError("Example discovery metadata is stale: " + name)
    return stale_strings(root)


def verify_public_assets(root):
    with TemporaryDirectory(prefix="tooloffer-discovery-") as directory:
        subprocess.run(["node", str(root / "machine/readback.mjs"), "--work", directory], cwd=root, check=True,
                       capture_output=True, text=True, timeout=300)
        return json.loads((Path(directory) / "public-readback.json").read_text())


def verify_live(root, contract):
    def fetch(url):
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ToolOfferDiscoveryVerification/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200 or "application/json" not in response.headers.get("Content-Type", ""):
                raise ValueError("Not a public JSON response: " + url)
            return response.read()

    check_surfaces(root, contract)
    local = (root / "site/public/manifest.json").read_bytes()
    public = fetch(contract["machine_readable_profile"])
    if public != local:
        raise ValueError("Live manifest differs from the generated source bytes")
    profile = json.loads(fetch(contract["json_profile_url"]))
    if profile.get("address") != contract["agent_address"] or profile.get("name") != contract["name"] or profile.get("short_description") != contract["short_description"]:
        raise ValueError("Public Agentverse profile identity differs")
    if profile.get("readme", "").replace("\r\n", "\n") != profile_text(root, contract):
        raise ValueError("Public Agentverse JSON README differs from the generated manifest-driven profile")
    surfaces = verify_public_assets(root)
    return {"manifest_url": contract["machine_readable_profile"], "manifest_sha256": hashlib.sha256(public).hexdigest(),
            "json_profile_url": contract["json_profile_url"], "public_profile_matches": True, "authentication_used": False,
            "version": contract["version"], "release_id": release_identity(root, contract), "public_surfaces": surfaces}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sync", "check", "stale", "live"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--extra-doc-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    contract = json.loads((root / "machine/contract.json").read_text())
    validate_contract(contract)
    if args.action == "sync":
        release = release_identity(root, contract)
        write_or_check(authored_outputs(root, contract))
        write_or_check(surface_outputs(root, contract, release, generated_outputs(root, contract, profile_text(root, contract, release), release)))
    elif args.action == "check":
        print("Verified discovery surfaces; scanned", check_surfaces(root, contract), "active documents")
    elif args.action == "stale":
        print("Critical stale-string hits: 0 across", stale_strings(root), "active documents")
    else:
        print(encoded(verify_live(root, contract)))
    for extra in args.extra_doc_root:
        write_or_check(authored_outputs(extra.resolve(), contract), check=args.action != "sync")
        stale_strings(extra.resolve())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
