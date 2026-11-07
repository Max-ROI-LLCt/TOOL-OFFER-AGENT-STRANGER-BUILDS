# Discovery and synchronized release procedure

<!-- tool-offer-discovery:start -->
## For machines

Machine-readable profile (canonical): https://tooloffer.kinganlogic.com/manifest.json

This manifest is the authority for capabilities, invocation and payment boundaries. Read it first; no Agentverse page rendering or ASI:One login is required for discovery.

### Capabilities
- Read public API/MCP documentation and retain source-attributed evidence.
- Collect seller-stated customer, pricing, payment, access and invocation terms.
- Draft, review and revise an offer within an isolated conversation.
- Explain the buyer offer and prepare listing guidance without publication.
- Assess retained offer readiness deterministically without inference or payment.
- Export structured and human-readable records, with verified multipart retrieval when needed.

### Boundaries
- Does not certify sellers, prove service execution, grant resale rights or publish listings.
- Does not share ASI:One conversation history with machine sessions.
- Does not connect wallets, create checkouts, execute FAHCE or make payments through MCP/REST.
- Does not sign, spend automatically or authorize a purchase on a buyer's behalf.

MCP protocol endpoint (POST, not a webpage): `https://tooloffer.kinganlogic.com/mcp`
Human machine-access documentation: https://tooloffer.kinganlogic.com/machine/
Browser GET returns 405 (no standalone SSE stream). /mcp/ supports the same protocol without redirecting POST bodies.
REST request template (not a webpage): `POST https://tooloffer.kinganlogic.com/api/machine/{tool_name}`
Native Agentverse address: `agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a` (Fetch Agent Chat Protocol).
Public Agentverse JSON profile: https://agentverse.ai/v1/agents/agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a/profile
Calls require identity-bound credentials; discovery is public. Retain session_id, request_id and job_id. Poll get_result for the same job; an acknowledgement is not completion. Never retry uncertain work with a new request_id. Verify signed results and every multipart export part.

### Registry publication
Published in the official MCP Registry as `com.kinganlogic/tool-offer-agent`: version 1.4.9 at 2026-11-07T03:32:16.914361Z, active/latest at the verified post-publication readback. The endpoint is https://tooloffer.kinganlogic.com/mcp. Publication is complete; no reenrollment or republication is required. Later local source corrections are not thereby deployed. Publication does not establish search indexing, adoption, execution certification or hackathon acceptance.

Drafting is free; operator inference costs and published quotas still apply.
Optional FAHCE evaluation is separate and buyer-authorized: 0.15 USDC on Base mainnet via the private human checkout. A free preflight is not an evaluation. Checkout preparation, wallet connection and a 402 challenge are not payment authorization, settlement or a completed result. Changed price, network, token or recipient stops payment. No automatic spending.
<!-- tool-offer-discovery:end -->

The canonical source is `machine/contract.json`. Its public, credential-free JSON
mirror is `/manifest.json` on the existing configured origin, augmented with the
current hosted/gateway `release_id` and OAuth documentation pointers. The human `/machine/`
page, capabilities endpoint, OpenAPI and Agentverse README are mirrors, not competing
authorities. The public Agentverse v1 JSON profile returns the README directly;
its v2 administration endpoint is authenticated and is not a discovery link.

## Discovery-only repairs to the current deployed release

For presentation/metadata repairs that do not change product behavior:

1. Run `python3 machine/discovery.py sync`, then
   `python3 machine/discovery.py check`. Sync refuses to proceed if the source
   contract, generated gateway and hosted-source constants disagree.
2. Run `python3 machine/release.py publish-discovery --work data/<unique-audit>`.
   This verifies the live hosted source, updates only the Agentverse profile,
   deploys the existing Cloudflare Worker/assets, and verifies both publications.
   It never stops, uploads, replaces or rolls back the hosted agent code.
3. Run `python3 machine/discovery.py live` for an independent full readback.

`site/public/discovery-surfaces.json` is generated from the entire public asset
tree and the Worker alias map, not a hand-maintained shortlist. It includes
pages, the 404 page, instructions in both formats, discovery metadata, examples,
schemas, ownership files, robots, sitemap, CSS, images and redirects. New files
and changed asset hashes fail the predeploy check until synchronized. The
Wrangler build hook runs this guard for direct CLI deployments too.

All product pages and machine metadata advertise the current version/release.
Fictional API versions and ownership-schema identifiers retain their own meaning;
their exact bytes and served release headers are still verified. Live checks
compare ordinary, revalidated and cache-busted responses against the inventory,
and also check MCP initialize/tools-list and the public Agentverse JSON profile.
Cloudflare-managed `/cdn-cgi/` and `/.webmcp/bridge.js` are explicitly distinguished
from application assets. Expected edge HTML injection is reported, not silently
treated as byte-identical source.

Cloudflare and Agentverse cannot publish atomically across providers. A partial
failure is an incomplete release, never success; the audit directory retains the
evidence for retry. Arbitrary later dashboard edits are not automatically monitored.
Use the publishing workflow for changes. No A2A protocol or agent card is added.

## Full product releases

1. Edit `machine/contract.json` first. Keep identity, capabilities, invocation and
   payment boundaries together. Increment the contract version for a release.
2. Do not stamp an edited contract with the previous runtime's release ID.
   Generate the full release in step 3; it propagates maintained documentation,
   profile metadata, configuration and every served document together.
3. Capture a fresh authenticated baseline with
   `python machine/release.py capture --work data/<unique-release>`.
   Run `python machine/release.py generate --work data/<unique-release>` and
   `python machine/release.py check --work data/<unique-release>`.
   Unselected live agent modules are preserved. Do not regenerate an old baseline
   into a new deployment without checking live drift.
4. Run `python machine/discovery.py check` and
   `python machine/discovery.py stale` with the same extra documentation roots.
   Critical stale-string hits must be zero. Retained private evidence and old ZIPs
   are historical records, never current instructions or files to overwrite.
5. Add every new ship candidate to the exact-path packaging source map. Rebuild with
   `python /workspaces/tool-offer-package-builder/packager.py refresh --full-checks`.
   The archive must contain the manifest, both profile representations, bridge,
   tests and setup instructions, with candidate/version stamps and per-file hashes.
   Run the extracted archive's `python scripts/verify_package.py`; copying files
   into an older ZIP manually is not an acceptable release.
6. Deploy through `python machine/release.py deploy --work data/<unique-release>`.
   This verifies the captured baseline, publishes the same profile and agent, then
   the website. Do not change DNS, identity, visibility, wallet policy or payment
   credentials. A failure is an incomplete release, never success.
7. Run `python machine/discovery.py live` and the release public readback. The
   canonical URL must return the exact generated JSON bytes. Agentverse's public
   JSON `readme`, `short_description`, name and address must match the source.
   Repeat the stale scan and ZIP verification after the final edit.

## Verification limits

Public discovery is credential-free; actual MCP/REST calls require automatic
identity proof and scoped credentials. A ChatGPT or other MCP client's ability to
configure this authentication is client-dependent. An MCP acknowledgement is not
a completed job. No arbitrary agent-commerce protocol or autonomous paid machine
checkout is advertised. Verification never needs to purchase an evaluation.

The initial inventory was completed before edits on November 6, 2026. The owner
confirmed that the existing `tooloffer.kinganlogic.com` hostname is correct; the
extra-letter spelling in the initial request was a typo. DNS remains unchanged.
