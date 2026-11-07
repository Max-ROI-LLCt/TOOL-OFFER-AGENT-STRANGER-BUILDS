"""Executable fictional seller fixture. No network, credentials or model calls."""
import hashlib
import json
import html
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid5, NAMESPACE_URL

from uagents_core.identity import Identity
from tool_offer_agent.documents import Document
from tool_offer_agent.export_delivery import reassemble
from tool_offer_agent.machine import MachineService, MachineRequest
from tool_offer_agent.offer_representation import buyer_offer, buyer_explanation
from tool_offer_agent.storage import StateStore
from tool_offer_agent.workflow import Workflow

from tool_offer_agent.parcel_fixture import URL, TOOL, SPEC as PARCEL_SPEC, FIELDS

SPEC = {**PARCEL_SPEC,
    "x-synthetic-notes": ["Fictional documentation retained to demonstrate multipart source export. " + str(i) for i in range(65)],
}
INTAKE = "\n".join(k + ": " + v for k, v in FIELDS.items())


class FictionalFetcher:
    def fetch(self, url):
        if url != URL:
            raise AssertionError("Fixture permits only its fictional documentation URL")
        return Document(URL, URL, json.dumps(SPEC, ensure_ascii=False), "application/json")


def example(contract, release_id, session_id="b8d164fa-706f-4c33-86d9-b393f7d3212c", *, signed=False):
    UUID(session_id)
    gateway = Identity.from_seed("fictional-fixture-gateway-only", 0)
    signer = Identity.from_seed("fictional-fixture-agent-only", 0)
    sender = Identity.from_seed("fictional-fixture-transport-only", 0).address
    records = []
    with TemporaryDirectory() as temporary:
        store = StateStore(Path(temporary) / "example.sqlite3")
        service = MachineService(Workflow(store=store, fetcher=FictionalFetcher()), contract, release_id, gateway.address, clock=lambda: 1793664000)

        def call(tool, arguments):
            rid = str(UUID(bytes=hashlib.sha256(("fictional:" + str(len(records))).encode()).digest()[:16], version=4))
            body = json.dumps({"principal": "fictional-client", "session_id": session_id, "request_id": rid,
                "operation": tool, "arguments": arguments, "release_id": release_id, "issued_at": 1793664000, "transport_sender": sender})
            result = service.execute(MachineRequest(body=body, authorization=gateway.sign_digest(hashlib.sha256(body.encode()).digest())), sender)
            signed_body = json.dumps(result)
            proof = {"agent_address": signer.address, "body": signed_body, "signature": signer.sign_digest(hashlib.sha256(signed_body.encode()).digest())}
            record = {"tool": tool, "arguments": {"session_id": session_id, "request_id": rid, **arguments}, "result": {**result, **({"proof": proof} if signed else {})}}
            job_id = str(UUID(bytes=hashlib.sha256(("fictional-job:" + str(len(records))).encode()).digest()[:16], version=4))
            record["accepted_response"] = {"job_id": job_id, "session_id": session_id, "release_id": release_id, "status": "pending"}
            record["poll"] = {"tool": "get_result", "arguments": {"job_id": job_id},
                              "response": {"job_id": job_id, **record["result"]}}
            records.append(record)
            assert result["status"] == "complete" and result.get("model_attempts", 0) == 0
            return result

        call("send_message", {"message": INTAKE})
        readiness = call("assess_offer_readiness", {})
        if readiness.get("readiness", {}).get("delivery") == "multipart":
            report_manifest = readiness["readiness"]["manifest"]
            report_parts = [json.loads(call("get_export_part", {"export_id": report_manifest["export_id"], "index": i})["text"])
                            for i in range(1, report_manifest["total_parts"] + 1)]
            assert "human_readable" in json.loads(reassemble(report_manifest, report_parts))
        exported = call("export_offer", {"format": "json"})
        manifest = json.loads(exported["text"])
        assert manifest["schema"] == "TOOL_OFFER_EXPORT_MANIFEST_V1"
        parts = [json.loads(call("get_export_part", {"export_id": manifest["export_id"], "index": i})["text"])
                 for i in range(1, manifest["total_parts"] + 1)]
        reconstructed = json.loads(reassemble(manifest, parts))
        state = store.load(store.key("machine:fictional-client", session_id))
        assert reconstructed["draft"] == state["draft"]
        return {"machine_readable_profile": contract["machine_readable_profile"], "capabilities": contract["capabilities"], "payments": contract["payments"],
                "fictional": True, "release_id": release_id, "scope": "Offline controlled fixture, not a live API, purchase, attestation or seller authorization.",
            "stress_coverage": "Retained filler source notes force multipart delivery. Accepted, polled and completed objects intentionally exercise response binding and client assembly; these are not live customer records.",
            "raw_api_facts": SPEC, "seller_assertions": FIELDS,
            "operational_proof": "NOT_ESTABLISHED: no external API invocation", "seller_commercial_authority": "NOT_ESTABLISHED: fictional seller assertions only",
            "buyer_offer": buyer_offer(state["draft"]), "buyer_copy": buyer_explanation(state["draft"]),
            "start_session": {"tool": "start_session", "arguments": {"request_id": "bb3ee030-c486-44fd-b3ce-468db93f1786"},
                              "response": {"session_id": session_id, "expires_at": "2026-11-10T00:00:00.000Z", "release_id": release_id}},
            "controlled_session_id": session_id, "operations": records,
            "polling": {"tool": "get_result", "arguments": records[0]["poll"]["arguments"], "completion": "Only complete is complete; preserve request IDs and verify proof. Static IDs illustrate the controlled fixture. The real gateway test creates and polls fresh jobs."},
            "multipart_verification": {"verified": True, "parts": len(parts), "sha256": manifest["sha256"], "bytes": manifest["total_bytes"]}}


def quickstart(contract, release_id, *, full=None):
    """A compact projection of actual deterministic output, not a fabricated marketing sample."""
    full = example(contract, release_id) if full is None else full
    operation = SPEC["paths"]["/normalize"]["post"]
    return {"machine_readable_profile": contract["machine_readable_profile"], "capabilities": contract["capabilities"], "payments": contract["payments"],
            "schema": "TOOL_OFFER_QUICKSTART_V1", "fictional": True, "release_id": release_id,
            "source": {"url": URL, "openapi": {k: v for k, v in SPEC.items() if k != "x-synthetic-notes"},
                       "scope": "Fictional source claims; no external API execution."},
            "seller_terms": FIELDS,
            "buyer_offer": full["buyer_copy"],
            "machine_offer": {"method": "POST", "path": "/normalize", "description": operation["summary"],
                              "request_schema": operation["requestBody"]["content"]["application/json"]["schema"],
                              "response_schema": operation["responses"]["200"]["content"]["application/json"]["schema"],
                              "source_pointers": ["/paths/~1normalize/post/summary", "/paths/~1normalize/post/requestBody", "/paths/~1normalize/post/responses/200"],
                              "pricing": full["buyer_offer"]["seller_terms"]["pricing"],
                              "evaluation": {"status": "not_requested", "machine_adapter_execution": "unavailable_by_design", "separate_human_checkout": "available_in_native_flow_subject_to_input_readiness"}},
            "distinctions": {"source_alignment": "Verified derivation of retained structural fields; not a contiguous quote or proof of truth.",
                             "operational_proof": "not_established", "seller_identity": "fictional_not_authenticated", "commercial_permission": "not_established"},
            "continue": {"authentication": contract["access"], "steps": ["Automatically enroll with OAuth or existing Fetch identity proof.",
                         "Create a session with a fresh request_id; send the fictional seller intake.",
                         "Poll each returned job until complete. Assess readiness and export; verify all multipart hashes."],
                         "full_integrity_fixture": contract["origin"] + "/examples/fictional-seller.json"}}


def quickstart_html(value):
    copy = "".join('<p>' + html.escape(line) + '</p>' for line in value['buyer_offer'].splitlines() if line.strip())
    request = html.escape(json.dumps(SPEC['paths']['/normalize']['post']['requestBody']['content']['application/json']['example'], indent=2))
    response = html.escape(json.dumps(SPEC['paths']['/normalize']['post']['responses']['200']['content']['application/json']['example'], indent=2))
    content = '''<section class="product-hero"><p class="eyebrow">A FICTIONAL API. A REAL OUTPUT.</p>
<h1>From API facts.<br>To a <em>buyer-ready explanation.</em></h1>
<p class="product-lede">Meet ParcelFormat: a fictional dimensions API. See what the source says, what its seller proposes, and what Tool Offer actually produces. No login needed to explore.</p>
<div class="actions"><a class="button button-primary" href="#buyer">Read the resulting offer</a><a class="button button-secondary" href="/examples/quickstart.json">Inspect compact JSON</a></div>
<ol class="journey"><li>01 · Read the source</li><li>02 · Add seller terms</li><li>03 · Explain the offer</li></ol></section>
<section class="product-grid" aria-label="Evidence and terms"><article class="product-panel"><p class="eyebrow">01 / DOCUMENTED INTERFACE</p><h2>One job. Clear limits.</h2>
<p><code>POST /normalize</code> converts length, width and height from centimetres or inches to centimetres.</p>
<dl><dt>Inputs</dt><dd>Length, width and height: required positive numbers. Unit: required, <code>cm</code> or <code>in</code>.</dd>
<dt>Outputs</dt><dd>JSON with length_cm, width_cm and height_cm. The source declares number fields but does not mark response properties required.</dd>
<dt>Not included</dt><dd>No carrier quotes, shipment booking or seller verification.</dd></dl>
<p class="product-note">Source pointer: <code>/paths/~1normalize/post</code>. Fictional .invalid documentation is supplied locally, never fetched. <a href="/examples/parcel-openapi.json">Download the fictional OpenAPI source</a>; this is documentation, not a running parcel service.</p></article>
<article class="product-panel"><p class="eyebrow">02 / SELLER-SUPPLIED TERMS</p><h2>The commercial layer.</h2><p class="price-line">$9 <span>USD / month</span></p>
<p>1,000 calls. Overage disabled. Proposed by Fictional Parcel Workshop for shipping-form developers.</p>
<dl><dt>Payment</dt><dd>Fictional invoice. No payment connection exists.</dd><dt>Access</dt><dd>Fictional seller-issued API key. Do not use a real credential.</dd>
<dt>Permission</dt><dd>Not established. A pricing statement is not proof of ownership or a right to resell.</dd></dl></article></section>
<section id="buyer" class="product-section"><p class="eyebrow">03 / ACTUAL DETERMINISTIC OUTPUT</p><h2>The offer your buyer reads.</h2>
<p>Generated from the same retained source and seller terms as the structured example—not handwritten substitute marketing copy.</p>
<article class="buyer-document" aria-label="Complete buyer explanation">''' + copy + '''</article></section>
<section class="product-section"><p class="eyebrow">A SMALL REQUEST. A USEFUL RESULT.</p><h2>The API, at a glance.</h2>
<div class="product-grid"><article class="product-panel"><h3>Example request</h3><pre>''' + request + '''</pre></article>
<article class="product-panel"><h3>Example response</h3><pre>''' + response + '''</pre></article></div>
<p>Exact schemas, requiredness, original examples and source pointers remain intact in <a href="/examples/quickstart.json">compact machine JSON</a>.</p></section>
<section class="product-section"><h2>Evidence, without overclaiming.</h2><div class="evidence-grid">
<article><h3>Source-backed</h3><p>Method, path and summary are a verified composition of structural source fields—not a contiguous quotation.</p></article>
<article><h3>Not operational proof</h3><p>No external API was executed. Readiness is preparation for review, not a certification.</p></article>
<article><h3>Not commercial permission</h3><p>Seller identity and distribution rights remain unverified. Nothing is listed or purchased.</p></article></div>
<details><summary>Optional FAHCE evaluation is a separate decision</summary><p>No evaluation was requested here. The machine adapter does not execute FAHCE by design. The native flow has a separate human-approved checkout, subject to input readiness; its evaluation charge is not this fictional API’s price.</p></details></section>
<section class="product-section product-next"><p class="eyebrow">MAKE IT YOUR OWN</p><h2>Your source. Your next offer.</h2>
<p>Authenticate with your own machine identity, start a session, supply your facts, then assess and export. No human enrollment approval. Keep every job ID until its result is complete.</p>
<div class="actions"><a class="button button-primary" href="/machine/#access">Connect an agent</a><a class="button button-secondary" href="/examples/fictional-seller.json">Full multipart integrity example</a></div>
<p class="product-note">The full fixture retains repeated polling/result views and long source notes deliberately to exercise multipart delivery and recovery. It is the stress test, not the introduction.</p></section>'''
    return page_shell('A fictional API, a real buyer offer', value['release_id'], content, '/examples/')


def page_shell(title, release_id, content, current):
    navigation = ''.join('<a href="' + route + '"' + (' aria-current="page"' if route == current else '') + '>' + label + '</a>'
                         for route, label in [('/', 'Overview'), ('/examples/', 'Example'), ('/machine/', 'Machine access')])
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="tool-offer-release" content="' + html.escape(release_id) + '"><title>Tool Offer | ' + html.escape(title) + '</title>'
            '<link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/product.css"><link rel="service-desc" type="application/vnd.oai.openapi+json" href="/openapi.json">'
            '</head><body class="product-page"><a class="skip-link" href="#main">Skip to content</a><header class="site-header"><div class="container nav-inner">'
            '<a class="brand" href="/">TOOL OFFER<span class="accent-dot"> / </span>KINGAN LOGIC</a><nav aria-label="Main">' + navigation + '</nav></div></header>'
            '<main id="main" class="container">' + content + '</main><footer class="container product-footer"><p>Source-attributed. Permission-aware. Not a trust certification.</p>'
            '<p><a href="/capabilities/machines">Discovery</a> · <a href="/openapi.json">OpenAPI</a> · <a href="/instructions.md">Full instructions</a> · <a href="/llms.txt">llms.txt</a></p>'
            '<details><summary>Release identity</summary><code>' + html.escape(release_id) + '</code></details></footer></body></html>\n')


def access_html(contract, release_id):
    limits = contract['limits']
    content = '''<section class="product-hero"><p class="eyebrow">ONE AGENT. TWO ENTRANCES.</p><h1>Your agent.<br><em>Its own access.</em></h1>
<p class="product-lede">Discover publicly. Prove control of your machine identity. Prepare source-attributed offers through MCP or REST—without a human enrollment queue.</p>
<p>MCP uses <code>POST /mcp</code> (2025-11-25 JSON responses), not a normal webpage. Browser <code>GET /mcp</code> and <code>GET /mcp/</code> return <code>405 Method Not Allowed</code> with a documentation link; no standalone SSE stream is offered. Both paths accept identical POST requests without redirects. Use the canonical <code>/mcp</code> URL in clients.</p>
<div class="actions"><a class="button button-primary" href="#access">Authenticate your machine</a><a class="button button-secondary" href="/examples/">See the result first</a></div>
<p class="product-note">Existing Bearer clients continue to work. Registration alone grants no access. Identity proves key control—not seller trust, ownership or distribution rights.</p></section>
<section class="quota-strip" aria-label="Machine quotas"><div><strong>''' + str(limits['daily_messages_per_client']) + '''</strong><span>messages / client / UTC day</span></div>
<div><strong>''' + f"{limits['daily_messages_global']:,}" + '''</strong><span>messages / service / UTC day</span></div><div><strong>''' + f"{limits['daily_operations_global']:,}" + '''</strong><span>operations / service / UTC day</span></div></section>
<section id="access" class="product-section"><p class="eyebrow">AUTONOMOUS AUTHENTICATION</p><h2>Choose your existing identity path.</h2>
<div class="product-grid"><article class="product-panel"><p class="eyebrow">ANY AGENT FRAMEWORK</p><h3>OAuth client credentials</h3>
<ol><li>Create a P-256 signing key locally. Register only its public JWK at <code>POST /oauth/register</code>.</li>
<li>Receive your stable client ID. Authenticate with <code>private_key_jwt</code>: sign a short-lived ES256 assertion and call <code>POST /oauth/token</code>.</li>
<li>Use the one-hour Bearer token. Renew unattended with a fresh assertion; keys and quota identity stay the same.</li></ol>
<p>Check your own registration using a fresh endpoint-bound assertion at <code>POST /oauth/status</code>. No client secret or refresh token.</p></article>
<article class="product-panel"><p class="eyebrow">EXISTING FETCH / UAGENTS IDENTITY</p><h3>Sign. Enroll. Continue.</h3>
<ol><li>Sign a fresh structured application using your existing Fetch identity. Include a separate RSA encryption public key and a hash of your private status capability.</li>
<li>Submit to <code>POST /api/access/applications</code>. Receive a request ID and a credential encrypted only to you.</li>
<li>Decrypt locally. Retrieve your status with the private <code>AccessRequest</code> capability; the public ID alone cannot access it.</li></ol>
<p>Credentials expire in 30 days. Re-enroll with the same Fetch identity to retain your quota principal. Your private signing key never leaves your client.</p></article></div></section>
<section class="product-section" id="example"><h2>A working client, not a contact form.</h2>
<p>From this project’s checkout, with Node 22 or later and its dependencies installed, the client creates private key storage and handles assertions, renewal and encrypted delivery. Its output does not print credentials.</p>
<pre>node machine/access-client.mjs register ~/.tooloffer/client.json "My agent"
node machine/access-client.mjs status ~/.tooloffer/client.json
node machine/access-client.mjs call ~/.tooloffer/client.json start_session '{"request_id":"&lt;fresh UUID v4&gt;"}'</pre>
<p>Generate a fresh UUID for each new operation; the placeholder is not executable. For an existing Fetch key instead:</p>
<pre>node machine/access-client.mjs fetch-enroll ~/.tooloffer/fetch.json /private/path/to/fetch-key</pre>
<p>The Fetch key file must be mode 0600 and contain your existing 64-character hex signing key. Keep the identity state for recovery; never upload either file to this site or source control.</p>
<details><summary>Implement OAuth in your own client</summary><p>Read <a href="/.well-known/oauth-authorization-server">authorization-server metadata</a> and <a href="/.well-known/oauth-protected-resource/mcp">MCP protected-resource metadata</a>. Exact request schemas are in <a href="/openapi.json">OpenAPI</a>.</p>
<p>Token requests are form-encoded: <code>grant_type=client_credentials</code>, <code>scope=tool_offer:machine</code>, <code>resource=https://tooloffer.kinganlogic.com/mcp</code>, client ID, assertion type and signed assertion. JWT claims require <code>iss=sub=client_id</code>, exact endpoint <code>aud</code>, <code>iat</code>, <code>exp</code> within 120 seconds, and a fresh <code>jti</code>. Replays are rejected.</p>
<p>Client ID Metadata Documents, remote JWKS fetch, interactive authorization-code consent, enterprise federation and A2A task operations are not implemented. No interoperability claim beyond these supported routes.</p></details></section>
<section class="product-section"><p class="eyebrow">KEEP THE RESULT, NOT JUST THE ACKNOWLEDGEMENT</p><h2>A recoverable offer workflow.</h2>
<ol class="workflow-steps"><li><strong>Start.</strong> Call <code>start_session</code>; retain its session ID.</li>
<li><strong>Supply.</strong> Send your source and commercial facts with <code>send_message</code>; retain its job ID.</li>
<li><strong>Retrieve.</strong> Poll <code>get_result</code> until <code>complete</code>. Pending, uncertain or truncated output is not a completed answer.</li>
<li><strong>Review.</strong> Call <code>assess_offer_readiness</code>, then <code>export_offer</code>. For multipart delivery, fetch every indexed part and verify each hash, total byte length and aggregate hash.</li></ol>
<p>After an interrupted request, replay its <em>same</em> request ID and arguments. Do not create duplicate jobs with new IDs. See the <a href="/examples/fictional-seller.json">complete multipart integrity fixture</a> and <a href="/instructions.md">recovery instructions</a>.</p></section>
<section class="product-section product-grid"><article class="product-panel"><h2>Bounded by design.</h2><p>Only scoped Bearer credentials can call protected operations. Cookies, registration IDs and browser WebMCP discovery do not grant access.</p>
<p>Enrollment: 5 requests/IP/UTC day; 100 globally. Access traffic: 30/IP/minute, 600 globally/minute, 10,000 globally/day. Credential issuance: 1,000 globally/day. Invalid attempts count. Honor <code>Retry-After</code>.</p>
<p>At most four issued tokens per identity remain valid at once. Rotation never resets machine quotas. Operators can revoke abusive identities; chat cannot mint credentials or grant operator privileges.</p></article>
<article class="product-panel"><h2>Native chat stays separate.</h2><p>ASI:One uses the native Fetch Chat Protocol, not this restricted machine adapter. Native conversations and this adapter’s sessions do not share state; native chat is outside these adapter quotas.</p>
<p>No wallet connection, payment, publishing or FAHCE evaluation through machine calls. The existing separate human-approved evaluation checkout remains available in native chat, subject to readiness. A seller’s API price and an optional evaluation charge are different things.</p></article></section>'''
    return page_shell('Autonomous machine access', release_id, content, '/machine/')


if __name__ == "__main__":
    import sys, os
    contract = json.loads((Path(__file__).parent / "contract.json").read_text())
    generated = json.loads((Path(__file__).parents[1] / "site/src/generated.json").read_text())
    print(json.dumps(example(contract, generated["release_id"], *sys.argv[1:], signed=os.getenv("TOOL_OFFER_FIXTURE_SIGNED") == "1"), ensure_ascii=False))
