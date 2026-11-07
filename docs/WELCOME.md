# First-response intake

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

## Anonymized before / after

A first-time tester found the response fast but the opening difficult to scan.
Before: a general capability question could reach the conversational interpreter,
whose internal role wording could appear in a long opening paragraph.
After: a short explanation, two actionable choices, and a visible public-URL
fallback. Short replies stay short; longer model replies are guided toward bullets
or short sections. No private screenshot or conversation is included.

## Maintained path

The canonical source is the inner `ToolOfferAgent` checkout selected by the
maintained packaging source map, not the outer legacy Python package.

Incoming ACP `ChatMessage` -> registered handler in `chat.create_agent` ->
`chat.respond` -> acknowledgement -> `strip_routing_mentions` -> `Workflow.handle`.
Previously, `what do you do?` was neither a profile starter nor an explicit
command, so a configured conversational interpreter handled it through `_converse`.
The phrase “conversational interpreter” appeared in its system prompt, not in the
deterministic capability answer. This is code-path attribution, not a claim to
have recovered the tester's private runtime trace or exact model completion.

Now the capability question and the first two existing profile starters reach
`guided_cards.is_guided_request` -> `_guided_response` -> `handle_welcome`.
`issue` returns `ReadinessText`; `respond` preserves it through bounded rendering
and `create_readiness_chat` appends ACP `MetadataContent`. The existing version-1
custom-card schema carries section/text/button nodes with `action.selection`.
The interpreter is not called to compose the welcome or the example.

## Choices and safety

- **Start with my tool:** asks for the first missing field. A pasted URL works
  without clicking. Fields alongside the opening use the existing validated
  intake/update path; a complete opening uses limited, no-model drafting.
- **Try a fictional example:** uses the shared bundled parcel fixture, never a
  fetched or running `.invalid` API. Saves “Demonstration only. No commercial use.”
  before limited drafting. The draft retains those restrictions and source
  excerpts, fictional pricing/access/payment terms, and review/correction actions.
- Existing work shows Continue intake, Review current draft, Review intake, or
  Build a limited draft as appropriate. The example cannot replace existing work.
- Card IDs are session-local and bound to intake revision and draft hash. Existing
  timestamp, duplicate-envelope, schema, cancellation and completed-action checks
  prevent stale or repeated selections from replacing state.
- Welcome actions create no checkout, wallet operation, publication or paid model
  call. Correction, review and the separate payment bridge keep their boundaries.

## Reproduction and acceptance boundary

Run `python -m unittest tests.test_welcome -v` after the documented local install,
or `python scripts/test_offline.py` for the full network-guarded package suite.
The maintained full refresh also runs welcome tests against flat hosted modules.
Tests enter through `chat.respond` with real SDK messages and the outgoing button
selection JSON; transport and providers are mocked. Text and metadata are examined
together for duplicated intro prose, payload bounds and complete button labels.
The plain-chat choices also work with metadata intentionally unavailable.

The welcome release was revision 80 (November 6, 2026). The subsequent three-module
card/readiness repair is revision 81; the judging ZIP remains a private candidate.
Authenticated readback matches all 29 tested Python modules. Schema checks and
signed live ACP tests do **not** demonstrate native
ASI:One visual acceptance. No authenticated ASI browser is connected to the test
environment; Agentverse CLI authentication does not grant that browser session.
Neither native rendering nor a current client rendering limitation is claimed.
Sanitized release evidence is in `evidence/hosted-welcome-release.json`.
See `evidence/test-results.json` and `REVIEW-REPORT.txt` for measured checks/skips.

The founder already observed both welcome choices working on revision 80, including
automatic demonstration-only drafting and a readable review card. Do not repeat
those unrelated checks. That journey exposed a failing Correct a value action;
authenticated retained protocol history confirmed its exact action structure and
the subsequent successful button-form save. See `docs/CARD-JOURNEY-REPAIR.md` for
the fix, separate protocol evidence, and the smallest remaining post-repair visual
check. Typed fallback success is never counted as button acceptance.

## Scoped existing-agent release

The established `machine/release.py` workflow supports `generate --agent-only`
and `deploy --agent-only`. Capture a fresh authenticated baseline into a new
private work directory first; select only reviewed modules. Agent-only staging
preserves every unselected hosted file and the existing machine/gateway release
ID, then verifies the candidate before upload and reads hosted source back after
upload. A scope mismatch or contract drift stops deployment. This mode updates
the existing agent and matching profile, never the website or payment settings.
CLI authentication does not provide an authenticated ASI:One browser session.
