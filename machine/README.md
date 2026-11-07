# Tool Offer machine entrance: operator workflow

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

This adapter uses the **existing Agentverse agent**. It adds a restricted, signed
request protocol, not another agent or a copy of the commercial workflow. Native
Fetch Chat Protocol remains available independently. The website has Human and
Machine entrances, public discovery, and credentialed MCP/REST tools.

The 2026-11-03 upgrade is deployed as running/compiled Agentverse revision **63**, with public contract release `b335ff91bcbceadf5cc4dde934c26a4d58be1eaa88887f19dc6890c2dbd7d9b3` and Cloudflare Worker version `8f1a1c4a-fabb-46ca-9038-2e70f32f4a88`. Final guarded deployment and ten-surface readback receipts are in `data/product-upgrade-source-fix-2026-11-03/`. The main upgrade's native buyer-copy, analytical-answer, live multipart and readiness evidence remains in `data/product-upgrade-2026-11-03/`. The canonical contract sets 20 messages/client, 500 global messages and 5,000 operations per UTC day. The owner explicitly authorized call-based controls without a dollar cap. Existing model credentials and the separate buyer-approved payment bridge were preserved. Final live receipt instructions used zero inference and five independently checked literal source blocks; source offsets match the captured public OpenAPI exactly.

Historical readiness release: agent revision **53**, with deployment and live controlled
MCP/REST readiness receipts in `data/readiness-v1-2026-11-02/`. Readiness adds no
inference. See `../evidence/readiness-v1-2026-11-02.md` for independently rechecked
signatures, complete reports, native card delivery and the outstanding ASI UI check.
Prior revision 51 fresh inference, signed results, resumable exports, pre-launch
planning and native interface-knowledge evidence remains in
`data/consolidated-2026-11-02/` and `../evidence/consolidated-repair-2026-11-02.md`.
Checkout infrastructure and provider eligibility remain unchanged.
`LIVE_CROSS_CLIENT_ISOLATION` remains outstanding until a legitimate independent
client is available; it does not block unrelated development. Preserve the live
receipts and label additional controlled-client tests as simulated, not independent
live verification. Authenticated source/profile custody was read back successfully
for revision 53 on November 2 at 09:58 UTC. Later owner-session expiry is not product
failure or a reason to require immediate login for unrelated development. Do not
issue artificial customer credentials to close an acceptance item.
`assess_offer_readiness` is deployed as the seventh operation, not a proposal.
Current allowances are published by `/capabilities/machines` and generated from
`machine/contract.json`; historical receipts do not define the current limits. Native chat
has separate controls. Credentials have already been provisioned: do not repeat
one-time setup when deploying routine updates.

## Readiness v1

Call `assess_offer_readiness` with your existing `session_id` and UUID-v4
`request_id`, using MCP or `/api/machine/assess_offer_readiness`. The immediate
response is an asynchronous job, not a finished report. Poll `get_result` for the
same job and verify its signed identity, session, request and release bindings.
`MachineClient.readiness(label, options)` performs this and assembles any multipart
report. Reuse the client's journal to resume; use a new label/request only for an
intentionally new assessment. Replaying a request returns the original snapshot.

The report schema is published at `/readiness.schema.json`. Every report includes
`human_readable`, source references and hashes, quote-alignment findings, missing
commercial information, unverified permission boundaries, saved proposed decisions,
one next step, and a policy/release-bound snapshot hash. `reviewable_with_caveats`
means preparation for review, never certification, authorization or semantic truth.
No new documents are fetched and no model, payment or FAHCE evaluation is invoked.

Business state is read-only. Derived idempotency journals and immutable export
snapshots still use bounded storage: seven-day machine sessions, 100 requests per
session, at most eight retained exports per session, and an 8 MiB export size guard.
Part retrieval consumes operation/request capacity, not conversational model quota;
the size guard is not a promise of unlimited part retrieval or permanent retention.
Native readiness has a separate 100-request journal per conversation. Full journals
fail explicitly rather than overwriting earlier request bindings.

Native commands are `readiness`, `readiness text`, and `readiness json`. The first
attaches a terminal informational custom card to the normal ChatMessage. There are
no buttons, payment controls, approvals or other privileged actions. All forms keep
complete text/JSON or an integrity-protected export; invalid cards fall back to text.
Signed native delivery and exact text fallback passed. Actual ASI:One drawer
rendering and visual field accuracy remain **unverified**: the available isolated
test browser reaches ASI's login screen and is not connected to the founder's
already-signed-in browser. API credentials are not browser authorization.

Recheck retained evidence entirely offline, without credentials or new jobs:

```sh
python machine/audit_readiness.py --work data/readiness-v1-2026-11-02
```

This independently checks 12 signed machine results and five native response
envelopes with the pinned official Python SDK, JSON Schema, complete report hashes,
readable/source-reference parity, missing-part rejection, exact native text fallback,
and unchanged protected modules. It does not establish ASI UI rendering.

## One release, not independent instruction copies

Author public product instructions in `machine/guide.md`, schemas/limits in
`machine/contract.json`, and behavior in the reviewed Python/Worker modules.
Do not edit `AGENT-PROFILE.md`, `machine_contract.py`, `site/src/generated.json`,
or generated discovery/instruction pages independently. Generation incorporates
the actual hosted baseline, only explicitly selected Python modules, and the
Worker implementation into one release fingerprint. This is a release workflow,
not automatic monitoring of arbitrary Agentverse dashboard edits.

For each subsequent release, choose a **new** audit directory and use it on all
four commands. Authenticate AVCTL first. Run from the repository root, using a
Python environment with the project's tested dependencies:

```sh
python machine/release.py capture --work data/releases/<release-name>
python machine/release.py generate --work data/releases/<release-name> --modules chat machine <changed-module>
python machine/release.py check --work data/releases/<release-name>
python machine/release.py deploy --work data/releases/<release-name>
```

`capture` reads the authenticated deployed source/profile, never GitHub main.
`check` rejects stale generated artifacts and runs bounded offline Python tests,
cross-language signing vectors, and a real Cloudflare runtime with fake outbound
responses. `deploy` repeats verification, rejects live source/profile drift,
uses the established AVCTL stop/push/run workflow, verifies source/profile
readback, then publishes the existing Cloudflare Worker with Wrangler.
It does not commit Git, reset storage, rotate existing keys, run inference, or
evaluate/pay for an offer. Review `receipt.json` and `website-deploy.log`.

After publication, run `node machine/smoke.mjs --work data/releases/<release-name>`.
This verifies public instructions, MCP negotiation/schemas, authentication, and
signed results for fresh-session status, an empty export, and a missing export
part. It never sends a conversational message or a drafting/payment command.
It saves request/job IDs before proceeding so rerunning resumes the same bounded
smoke test rather than silently duplicating work. Retain `live-smoke.json`.

For public-only content/hash readbacks of eight published assets, without any
credential or model execution, run:

```sh
node machine/readback.mjs --work data/releases/<release-name>
```

The receipt distinguishes exact bytes from HTML with one specifically observed
`.webmcp/bridge.js` injection absent from the release files. It retains both hashes
and the added tag; it does not silently call these HTML responses byte-identical.
Other differences fail verification. The injection's provenance is not established.

For the consolidated November 2 receipt set, `python machine/audit_receipts.py
--work data/consolidated-2026-11-02` independently re-verifies all 29 retained
result signatures with the pinned official Python SDK, the historical 7,045-byte
export, its 29 source quotes/offsets, and unchanged protected module hashes.
It is entirely offline and does not contact the model or payment services.

Fresh inference acceptance requires explicit operator authorization and the
existing private `data/machine-credentials/owner-client.json` configuration:

```sh
node machine/acceptance.mjs --run-fresh --work data/releases/<release-name>
```

This is NOT the zero-inference smoke test. The conversational test and completing
the documentation intake can each invoke the existing ASI model (at most two
attempts per message); inspect every job's `model_attempts`, not just the first
test. The November 2 run used two attempts overall. It starts no checkout,
FAHCE evaluation, payment or publication. It retains request/job IDs atomically;
rerun with the SAME work directory to resume. Never delete its journal to retry
uncertain work. Only one owner-issued client was available for that live run;
two-client isolation and forced quota/uncertain-state cases remain offline tests.

`client.mjs` exports `MachineClient`, `verifyResult`, and `assemble` for callers.
Pass the owner-issued Authorization value privately; never place it in URLs.
Supply the canonical agent address and expected release independently of the
response. `job` preserves its request ID before dispatch, polls with a bounded
deadline, and verifies the exact signed body and session/request/release bindings.
`download` assembles indexed base64 parts, checks each part plus the whole export,
and returns normal UTF-8 text/JSON. An interrupted journal resumes already-known
jobs. A missing/corrupt part or an uncertain job is never reported as success.
Read-only retrieval methods avoid using conversational quota for export commands.

The public schemas currently use `format: uuid`; runtime requires UUID v4.
Pre-launch commands are documented in the synchronized instructions; the shorter
discovery `safe_commands` list is not a full grammar. A future contract revision
can add their examples and a v4 pattern without changing existing method names.

If Agentverse succeeds but the site fails, retain the audit directory and run
`publish-site --work <same-directory>` after resolving the website failure. It
retests and verifies the agent still matches; it does not push the agent again.
If Wrangler already reports a version ID but its public readback failed, use
`verify-site --work <same-directory>` to recheck without redeploying either side.
During a mismatched rollout, the signed capability/release check prevents new
machine work from running with stale instructions. Poll an existing job rather
than resending it under a new request ID. No cross-provider deployment is atomic.

AVCTL uses this checkout's `.avctl/config.toml`, with `readme_path` set to
`AGENT-PROFILE.md`. The release guard preserves the existing description and
starter prompts; changing those is a separately reviewed metadata change.

## Credentials and identity boundaries

`node machine/provision.mjs` is a **one-time** provisioning command. It refuses
existing output paths. It generates a new Tool Offer-only message authorization
key plus an owner client token, saving private files under the ignored
`data/machine-credentials/` directory with mode 0600. The public identity is in
`machine/gateway.json`. Do not regenerate the key for routine releases.

Install only those two new Worker secrets using the existing Worker config:

```sh
cd site
npx wrangler secret bulk ../data/machine-credentials/worker-secrets.json --config wrangler.production.jsonc
```

This is an additive secret update, not permission to replace other product keys.
Never print or commit the secret file or `owner-client.json`. The latter is the
private MCP client configuration; use a client supporting custom Authorization
headers. No public self-service token issuance is provided. To onboard another
client, issue a distinct random `toa_` token, store only its SHA-256 digest mapped
to a distinct principal in `TOOL_OFFER_MACHINE_CLIENTS`, and deliver the token
privately. Preserve the full existing map when updating it. Revocation removes
only that digest. No client may choose another client's principal.

The gateway identity signs application messages only. Each transport request
uses an ephemeral identity to isolate synchronous replies; the existing Tool
Offer Agent identity signs responses. Neither is a FAHCE/OCI attestation key or
buyer wallet. The adapter receives **no commercial execution dependencies**.
Wallet instructions remain publicly readable; payment approval stays with the
human using the existing native-chat/private-checkout workflow.

## Discovery and limitations

- Human page: `/`; machine page: `/machine/`.
- Public instructions: `/instructions.md`, `/llms.txt`.
- Public schemas: `/capabilities/machines`, `/openapi.json`, `/readiness.schema.json`.
- Public discovery links: `/.well-known/api-catalog`, `/.well-known/mcp.json`.
- MCP: `/mcp`, protocol 2025-11-25; initialize/tools-list public, tool calls authenticated.
- REST: `/api/machine/<tool_name>`; same authentication, limits, jobs and schemas.

These well-known files do **not** claim official MCP Registry publication or an
Agentverse verification badge. A reverse-DNS Registry name is a separate discovery
registration, not what makes MCP calls work and not what fixes chat intent routing.
Native Agentverse agents use the existing address and Fetch Chat Protocol; they
do not need the restricted gateway protocol or its private signing key.

Calls return durable jobs. Only `complete` is success. Unknown dispatch outcomes
are recovered by reading the agent's cached result, never by repeating inference.
Expired gateway sessions do not promise deletion of existing agent audit state.
Message quotas bound attempts, not dollars; native chat has its existing separate
provider controls. New agents are not promised unauthenticated, unlimited access.


## Approved client issuance, rotation and revocation

The one-time `machine/provision.mjs` setup created the existing gateway and initial owner credential. Do not rerun it for customers. New per-client issuance uses `machine/clients.mjs`, which is offline and changes no deployed credential:

```sh
node machine/clients.mjs issue /private/current-clients.json customer-unique 2026-12-01T00:00:00Z /private/one-time-delivery.json --owner-approved
node machine/clients.mjs revoke /private/current-clients.json customer-unique <old-token-sha256>
```

Use the complete authoritative current hash-to-principal registry from the owner's secure custody; do not use a stale copied registry. Review the prepared registry and install only `TOOL_OFFER_MACHINE_CLIENTS` using the existing Wrangler secret workflow. Never upload the gateway signing key during ordinary client issuance. Do not print the token or put either private file in assets. Hand the delivery file to the approved client through a confidential channel once, then securely retire the plaintext copy. This is an operator procedure, not a claim that plaintext cannot be copied. Email sending is not connected and the tool does not send messages. Rotation issues another token with the same principal and then revokes the old hash, preserving the client's sessions and quota accounting. New credentials must expire within 90 days; legacy string records are preserved until explicitly migrated. The existing `owner-machine` principal is reserved for the operator, not customer access.

The staged release binds the landing page, short machine entrance, readiness schema, catalog, example and all generated instructions to the same identity. The guarded deployment runs `machine/readback.mjs` across all nine required surfaces and the example, checking Content-Type, release headers and exact generated bytes (with only the previously documented bridge-tag exception). The current call-only policy has no dollar-budget gate. To change availability, edit the canonical contract, regenerate and run the guarded check/deploy workflow. Call counts do not guarantee maximum dollar charges.
