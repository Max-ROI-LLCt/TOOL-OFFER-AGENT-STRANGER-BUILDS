# Review, correction and rebuild repair

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

## Observations and limits

The founder's revision-80 ASI:One browser observations establish that both welcome
choices worked. The automatically generated fictional review's **Correct a value**
selection was rejected as an invalid schema. Typed review intake allowed the
customer to change, and Finish review worked on a later typed review offer card.
The founder did not capture the immediate save reply or its committing route.
Authenticated retained protocol history now confirms the button-driven form
submission and its successful customer-save reply. No original
conversation identifiers or captures belong in this package.

Both review origins use the same `guided_cards.issue(..., "offer", ...)` custom
card builder. The prior validator treated `approved` as an approve/reject toggle:
it required false for `edit`, whereas true was accepted for other actions.
Authenticated retained history contains the actual failing automatic-card action:
`action: edit`, the matching issued `card_id`, and boolean `approved: true`,
preceded by the target-agent routing mention. Its reply is the reported schema
error. The recovered form save uses `field`, `value`, `action: correct`, its issued
`card_id`, and `approved: true`; the later typed-card Finish uses `action: reviewed`
and `approved: true`. Both bindings and replies were checked privately. The cause
is confirmed, not merely inferred from a synthetic flag combination. Sanitized
structural replays replace identifiers and use fresh isolated state; they are not
historical per-message storage snapshots or new physical browser observations.

## Maintained repair

- Treat the optional boolean flag as a transport acknowledgement for edit; the
  issued action determines the transition. Both boolean values are accepted for
  edit only. Malformed flags, extra fields and unissued actions remain rejected.
- Preserve sender/session/card/revision/draft-hash binding, duplicate JSON-key
  rejection, stale and cross-session rejection, and correction replay handling.
- Exercise each button on independently issued cards from both origins. Test
  correction submission separately from typed correction, including unchanged
  values. Finish review grants no approval, checkout, publication or payment.
- Label the assessed intake revision separately from the saved draft revision.
  The detailed readiness formatter previously mislabeled `basis.revision`, which
  is the intake revision. Saved draft revision is now an explicit recorded fact
  within the existing report schema; the assessment policy and API schema remain
  unchanged. Put `draft limited` beside fictional stale-state warnings.
- Keep `buyer explanation` concise. `export buyer readable` already selected the
  detailed renderer; repair its misleading heading and Markdown paragraph/list
  boundaries, rather than changing routing. Keep source attribution and UTF-8
  delivery limits. Existing export snapshots retain their bytes and hashes.
- A correction makes intake revision 2 while leaving saved draft revision 1.
  Explicit `draft limited` then produces draft version 2 at state revision 3,
  following the existing rebuild revision behavior. The corrected customer and
  demonstration-only restrictions remain saved; no commercial execution occurs.

## Verification

`tests/test_card_journey.py` drives the actual ACP handler locally, covers the
retained compact JSON action structures with routing mentions, and tests the
complete correction/stale/rebuild/reopen flow. It retrieves every multipart export
part through `export part`, validates each part and the ordered total byte count,
SHA-256 and identity, and parses reconstructed JSON. It also tests the disposable
live-probe procedure against local ACP. `tests/live_card_journey.py` is the shared
disposable scenario using fresh bindings. Revision 81 passed 72 signed live ACP
replies, including all four independently generated origin/button combinations,
customer-only and identical-value form submission, separate typed correction,
stale review/readiness, explicit `draft limited`, and same-session reentry with
authenticated retained-state readback. The temporary mailbox was removed.

An independent audit verified every signed reply and reconstructed four complete
JSON exports from 29 part replies (24 unique parts plus five historical parts
retrieved again after rebuilding). It checked Base64, indexes, offsets, lengths,
part and total SHA-256, export identity, UTF-8, and JSON parsing without calling
the application's reassembler. The pending saved-draft export was five parts and
12,891 bytes; the rebuilt revision-3 export was nine parts and 24,177 bytes. Exact
hashes and the readiness JSON export are in the sanitized release evidence.

Guarded deployment passed six journey tests, 362 other hosted tests, 13 chat tests,
and 45 site tests; the maintained builder passed 16 tests. Suites overlap and must
not be summed as unique tests. Clean-package counts and explicitly configured
local-custody skips are recorded separately in `evidence/test-results.json`.

Native rendering, physical clicks and browser reload are not established by local
or signed protocol tests. Both buttons from both origins are covered separately
by protocol tests. The smallest remaining visual check uses one new fictional
chat: click Correct a value on its automatic card, save a customer correction,
then inspect a fresh `review offer` card and click Finish review. Check the stale
revision labels and paragraph/list boundaries in `readiness text` and
`export buyer readable`; send `draft limited`, reopen that disposable chat, and
confirm the corrected customer and demonstration-only restriction remain.
Do not repeat the already-observed welcome choices or use saved founder records.

## Commercial bridge boundary

The payment bridge remains a separate, prominent part of the judging
source materials: see the root README, `bridge/checkout`, `bridge/custody`, and
`docs/EVIDENCE.md`. Review and drafting are not payment approval. This repair does
not modify or deploy FAHCE, the checkout Worker, wallets, or payment infrastructure;
no paid call, signing, purchase or settlement is performed. The ZIP is a private
judging candidate, not a finalized submission or publication.
