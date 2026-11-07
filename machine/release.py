"""Generate, verify and release the same contract through existing avctl/Wrangler workflows."""

import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "machine"))
from build_hosted import build, MODULES, validate_import_graph
from agentverse_auth import access_token, cli_environment
from discovery import authored_outputs, check_surfaces, generated_outputs, html_section, markdown_section, profile_text, replace_section, verify_live, write_or_check
from surfaces import release_identity, surface_outputs, without_release_stamp

WORK = ROOT / "data/machine-release"
BASELINE = WORK / "baseline"
CANDIDATE = WORK / "candidate"
AVCTL = str(Path.home() / ".local/bin/avctl")
WRANGLER = str(ROOT / "site/node_modules/.bin/wrangler")


def read(path):
    return json.loads(path.read_text())


def encoded(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def sources(code):
    result = {}
    for entry in json.loads(code["code"]):
        name = entry["name"]
        if name.endswith(".py"):
            if Path(name).name != name or name in result:
                raise ValueError("Unexpected hosted filename")
            result[name] = entry["value"].replace("\r\n", "\n")
    return result


def live():
    contract = read(ROOT / "machine/contract.json")
    address = contract["agent_address"]
    token = access_token()

    def fetch(path):
        request = urllib.request.Request("https://agentverse.ai" + path, headers={"Authorization": "Bearer " + token, "User-Agent": "avctl/0.1.18", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)

    metadata = fetch(f"/v2/hosting/{address}?no_cache=true")
    code = fetch(f"/v2/hosting/{address}/code?no_cache=true")
    profile = fetch(f"/v2/agents/{address}")
    latest = fetch(f"/v2/hosting/{address}?no_cache=true")
    if not (metadata["address"] == profile["address"] == address and metadata["revision"] == latest["revision"] and metadata["code_digest"] == code["digest"] == latest["code_digest"]):
        raise ValueError("Live source changed during readback")
    return {"metadata": latest, "code": code, "profile": profile}


def capture():
    if BASELINE.exists():
        raise ValueError("Baseline already exists; retain it as evidence. Use a new --work directory for the next release.")
    snapshot = live()
    BASELINE.mkdir(parents=True, mode=0o700)
    (BASELINE / "source").mkdir()
    for name, value in snapshot.items():
        (BASELINE / (name + ".json")).write_text(encoded(value))
    for name, text in sources(snapshot["code"]).items():
        (BASELINE / "source" / name).write_text(text)
    print("Captured actual deployed revision", snapshot["metadata"]["revision"], snapshot["code"]["digest"])


def generate_agent_only(selected, check=False):
    selected = tuple(dict.fromkeys(selected))
    if not selected or any(name not in MODULES or name == 'machine_contract' for name in selected):
        raise ValueError('Choose authored modules; agent-only releases preserve the machine contract')
    baseline = sources(read(BASELINE / 'code.json'))
    local_contract = (ROOT / 'tool_offer_agent/machine_contract.py').read_text()
    if local_contract != baseline['machine_contract.py']:
        raise ValueError('Local machine contract differs from live; reconcile without breaking the existing gateway')
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(local_contract).body
                 if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    contract = read(ROOT / 'machine/contract.json')
    if contract != constants['CONTRACT']:
        raise ValueError('Machine contract settings changed; not an agent-only release')
    staged = dict(baseline)
    for name in selected:
        text = (ROOT / 'tool_offer_agent' / (name + '.py')).read_text()
        staged[name + '.py'] = re.sub(r'(?m)^(\s*)from \.([a-z_]+) import ', r'\1from \2 import ', text)
    validate_import_graph(staged)
    for name, text in staged.items():
        compile(text, name, 'exec')
    profile = (profile_text(ROOT, contract) if 'machine_readable_profile' in contract else
               (ROOT / 'machine/public-profile.txt').read_text().strip().replace('{{origin}}', contract['origin']).replace('{{agent_address}}', contract['agent_address']) + '\n')
    settings = read(ROOT / 'machine/public-profile.json')
    hashes = {name: sha(text) for name, text in sorted(staged.items())}
    manifest = {'scope': 'agent_only', 'release_id': constants['RELEASE_ID'],
                'candidate_id': sha(encoded({'source_hashes': hashes, 'profile': sha(profile), 'settings': settings})),
                'selected_modules': list(selected), 'baseline_revision': read(BASELINE / 'metadata.json')['revision'],
                'baseline_digest': read(BASELINE / 'code.json')['digest'], 'source_hashes': hashes,
                'changed_modules': sorted(name for name in staged if staged[name] != baseline.get(name)),
                'profile_sha256': sha(profile), 'profile_settings': settings}
    outputs = {CANDIDATE / name: text for name, text in staged.items()}
    outputs[ROOT / 'AGENT-PROFILE.txt'] = profile
    outputs[WORK / 'manifest.json'] = encoded(manifest)
    for path, content in outputs.items():
        if check:
            if not path.exists() or path.read_text() != content:
                raise ValueError('Agent-only candidate changed; regenerate and retest: ' + path.name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    print('Verified' if check else 'Generated', manifest['candidate_id'], 'agent-only; machine release unchanged; changed:', ', '.join(manifest['changed_modules']))
    return manifest


def generate(selected, check=False, *, agent_only=False):
    if agent_only:
        return generate_agent_only(selected, check)
    from tool_offer_agent.machine import MachineRequest, MachineResponse
    from tool_offer_agent.readiness import ReadinessReport
    from uagents import Model

    contract = read(ROOT / "machine/contract.json")
    gateway = read(ROOT / "machine/gateway.json")["gateway_address"]
    write_or_check(authored_outputs(ROOT, contract), check=check)
    baseline = sources(read(BASELINE / "code.json"))
    staged = dict(baseline)
    selected = tuple(dict.fromkeys((*selected, "machine", "chat")))
    if any(name not in MODULES or name == "machine_contract" for name in selected):
        raise ValueError("Unknown module; generated machine_contract cannot be authored")
    import re
    for name in selected:
        text = (ROOT / "tool_offer_agent" / (name + ".py")).read_text()
        staged[name + ".py"] = re.sub(r"(?m)^(\s*)from \.([a-z_]+) import ", r"\1from \2 import ", text)
    guide = (ROOT / "machine/guide.txt").read_text().strip()
    profile_template = (ROOT / "machine/public-profile.txt").read_text().strip()
    profile_settings = {**read(ROOT / "machine/public-profile.json"), "description": contract["short_description"]}
    for key, value in contract["limits"].items():
        guide = guide.replace("{{" + key + "}}", str(value))
    landing = (ROOT / "site/public/index.html").read_text()
    landing = without_release_stamp(landing)
    implementation = {path.name: sha(path.read_text()) for path in (ROOT / "site/src").glob("*.mjs")}
    release = sha(encoded({"source": {name: sha(text) for name, text in sorted(staged.items()) if name != "machine_contract.py"},
                          "contract": contract, "guide": guide, "public_profile": profile_template,
                          "profile_settings": profile_settings, "gateway": gateway, "adapter": implementation,
                          "landing": sha(landing), "generator": sha(Path(__file__).read_text()),
                          "discovery_generator": sha((ROOT / "machine/discovery.py").read_text()),
                          "registry_publication": sha((ROOT / "machine/registry-publication.json").read_text()),
                          "surface_generator": sha((ROOT / "machine/surfaces.py").read_text()),
                          "discovery_routes": sha((ROOT / "site/src/discovery-routes.json").read_text()),
                          "product_styles": sha((ROOT / "site/public/product.css").read_text()),
                          "landing_styles": sha((ROOT / "site/public/styles.css").read_text()),
                          "security_headers": sha((ROOT / "site/public/_headers").read_text()),
                          "machine_client": sha((ROOT / "machine/access-client.mjs").read_text()),
                          "verified_client": sha((ROOT / "machine/client.mjs").read_text()),
                          "sitemap": sha((ROOT / "site/public/sitemap.xml").read_text()),
                          "examples": sha((ROOT / "machine/examples.py").read_text())}))
    constants = '"""Generated by machine/release.py; edit machine/contract.json instead."""\nCONTRACT = ' + repr(contract) + '\nRELEASE_ID = ' + repr(release) + '\nGATEWAY_ADDRESS = ' + repr(gateway) + '\n'
    staged["machine_contract.py"] = constants
    validate_import_graph(staged)
    generated = {"contract": contract, "release_id": release, "gateway_address": gateway,
                 "request_digest": Model.build_schema_digest(MachineRequest), "response_digest": Model.build_schema_digest(MachineResponse)}
    origin = contract["origin"]
    machine_text = "\n".join([
        "## Machine entrance", f"Release: `{release}`", contract["scope"], contract["authentication"], contract["limitations"],
        f"MCP: {origin}/mcp (Streamable HTTP, protocol 2025-11-25, JSON responses, custom Authorization header).",
        f"REST: {origin}/api/machine/<tool_name>. OpenAPI: {origin}/openapi.json. Canonical machine-readable profile: {contract['machine_readable_profile']}.",
        "MCP initialize and tools/list are public. For calls supply Authorization: Bearer <IDENTITY_BOUND_CLIENT_TOKEN>. Enroll automatically with identity proof at /machine/#access; no human approval.",
        "1. Call start_session with a fresh UUID v4 request_id; retain session_id.",
        "2. Call send_message (or a deterministic tool) with session_id and a fresh UUID v4 request_id; retain job_id.",
        "3. Poll get_result with that job_id. Only complete means completed. pending, processing and uncertain do not.",
        "4. Replaying the same operation with the same request_id returns the same job. Never use a new request_id to retry uncertain work. Conflicting arguments are rejected.",
        "5. For resumable exports preserve the manifest, fetch every indexed part with get_export_part, and verify the agent's hashes. No automatic submission.",
        "Access and gateway job/idempotency records expire seven days after session creation. Agent-side offer/audit state is retained under existing storage policy; expiry is not a deletion promise.",
        "Credentials isolate callers. Sessions cannot access other clients, ASI:One conversations, owner exports or human wallet checkouts.",
        "Limits (UTC days; message limits include commands sent through send_message): " + json.dumps(contract["limits"], sort_keys=True),
        "Quota accounting: " + json.dumps(contract["quota_accounting"], sort_keys=True),
        "Model usage is billed to the operator's existing ASI-1 integration. The owner has selected call-based abuse controls without a dollar cap. Token and reasoning usage remain logged safely; request counts do not bound dollar charges. No automatic retry of uncertain inference. Native chat remains outside the adapter's quotas.",
        "Authentication uses a dedicated Tool Offer gateway identity, ephemeral transport identities, and signed replies from the existing Tool Offer Agent identity. No FAHCE/OCI/wallet key is used; message signatures are not certifications or transactions.",
        "Native Fetch Chat Protocol is also available separately at agent address " + contract["agent_address"] + ". Resolve its current endpoint through the Agentverse Almanac and use the official uagents Chat Protocol SDK. Its chat acknowledgement is not the final reply. Native chat is the existing human-capable interface, not this restricted adapter and not covered by its quotas.",
        "### Readiness", f"Read-only report schema: {origin}/readiness.schema.json. Completed readiness reports contain the full human_readable document and source/snapshot references. Multipart reports require verified assembly. No inference or privileges. Native chat: readiness, readiness text, readiness json. Optional terminal card is a summary; text/export remains authoritative. Actual ASI UI rendering is a separate acceptance check.",
        "### Tools", *[f"- {tool['name']}: {tool['description']}" for tool in contract["tools"]],
        "### Free commands", ", ".join(contract["safe_commands"]),
    ])
    profile = profile_text(ROOT, contract, release)
    _, technical_heading, technical_body = guide.partition("## Structured intake and complete review")
    if not technical_heading:
        raise ValueError("Missing technical guide boundary; do not discard reference material")
    instructions = profile + "\n## Technical reference\n\nThe following preserves the detailed integration, recovery and operator guidance. Start with my tool for real documentation; Try a fictional example is optional.\n\n" + technical_heading + technical_body + "\n\n" + machine_text + "\n"
    discovery = {**contract, "release_id": release, "instructions": origin + "/instructions.md", "openapi": origin + "/openapi.json",
                 "mcp": {"endpoint": origin + "/mcp", "protocol_version": "2025-11-25", "transport": "streamable-http", "authentication": "identity-bound Bearer"},
                 "native": {"protocol": "Fetch Chat Protocol", "address": contract["agent_address"], "almanac": "https://agentverse.ai/v1/almanac/agents/" + contract["agent_address"]}}
    openapi = {"openapi": "3.1.0", "x-limits": contract["limits"], "x-quota-accounting": contract["quota_accounting"], "info": {"title": contract["name"] + " restricted machine adapter", "version": contract["version"], "description": contract["scope"]},
               "x-machine-readable-profile": contract["machine_readable_profile"], "x-capabilities": contract["capabilities"], "x-payments": contract["payments"],
               "servers": [{"url": origin}], "security": [{"machineBearer": []}], "x-release-id": release,
               "components": {"securitySchemes": {"machineBearer": {"type": "http", "scheme": "bearer"}}}, "paths": {}}
    report_schema = copy.deepcopy(ReadinessReport.schema(ref_template="#/components/schemas/{model}"))
    schemas = report_schema.pop("definitions", {})
    schemas["ReadinessReport"] = report_schema
    schemas["ReadinessDelivery"] = {"type": "object", "required": ["schema_version", "snapshot_sha256", "report_sha256", "delivery"],
        "properties": {"schema_version": {"const": "TOOL_OFFER_READINESS_DELIVERY_V1"}, "snapshot_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "report_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "delivery": {"enum": ["inline", "text_json", "multipart"]},
            "report": {"$ref": "#/components/schemas/ReadinessReport"}, "manifest": {"type": "object", "description": "Existing complete-payload-false export manifest; retrieve and verify all parts."}},
        "allOf": [{"if": {"properties": {"delivery": {"const": "inline"}}}, "then": {"required": ["report"]}},
                  {"if": {"properties": {"delivery": {"const": "multipart"}}}, "then": {"required": ["manifest"]}}]}
    schemas["ReadinessSummary"] = {"type": "object", "additionalProperties": False,
        "required": ["status", "scope", "basis", "authorization", "finding_count", "next_step"],
        "properties": {**{name: report_schema["properties"][name] for name in ("status", "scope", "basis", "authorization", "next_step")},
                       "finding_count": {"type": "integer", "minimum": 0}}}
    schemas["ReadinessDelivery"]["properties"]["summary"] = {"$ref": "#/components/schemas/ReadinessSummary"}
    schemas["StructuredIntake"] = {"type": "object", "additionalProperties": False, "minProperties": 1,
        "properties": {**{name: {"type": "string", "minLength": 1, "maxLength": 6000} for name in
                              ("tool_url", "customer", "pricing", "payment", "access", "invocation", "seller_name", "job")},
                       "docs": {"oneOf": [{"type": "string", "minLength": 1, "maxLength": 6000},
                           {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string", "minLength": 1, "maxLength": 2000, "format": "uri"}}]},
                       "schema": {"const": "TOOL_OFFER_INTAKE_V1"}},
        "anyOf": [{"required": [name]} for name in ("tool_url", "docs", "customer", "pricing", "payment", "access", "invocation", "seller_name", "job")]}
    openapi["components"]["schemas"] = schemas
    openapi["components"]["securitySchemes"]["machineOAuth"] = {"type": "oauth2", "flows": {"clientCredentials": {
        "tokenUrl": origin + "/oauth/token", "scopes": {"tool_offer:machine": "Bounded offer preparation and exports; no payment or administration."}}}}
    openapi["security"] = [{"machineBearer": []}, {"machineOAuth": ["tool_offer:machine"]}]
    for tool in contract["tools"]:
        openapi["paths"]["/api/machine/" + tool["name"]] = {"post": {"operationId": tool["name"], "description": tool["description"],
            "requestBody": {"required": True, "content": {"application/json": {"schema": tool["inputSchema"], "example": tool["inputSchema"].get("examples", [None])[0]}}},
            "responses": {"200": {"description": "Session, queued job or stored result; inspect status before claiming completion."}, "400": {"description": "Invalid arguments"}, "401": {"description": "Identity-bound Bearer credential required; enroll or renew using proof of key control"}, "403": {"description": "Origin not allowed"}, "405": {"description": "POST JSON required"}, "413": {"description": "Request body exceeds byte limit"}, "415": {"description": "application/json Content-Type required"}, "404": {"description": "Not found or not owned"}, "409": {"description": "Conflict or session busy/uncertain"}, "429": {"description": "Quota exceeded"}, "503": {"description": "Unavailable; do not blindly replay"}}}}
        uuid_schema = {"type": "string", "format": "uuid"}
        result_schema = {"type": "object", "required": ["session_id", "release_id"], "properties": {
            "session_id": uuid_schema, "release_id": {"type": "string"}, "expires_at": {"type": "string", "format": "date-time"}}}
        if tool["name"] != "start_session":
            result_schema["required"] += ["job_id", "status"]
            result_schema["properties"].update({"job_id": uuid_schema,
                "status": {"type": "string", "enum": ["pending", "processing", "uncertain", "complete", "error"]},
                "text": {"type": "string", "description": "Complete transport text, which may itself be a multipart manifest or explicitly incomplete generation; inspect its content."},
                "error": {"type": "string"}, "model_attempts": {"type": "integer", "minimum": 0, "maximum": 2},
                "proof": {"type": "object", "required": ["agent_address", "body", "signature"], "properties": {
                    "agent_address": {"type": "string"}, "body": {"type": "string", "description": "Exact signed UTF-8 JSON body; never reserialize before verifying SHA-256/secp256k1 via uAgents identity."},
                    "signature": {"type": "string"}}}})
        responses = openapi["paths"]["/api/machine/" + tool["name"]]["post"]["responses"]
        if tool["name"] == "get_result":
            result_schema["properties"]["readiness"] = {"$ref": "#/components/schemas/ReadinessDelivery"}
        responses["200"]["content"] = {"application/json": {"schema": result_schema}}
        for status, response in responses.items():
            if status == "200":
                continue
            response["content"] = {"application/json": {"schema": {"type": "object", "required": ["error"], "properties": {
                "error": {"type": "string"}, "recovery": {"type": "string"}, "scope": {"type": "string", "enum": ["client", "global", "session"]},
                "window": {"type": "string", "enum": ["minute", "utc_day", "lifetime"]}, "resource": {"type": "string"},
                "limit": {"type": "integer"}, "reset_at": {"type": "string", "format": "date-time"},
                "retry_after_seconds": {"type": "integer", "minimum": 1}, "retry_same_session": {"type": "boolean"}}}}}
        responses["429"]["headers"] = {"Retry-After": {"description": "Seconds until a minute/daily quota resets; absent for lifetime limits.", "schema": {"type": "integer"}}}
        responses["401"]["headers"] = {"WWW-Authenticate": {"schema": {"type": "string"}, "description": "Bearer realm=tool-offer-machine; obtain an automatically enrolled client credential."}}
    access_schemas = {
        "OAuthRegistration": {"type": "object", "additionalProperties": False, "required": ["client_name", "grant_types", "token_endpoint_auth_method", "token_endpoint_auth_signing_alg", "jwks"],
            "properties": {"client_name": {"type": "string", "minLength": 2, "maxLength": 100}, "grant_types": {"type": "array", "items": {"const": "client_credentials"}, "minItems": 1, "maxItems": 1},
                "token_endpoint_auth_method": {"const": "private_key_jwt"}, "token_endpoint_auth_signing_alg": {"const": "ES256"}, "scope": {"const": "tool_offer:machine"},
                "jwks": {"type": "object", "required": ["keys"], "properties": {"keys": {"type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "object", "description": "Public P-256 EC JWK only; private fields rejected. No remote jwks_uri fetch."}}}}}},
        "OAuthClientAssertion": {"type": "object", "required": ["client_id", "client_assertion_type", "client_assertion"], "additionalProperties": False,
            "properties": {"grant_type": {"const": "client_credentials"}, "client_id": {"type": "string"}, "client_assertion_type": {"const": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"},
                "client_assertion": {"type": "string", "description": "ES256 private_key_jwt: iss=sub=client_id, aud=exact endpoint, iat, exp<=iat+120 seconds, fresh jti. Replay rejected."}, "scope": {"const": "tool_offer:machine"}, "resource": {"const": origin + "/mcp"}}},
        "FetchEnrollment": {"type": "object", "additionalProperties": False, "required": ["body", "signature"], "properties": {
            "body": {"type": "string", "description": "Exact JSON: schema TOOL_OFFER_ACCESS_ENROLL_V1, name (2..100), use_case (10..1000), identity {type:uagents,address:caller agent1 address}, RSA-OAEP-256 public_key JWK (2048/3072/4096 bits), status_secret_sha256 (SHA-256 of applicant-generated tar_ + 32 random base64url bytes), issued_at (UTC milliseconds within 60 seconds), nonce (fresh UUID v4)."},
            "signature": {"type": "string", "description": "uAgents secp256k1 signature over SHA-256 of TOOL_OFFER_ACCESS_ENROLL_V1 followed by newline and exact body. The caller's existing identity signs, never the operator."}}},
        "OperatorAccessRequest": {"type": "object", "required": ["body", "signature"], "properties": {"body": {"type": "string", "description": "Domain-separated TOOL_OFFER_ACCESS_OWNER_V1 JSON with action list/revoke/audit, request_id (client ID for revoke/audit), issued_at UTC milliseconds and nonce UUID; expires after 60 seconds."}, "signature": {"type": "string", "description": "Existing operator gateway signature; never granted by chat, enrollment or OAuth."}}},
    }
    openapi["components"]["schemas"].update(access_schemas)
    openapi["components"]["schemas"]["OAuthTokenRequest"] = {**access_schemas["OAuthClientAssertion"],
        "required": ["grant_type", "client_id", "client_assertion_type", "client_assertion", "scope", "resource"]}
    openapi["components"]["securitySchemes"]["accessRequestCapability"] = {"type": "apiKey", "in": "header", "name": "Authorization",
        "description": "AccessRequest followed by the applicant's private tar_ status capability, not a machine Bearer token."}
    for path, schema_name, media, description in [
        ("/oauth/register", "OAuthRegistration", "application/json", "Automatic public-key client registration. Registration is not authorization. No human approval; prove possession at token endpoint."),
        ("/oauth/token", "OAuthTokenRequest", "application/x-www-form-urlencoded", "Client credentials with private_key_jwt. Required: grant_type=client_credentials, scope=tool_offer:machine, resource=" + origin + "/mcp. Scoped one-hour Bearer token returned over TLS; store privately. No refresh token or interactive consent."),
        ("/oauth/status", "OAuthClientAssertion", "application/x-www-form-urlencoded", "Read only your own registration status with a fresh assertion whose audience is this status endpoint."),
        ("/api/access/applications", "FetchEnrollment", "application/json", "Automatically verify existing Fetch identity and return request ID plus applicant-bound encrypted credential. No approval queue; RSA private key remains with applicant."),
        ("/api/access/owner", "OperatorAccessRequest", "application/json", "Signed operator list, audit and revocation only. Enrollment never requires an operator decision."),
    ]:
        openapi["paths"][path] = {"post": {"security": [], "description": description, "requestBody": {"required": True, "content": {media: {"schema": {"$ref": "#/components/schemas/" + schema_name}}}},
            "responses": {"200": {"description": "Bounded result; credentials only in private token/encrypted delivery, never discovery."}, "400": {"description": "Invalid metadata, scope or request"}, "401": {"description": "Missing, invalid, expired or replayed proof"}, "403": {"description": "Identity revoked or origin denied"}, "409": {"description": "Conflicting application replay"}, "429": {"description": "Access rate limit; honor Retry-After"}}}}
    openapi["paths"]["/api/access/applications/{request_id}"] = {"get": {"security": [{"accessRequestCapability": []}], "description": "Own Fetch application status, using Authorization: AccessRequest <private tar_ capability>. A request ID alone never grants access. Credential remains RSA-encrypted.",
        "parameters": [{"name": "request_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}], "responses": {"200": {"description": "Own status and encrypted delivery"}, "401": {"description": "Wrong capability, ID or expired application"}, "429": {"description": "Rate limited"}}}}
    summary = (f'Release: {release}\n\n' + contract["scope"] + '\n\nLimits: ' + json.dumps(contract["limits"], sort_keys=True))
    from examples import SPEC, access_html, example, quickstart, quickstart_html
    page = replace_section(access_html(contract, release), html_section(contract))
    sample = example(contract, release)
    compact = quickstart(contract, release, full=sample)
    for document in (sample, compact):
        document.update(machine_readable_profile=contract["machine_readable_profile"], capabilities=contract["capabilities"], payments=contract["payments"])
    authorization_server = {"issuer": origin, "token_endpoint": origin + "/oauth/token", "registration_endpoint": origin + "/oauth/register",
                            "grant_types_supported": ["client_credentials"], "response_types_supported": [],
                            "token_endpoint_auth_methods_supported": ["private_key_jwt"], "token_endpoint_auth_signing_alg_values_supported": ["ES256"],
                            "scopes_supported": ["tool_offer:machine"], "client_id_metadata_document_supported": False,
                            "service_documentation": origin + "/machine/", "x-status-endpoint": origin + "/oauth/status", "x-release-id": release}
    protected_resource = {"resource": origin + "/mcp", "authorization_servers": [origin], "bearer_methods_supported": ["header"],
                          "scopes_supported": ["tool_offer:machine"], "resource_documentation": origin + "/machine/", "x-release-id": release}
    outputs = {ROOT / "tool_offer_agent/machine_contract.py": constants, ROOT / "site/src/generated.json": encoded(generated), ROOT / "AGENT-PROFILE.txt": profile,
               ROOT / "site/public/index.html": landing,
               ROOT / "site/public/examples/fictional-seller.json": encoded(sample),
               ROOT / "site/public/examples/quickstart.json": encoded(compact),
               ROOT / "site/public/examples/parcel-openapi.json": encoded(SPEC),
               ROOT / "site/public/examples/parcel-openapi-compact.json": json.dumps(SPEC, ensure_ascii=False, separators=(",", ":")) + "\n",
               ROOT / "site/public/examples/index.html": replace_section(quickstart_html(compact), html_section(contract)),
               ROOT / "site/public/.well-known/oauth-authorization-server": encoded(authorization_server),
               ROOT / "site/public/.well-known/oauth-protected-resource.json": encoded(protected_resource),
               ROOT / "site/public/readiness.schema.json": encoded({**ReadinessReport.schema(), "x-release-id": release}),
               ROOT / "site/public/instructions.txt": instructions, ROOT / "site/public/llms.txt": "# Tool Offer Agent\n\n> Source-attributed offer preparation with identity-bound machine credentials; no machine payments.\n\n## Canonical interfaces\n\n" + "\n".join(f"- [{label}]({origin}{path})" for label, path in [("Instructions and recovery", "/instructions.md"), ("OpenAPI request/response schemas", "/openapi.json"), ("Discovery and quotas", "/capabilities/machines"), ("Autonomous machine authentication", "/machine/"), ("Short human example", "/examples/"), ("Compact structured example", "/examples/quickstart.json"), ("Full multipart integrity fixture", "/examples/fictional-seller.json"), ("OAuth server metadata", "/.well-known/oauth-authorization-server"), ("MCP protected resource", "/.well-known/oauth-protected-resource/mcp")]) + "\n\n" + summary + "\n",
               ROOT / "site/public/capabilities/machines": encoded(discovery), ROOT / "site/public/openapi.json": encoded(openapi),
               ROOT / "site/public/.well-known/mcp.json": encoded({"name": contract["name"], "url": origin + "/mcp", "release_id": release, "authentication": contract["authentication"], "machine_readable_profile": contract["machine_readable_profile"], "capabilities": contract["capabilities"]}),
               ROOT / "site/public/.well-known/api-catalog": encoded({"x-release-id": release, "machine_readable_profile": contract["machine_readable_profile"], "capabilities": contract["capabilities"], "linkset": [{"anchor": origin, "describedby": [{"href": contract["machine_readable_profile"], "type": "application/json"}], "service-desc": [{"href": origin + "/openapi.json", "type": "application/vnd.oai.openapi+json"}], "service-doc": [{"href": origin + "/instructions.md", "type": "text/markdown"}]}]}),
               ROOT / "site/public/machine/index.html": page}
    outputs[ROOT / "site/public/instructions.md"] = instructions
    outputs[ROOT / "site/public/llms.txt"] += "\n" + markdown_section(contract) + "\n"
    outputs.update(generated_outputs(ROOT, contract, profile, release))
    outputs = surface_outputs(ROOT, contract, release, outputs)
    outputs.update({CANDIDATE / name: text for name, text in staged.items()})
    for path, content in outputs.items():
        if check:
            if not path.exists() or path.read_text() != content:
                raise ValueError("Stale or missing generated artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    for name, text in staged.items():
        compile(text, name, "exec")
    manifest = {"release_id": release, "selected_modules": list(selected), "baseline_revision": read(BASELINE / "metadata.json")["revision"],
                "baseline_digest": read(BASELINE / "code.json")["digest"], "source_hashes": {name: sha(text) for name, text in sorted(staged.items())},
                "changed_modules": sorted(name for name in staged if staged[name] != baseline.get(name)), "profile_sha256": sha(profile),
                "profile_settings": profile_settings}
    if check and read(WORK / "manifest.json") != manifest:
        raise ValueError("Release manifest changed; regenerate and retest")
    if not check:
        (WORK / "manifest.json").write_text(encoded(manifest))
    print("Verified" if check else "Generated", release, "changed:", ", ".join(manifest["changed_modules"]))
    return manifest


def run(command, cwd=ROOT):
    if command[0] == AVCTL:
        with cli_environment() as environment:
            subprocess.run(command, cwd=cwd, check=True, timeout=180, env=environment)
    else:
        subprocess.run(command, cwd=cwd, check=True, timeout=180, env={**os.environ, "TOOL_OFFER_TEST_PYTHON": sys.executable, "WRANGLER_SEND_METRICS": "false"})


def verify():
    manifest = read(WORK / "manifest.json")
    generate(manifest["selected_modules"], check=True, agent_only=manifest.get('scope') == 'agent_only')
    check_surfaces(ROOT, read(ROOT / "machine/contract.json"))
    run([sys.executable, "-m", "tests.run_staged_wallet_regression", "--source", str(CANDIDATE), "--tests", "tests.test_card_journey"])
    run([sys.executable, "-m", "tests.run_staged_wallet_regression", "--source", str(CANDIDATE), "--tests",
         "tests.test_welcome", "tests.test_judging_polish", "tests.test_public_journey", "tests.test_native_correction", "tests.test_buyer_view", "tests.test_card_client_acceptance", "tests.test_customer_release", "tests.test_extraction_cache", "tests.test_readiness", "tests.test_chat.ChatTests", "tests.test_machine", "tests.test_buyer_guide_delivery", "tests.test_wallet_information", "tests.test_buyer_guidance", "tests.test_fahce_checkout", "tests.test_conversation", "tests.test_workflow", "tests.test_product_reliability", "tests.test_customer_repair", "tests.test_listing_guidance", "tests.test_listing_intent_regression", "tests.test_owner_export", "tests.test_consolidated_repair", "tests.test_product_upgrade", "tests.test_post_custody", "tests.test_ticketlens_acceptance", "tests.test_document_intake"])
    run([sys.executable, "-m", "unittest", "tests.test_chat"])
    run(["npm", "run", "check"], ROOT / "site")
    return manifest


def deploy(*, agent_only=False):
    manifest = verify()
    if agent_only != (manifest.get('scope') == 'agent_only'):
        raise ValueError('Deployment scope does not match the tested candidate')
    # Honor the current explicit owner policy; unknown/capped modes still need
    # financial evidence. Call-only authorization does not change credentials.
    policy = read(ROOT / "machine/contract.json").get("spending_policy") or {}
    if policy.get("mode") != "call_limits_only":
        from tool_offer_agent.model_runtime import SpendingGuard
        SpendingGuard(None, policy).configuration()
    snapshot = live()
    if sources(snapshot["code"]) != sources(read(BASELINE / "code.json")) or snapshot["code"]["digest"] != manifest["baseline_digest"]:
        raise ValueError("Deployed source drifted; do not overwrite. Capture a fresh baseline and review.")
    if snapshot["profile"] != read(BASELINE / "profile.json"):
        raise ValueError("Live profile drifted; review before overwriting")
    address = read(ROOT / "machine/contract.json")["agent_address"]
    local = tomllib.loads((ROOT / ".avctl/config.toml").read_text())["agent"]
    profile = snapshot["profile"]["profile"]
    if local["address"] != address or local["readme_path"] != "AGENT-PROFILE.txt":
        raise ValueError("AVCTL identity/profile configuration changed; review before deployment")
    context = profile_push_context(manifest, address)
    run([AVCTL, "hosting", "stop", "-a", address])
    try:
        run([AVCTL, "hosting", "push", "-a", address, "-f", ",".join(str(CANDIDATE / name) for name in manifest["source_hashes"])], cwd=context)
    finally:
        run([AVCTL, "hosting", "run", "-a", address])
    import time
    for attempt in range(6):
        current = live()
        if current["metadata"]["compiled"] and current["metadata"]["running"]:
            break
        time.sleep(5)
    if not current["metadata"]["compiled"] or not current["metadata"]["running"]:
        raise ValueError("Agent not running; website not deployed")
    if {name: sha(text) for name, text in sources(current["code"]).items()} != manifest["source_hashes"]:
        raise ValueError("Hosted readback differs from verified candidate")
    synchronize_profile_settings(current["profile"]["profile"], profile, manifest, address, context)
    current = live()
    if {name: sha(text) for name, text in sources(current["code"]).items()} != manifest["source_hashes"]:
        raise ValueError("Hosted source changed during profile synchronization")
    if not profile_matches(current["profile"]["profile"], profile, manifest):
        raise ValueError("Hosted instructions did not synchronize")
    receipt = {**manifest, "checked_at": datetime.now(timezone.utc).isoformat(), "agent_revision": current["metadata"]["revision"],
               "agent_code_digest": current["code"]["digest"], "compiled": True, "running": True, "website_deployed": False,
               "inference_calls": 0, "payment_calls": 0, "fahce_calls": 0}
    (WORK / "receipt.json").write_text(encoded(receipt))
    (WORK / "deployed-code.json").write_text(encoded(current["code"]))
    if not agent_only:
        publish_site(manifest)
    else:
        print(encoded(receipt))


def verify_deployed_agent(manifest):
    current = live()
    receipt = read(WORK / "receipt.json")
    if (receipt["release_id"] != manifest["release_id"]
            or {name: sha(text) for name, text in sources(current["code"]).items()} != manifest["source_hashes"]
            or not profile_matches(current["profile"]["profile"], read(BASELINE / "profile.json")["profile"], manifest)
            or not current["metadata"]["compiled"] or not current["metadata"]["running"]):
        raise ValueError("Agent must exactly match the verified release before publishing its website")
    return receipt


def profile_matches(current, baseline, manifest):
    expected = {**baseline, **manifest["profile_settings"], "readme": (ROOT / "AGENT-PROFILE.txt").read_text()}
    normalized = {**current, "readme": current.get("readme", "").replace("\r\n", "\n")}
    return normalized == expected


def synchronize_profile_settings(current, baseline, manifest, address, context):
    settings = manifest["profile_settings"]
    observed_settings = {name: current.get(name) for name in settings}
    if any(value not in (baseline.get(name), settings[name]) for name, value in observed_settings.items()):
        raise ValueError("Public metadata drifted during upload; do not overwrite")
    if not profile_matches(current, baseline, {**manifest, "profile_settings": observed_settings}):
        raise ValueError("Unrelated profile content changed during upload")
    for field, name in (("description", "description"), ("starter-prompts", "starter_prompts")):
        if current.get(name) != settings[name]:
            values = settings[name] if isinstance(settings[name], list) else [settings[name]]
            run([AVCTL, "hosting", "set", "agent", field, *values, "-a", address], cwd=context)


def profile_push_context(manifest, address):
    settings = manifest["profile_settings"]
    if set(settings) != {"description", "starter_prompts"} or not isinstance(settings["description"], str):
        raise ValueError("Unexpected public profile settings")
    prompts = settings["starter_prompts"]
    if not isinstance(prompts, list) or not prompts or not all(isinstance(prompt, str) and prompt.strip() for prompt in prompts):
        raise ValueError("Invalid starter prompts")
    context = WORK / "profile-push"
    (context / ".avctl").mkdir(parents=True, exist_ok=True)
    (context / "AGENT-PROFILE.txt").write_text((ROOT / "AGENT-PROFILE.txt").read_text())
    (context / "agent.py").write_text((CANDIDATE / "agent.py").read_text())
    (context / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text().replace('readme = "README.md"', 'readme = "AGENT-PROFILE.txt"'))
    configuration = {"address": address, "include": "", "readme_path": "AGENT-PROFILE.txt", **settings}
    (context / ".avctl/config.toml").write_text("[agent]\n" + "\n".join(name + " = " + json.dumps(value) for name, value in configuration.items()) + "\n")
    return context


def publish_site(manifest):
    if manifest.get('scope') == 'agent_only':
        raise ValueError('An agent-only candidate cannot publish the website')
    receipt = verify_deployed_agent(manifest)
    deployment = subprocess.run([WRANGLER, "deploy", "--config", "wrangler.production.jsonc"], cwd=ROOT / "site",
                                capture_output=True, text=True, timeout=180, env={**os.environ, "WRANGLER_SEND_METRICS": "false"})
    (WORK / "website-deploy.log").write_text(deployment.stdout + deployment.stderr)
    print(deployment.stdout)
    deployment.check_returncode()
    import re
    version = re.search(r"Current Version ID:\s*([a-f0-9-]{36})", deployment.stdout)
    if not version:
        raise ValueError("Website command completed but version receipt missing; inspect website-deploy.log")
    receipt["website_version_id"] = version.group(1)
    (WORK / "receipt.json").write_text(encoded(receipt))
    verify_site(manifest)


def publish_discovery():
    contract = read(ROOT / "machine/contract.json")
    check_surfaces(ROOT, contract)
    release = release_identity(ROOT, contract)
    if not BASELINE.exists():
        capture()
    current = live()
    baseline_code = read(BASELINE / "code.json")
    baseline_profile = read(BASELINE / "profile.json")["profile"]
    if current["code"]["digest"] != baseline_code["digest"] or sources(current["code"]) != sources(baseline_code):
        raise ValueError("Hosted source changed since capture; review the newest release before publishing discovery")
    if sources(current["code"])["machine_contract.py"] != (ROOT / "tool_offer_agent/machine_contract.py").read_text():
        raise ValueError("The hosted agent does not match the local release identity")
    settings = read(ROOT / "machine/public-profile.json")
    manifest = {"scope": "discovery_only", "release_id": release, "version": contract["version"],
                "baseline_digest": baseline_code["digest"], "profile_settings": settings,
                "source_hashes": {name: sha(text) for name, text in sources(current["code"]).items()}}
    if current["profile"]["profile"] != baseline_profile and not profile_matches(current["profile"]["profile"], baseline_profile, manifest):
        raise ValueError("Unrelated public profile edits detected; do not overwrite")
    write_or_check({WORK / "manifest.json": encoded(manifest)}, check=(WORK / "manifest.json").exists())
    context = WORK / "profile-only"
    (context / ".avctl").mkdir(parents=True, exist_ok=True)
    (context / "AGENT-PROFILE.txt").write_text((ROOT / "AGENT-PROFILE.txt").read_text())
    (context / ".avctl/config.toml").write_text('[agent]\naddress = ' + json.dumps(contract["agent_address"]) + '\nreadme_path = "AGENT-PROFILE.txt"\n')
    if not profile_matches(current["profile"]["profile"], baseline_profile, manifest):
        run([AVCTL, "hosting", "set", "agent", "readme", "AGENT-PROFILE.txt", "-a", contract["agent_address"]], cwd=context)
        updated = live()
        synchronize_profile_settings(updated["profile"]["profile"], baseline_profile, manifest, contract["agent_address"], context)
    if not (WORK / "receipt.json").exists():
        (WORK / "receipt.json").write_text(encoded({"scope": "discovery_only", "release_id": release, "version": contract["version"],
            "agent_code_unchanged": True, "hosted_code_digest": baseline_code["digest"], "website_deployed": False}))
    verify_deployed_agent(manifest)
    publish_site(manifest)


def verify_site(manifest):
    receipt = verify_deployed_agent(manifest)
    if not receipt.get("website_version_id"):
        raise ValueError("No completed Wrangler version receipt; do not infer publication")
    origin = read(ROOT / "machine/contract.json")["origin"]
    request = urllib.request.Request(origin + "/capabilities/machines", headers={"User-Agent": "ToolOfferRelease/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        public = json.load(response)
    if public["release_id"] != manifest["release_id"]:
        raise ValueError("Published machine discovery is stale")
    run(["node", "machine/readback.mjs", "--work", str(WORK)])
    receipt["public_discovery"] = verify_live(ROOT, read(ROOT / "machine/contract.json"))
    receipt["website_deployed"] = True
    receipt["website_checked_at"] = datetime.now(timezone.utc).isoformat()
    (WORK / "receipt.json").write_text(encoded(receipt))
    print(encoded(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "generate", "check", "deploy", "publish-site", "verify-site", "publish-discovery"))
    parser.add_argument("--modules", nargs="+", default=["chat", "machine"])
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--agent-only", action="store_true", help="Generate/deploy only the existing agent and profile, preserving the gateway release and website")
    arguments = parser.parse_args()
    WORK = arguments.work.resolve()
    BASELINE = WORK / "baseline"
    CANDIDATE = WORK / "candidate"
    if arguments.action == "capture":
        capture()
    elif arguments.action == "generate":
        generate(arguments.modules, agent_only=arguments.agent_only)
    elif arguments.action == "check":
        verify()
    elif arguments.action == "publish-site":
        publish_site(verify())
    elif arguments.action == "verify-site":
        verify_site(verify())
    elif arguments.action == "publish-discovery":
        publish_discovery()
    else:
        deploy(agent_only=arguments.agent_only)
