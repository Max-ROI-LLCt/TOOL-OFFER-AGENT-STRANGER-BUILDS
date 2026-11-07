# Tool Offer Agent — from API docs to a buyer offer

<!-- tool-offer-release:start -->
Version: 1.4.9
Release: 66979784d826683d48d83d6639e924078a3a3476c3ab488a93a9a57519767f19
<!-- tool-offer-release:end -->
![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

By Kingan Logic.

Give Tool Offer Agent a public API or MCP documentation URL and your proposed customer, price and access terms. Receive a saved, source-attributed offer explaining the buyer's job, required inputs, expected result, limitations and terms. Review it, correct one value, assess what is still missing, and export it from the same conversation.

For machines: [canonical machine-readable profile](https://tooloffer.kinganlogic.com/manifest.json).

**Human chat:** open this agent in ASI:One and keep `@tool-offer-builder` selected. **Machine clients:** use the separate [MCP / REST quick-start](https://tooloffer.kinganlogic.com/machine/#access). Machine sessions do not inherit your ASI:One history.

## Try it — no checkout or wallet

### Start with my tool — real documentation and seller terms

Send `Help me turn my API documentation into a commercial offer draft.` Select **Start with my tool**, or paste your public documentation URL. Supply actual service information and truthful customer, pricing, payment, access and invocation terms. Only claim seller rights and commercial authorization you actually hold. Do not send credentials. Review the attributed draft, correct intake with `revise field: value`, rebuild with `draft` or `draft limited`, then use `readiness` and `export json`. Drafting, review, readiness and export do not themselves authorize commercial use or publish an offer.

### Try a fictional example — optional demonstration

Start a **new conversation** for this fictional example; do not replace a real saved offer. ASI:One access and usage limits still apply. The example API is not a running service, and its proposed price is not a charge.

1. Send `Help me turn my API documentation into a commercial offer draft.` Tool Offer Agent offers **Start with my tool** and **Try a fictional example**, with a plain-chat URL fallback. For a bundled, restricted parcel draft without fetching documentation or calling a model, choose **Try a fictional example** and continue at step 5. Alternatively paste the demonstration block below.
2. Send this entire block together, including its first line so the demonstration restriction reaches the agent with the intake:

```text
Demonstration only. No commercial use.
tool_url: https://parcel-example.invalid/
docs: https://tooloffer.kinganlogic.com/examples/parcel-openapi.json
customer: Shipping form developers
payment: Fictional invoice; no connection exists
access: Fictional seller-issued key; use placeholders
invocation: POST /normalize with length, width, height, unit
```

3. Send `revise pricing: USD 9 per month`. You receive a short saved/unchanged acknowledgment, not a full export.
4. Send `draft limited`. This deliberately uses deterministic extraction without an extraction-model call; coverage remains limited, not certified. For your own documentation, `draft` uses the configured extraction model and its quota; failures preserve the previous draft.
5. Send `buyer explanation`. You receive a concise offer: dimension normalization for shipping forms, input dimensions and units, results in centimetres, the fictional seller terms, and no carrier quotes or shipment booking. [See the attributed example](https://tooloffer.kinganlogic.com/examples/).
6. Send `review offer`, choose **Correct a value**, and submit the existing customer wording. Expect **customer unchanged**, with the current revisions. Send `readiness` to see gaps. Send `review offer` again for a fresh card, then choose **Finish review**: this records review only, not approval or purchase.

## Send in chat | What you receive

| Send in chat | What you receive |
| --- | --- |
| `tool_url: <public URL>` and `docs: <public documentation URL>` | Saved intake and an actual documentation-read outcome; supply customer, pricing, payment, access and invocation next. Use `undecided` for unknown terms. No secrets. |
| `draft` / `draft limited` | With the seven intake fields, a saved offer from model / limited deterministic extraction. Incomplete evidence is labeled; this does not run or certify the offered API. |
| `review offer` | With a saved draft, a review card separating documented claims from seller terms. **Finish review** grants no authority. |
| `review intake` / `revise customer: <complete replacement>` | A one-field correction form / concise correction outcome. An unchanged value keeps its revision. A changed value updates intake only; use `draft` or `draft limited` to rebuild the saved offer. |
| `cancel review` | Dismisses the active card without changing the draft. Old-card actions reject; `review offer` opens a fresh review. |
| `readiness` / `readiness text` / `readiness json` | Scan-friendly status, caveats and next action / detailed text / full structured assessment. Source-backed derived information is distinguished from exact quotations. No model call, checkout, certification or permission. |
| `buyer explanation` | With a saved draft, the concise human view; pending corrections are distinguished from the saved offer. |
| `export buyer readable` / `export buyer` / `export json` | Detailed human view / structured buyer offer / complete audit with original sources and seller statements. Large exports intentionally use resumable, hashed parts. A manifest is not the complete document; [machine clients assemble and verify parts](https://tooloffer.kinganlogic.com/machine/). |

### JSON intake in chat

In a fresh conversation, send this **bare JSON object as message text**, without the Markdown fence:

```json
{"schema":"TOOL_OFFER_INTAKE_V1","customer":"Small online retailers preparing parcel shipment data.","pricing":"USD 9 per month"}
```

This saves two seller-stated intake fields, not a complete offer or permission. Partial objects are supported; the seven required fields are tool_url, docs, customer, pricing, payment, access and invocation. The schema marker is optional; job and seller_name are optional fields. Unknown/duplicate keys, wrong types and empty values reject atomically. docs accepts a public URL string or a list of one to three public URL strings. [Exact limits and complete example](https://tooloffer.kinganlogic.com/instructions.md).

For machine `send_message`, serialize this object into the **message string**; do not pass an object as the typed message parameter or wrap it in an unsupported intake envelope. Supplying the last required field through ordinary intake can start drafting. Use `revise field: value` for correction without rebuilding, then `draft` or `draft limited` explicitly.

## Evidence boundaries

- Documentation supports attributed claims, not proof that a service ran. Illustrative examples are not execution results, and other documented operations are not automatically included in the selected offer.
- Price, payment, access and customer wording are seller statements. Public documentation does not grant ownership, resale rights or authority to publish.
- Readiness and Finish review concern preparation only. They establish neither buyer authorization nor payment or settlement. Missing or partially extracted information remains unresolved, not proof of absence.

## Optional paid FAHCE evaluation — separate from drafting

`wallet` or `purchase guide` explains the separate human-controlled flow without creating checkout. `preflight` screens input without payment. Only an explicit `check` can prepare an eligible checkout; it is **not** part of this quick-start. Some new drafts still require input-format repair. The buyer must review the exact request and separately authorize any payment in the private checkout. `purchase status` reads an existing outcome; never pay again to resolve an uncertain response. The restricted machine adapter cannot buy or evaluate. [Full prerequisites and recovery guide](https://tooloffer.kinganlogic.com/instructions.md).

## Technical reference and machine access

[Human homepage](https://tooloffer.kinganlogic.com/) · [Complete technical and operator reference](https://tooloffer.kinganlogic.com/instructions.md) · [Machine access and examples](https://tooloffer.kinganlogic.com/machine/) · [Canonical machine-readable profile](https://tooloffer.kinganlogic.com/manifest.json) · [OpenAPI](https://tooloffer.kinganlogic.com/openapi.json) · [Readiness schema](https://tooloffer.kinganlogic.com/readiness.schema.json)

Native interface: Fetch Agent Chat Protocol (ACP). Agent address: `agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a`. Machine callers enroll with identity proof, retain session/job/request IDs, verify signed results and use asynchronous `get_result` if `Prefer: wait=1` through `wait=5` does not complete. Waiting observes an existing job; it never resubmits work. Limits, OAuth/Fetch setup, exact schemas, deployment guidance and inference accounting are in the technical reference, not required for human drafting.

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

## Hackathon categories

These are the category tags specified by the [Stranger Builds hackpack](https://innovationlab.fetch.ai/events/hackathons/stranger-builds-1/hackpack), not awards, identity verification, endorsement or a claim of prize eligibility.

## Technical reference

The following preserves the detailed integration, recovery and operator guidance. Start with my tool for real documentation; Try a fictional example is optional.

## Structured intake and complete review
The JSON intake below is serialized text sent as a bare chat message (no Markdown fence). For machine send_message, message remains a string containing that JSON, not a typed intake-object parameter. Do not add an intake envelope. Ordinary intake can start drafting when the final required field is supplied; single-field revise commands do not rebuild.
Plain field: value lines remain supported. Native chat and the machine send_message.message string also accept a JSON-serialized intake object, for example {"schema":"TOOL_OFFER_INTAKE_V1","tool_url":"https://example.com/api","docs":["https://example.com/openapi.json"],"customer":"API developers","pricing":"Undecided","payment":"Probably Stripe","access":"Public signup; never send keys","invocation":"POST /convert with placeholders"}. Required for a complete intake: tool_url, docs, customer, pricing, payment, access, invocation. Partial updates are accepted; job and seller_name are optional. All values must be nonempty strings (up to 6000 characters); docs also accepts a list of one to three URL strings (up to 2000 characters each). The whole machine message remains bounded by its 4000-character limit. Unknown/duplicate keys, wrong types and unsafe URLs reject the whole update. Arbitrary documents, quoted examples and card-action JSON are not intake objects. Credentials are prohibited. Tentative terms remain tentative seller statements, not implemented billing.

Review offer presents a labeled summary and an optional revision-bound card, not an incomplete document disguised as a full draft. Review intake displays all current retained seller values, with missing values marked, plus Correct a value and Cancel review actions. Correct a value opens a separate one-field replacement form; the form supports the plain-chat cancel review fallback, not a separate cancel button. Revise field: value also works in plain chat. Finish review records review of that exact saved draft, not a rebuilt successor, and does not authorize approval, checkout, payment or publication. Complete buyer, readable and audit exports remain available. Multipart manifests are not complete documents: retrieve every part, decode base64, and verify all part hashes plus the total length and SHA-256. Existing manifests retain their boundaries and hashes.

Send readiness, or ask “Assess this offer's readiness,” for the same substantive deterministic status, evidence distinctions, pending-correction warning and next action without a model call. readiness text and readiness json retain the detailed facts, schema paths, hashes and audit findings, with intentional multipart delivery when large. A source-backed derived schema extraction is not an exact quotation; neither establishes execution or semantic truth. A restriction lifecycle of current_product identifies which retained product the declaration applies to, not commercial readiness or a real deployed service. Explicit demonstration declarations remain non-commercial through correction and rebuild; no commercial use is a restriction, not seller permission. URLs, including .invalid examples, do not themselves establish demonstration status or authority. Draft vN counts generated drafts; state revision advances for a changed intake value and again when a new draft is built. Earlier review covers only its saved draft, not a successor.

Correction forms and single-field revise commands acknowledge saved, unchanged or rejected values inline, with intake and saved-draft revisions distinguished. Changed corrections update intake only; request draft to rebuild the derived offer. An unchanged correction performs no fetch or model call and does not advance the revision. Rejected bound forms offer a fresh form; stale review actions point to review offer. Native submit selections may carry approved:true as a UI submission marker only: it never grants commercial authority. Product-origin changes are not single-field corrections; use tool_url: <new URL> for the existing product-switch flow, which archives prior terms instead of silently reusing them. Buyer explanations distinguish pending corrections, selected operations, platform context, illustrative examples and documentation references. Exact seller task wording, complete schemas and original source excerpts remain in the audit.

Machine HTTP and MCP calls optionally accept the Prefer: wait=1 through wait=5 header. Waiting only observes the already-enqueued job, never redispatches inference, and retains asynchronous get_result fallback and stable IDs. Every completed result must still pass signature and request/session/release binding checks. Readiness deliveries include a compact summary matching the same report and snapshot hash, including canonical status, scope, authorization and finding count; none is certification or permission to transact. JSON model input uses bounded source-mapped values; model coverage remains separate from deterministic extraction and may be PARTIAL.

## Buying wallet and paid evaluation — human chat only

Send **wallet**, **send wallet**, **Set up my buying wallet**, or **purchase guide** for step-by-step guidance. Native ASI:One/Fetch chat agents can request these same text-only instructions on a human's behalf. Buyers do not need a repository, Codespace, or developer login for the normal checkout flow. The agent does not create or fund wallets. Do not paste wallet addresses, private keys, or seed phrases into chat.

FAHCE is Kingan Logic's separate offer-and-evidence evaluation flow, not Agentverse website verification, a Fetch identity badge, or seller certification. Do not replace this documented x402 checkout with instructions to fund an Agentverse wallet with FET. A requesting agent can explain the steps; the human retains wallet control and separately approves any payment. MCP/REST clients can read this public guide but cannot initiate checkout or payment through the restricted machine adapter.

You can also ask, **“Can I connect my wallet before I have an offer?”** Wallet guidance is available before an offer. Actual wallet connection happens only inside an eligible private checkout after offer preparation. Guidance does not create a checkout, request a signature, or authorize payment. Wallet setup questions do not depend on the language-model provider being available.

1. Supply your offer information and public documentation. Send **draft**, review the result, and revise incorrect or missing fields.
2. Send **offer approve** to approve this exact seller draft. This grants no buyer wallet authority.
3. Send **check** to request the free input preflight and a private checkout. If the request is blocked, unavailable, or requires reconciliation, stop: no payment readiness is claimed. Some generated offers still need operator-assisted input-format repair; this beta does not promise every new draft can check out without help.
4. At the exact private checkout returned by this conversation, review the request hash, offer, sources, price, network, and linked policies. Select a compatible wallet and click **Connect wallet — no payment**. Connecting shares a public account with the page; it neither signs a payment nor accepts policies.
5. Separately accept the policies and click **Pay now — 0.15 USDC** once, then personally approve the one-time authorization in your wallet. This purchases one FAHCE Diagnose request on Base, not the API/MCP service described by your offer. A completed negative determination can still be billable.
6. Return to the same conversation and send **purchase status** to read the existing checkout outcome. This command never starts a new purchase. **check** also retrieves an existing checkout. If delivery is uncertain, do not pay again: use the same purchase status and seek reconciliation.
7. Send **export json** for the attributed record and actual returned evaluation. Large exports return a manifest, not a complete payload. Retrieve one part per command with **export part <export_id> <index>**. Parts carry base64 data and hashes for exact automated reconstruction; missing or corrupt parts must not be treated as a complete record.

### Cross-region checkout bridge

Tool Offer's bridge separates conversation hosting from payment delivery. A dedicated, authenticated US relay resolved the observed rejection of UK-origin server requests and forwards the unchanged buyer-approved x402 request to FAHCE. Live egress was rechecked as US/IAD on November 2, 2026. The recorded November 1 purchase delivered a FAHCE result and a separately verified 0.15 USDC transfer on Base. The wallet remains buyer-controlled; this is not a separate ASI currency or native Fetch settlement rail.

Provider policy, separately: [Cloudflare Monetization Gateway eligibility](https://developers.cloudflare.com/monetization-gateway/eligibility/) currently requires US-based buyers and sellers. Relay location is not buyer residence, and successful delivery is not an eligibility exemption. This is a provider condition on the paid path, not a US-only limitation on Tool Offer's free offer preparation or agent hosting. Placement hints are best-effort; no visitor location headers, payment terms or authorizations are rewritten.

Wallet-approved x402 checkout is configured for this external evaluation service. It is separate from Fetch's native test-only payment-message demonstration. The agent cannot sign, approve, spend automatically, choose the buyer's wallet, or use the developer's wallet for another customer. It does not support arbitrary merchant purchases or ongoing spending budgets. Configuration is not a guarantee of service availability, input readiness, settlement, or a positive evaluation.

Wallet addresses are masked by default for recordings; use the checkbox to inspect the public account locally. Masking does not redact an external wallet popup, private checkout capability, chat history, or the wallets discoverable from a public transaction hash. Keep checkout links private.

## Guided recovery and review

Tool Offer Agent prepares an offer from public documentation and seller terms; it does not independently certify tools, sell the seller’s product or publish listings. Before: “Here is my MCP URL.” After: “For travel planners, find destination experiences using documented inputs and outputs, with price and access explained.” This is an example, not a claim about any supplied tool.

A successful page fetch is not proof of relevant documentation. Missing source-grounded capabilities, inputs or outputs produce an INCOMPLETE DRAFT — evidence insufficient; not buyer-ready. General travel articles do not establish MCP request/response schemas. Original customer wording, source provenance, failed read attempts and replaced source documents are retained. Publicly referenced contract suggestions require explicit selection; a server card or REST contract does not automatically establish an MCP schema or seller ownership.

You can answer an intake question and ask to retry the previous documentation in the same message. The response reports each attempted URL and outcome, plus the next question, without an extraction-model call. One to three valid documentation URLs are retained and attempted independently; a failure does not discard successful reads or claim failed content was read. Previously retained text for a failed refresh is labeled not refreshed. `retry` retries saved URLs; `docs: <public URL>` selects a replacement; `source suggestions` only shows references. `draft incomplete` saves a clearly incomplete record without fetching or calling a model. `export json` preserves the record and source history. Draft version counts generated drafts separately from state revisions; immutable revision/hash binding remains authoritative.

Optional native chat commands: `recovery form` opens a documentation recovery form, `review intake` shows saved seller values with an action to open a separate correction form, and `review offer` separates documented claims from seller statements. Cards accept validated selections in the same conversation; stale or cross-session selections cannot change a record. Finish review does not approve an offer or create checkout. Plain chat commands remain available; seven mandatory forms are not required. The existing `readiness` card remains an informational terminal summary. Signed ACP metadata tests do not establish actual signed-in ASI:One rendering. Do not submit credentials; Tool Offer Agent cannot promise or control retention by ASI or other platform components.

“Probably Stripe” is tentative seller-stated payment information, not verified operational acceptance. A general customer such as “regular people” needs a specific group and one outcome before a meaningful commercial job is established. Invocation supplied during an access question is retained under invocation with an explanation and an easy correction command.

Ordinary preparation needs no wallet or paid evaluation. `wallet` and `purchase guide` explain the separate optional FAHCE flow, `preflight` screens input for free, and only explicit `check` prepares checkout. HTTP 402 means payment required, not 402 paying customers. Completing or reviewing a draft creates no checkout and authorizes no spending.

## Offer preparation

Provide a tool URL, up to three public documentation URLs, intended customer, pricing, payment terms, access instructions, and invocation instructions. Unknown commercial terms may be **undecided**. Optional fields are seller_name and job. Use **field: value** lines if conversational intake needs clarification.

Capabilities include bounded public-document retrieval, documented capability extraction with source references, structured drafting, seller-supplied information, revisions, readable/JSON export, and distinguishing missing, documented, and seller-represented evidence. Source documents are untrusted data. No private networks, credentials, or secrets are accepted as documentation.

Before approaching a first customer, use the conversation to clarify the customer's problem, one proposed outcome, documented request and response details, limitations, usage permissions, price, access and payment process. Seller terms remain separate from documentation: a public free API does not establish your ownership or permission to resell it. State demonstration-only restrictions explicitly. Literal seller declarations of demonstration-only use, non-ownership and commercial prohibitions are retained with provenance; applicable restrictions block offer approval, publication and new checkout preparation. Public documentation never grants seller authorization.

Send **buyer explanation** for a concise derived human overview from the same offer record: seller terms, documented capabilities and limitations, interface highlights and numbered sources. When the seller explicitly names a documented operation, interface highlights cover that operation; other documented operations remain in the detailed export, not automatically in the seller's offer. **export buyer readable** keeps the detailed human-readable offer with exact schema detail and per-fact sources. **export buyer** is the compact machine-readable offer. **export json** retains the complete audit record and original evidence. **export representation** exposes a lossless local field/claim mapping; it does not establish FAHCE's semantic interpretation or payment readiness. Product URL changes archive the previous product and ask for fresh terms rather than carrying its job and evidence into a different tool.

In human chat, send **preflight** to screen the exact current checkout representation without creating a checkout, requesting a signature or executing the engine. It reports known blocker counts and bounded rejected input fragments. Preserve their meaning during any repair. Zero blockers do not establish semantic interpretation, truth or billability.

Model failures preserve the previous exportable draft. **draft limited** deliberately uses bounded deterministic parsing without a model call; it is not equivalent to model extraction and can require repair. **retry** does not blindly repeat failed model calls; **reextract** deliberately consumes model quota. Listing preparation and export do not submit an offer or prove directory eligibility.

General conversation and model extraction use the operator's explicitly configured personal ASI:One API integration. Its credentials remain server-side and its usage is separately billed to the operator. Machine message quotas do not represent a US-dollar spending cap. Changing a wallet or repeating the same prompt cannot repair a provider outage or restore exhausted inference allowance.

## Evidence and authorization boundaries

A source citation identifies where a claim came from, not whether the source is authentic. Seller claims remain seller claims; missing facts are not invented. An export is not publication. The agent does not execute the offered external API, certify sellers, or collect the offered API's commercial subscription.

A prepared checkout is not payment. A wallet signature is not settlement. A FAHCE result, its receipt proof, and payment evidence are distinct. Read the actual determination: REPAIR_REQUIRED or a completed negative result is not a verified offer. Evaluations cover only their exact submitted request. Revisions invalidate association with a previous evaluation; never present an old result as covering an edited offer.

State is isolated by sender and conversation. Never reset or switch conversations to recover an uncertain or completed payment. Ordinary drafting and wallet guidance grant no spending authorization.

## About

## Proposed products and complete outputs

An unfinished concept needs no public URL for planning. Send `mode prelaunch`, then explicitly save `plan requirement: <text>`, `plan decision: <text>`, `plan exercise: <fictional material>`, or `plan test R1: <criterion>`. Inspect `plan status` or `export plan`. Each isolated conversation retains at most 24 items of 1,000 characters with exact wording and test-to-requirement lineage; ordinary brainstorming does not save requirements. Decisions remain unresolved, tests unexecuted, exercises fictional, and requirements proposed. `mode evidence` restores normal evidence-backed intake without promoting planning into implementation, seller terms or authorization. Existing commercial records and checkout are preserved.

Use `buyer explanation` for the concise overview, `export buyer readable` for the detailed buyer document, `export buyer` for machine-readable buyer data, and `export json` for the full audit record. Even an overview can require multipart delivery when material terms are genuinely large. A manifest alone is not delivery. Clients must retrieve all indexed parts, verify their hashes and assemble UTF-8 after byte concatenation. Interrupted downloads resume with the same request IDs and manifest. Existing manifests keep their original content even after a display improvement. An incomplete model response is explicitly marked, never treated as a complete document; `export incomplete` retrieves the retained partial separately. No automatic model retry is performed for truncation.

Bare `transaction status` and `transaction summary` inspect the sole linked seller-side transaction or ask which ID; with none they say so. Buyer FAHCE results use the distinct `purchase status`. Defined payment protocols are not operational seller billing: the production seller-side operational list remains empty. Seller-managed Stripe descriptions are terms, not an integration or authority to charge.

## Deterministic offer readiness

The readiness source-record SHA-256 hashes canonical JSON of the retained document record (sorted keys, compact separators, UTF-8, non-ASCII preserved), not just the source text. SHA-256 of source-text bytes is a different digest. Recompute the record digest from the exported document record; do not change either calculation to force equality. Draft and complete-report hashes retain their distinct existing meanings.

Use the authenticated `assess_offer_readiness` tool with the existing `session_id` and a new UUID-v4 `request_id`. Poll `get_result` using the returned `job_id`; reuse the same request ID after interruptions. This operation reads only evidence and saved information already in that isolated machine session. It makes zero model calls, fetches no documentation and does not execute FAHCE, approve an offer, publish it, start checkout or spend money. It consumes ordinary request/session limits, not the conversational message quota. Identity-proven self-service enrollment supplies the required credential; anonymous discovery alone never authorizes calls.

The completed signed result includes a `readiness` delivery record. For `delivery: inline`, `readiness.report` contains typed `TOOL_OFFER_READINESS_V1` JSON and `text` contains its complete human-readable counterpart. `text_json` contains that same report as JSON. For `multipart`, retrieve all indexed parts from the included export manifest, verify part and overall hashes, then parse the assembled UTF-8 JSON. The JSON itself retains the complete `human_readable` document. A manifest or partial download is not a completed report delivery. The machine report schema is published at https://tooloffer.kinganlogic.com/readiness.schema.json . The client helper's `readiness()` method verifies the signed binding and assembles all required parts.

Reports bind the exact saved snapshot, draft hash, agent release and readiness policy version. They distinguish document quotations with source references, unaligned or derived claims, seller declarations, missing or undecided commercial fields, saved restrictions, proposed requirements and fictional exercises. `reviewable_with_caveats` means preparation for review only, never verified truth, seller ownership, commercial permission, payment eligibility or FAHCE clearance. An absent restriction is not permission. No live runtime or independent rights verification is performed. A changed session needs a new assessment request ID; replaying an old ID returns the original snapshot result.

In native Fetch/ASI:One chat send `readiness`, `readiness text`, or `readiness json`. The default command attaches an optional terminal informational card when a valid payload can be prepared. It has no approval, payment, publication or other action controls. Text-only and unsupported clients retain the complete text or integrity-protected resumable export. The card is a compact summary, not a replacement for the complete report; long entries and omitted counts point to that report. `readiness text` explicitly suppresses the card. Native conversation state and authenticated machine sessions remain separate. Card transport compatibility does not establish actual ASI:One UI rendering; rendering is a separate client acceptance check.

## Machine compatibility and evidence

Native chat can explain the release-generated MCP/REST product contract, but cannot claim live runtime introspection. Native Fetch/ASI:One collaboration and the authenticated website adapter are separate interfaces and have separate state.

MCP remains **2025-11-25** for existing initialize/tools clients. The official **2026-07-28** specification was reviewed on **2026-11-02**: its request metadata, server/discover lifecycle, result types and cache fields are different. This endpoint does not claim that newer protocol. A compatibility client must negotiate 2025-11-25 or use REST. Application session IDs and application request_id idempotency remain necessary even when transport conventions change.

New completed machine results include `proof.agent_address`, `proof.body` and `proof.signature`: verify the exact signed body using the Tool Offer Agent identity, then compare request_id, session_id, release_id, status and text. Older cached results may lack this client-visible proof. The gateway already verifies signatures before accepting replies; exposing proof additionally allows the caller to check it. Signatures do not prove factual truth, seller identity, payment or certification.

HTTP 429 bodies identify minute/daily/lifetime scope where applicable; minute/daily limits include reset_at and Retry-After. Keep the same application request_id after an uncertain network response. Error/uncertain/pending/processing are not completion. HTTP 503 does not establish that no work occurred.

Tool Offer Agent is published in the official MCP Registry as `com.kinganlogic/tool-offer-agent`. Version 1.4.9 was published at 2026-11-07T03:32:16.914361Z and was active/latest at the verified post-publication readback, with endpoint https://tooloffer.kinganlogic.com/mcp. Publication is complete; do not republish or repeat enrollment. Canonical publication evidence is machine/registry-publication.json, tied to the published baseline source. Later local source corrections are not thereby deployed. Publication does not guarantee search indexing, adoption, runtime certification or hackathon acceptance. This service's autonomous caller enrollment is separate from registry publication. Preparing a seller's offer does not publish that seller's service.

The dedicated publisher key authenticates registry publication only: it neither attests to engine execution nor certifies an offer. Product runtimes do not need publisher signing access. The existing FAHCE ownership proof, engine and receipt signing boundaries remain separate.

Sources reviewed 2026-11-02: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx and https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/remote-servers.mdx .

## About the developer

Tool Offer Agent and its buyer-approved checkout integration are developed by Kingan Logic. FAHCE is a separately operated Kingan Logic integrity service. Pattern intelligence for real-world decisions.


## Machine access and recovery

Public discovery, OpenAPI, instructions, MCP initialize and tools/list require no credential. Tool calls require an identity-bound per-client Bearer token. Enroll programmatically at https://tooloffer.kinganlogic.com/machine/#access using OAuth public-key registration plus private_key_jwt proof, or an existing Fetch identity signature. No mailto, human enrollment approval or chat-based credential minting. Do not include tokens, private documents, API keys or wallet details in application metadata.

After proof verification, policy issues an expiring credential to that identity automatically. OAuth returns a one-hour scoped Bearer token over TLS; Fetch returns a 30-day credential encrypted to the applicant's RSA key. The Worker retains token hashes, not plaintext credentials. At most four issued tokens per identity remain active; older tokens expire from the registry. Use fresh OAuth assertions or re-enroll with the same Fetch identity for renewal. Stable principals preserve sessions and quotas. Operators may revoke abusive identities; they do not approve enrollment. Legacy string records remain valid until deliberately rotated or revoked; no retroactive expiry is claimed. Previously accepted jobs are not cancelled by revocation.

REST examples (environment variables are private; never put them in assets):

```sh
curl -X POST "$ORIGIN/api/machine/start_session" -H "Authorization: Bearer $CLIENT_TOKEN" -H 'Content-Type: application/json' --data '{"request_id":"bb3ee030-c486-44fd-b3ce-468db93f1786"}'
curl -X POST "$ORIGIN/api/machine/get_result" -H "Authorization: Bearer $CLIENT_TOKEN" -H 'Content-Type: application/json' --data '{"job_id":"<job_id from accepted response>"}'
```

For 401, obtain or renew the identity-bound credential and use `Authorization: Bearer <token>`; discovery remains public. A revoked identity cannot re-enroll. For 409 idempotency conflict, restore the original arguments and request_id; a changed operation needs its own UUID only after the prior operation is resolved. For session_busy_or_uncertain, poll the existing job. Never resend uncertain work with a new ID. For 429, wait for `Retry-After` seconds / `reset_at`, then replay the original ID and arguments. Lifetime session limits have no timed reset; a new session does not inherit the old offer. No client should rotate tokens to evade quota. Errors do not disclose another caller's private session details.

## Quota accounting

The generated contract below is the canonical source of numeric limits and exact accounting. A message means an accepted new `send_message` job, including free commands submitted through that tool. Status, readiness, export and export-part tools each consume one global operation and one lifetime session request, but no message allowance. `get_result` polling consumes only the minute allowance. A new `start_session` consumes the client's daily session allowance, but no message or global operation. Identical request replay consumes only the minute allowance. Rejected transactions roll back their increments. Daily windows reset at 00:00 UTC; minute windows are fixed buckets ending on the next UTC minute. No rolling 24-hour window is claimed. Session expiry and the session's lifetime request limit are separate.

A 500-message day can exceed the previous 1,000-operation allowance when each message is followed by status, readiness and exports. The controlled quota workflow covers 500 sends plus 2,000 deterministic operations; the initial operations ceiling is therefore 5000, preserving capacity for multipart retrieval. Polling does not consume that ceiling. Native Fetch chat is outside the adapter's message quota.

## Operator inference usage and abuse controls

The owner has selected call-based abuse controls **without a dollar cap**. The current client/global limits are generated from the canonical contract below. The adapter retains per-minute limits, isolated sessions, idempotency and a maximum of two application model attempts per message, including extraction. There are no automatic retries for uncertain inference or incomplete answers. Native chat is separate from adapter quotas; personal ASI:One account usage outside this agent is unaffected.

Token metadata, finish reasons and safe request identifiers are retained for diagnostics. Observed hosted metadata on 2026-11-03 included 7,052 prompt, 464 completion and 16 reasoning tokens. This is one observation, not a bill or a maximum. ASI reasoning and internal recovery can exceed the requested token allowance; request counters do not guarantee a maximum dollar charge. This release does not block inference or deployment for missing dollar-budget evidence.

To change availability, edit the limits in `machine/contract.json`, regenerate, test and deploy using `machine/release.py`. Deterministic status, readiness, export and polling avoid spending conversational message allowance when called through their dedicated tools. Model credentials and the separate buyer-approved FAHCE bridge remain unchanged. Ordinary machine calls cannot purchase a FAHCE evaluation; human/native buyer-approved checkout remains a separate flow.

## Fictional API seller example

The landing-page Parcel Format example is synthetic. Its .invalid URL is never fetched: a controlled fixture returns local documentation. Raw documentation describes POST /normalize, dimensions and cm/in units, a JSON response and no carrier booking. The fictional seller separately proposes USD 9/month for 1,000 calls, invoice payment and owner-approved API-key access. Those declarations are not operational proof or commercial permission.

https://tooloffer.kinganlogic.com/examples/fictional-seller.json contains a real TOOL_OFFER_BUYER_V1 result, the raw synthetic API specification, seller assertions, MachineRequest/result examples, readiness, an export manifest, indexed parts and verified reconstruction. Run `python -m machine.examples` offline; the controlled gateway regression executes start_session, send_message, get_result, assess_offer_readiness, export_offer and every get_export_part with real schemas and signature checks. A real client must substitute its actual session/job/request IDs, preserve release binding, poll to completion and verify every manifest part before consuming the complete export. These fixtures make no external API call, model request or payment.

## Developer integration accuracy

Use an external service's public machine documentation as the protocol reference; do not infer headers from token names. For FAHCE the published receipt instructions specify `Authorization: FAHCEReceipt <FAHCE-Recovery-Token>`, not a scheme named after the recovery token. Receipt retrieval is distinct from the paid HTTP 402 challenge and authorized retry. Consult https://fahce.kinganlogic.com/openapi.json and https://fahce.kinganlogic.com/capabilities/machines for the current credential names and steps. Described settlement/attestation capabilities do not establish this customer's settlement, attestation or execution. Tool Offer's machine adapter cannot execute those steps. Its separate buyer-approved bridge is unchanged.

A grammatical introduction is not a completed requested deliverable. Obvious preamble-only buyer copy and numbered analytical omissions return CHAT_INCOMPLETE; token-limit truncation returns CHAT_TRUNCATED; provider failure remains separate. No blind model retry is made. Use export incomplete for a retained partial, or explicitly request one shorter complete section. Literal source quotations and offsets remain evidence pointers. Missing support in bounded excerpts means unknown, not absent from the full document.

Listing checklists, profiles and exports remain preparation features. Eligibility may be unknown, conditional/unverified or unavailable by the seller. A published x402 endpoint does not establish Coinbase Bazaar indexing. Cloudflare Monetization Gateway interoperability with Bazaar is unestablished. Respect explicit seller unavailability; no publisher submission, acceptance, indexing or market ranking is invented.


Automatic machine authentication
Agents from any framework can use OAuth client_credentials with ES256 private_key_jwt. Read /.well-known/oauth-protected-resource/mcp and /.well-known/oauth-authorization-server. Register a public P-256 JWK at POST /oauth/register; prove control with a short-lived signed JWT at POST /oauth/token (form encoded). Registration alone grants no access. Token claims: iss=sub=client_id, aud=the exact token endpoint, iat, exp at most 120 seconds after iat, and a fresh jti. Request scope tool_offer:machine and resource https://tooloffer.kinganlogic.com/mcp. Tokens last one hour; renew unattended with a new assertion. No browser or human approval.
An existing Fetch/uAgents identity may alternatively sign a fresh TOOL_OFFER_ACCESS_ENROLL_V1 request and receive its credential encrypted with RSA-OAEP-256 to its own public key. Status uses a private AccessRequest capability, never a public identifier alone. See /openapi.json for exact fields.
Both routes preserve stable per-key/per-address quota principals, tenant isolation, expiration, revocation and the existing Bearer adapter. Anonymous enrollment is limited to 5 requests/IP/day and 100 globally/day, with 30 access requests/IP/minute, 600 globally/minute, 10,000 access requests globally/day and 1,000 credential issuances globally/day. Invalid attempts count; access audit records have a 90-day retention window. Rate limits do not certify a unique person. Operator revocation is a separate abuse control; no approval queue. Public discovery needs no credential. Machine OAuth scope never grants payment, checkout or administration.
Client ID Metadata Documents are not fetched or implemented. OAuth client-credentials discovery is published; full interactive authorization-code login and external enterprise IdP federation are not claimed. A2A clients can use this OAuth/Bearer service through MCP/REST; A2A task operations are not implemented.

Start with /examples/ for the concise buyer demonstration or /examples/quickstart.json for compact JSON. /examples/fictional-seller.json remains the full multipart integrity fixture.

## Machine entrance
Release: `66979784d826683d48d83d6639e924078a3a3476c3ab488a93a9a57519767f19`
Source-attributed API/MCP offer intake, conversation, drafting, revision, deterministic readiness assessment and exports. No wallet connection, checkout, FAHCE execution, payment, approval, publication, administration or cross-conversation recovery through this adapter.
Public credential-free discovery. Automatic identity-bound enrollment: OAuth client_credentials with ES256 private_key_jwt for agents from any framework, or signed Fetch/uAgents identity proof. No human approval. Calls use scoped Bearer credentials.
Sources and seller terms are not independently certified. Public documentation does not grant resale rights. Machine sessions do not inherit ASI:One chat history. Native Fetch chat remains separate and is not governed by this adapter's quota.
MCP: https://tooloffer.kinganlogic.com/mcp (Streamable HTTP, protocol 2025-11-25, JSON responses, custom Authorization header).
REST: https://tooloffer.kinganlogic.com/api/machine/<tool_name>. OpenAPI: https://tooloffer.kinganlogic.com/openapi.json. Canonical machine-readable profile: https://tooloffer.kinganlogic.com/manifest.json.
MCP initialize and tools/list are public. For calls supply Authorization: Bearer <IDENTITY_BOUND_CLIENT_TOKEN>. Enroll automatically with identity proof at /machine/#access; no human approval.
1. Call start_session with a fresh UUID v4 request_id; retain session_id.
2. Call send_message (or a deterministic tool) with session_id and a fresh UUID v4 request_id; retain job_id.
3. Poll get_result with that job_id. Only complete means completed. pending, processing and uncertain do not.
4. Replaying the same operation with the same request_id returns the same job. Never use a new request_id to retry uncertain work. Conflicting arguments are rejected.
5. For resumable exports preserve the manifest, fetch every indexed part with get_export_part, and verify the agent's hashes. No automatic submission.
Access and gateway job/idempotency records expire seven days after session creation. Agent-side offer/audit state is retained under existing storage policy; expiry is not a deletion promise.
Credentials isolate callers. Sessions cannot access other clients, ASI:One conversations, owner exports or human wallet checkouts.
Limits (UTC days; message limits include commands sent through send_message): {"daily_messages_global": 500, "daily_messages_per_client": 20, "daily_operations_global": 5000, "daily_sessions_per_client": 10, "message_characters": 4000, "model_attempts_per_message": 2, "requests_per_minute": 60, "requests_per_session": 100, "session_days": 7}
Quota accounting: {"get_result": "Minute quota only; no operation, session request or message.", "get_status_assess_offer_readiness_export_offer_get_export_part": "One global operation and one session request per new accepted job; no messages.", "replay": "Same request_id and arguments consumes minute quota only; changed arguments cause 409.", "requests_per_minute": "All valid authenticated tool calls use fixed UTC minute buckets; rejected transactions roll back quota increments.", "reset": "Daily counters reset at 00:00 UTC; minute counters reset at the next minute. Sessions expire seven days after creation; 100 requests is a lifetime limit.", "retry_after": "429 minute/daily responses include Retry-After seconds and reset_at; lifetime 429 has no reset and retry_same_session=false.", "send_message": "One client message, one global message, one global operation and one session request per new accepted job; commands also count.", "start_session": "One client session per new session; no global operation or message."}
Model usage is billed to the operator's existing ASI-1 integration. The owner has selected call-based abuse controls without a dollar cap. Token and reasoning usage remain logged safely; request counts do not bound dollar charges. No automatic retry of uncertain inference. Native chat remains outside the adapter's quotas.
Authentication uses a dedicated Tool Offer gateway identity, ephemeral transport identities, and signed replies from the existing Tool Offer Agent identity. No FAHCE/OCI/wallet key is used; message signatures are not certifications or transactions.
Native Fetch Chat Protocol is also available separately at agent address agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a. Resolve its current endpoint through the Agentverse Almanac and use the official uagents Chat Protocol SDK. Its chat acknowledgement is not the final reply. Native chat is the existing human-capable interface, not this restricted adapter and not covered by its quotas.
### Readiness
Read-only report schema: https://tooloffer.kinganlogic.com/readiness.schema.json. Completed readiness reports contain the full human_readable document and source/snapshot references. Multipart reports require verified assembly. No inference or privileges. Native chat: readiness, readiness text, readiness json. Optional terminal card is a summary; text/export remains authoritative. Actual ASI UI rendering is a separate acceptance check.
### Tools
- start_session: Create an isolated seven-day offer conversation. Requires a unique request_id; replaying it returns the same session. No model inference.
- send_message: Send field: value lines, or a JSON-serialized StructuredIntake object in message, a product question, a revision or a drafting command. Intake keys: tool_url, docs (URL string or 1–3 URL strings), customer, pricing, payment, access, invocation; optional job and seller_name. All other values are strings. Optional schema is TOOL_OFFER_INTAKE_V1. Unknown/duplicate keys and invalid values reject the entire update. Card selections are separate. May use bounded operator model quota. Returns a stable job; optional HTTP Prefer: wait=1 through wait=5 waits without redispatch and may include the signed completed result. Otherwise poll get_result. Never resend uncertain work with a new request_id. No payments or FAHCE execution. May overwrite seller fields or rebuild retained drafts; not read-only. Request-ID deduplication is bounded by retained session/job lifetime, not an unqualified retry guarantee.
- get_status: Ask the existing agent for the current offer status without inference. Returns a job; poll get_result. Does not revise seller terms, but creates a metered asynchronous job and may retain delivery state.
- assess_offer_readiness: Deterministic assessment of your retained session without revising seller terms. No fetching, inference, FAHCE, approval or payment. Returns a job, not the report: poll get_result for signed readiness JSON plus full human_readable content, or a resumable report manifest. Not seller certification or commercial clearance. Does not revise seller terms, but creates a metered asynchronous job and may retain delivery state.
- export_offer: Export your session's saved offer, proposed plan or explicitly incomplete response without inference. Large responses use the agent's resumable manifest; retrieve each indexed part with get_export_part. An export is not publication or certification. Does not revise seller terms, but creates a metered asynchronous job and may retain delivery state.
- get_export_part: Retrieve one existing resumable export part from your session, without inference. Preserve the manifest and verify its hashes; do not claim completion until all parts are received. Does not revise seller terms, but creates a metered asynchronous job and may retain delivery state.
- get_result: Read a job owned by your authenticated client. pending/processing/uncertain is not completion. Poll this same job; do not duplicate an uncertain message. No inference. Polling is metered and may wake queued processing; it is not annotated as a side-effect-free read.
### Free commands
help, start, status, draft, draft limited, retry, refresh docs, reextract, buyer explanation, listing checklist, listing checklist json, listing profile api, listing profile mcp, listing profile agent, export json, export readable, export buyer, export representation, export listing, export part <export_id> <index>, revise field: value
