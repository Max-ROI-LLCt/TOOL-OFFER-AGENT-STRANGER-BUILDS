# Origin and release correspondence

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

This document preserves the initial November 5 review context. For the current rebuilt candidate, use `REVIEW-REPORT.txt` and `evidence/source-correspondence.json`; historical source/commit/test observations remain separately preserved in `evidence/history/`. The packaging command reads local Git and working files only, not fresh GitHub refs or deployed server source.

## Authoritative boundaries

Two independent Git working trees were inspected: outer `/workspaces/tool-offer-agent` and inner `/workspaces/tool-offer-agent/ToolOfferAgent`. The inner tree supplies the current Python agent, profile, machine gateway, site and commercial custody Worker. The outer tree supplies the current checkout Worker, relay and browser wallet implementation. The older inner `wallet-approval` adapter is not the current hosted checkout.

The selected package is a copy outside both working trees. It has no `.git` directory, new commits, fabricated replacement history or publication. Existing files, private history, local modifications, customer records and recovery archives remain in their original locations. The separately requested private GitHub inventory report is not part of this package.

## GitHub baseline, refreshed read-only

The original inventory examined 30 reachable pushed commits and 508 distinct blobs, including compressed archives. In this pass, read-only remote heads/tags inspection still returned the following pushed branches and no tags:

| Branch | Commit |
| --- | --- |
| `main` | `218618b7c5cd57ebb111b51c6d906bd0373fe810` |
| `preserve/deployed-r63-b335ff91-20261103` | `3191c938547cb609fe41b55cd7671cf2c7c1dc88` |
| `improve/machine-access-and-examples-20261103` | `6d4904c768d6b7c0f731957d6f3294a7418ccfd6` |

The last branch is the inner HEAD and committed product 1.4.4, not the full revision-79 working source. Its cached “six ahead” tracking state was stale; those commits are pushed. The outer HEAD `7b38c2f610de5108698430365210152341e61742` is already in pushed ancestry. The local historical branch at `7a4583c90e78c285ab1907cf237fcfb92d159057` is not a pushed release. No fetch, commit or push was performed here.

The inventory recorded 34 inner unstaged tracked edits, two outer tracked edits and no staged edits. This pass adds focused display/test changes; `evidence/source-correspondence.json` records current selected paths, whether they are tracked or local-only, and their relationship to the pushed head. Untracked implementation was selected deliberately, not discarded. The broader historical inventory was reused, not misrepresented as a new full-history rescan.

## Revision 79 / product 1.4.6

- Release ID: `286e0c584063b4473836a02c7eeaf5a22deb7c8a6ba1df3b4476c049f34528c7`.
- Retained Agentverse code digest: `768c0e56565d1d513a00409d525540557ded2c6441b9239b2da00187e1944753`.
- Retained Cloudflare site version: `38aec8d4-21e2-4f97-9ad9-f9509127b0de` (historical receipt, not a fresh server-source readback).
- Exact retained source archive: `evidence/releases/revision-79/hosted-source.json.gz`, SHA-256 `7478cae2a42f3dd6b18f934169f6d70b1ff9488ca22f500001c1a725a1a27884`.
- Fully reconstructed archive SHA-256: `c262d3f3e2563b84032338d0ab00b230bc5a27195dd64b58cfabed1e87176e2a`.

The archive contains 28 flat Python members and no environment entries. Before local polish the working source corresponded to that baseline. Relative to the pushed head, seven retained runtime modules differed: `guided_cards`, `machine_contract`, `offer_representation`, `readiness`, `readiness_cards`, `restrictions`, `workflow`; the remaining baseline members matched the applicable build/initializer source.

The new local candidate differs from the revision-79 runtime in **three presentation modules only**: `guided_cards.py`, `offer_representation.py`, `readiness_cards.py`. Source/test/package transformations and every selected file hash are recorded in `evidence/package-manifest.json`. Local builds do not change the retained deployed release ID. The generated entry point and local CLI placeholder are distinguished from the package CLI; the local builder includes the unchanged package initializer, matching the retained archive member. This creates no deployment.

Fresh public GETs still advertised the baseline product/release. The wallet bundle rebuilt from the selected source is byte-identical to the outer working bundle and the freshly fetched public `/app.js`. That proves those browser bytes, **not the current checkout Worker server implementation**. Available authentication did not complete an Agentverse source readback. Native rendering of the new card layout remains unobserved.

## Development dates without private conversations

**Original development repository created (UTC): `2026-10-31T04:33:07Z`.** An authenticated GitHub CLI read returned this exact creation timestamp for `Max-ROI-LLCt/tool-offer-agent`. See the [short development timeline](EVIDENCE.md#short-development-timeline--original-repository-and-curated-copy) and [three-field API record](../evidence/original-repository-metadata.json). This is the original repository's creation date, not the creation date of this separate curated judging copy or proof of when every file was developed.

`evidence/source-correspondence.json` includes original commit IDs and recorded author/committer dates, without names, emails or private commit messages. Existing hosted-source hashes and retained operational timestamps add separate release/operation evidence. Git timestamps are self-recorded and are not independent proof of when all uncommitted code was developed. Public read-only identity checks prove what was advertised at the check time, not the entire historic deployment chronology.

Judges can inspect the original pushed commit objects through an organizer-approved access method, compare approved source/archive hashes, and exercise the public ASI workflow. A controlled review of selected original signed operational records would be a separate privacy/authorization decision; the sanitized evidence report alone cannot independently reverify an omitted signed receipt. Do not grant broad private history access on the assumption that this curated package conceals files already present there.

## Specific organizer clarification required

The official [Stranger Builds hackpack](https://innovationlab.fetch.ai/events/hackathons/stranger-builds-1/hackpack) calls for a public GitHub repository with setup instructions and an ASI:One-usable primary workflow. No repository visibility was changed here. Ask:

> Will a curated public source snapshot containing the complete current implementation, tests, preserved release hashes and original commit/date references satisfy the repository requirement, while the original private history remains private? If original development history is required, what limited evidence/access procedure is acceptable without exposing customer conversations, credentials or unrelated work?

Do not assume a newly created repository is accepted, or that timestamps alone meet provenance requirements. The external x402 bridge is not presented as satisfying a native Fetch Payment Protocol bonus. Existing innovationlab/hackathon badges retain category meaning only, not endorsement or awards.
