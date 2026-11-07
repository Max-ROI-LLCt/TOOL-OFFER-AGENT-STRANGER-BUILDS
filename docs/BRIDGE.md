# From an ASI:One offer to a buyer-authorized service result

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

## Problem and implemented mechanism

An ASI conversation can produce a request, but payment requires a different principal and a durable boundary. A timeout after signing must not cause the agent to make a second purchase. This project implements request/draft binding across Python agent state, a Cloudflare checkout Durable Object, an external buyer wallet and an x402 service endpoint. Review, free compatibility screening, signing, paid delivery, result recovery and proof verification are explicit stages.

The bridge is a substantial optional capability alongside free drafting. The selected operation is **FAHCE Diagnose**, not a promise of every operation documented by that service. Its negative result is a useful integrity assessment, not a failure to complete and not a verified commercial offer. This package does not implement FAHCE's engine or settlement infrastructure.

## Architecture and actual order

```mermaid
sequenceDiagram
    actor Human as ASI user
    participant ASI as Fetch ASI:One / ACP
    participant Agent as Tool Offer Python workflow
    participant Checkout as Tool Offer checkout Durable Object
    actor Buyer as External buyer browser + wallet
    participant Relay as Tool Offer payment relay
    participant Service as External FAHCE x402 / gateway
    participant Proof as External published policy / keys / Base RPC
    Human->>ASI: Intake, draft, review, readiness (free of checkout)
    ASI->>Agent: Session-bound messages and card selections
    Agent-->>ASI: Source-attributed draft / bounded replies / exports
    Human->>ASI: Optional evaluation request (not payment authorization)
    ASI->>Agent: check, subject to saved restrictions and eligibility
    Agent->>Checkout: Authenticated prepare: exact request, draft hash, deterministic key
    Checkout->>Checkout: Create or recover one bound checkout
    Checkout->>Service: Free input compatibility screen
    Checkout-->>Agent: Private checkout capability; may be input_blocked
    Agent-->>ASI: External buyer review link / status; no signature
    Buyer->>Checkout: Connect buyer + explicitly accept current policy
    Checkout->>Service: Re-screen; unsigned request for 402 challenge
    Service-->>Checkout: x402 requirement (not proof of payment)
    Checkout->>Checkout: Validate pinned price / network / token / recipient / timing
    Buyer->>Checkout: Authorize; persist awaiting_wallet
    Buyer->>Buyer: Sign EIP-3009 with buyer wallet
    Buyer->>Checkout: Submit signed payload
    Checkout->>Checkout: Persist validating; bind payload to buyer, request and policy
    Checkout->>Relay: Verify signature via pinned RPCs
    Relay->>Proof: Read-only signature/network checks
    Checkout->>Checkout: Persist submitting before signed delivery
    Checkout->>Relay: One signed request, original bytes + idempotency key
    Relay->>Service: Fixed Diagnose endpoint, allowlisted payment headers
    Service-->>Checkout: HTTP result / gateway response / recovery material
    Checkout->>Checkout: Persist response metadata, then parse service result
    Checkout->>Proof: Verify attestation with published policy and independent keys
    ASI->>Agent: purchase status / subsequent check
    Agent->>Checkout: Retrieve same bound checkout; do not purchase again
    Checkout-->>Agent: Result and separate gateway/proof states, or uncertainty
    Agent-->>ASI: Bounded result/status acknowledgment; detailed export separately
```

**Additional custody boundary:** `bridge/custody/transaction_custody.mjs` provides atomic compare-and-swap storage for the agent's commercial records, wired by `cloudflare_custody.py` and `chat.py`. It is not the checkout's wallet-state database. Checkout attempt state lives in the `FahceCheckout` Durable Object; conversation/intake state uses the agent's configured state store. This distinction matters when reasoning about recovery.

The diagram deliberately places checkout creation before its free screen. An `input_blocked` checkout can exist; a current draft alone is not sufficient to sign or pay. Saved demonstration/no-commercial-use restrictions block the paid branch. The free quick-start never calls `check`.

## Source and test map

Paths are relative to the package. Symbols and test names provide stable navigation even if line numbers change.

| Stage | Implemented here | Reproduction / boundary evidence |
| --- | --- | --- |
| ASI transport and state | `tool_offer_agent/chat.py` (`create_agent`, `bounded_send`), `conversation.py`, `workflow.py` | `tests/test_chat.py`, `test_workflow.py`, `test_protocol_exchange.py`; bounded transport is not proof the ASI UI displayed it. |
| Exact request and current draft binding | `fahce_checkout.py` (`checkout_request`, `FahceCheckoutClient`), `workflow.py` (`_wallet_check`) | `tests/test_fahce_checkout.py`, `test_wallet_information.py`, `test_commerce.py`. |
| Create/recover checkout and private access | `bridge/checkout/checkout-worker.mjs` default fetch `/v1/checkouts`, `FahceCheckout` | `checkout.test.mjs`: “durable checkout allows arbitrary buyers, isolates tokens and recovers preparation”. |
| Free compatibility and optional candidate review | `FahceCheckout.evaluateInput`, `screenInput`, input-revision routes; `browser.mjs` | `checkout.test.mjs`, `input-review-browser.test.mjs`. Original evidence remains unchanged; one explicitly buyer-accepted candidate representation can replace the original with recorded hashes. |
| Wallet connection, consent and challenge | `browser.mjs`, `payment-policy.mjs`, `checkout-worker.mjs` challenge/authorize routes | `wallet-onboarding-browser.test.mjs`, checkout policy tests. Connection alone does not sign. |
| Signed payload validation and one delivery attempt | `payment-policy.mjs`, Worker pay route and `FahcePaymentRelay` | `checkout.test.mjs`: concurrent one-attempt and ambiguous-delivery cases; signature/provider failure cases. |
| Expiry reconciliation | `expired-authorization.mjs`, Worker owner-only diagnostic/reconciliation routes | `expired-authorization.test.mjs`, checkout archive rollback / owner-only / no-payment tests. |
| Result and attestation | Worker result handling; `attestation-verifier.mjs`; Python `_wallet_check` | `tests/test_fahce_checkout.py`; synthetic `receipt-boundaries.test.mjs`; retained positive proof observation in `evidence/bridge-observations.json`, with limitations. |
| Agent commercial custody | `tool_offer_agent/cloudflare_custody.py`, `commerce.py`, `bridge/custody/transaction_custody.mjs` | `tests/test_cloudflare_custody.py`, `test_commerce.py`, `test_hosted_custody.py`. Live credential-gated custody checks are not run in this package. |
| Delivery and large records | `chat.py`, `export_delivery.py`, `owner_export.py` | `tests/test_customer_repair.py` (`ExportIntegrityTests`), `test_owner_export.py`, native/correction/transport tests. Hash reconstruction proves bytes, not UI acknowledgment. |

## Protections and limits

- **Preparation duplicates:** deterministic session/draft checkout key recovers a bound checkout; conflicting data is rejected. The private capability authorizes checkout access, not agent authority over the buyer's wallet.
- **Buyer boundary:** current legal-policy acceptance and the buyer address are bound before authorization. The pinned policy is exact 0.15 USDC on Base (chain 8453), with fixed token and service recipient checked in code. Those are implementation expectations; a publication change stops the flow rather than silently accepting a new price. No current market-price guarantee is made.
- **Before delivery:** pending signed material is retained; signature, amount, recipient, chain, expiry and request constraints are checked. Verification can try pinned RPC alternatives without skipping signature checks. Relay placement is a Cloudflare hint, not a fabricated location guarantee.
- **Provider and custody boundaries:** relay location is not buyer residence or an exemption from published provider eligibility/legal conditions. The bridge does not spoof location headers. Its owner token and private checkout capabilities are sensitive bearer credentials; retained signed authorizations require protected custody. Wallet private keys remain with the wallet. This is not a claim of end-to-end secrecy from the checkout operator.
- **Ambiguity:** requesting challenge, awaiting wallet, validating, submitting and unresolved states conservatively block another authorization/submission. The submission state is persisted before the signed external call. A missing HTTP body is not proof that nothing happened. There is no claim of globally exactly-once settlement across every external failure.
- **Retries:** explicit unsigned wallet rejection can permit a new review. A narrowly guarded retained-authorization path permits explicit submission only when the previous signature was not delivered and fresh policy/input/integrity/signature checks pass. It is not an automatic retry after uncertain paid delivery.
- **Reconciliation:** expired non-billable authorization recovery requires the expected 422 outcome, no settlement/recovery/released-content evidence, exact retained attempt matching, and two independent pinned RPC observations of unused nonce at finalized blocks after expiry. Original attempt evidence and replacement state are archived atomically; failure rolls back both. It does not refund, erase or rewrite the old attempt.
- **Result vs payment:** `response_received` requires the expected Diagnose schema. The Python outcome labels settlement as `gateway_reported_success`, not independently verified settlement. An HTTP 200 is not a positive determination or a payment receipt.
- **Attestation:** the client validates an attestation against independently fetched keys and published policy at issuance time. Its own result explicitly disclaims external-action certification, caller evidence truth, caller-original-input verification and a fresh execution. A valid historical proof does not confer publication or commercial rights.
- **Delivery:** saved result recovery and a successful ACP send are distinct from native UI display. Bounded-wait outcomes can remain unobserved in the browser. Historical complete exports remain separately retrievable.

These protections are implemented and covered by the mock tests indicated above. Retained live observations cover a completed negative service determination, gateway-reported success, independent receipt audit and read-only chain observations, not every failure path. Fresh review checks made no payments and did not prove native rendering or current checkout server-byte identity.

## Current, historical and external components

The **current** checkout came from the outer checkout's `wallet-approval/` and is staged at `bridge/checkout/`. The inner checkout's older directory of the same name is not substituted for it. `bridge/checkout/server.mjs` is included solely as the historical local helper still exercised by its regression tests; `checkout-worker.mjs` is the hosted entry point. `record-proof.mjs` and FAHCE engine/grammar repair tools are excluded because they depend on private purchase records or modify a different service.

`tool_offer_agent/protocol_payment.py` and the commercial custody plumbing remain for compatibility and local/explicitly enabled test paths. The active wallet bridge is external x402 and **is not claimed as native Fetch Payment Protocol implementation**. No contribution claim is made for the underlying Fetch ACP runtime, wallet SDK, x402 specification/libraries, Base/USDC, FAHCE computation, gateway or attestation issuer.
