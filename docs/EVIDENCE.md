# Evidence boundaries and readable results

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

MCP: https://tooloffer.kinganlogic.com/mcp
REST: POST https://tooloffer.kinganlogic.com/api/machine/{tool_name}
Native Agentverse address: `agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a` (Fetch Agent Chat Protocol).
Public Agentverse JSON profile: https://agentverse.ai/v1/agents/agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a/profile
Calls require identity-bound credentials; discovery is public. Retain session_id, request_id and job_id. Poll get_result for the same job; an acknowledgement is not completion. Never retry uncertain work with a new request_id. Verify signed results and every multipart export part.

Drafting is free; operator inference costs and published quotas still apply.
Optional FAHCE evaluation is separate and buyer-authorized: 0.15 USDC on Base mainnet via the private human checkout. A free preflight is not an evaluation. Checkout preparation, wallet connection and a 402 challenge are not payment authorization, settlement or a completed result. Changed price, network, token or recipient stops payment. No automatic spending.
<!-- tool-offer-discovery:end -->

## Short development timeline — original repository and curated copy

**Original development repository created (UTC): `2026-10-31T04:33:07Z`.** This is the exact `created_at` returned by an authenticated, read-only GitHub CLI lookup on November 5, 2026:

```sh
gh api repos/Max-ROI-LLCt/tool-offer-agent --jq '{full_name, created_at, html_url}'
```

The returned `full_name` is `Max-ROI-LLCt/tool-offer-agent`; `html_url` is `https://github.com/Max-ROI-LLCt/tool-offer-agent`. The three returned fields are preserved in [original-repository-metadata.json](../evidence/original-repository-metadata.json). Recording the URL does not grant access or change repository visibility.

| Time (UTC) | Milestone and evidence boundary |
| --- | --- |
| `2026-10-31T04:33:07Z` | Original development repository created, as reported by GitHub. |
| `2026-10-31T04:33:07Z` | Earliest commit in the retained original commit list: `7b38c2f610de5108698430365210152341e61742`. Its recorded author/committer time is `2026-10-30T23:33:07-05:00`, normalized here to UTC. This is Git commit metadata, separate from GitHub repository metadata. |
| `2026-11-04T12:55:41Z` | Latest commit in that retained list: `6d4904c768d6b7c0f731957d6f3294a7418ccfd6`, the pushed product-1.4.4 baseline, not the complete revision-79 working source. |
| `2026-11-05T03:12:16.143241+00:00` | First local judging package assembled, according to [its preserved original manifest](../evidence/history/initial-package-manifest.json). Later candidates have separate creation times in their own manifests. Each is a **curated copy**, not the original development repository, a new Git history, or a deployed release. |

Original commit IDs and dates remain in [source-correspondence.json](../evidence/source-correspondence.json). The curated copy includes retained revision-79 / product-1.4.6 evidence with release ID `286e0c584063b4473836a02c7eeaf5a22deb7c8a6ba1df3b4476c049f34528c7` and the exact [hosted source archive](../evidence/releases/revision-79/hosted-source.json.gz), SHA-256 `7478cae2a42f3dd6b18f934169f6d70b1ff9488ca22f500001c1a725a1a27884`. See [origin and release correspondence](ORIGIN.md) for the deployed-source digest, complete reconstruction hash and subsequent local polish. No deployment timestamp is inferred from repository or package creation.

GitHub's timestamp establishes repository creation, not when every implementation was written. Git author/committer dates and the local package timestamp are separate records, not independent proof of all development dates. No supplied GitHub Insights Network screenshot was located in the bounded accessible Codespace search, so no graph is included. The weekly code-frequency graph is omitted.

## Separate evidence classes

The current candidate's `REVIEW-REPORT.txt`, `evidence/test-results.json` and `evidence/source-correspondence.json` are generated from its exact selected inputs and validation. Initial review/test/source records remain under `evidence/history/`. A refresh performs lighter local checks than finalize and lists the full checks it did not run. Retained public observations and payment audits below are historical, not fresh checks performed by the packaging command.

1. **Local source/tests:** inspectable current implementation plus synthetic reproducible checks. Passing mocks are not live payment or ASI UI evidence.
2. **Retained deployment evidence:** exact revision-79 hosted Python source archive and its hashes. This predates the three-module local presentation polish.
3. **Retained bridge observations:** `evidence/bridge-observations.json` is an allowlisted, sanitized extraction from saved operational/audit records. Source SHA-256 commitments are supplied, but the private originals are not distributed. This extraction is not a redacted-and-still-valid signed receipt or an independent new cryptographic audit.
4. **Fresh read-only observations:** public machine identity and wallet browser bundle checks. Authentication failure is recorded separately. They do not prove current checkout Worker server bytes or native ASI rendering.
5. **Human acceptance supplied by the founder:** unchanged correction and Finish review passed previously; founder revision-6 offer stayed current; fictional restrictions, readable explanation and profile badges were observed. No later Finish click is invented. These statements are not a new browser session conducted for this review.

## Retained bridge result — do not merge the stages

The November 1 retained audit reports `response_received`, HTTP 200 and a **DETERMINATION_COMPLETE_NEGATIVE**, with `offerVerified: false`. This is completed service execution with a negative conclusion, not a verified offer.

Recorded signed-payload existence and timestamp support a wallet authorization attempt. They are not a recording of the buyer's consent UI. The gateway reports success, while the immutable service receipt records **AUTHORIZED_PENDING_GATEWAY_SETTLEMENT**. Preserve both: later evidence does not retroactively change the receipt's text.

Two read-only RPC observations found a successful matching transaction and matching authorization amount/recipient. The initial observations were not finalized. In the later follow-up only one of the two providers reported the transaction at or before its finalized head. Do not call this two-provider finality convergence.

The prior independent receipt audit returned `verified: true` for historical confidential deterministic computation, with explicit exclusions: no fresh execution, external actions, evidence truth, original caller input or full service-TEE certification. This check is separate from gateway payment and message delivery. Its prior chat/hash match is retained audit testimony; raw private conversation text is excluded and native rendering was not re-observed here.

## Why legacy readiness says 22 / 0 / 48

The assessed legacy record has **22 exact-quotation alignments, zero stored supported-derived statements, and 48 unresolved schema/alignment entries**. Nine seller/record declarations are a separate category. These are classification counts, not proof that the statements are true.

`offer_representation.representation()` assesses stored leaf facts against retained sources and derivation metadata. Literal source alignment can be a quotation; a verified structured derivation requires the supported pointer/derivation metadata. Old fragments that lack that metadata remain unresolved even when a reader can recognize part of an API schema.

The buyer renderer additionally calls `display_facts()` / `presentation_fact()`. It can recover a selected operation's structured schema from retained documentation when the legacy prefix/pointer actually matches. This is an **ephemeral derived presentation**, not a mutation that writes supported-derived facts back to the saved draft. Therefore recovered buyer summaries and zero stored-derived claims can coexist. We found no established classifier defect warranting promotion of the 48 unresolved records.

The legacy incomplete-excerpt marker occurs 10 times across the selected inspected fields, representing **7 distinct fragments**, not 10 unique missing documents. Repeated appearances are not extra evidence. Original fragments, sources, hashes and historical exports are preserved; partial extraction is not proof the documentation lacks information. `evidence/legacy-classification.json` contains only counts, method and private-source hash commitment.

## Deployed display changes

- Long native offer review content now uses supported custom card sections/text rather than narrow summary label/value rows. The existing review/correct selections and validators retain their session/draft/replay checks.
- Preview truncation is UTF-8-aware where needed; complete-result commands occupy a separate untruncated section. “1 more detail” is singular.
- Duplicate terminal punctuation is removed only from derived display highlights; stored excerpts and detailed historical exports are not rewritten.
- Readiness explicitly distinguishes stored claim assessment from recovered buyer presentation.

The revision-80 paragraph below is historical welcome-release evidence. The latest
three-module correction is revision 81 on November 6, 2026, with authenticated
digest `3347eea4261f72b3fb36eac773c9f18a4593a9da3564c0e9c491cf54322b1b54`.
Its 29 hosted modules match the tested candidate. Actual retained browser history
confirms the failing `edit` action carried boolean `approved: true`, and recovers
the later form-save route and reply; sanitized structural replays cover both card
origins. See `docs/CARD-JOURNEY-REPAIR.md` and the current
`evidence/hosted-welcome-release.json` for scoped results and remaining visual
acceptance. The prior nine-declaration legacy assessment above is retained
evidence; new reports add the saved-draft-revision declaration without rewriting
that assessment or historical exports. Payment and service evidence remains
separate and unchanged.

The official custom-card structure was checked against Fetch's [interactive-card documentation](https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards). Schema/byte/action checks pass locally. The welcome and display changes were deployed to the existing agent as revision 80 on November 6, 2026; authenticated readback matches all 29 staged Python modules. A separate isolated live ACP probe verified 23 signed replies, including welcome actions, demonstration restrictions, duplicate/stale protection, review, unchanged correction and readiness metadata. Full-width/left-aligned intent is expressed with section/text components; **actual ASI renderer layout remains unobserved**. No authenticated ASI browser was available, and human visual acceptance was not claimed. The judging ZIP remains a private candidate. See `evidence/hosted-welcome-release.json` for sanitized results and `docs/WELCOME.md` for the remaining visual checks.
