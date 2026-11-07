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
