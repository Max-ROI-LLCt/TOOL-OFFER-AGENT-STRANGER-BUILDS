# Tool Offer Agent: release and judging readiness

Working review date: November 7, 2026 (UTC). This is a current engineering report, not a signed execution attestation, organizer decision or public repository announcement.

The bounded November 7 live-findings correction is a **local, undeployed candidate** based on commit `03c58e64c890b53bdcc9b003de42f8d3567eb403`. See `docs/CORRECTIONS-2026-11-07.md` for each finding, source correspondence, verification and the separate revised package. The frozen judging ZIP and original release receipts remain unchanged. Registry 1.4.9 publication is complete; it is not a remaining blocker. No new Agentverse or Cloudflare deployment is claimed by these local corrections.

## Change surface and canonical ownership

- `machine/contract.json`: product version, stable identity, protocol, capabilities, authentication, quota and payment boundaries.
- `machine/public-profile.txt`, `machine/guide.txt`, `machine/public-profile.json`: maintained Agentverse presentation, ASI-facing guide and hosted profile settings. Real documentation and truthful seller authorization come first; the fictional demonstration remains a separate restricted option.
- `machine/discovery.py`, `machine/examples.py`, `machine/surfaces.py`, `machine/release.py`: generators for profile/guide mirrors, instructions, discovery, OpenAPI, release identity, runtime constants and asset inventory. Historical records are not regeneration targets.
- `prepare_agentverse_release.py`, `build_hosted.py`, `agentverse_release.toml`: complete current hosted module selection and packaging. Actual source readback, not a displayed version, establishes correspondence.
- `site/public/index.html`, `site/src/worker.mjs`, generated `site/src/discovery-routes.json`: presentation and route behavior. Both MCP path forms preserve POST bodies; browser GET is a documented 405 with `Allow: POST` and human documentation, not a fake protocol success. Origin checks still apply.
- Current outer `wallet-approval` source and its entire generated bundle were inspected. `bridge/checkout/SOURCE-PROVENANCE.json` records exact preserved source hashes; the old inner adapter is not a replacement. Separate `cloudflare/transaction_custody.mjs` and Python custody client remain included.
- `tests/test_presentation_accuracy.py`, site routing tests and existing workflow suites prevent alias regression and fictional-to-commercial promotion through correction, rebuild, readiness and export. Hash calculations are unchanged: readiness source-record SHA-256 hashes canonical retained-record JSON, not source-text bytes.

## Historical verification and deployment

The initial authenticated baseline is Agentverse revision 82, digest `50c2ee4a67614b59118d646cff83c0ef1d4c0914aefcef08e870305f854c0e2f`. Release 1.4.8 completed without interruption. The subsequently requested badge, metadata and HSTS changes were deployed as **1.4.9** on November 7, 2026 at 02:38 UTC:

- Release: `294379abcc1a2df39f22d9aa94423f2902e5353bb74fc29411e657e6d2c0afa1`.
- Agentverse revision **85**, compiled and running, code digest `d2e207b7a158acdc56f870ad1913e439d9742de837e7cedc0267218efe25e3fc`. All 29 hosted source members match the intended candidate byte-for-byte. The authored Python runtime is unchanged from the captured baseline; the generated contract carries the release/metadata changes.
- Cloudflare `kingan-tooloffer-site` version **2c93af6b-54f0-4e83-ad79-8da32094a0c9**. Neither checkout nor FAHCE was redeployed.
- All 108 public readbacks (ordinary, revalidated and cache-busted) match release content, including website, instructions, manifest, OpenAPI, discovery and public profile. Four HTML routes have the already-configured Cloudflare WebMCP script injection: their raw HTTP hashes differ from static files, while removing that exact recorded addition gives the intended bytes. This is an observed edge transformation, not an alleged client cache issue or a claim all HTTP bodies are byte-identical. WebMCP script execution is not certified by these checks.
- Six desktop/mobile website route checks and two rendered Agentverse profile viewport checks passed. The first browser run found an auto-linked REST template; the canonical generator now renders protocol addresses as code, with human documentation links. Final profile navigation passes.
- Existing acceptance client identity reused without reenrollment. A new isolated `/mcp/` status operation completed with zero inference and payments; its pinned signature, request/session/release bindings, same-request/same-job replay and altered-byte rejection were checked. Original 1.4.7 state, keys and proofs were not written or copied into the package.

Final clean-package Python regression passed **531 tests, with three explicitly skipped local-Wrangler custody integration cases**. Staged card journey passed six tests, staged runtime passed 362, chat passed 13, and site passed **51**. The current outer wallet passed **90**; preserved runtime checkout tests passed **85**, and the judges' selection passed **87** including two additional receipt-boundary tests, plus **five** standalone SQLite custody tests. The five outer tests not selected exercise FAHCE engine grammar repair, not checkout runtime; private engine repair tooling remains outside the package. Initial sandbox socket failures were rerun with authorized localhost access. An initial extracted Node check raced its Python dependency installation and failed; rerunning after installation passed. None of these initial failures was called a pass. Generator consistency and archive-byte verification passed.

## Focused 1.4.9 metadata and transport follow-up

The website and README use the exact owner-supplied linked VerifyMCP verified-variant SVG, with alt text “VerifyMCP report for Tool Offer Agent.” Both URLs returned 200 and Chromium loaded the live image on desktop/mobile. CSP permits that exact image path, not a broad new script origin. No score is hard-coded; this third-party report is not blanket security certification.

Every tool input parameter now has a concise description; each tool has one schema-valid short example in canonical `machine/contract.json`, also emitted into OpenAPI. Example session/job/export identifiers are illustrative and must be replaced by actual returned identifiers. `send_message` is explicitly state-changing, potentially destructive to retained fields/drafts and open-world (documentation/model access). Other queued tools also write job, quota or delivery state. Polling can wake queued work. Annotations conservatively avoid read-only or unconditional idempotency claims; bounded same-request deduplication remains implemented and tested. No new tool, authentication redesign or protocol upgrade was introduced.

HSTS was absent on the deployed product host before this follow-up. HTTPS responses for **tooloffer.kinganlogic.com only** now carry `Strict-Transport-Security: max-age=86400`. Live 200, 401, 403, 404 and both MCP 405 responses were checked. HTTP, preview and apex hosts do not acquire this policy in the Worker. There is no `includeSubDomains`, `preload`, apex-domain or FAHCE change.

VerifyMCP's report says Stability is unverified because there is insufficient scan history for a 30-day window, explicitly describing that as a verification gap rather than a product finding. It is not treated as an observed stability defect, and no architectural changes were made to chase the score. A future scanner rescan/index refresh is external; this release does not claim its displayed score has updated.

The owner completed the fictional Agentverse manual journey, including corrections, rebuild, persistence, unchanged replacement, cancellation and restricted authorization. ASI:One delivery is resolved, as confirmed by the owner on November 13, 2026. The November 7 observations below are historical; they are not a current product limitation. Payload tests retain their original scope and do not independently verify physical rendering.

## Existing acceptance: release 1.4.7 only

The owner retained private live acceptance for release `eccf0fa13eb9867a9f1880a008f5946cda8fb73dc99f63098dbbbd11363d13a9`. Original proofs and credentials remain outside both repositories. The following is an allowlisted owner-reported summary, not a new independent replay:

- Public initialization and all seven tools; automatic OAuth registration and private-key JWT issuance; authenticated isolated sessions and asynchronous completion.
- Signatures pinned to the established Tool Offer Agent address; request/session/release binding; altered-byte rejection.
- Fictional parcel intake, one model attempt, source-attributed draft, deterministic `reviewable_with_caveats` and explicit commercial restriction.
- Fully assembled readiness: six parts, 15,569 bytes. Fully assembled JSON export: eight parts, 23,973 bytes. All part indices, offsets, lengths, signatures, individual and overall hashes checked.
- All 7,766 source bytes retained, including 65 synthetic notes; canonical source-record and draft hashes independently recomputed from export.

This evidence is not silently relabeled 1.4.8. The acceptance client alone does not identify an outside agent such as Grok. No private credential, original customer record or raw acceptance export belongs in the judging selection.

## Registry and trust boundaries

The owner supplied the completed official post-publication readback: `com.kinganlogic/tool-offer-agent`, version **1.4.9**, status **active**, **isLatest: true**, published **2026-11-07T03:32:16.914361Z**, endpoint `https://tooloffer.kinganlogic.com/mcp`. `machine/registry-publication.json` is the canonical record of that supplied evidence, its baseline commit/release and registry-server file hash. The generated `machine/registry-server.json` matches that name, version, endpoint and complete file hash; it is not itself a receipt. Later local candidate source changes are not represented as the published runtime.

Dedicated publisher: resource group `rg-tooloffer-publisher`, vault `kv-toa-pub-0dc85b24`, key `tool-offer-mcp-registry-p384`; HTTP proof Worker `tooloffer-registry-proof`, exact route `kinganlogic.com/.well-known/mcp-registry-auth`. Do not change FAHCE DNS ownership proof, engine/receipt/OCI/attestation/signing boundaries, keys or identities. Registry signing authenticates publication, not engine execution or offer certification. Product runtimes do not receive this key.

Publication is complete. Do not republish 1.4.9, repeat enrollment or create/rotate publisher keys. Earlier publication evidence remains historical. Listing publication does not guarantee indexing, adoption, certification or submission acceptance. Updating live Agentverse profile/runtime or Cloudflare surfaces is outside this local correction job.

## Current findings

- **Open dependency advisory:** fresh outer wallet `npm audit` still reports four high affected dependency entries from GHSA-mrhx-c7xc-m3w5 (Zod memory exhaustion), through the existing Base/Coinbase SDK chain. The suggested SDK downgrade is not a verified safe fix. No application exploit established; current checkout behavior was preserved, not redeployed. Remediation needs an independently tested SDK update/pin, not an unreviewed downgrade.
- **Open external harness:** `verify_new_tooloffer.mjs` was not found in accessible workspaces. The previously reported exit-code-1 is neither resolved nor a pass. Owner action: supply the original script and nonsecret failure output for reproducible diagnosis.
- ASI:One delivery is resolved, as confirmed by the owner on November 13, 2026. The November 7 observations below are historical; they are not a current product limitation.
- **History/privacy decision:** known private history and customer-derived fixture disclosures remain in the original private repository. The judges' builder replaces that fixture only in the package with a clearly labeled synthetic fixture. Do not publish the original history or claim curated history is organizer-approved.

## Judges' selection and reproducibility

`judging/selection.json` allowlists exact files and protected reviewed hashes; `judging/inputs/` contains reviewed synthetic/adapted package inputs and explicitly historical sanitized evidence. `judging/package.py` creates only a new ignored local directory and ZIP, verifies every archive member byte-for-byte and records source/output hashes and source commit. There is no automatic repository creation or visibility change. Bounded secret scans are not a guarantee; the owner still reviews the resulting manifest and disclosure scope.

The selection includes current native/runtime modules, extraction/review/readiness/export, machine gateway, discovery/generators, full current checkout/relay/wallet source, separate custody Worker/client, configuration placeholders and tests. It excludes credentials, raw customer acceptance exports, private chat captures, caches and Git history. Pre-existing FAHCE services are attributed external dependencies, not copied or claimed as new hackathon work. Existing sanitized historical evidence keeps its original release and limitations.

## Supporting facts for a video under two minutes

No video is created or published by this coding job. Use **Tool Offer Agent** throughout. Suggested factual sequence:

1. Explain real docs and actual seller terms, then explicitly choose a fictional parcel service for a safe example. Tool Offer Agent executes for real; the parcel business and its service rights are fictional.
2. Identify native ASI and machine-client demonstrations as distinct interfaces. Only claim the native layout/clicks actually observed.
3. Show completed assembled readiness and export content with verification, not a multipart manifest masquerading as full delivery. State which release each retained run used.
4. Connect the owner's specific `/mcp/` 404 and `/mcp` browser error feedback to the same-body slash routing and human documentation improvement. Connect naming/real-journey feedback to the canonical profile and generator corrections.
5. Treat the earlier buyer-approved FAHCE payment as separate historical evidence with its actual determination and receipt limits. No positive evaluation, native Fetch payment integration, outside-agent identity, first-of-kind status or acceptance claim without corresponding retained evidence.

Publication remains an owner decision: approve the concrete sanitized manifest and confirm organizer requirements for curated source versus private history. No existing private repository has been made public, no separate judging repository has been published and no submission acceptance has been asserted.
