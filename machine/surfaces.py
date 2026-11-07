"""Release presentation and exhaustive public-asset inventory; no runtime changes."""

import ast
import copy
import hashlib
import json
import mimetypes
from pathlib import Path
import re


STAMP_START = "<!-- tool-offer-release:start -->"
STAMP_END = "<!-- tool-offer-release:end -->"
INVENTORY = "discovery-surfaces.json"


def encoded(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def release_identity(root, contract):
    generated = json.loads((root / "site/src/generated.json").read_text())
    constants = {node.targets[0].id: ast.literal_eval(node.value)
                 for node in ast.parse((root / "tool_offer_agent/machine_contract.py").read_text()).body
                 if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    if generated["contract"] != contract or constants["CONTRACT"] != contract:
        raise ValueError("Runtime contract differs; generate a full release before syncing discovery")
    release = generated["release_id"]
    if not re.fullmatch(r"[a-f0-9]{64}", release) or constants["RELEASE_ID"] != release:
        raise ValueError("Agent and gateway release identities differ")
    return release


def machine_manifest(contract, release):
    manifest = {"schema": contract["schema"], "version": contract["version"], "release_id": release, **copy.deepcopy(contract)}
    manifest["access"]["oauth"].update(details=contract["origin"] + "/machine/#access", openapi=contract["origin"] + "/openapi.json")
    return manifest


def without_release_stamp(text):
    text = re.sub(re.escape(STAMP_START) + r".*?" + re.escape(STAMP_END) + r"\n?", "", text, flags=re.S)
    return re.sub(r'<meta name="tool-offer-(?:release|version)" content="[^"]+">\n?', "", text)


def stamp_text(text, version, release, *, html=False):
    text = without_release_stamp(text)
    text = re.sub(r'(Release:\s*`?)[a-f0-9]{64}', lambda match: match[1] + release, text)
    text = re.sub(r'(<summary>Release identity</summary><code>)[a-f0-9]{64}', lambda match: match[1] + release, text)
    if html:
        metadata = f'<meta name="tool-offer-version" content="{version}"><meta name="tool-offer-release" content="{release}">'
        text = text.replace("<head>", "<head>" + metadata + "\n", 1)
        stamp = f'{STAMP_START}<p class="container release-identity">Version: {version} · Release: <code>{release}</code></p>{STAMP_END}'
        return text.replace("</body>", stamp + "\n</body>", 1)
    stamp = f"{STAMP_START}\nVersion: {version}\nRelease: {release}\n{STAMP_END}\n"
    first, separator, rest = text.partition("\n\n")
    return first + "\n\n" + stamp + rest if separator else stamp + text


def public_files(root):
    public = root / "site/public"
    ignored = {".assetsignore", "_headers", "_redirects"}
    ignore_file = public / ".assetsignore"
    if ignore_file.exists():
        ignored.update(line.strip() for line in ignore_file.read_text().splitlines() if line.strip() and not line.startswith("#"))
    return {path.relative_to(public).as_posix(): path for path in sorted(public.rglob("*"))
            if path.is_file() and path.relative_to(public).as_posix() not in ignored}


def surface_outputs(root, contract, release, outputs=None):
    outputs = dict(outputs or {})
    public = root / "site/public"
    files = public_files(root)
    if (public / "instructions.md").exists():
        files["instructions.md"] = public / "instructions.md"
    files.update({path.relative_to(public).as_posix(): path for path in outputs if path.is_relative_to(public)})
    aliases = json.loads((root / "site/src/discovery-routes.json").read_text())
    for name, path in files.items():
        if name == INVENTORY or path.suffix not in {".html", ".md", ".txt", ".json"} and name not in {"capabilities/machines", ".well-known/api-catalog", ".well-known/oauth-authorization-server"}:
            continue
        text = outputs.get(path, path.read_text() if path.exists() else "")
        if path.suffix == ".html":
            outputs[path] = stamp_text(text, contract["version"], release, html=True)
        elif path.suffix in {".txt", ".md"} and name != "robots.txt":
            outputs[path] = stamp_text(text, contract["version"], release)
        elif path.suffix not in {".txt", ".md"}:
            document = json.loads(text)
            if name in {"manifest.json", "capabilities/machines"}:
                document = {**machine_manifest(contract, release), **{key: value for key, value in document.items() if key not in {*contract, "release_id"}}}
            elif "release_id" in document:
                document.update(release_id=release, version=contract["version"])
            elif "x-release-id" in document:
                document.update({"x-release-id": release, "x-tool-offer-version": contract["version"]})
                if name == "openapi.json":
                    document["info"]["version"] = contract["version"]
            else:
                continue
            outputs[path] = encoded(document)
    routes = []
    for name, path in sorted(files.items()):
        if name == INVENTORY or "/" + name in aliases:
            continue
        content = outputs[path].encode() if path in outputs else path.read_bytes()
        if path.suffix in {".json", ".html", ".txt", ".md"}:
            mentions = re.findall(r'\brelease_id"\s*:\s*"([a-f0-9]{64})"', content.decode())
            if any(value != release for value in mentions):
                raise ValueError("Embedded release identity is stale; regenerate the full artifact: " + name)
        route = "/" + name
        redirects = []
        if name.endswith("index.html"):
            canonical = route.removesuffix("index.html")
            redirects = [route] + ([canonical.rstrip("/")] if canonical != "/" else [])
            route = canonical
        elif name.endswith(".html"):
            redirects = [route]
            route = route.removesuffix(".html")
        content_type = mimetypes.guess_type(name)[0] or "application/json"
        content_type = "text/markdown" if name == "instructions.md" else content_type
        routes.append({"path": route, "file": name, "content_type": content_type, "sha256": hashlib.sha256(content).hexdigest()})
        routes.extend({"path": alias, "redirect": route} for alias in redirects)
    for alias, target in aliases.items():
        match = next(item for item in routes if item.get("file") == target.lstrip("/"))
        routes.append({**match, "path": alias, "content_type": "text/markdown" if alias.endswith(".md") else match["content_type"]})
    routes.append({"path": "/" + INVENTORY, "file": INVENTORY, "content_type": "application/json"})
    outputs[public / INVENTORY] = encoded({"schema": "TOOL_OFFER_DISCOVERY_SURFACES_V1", "version": contract["version"], "release_id": release,
        "surfaces": sorted(routes, key=lambda item: item["path"]),
        "dynamic_discovery": ["/mcp initialize", "/mcp tools/list", contract["json_profile_url"]],
        "excluded": {"/.webmcp/bridge.js": "Cloudflare-managed injection, not a Tool Offer release asset.",
                     "/cdn-cgi/": "Cloudflare-managed infrastructure, not Tool Offer product documentation."}})
    return outputs
