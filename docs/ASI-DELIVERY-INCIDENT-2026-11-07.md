# Tool Offer Agent — ASI delivery incident

Status: unresolved external delivery incident; sanitized, support-ready summary. Date: November 7, 2026 UTC. These observations were supplied by the owner from completed live testing, not replayed during the local correction job.

## Observed behavior

- ASI reported a `MetaConnectorEventHandler` database-pool timeout: `couldn't get a connection after 5.00 sec`.
- Subsequent hosted-agent requests completed quickly and emitted reply payloads/envelopes, but transport remained `transport_unconfirmed`; replies were absent from the returned ASI conversation history.
- Fresh ASI conversations also failed. Agentverse manual Testing continued to work.
- Trace `c5d30610-11c1-4bef-8913-8dfe08a1be93`: 123 ms, zero model calls, 3,168-byte response.
- Trace `d6a97d9b-facf-45a3-9d40-65d9bb5d29b3`: fresh conversation, 67 ms, zero model calls, 262-byte response.

The observations do not establish that envelope submission completed persistence or UI delivery. Fast processing and the small fresh-conversation reply do not demonstrate a model timeout or oversized-reply cause. No private conversation body, credential, wallet address, callback or signing material is included here.

## Local ACP inspection

Inspected `tool_offer_agent/chat.py` and installed **uagents 0.26.1 / uagents-core 0.4.11** chat, cards, context and delivery-status implementations. The handler acknowledges the incoming message ID, obtains the session from the existing SDK context, creates a ChatMessage with timestamp/message ID/text, optionally appends validated card metadata, and sends it to the incoming sender through `ctx.send`. The SDK serializes the message under its schema and carries the context session in its outbound envelope; this application does not replace the transport or sign arbitrary envelopes. The installed version identifies the inspected implementation, not a new authenticated claim about the platform's current package inventory.

`bounded_send` distinguishes `DELIVERED`, `FAILED`, `SENT`/missing status, timeout and exception. `SENT` or an envelope log remains unconfirmed. Even SDK transport-delivered status does not prove inclusion in ASI history or rendering. Logging now explicitly states this scope. Controlled tests cover these states, acknowledgement correlation and the metadata path without contacting ASI.

A separate, demonstrated local defect was found: incoming card-response metadata was ignored because `msg.text()` reads only text content. The local candidate now decodes SDK card responses, preserves bound card identity, handles metadata-only cancellation and rejects conflicting or multiple responses. This is not evidence that the reported database-pool incident was caused or fixed by that defect. The candidate is not deployed.

## Requested provider investigation

Correlate the two trace IDs with MetaConnector ingress, outbound envelope acceptance, ASI history persistence and delivery status around the database-pool timeout. Determine where persistence/delivery stopped and whether affected conversations require recovery. Agentverse manual success and fresh ASI failure should be considered separately.

No database fix is asserted. No restart, redeployment, credential rotation, enrollment or repeated live-testing campaign was performed to chase this incident. Resolution requires provider-side evidence or a later owner-authorized delivery observation, not another local envelope-submission claim.
