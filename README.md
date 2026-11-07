# Tool Offer Agent

[![VerifyMCP report for Tool Offer Agent.](https://verifymcp.io/badge/com-kinganlogic-tool-offer-agent/tooloffer.svg?variant=verified)](https://verifymcp.io/servers/com-kinganlogic-tool-offer-agent/tooloffer)

The live badge links to a third-party report, not blanket security certification. No score is fixed in this repository.

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

By Kingan Logic. Tool Offer Agent turns public API/MCP documentation and truthful seller terms into source-attributed offer drafts. It supports intake, drafting, review, correction, rebuilding, deterministic readiness and complete exports. Bring real documentation with **Start with my tool**. **Try a fictional example** is an optional, commercially restricted demonstration of the real agent—not a working parcel service.

Documentation is evidence of documented claims, not proof of service execution or seller rights. Price, access, customer and payment terms are seller statements. Review, readiness and export never certify an offer, publish a listing or authorize commercial use. Fictional restrictions survive correction, rebuilding and export. No fabricated integrations, buyers or rights are supplied.

## Entrances

- Homepage: https://tooloffer.kinganlogic.com/
- Native ASI:One handle: `@tool-offer-builder` (Fetch Agent Chat Protocol).
- Agent address: `agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a`
- Agentverse: https://agentverse.ai/agents/details/agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a/profile
- Human machine-access instructions: https://tooloffer.kinganlogic.com/machine/
- MCP: `POST https://tooloffer.kinganlogic.com/mcp`, protocol **2025-11-25**, JSON responses. `/mcp/` is a body-preserving alias. GET returns 405 with `Allow: POST` and a help link, not a webpage or standalone SSE stream.
- REST: `POST /api/machine/{tool_name}`; discover exact schemas in `/openapi.json` and `/manifest.json`.
- Detailed guidance: `/instructions.md` (`/instructions.txt` has the same bytes).

Discovery is public. Machine calls use identity-bound Bearer credentials obtained through automatic OAuth registration plus `private_key_jwt`, or existing Fetch identity proof. There is no human enrollment queue. Machine application sessions are isolated from each other and from native ASI conversations. Retain request, session and job IDs, poll existing jobs, and verify signed completed results and every export part. A manifest or acknowledgement is not completed delivery. See `machine/contract.json` for actual quotas and payment boundaries; `machine/access-client.mjs` and `machine/client.mjs` implement access and verified delivery.

## Payment And Trust Boundaries

Offer drafting is free to users; operator inference costs and quotas remain. Optional buyer-authorized FAHCE evaluation is a separate native-chat checkout flow, not an MCP/REST operation and not native Fetch payment integration. `wallet` / `purchase guide` explain prerequisites, `preflight` is free screening, and explicit `check` can prepare eligible checkout. A checkout or 402 challenge is not buyer authorization, payment, settlement or a positive evaluation. Never retry payment to resolve an uncertain result.

The dedicated MCP Registry publisher authenticates publication only. It does not attest to FAHCE execution or certify offers. Keep `rg-tooloffer-publisher`, `kv-toa-pub-0dc85b24`, key `tool-offer-mcp-registry-p384`, and Worker `tooloffer-registry-proof` separate from product runtimes. Ownership proof route: `kinganlogic.com/.well-known/mcp-registry-auth`. Do not change the separate FAHCE DNS proof, receipt, OCI, attestation or signing boundaries.

The official Registry identity `com.kinganlogic/tool-offer-agent` was published as 1.4.9 at `2026-11-07T03:32:16.914361Z`, active/latest at the verified post-publication readback. Publication is complete. `machine/registry-publication.json` records the owner-supplied official readback and baseline source correspondence; later local corrections are not thereby deployed. Publication does not guarantee indexing, adoption, certification or hackathon acceptance.

## Source Layout

- `tool_offer_agent/`: Python runtime, retained evidence, restrictions, cards, readiness and native/machine operations.
- `machine/contract.json`, `machine/public-profile.txt`, `machine/public-profile.json`, `machine/guide.txt`: canonical release inputs. `machine/release.py`, `machine/discovery.py`, `machine/surfaces.py`: release generation, mirror consistency and public-asset inventory.
- `site/src/`: existing Cloudflare gateway, identity registry, signing and HTTP routes. `site/public/`: authored homepage/styles/assets plus generated profiles, examples, schemas and instructions.
- `cloudflare/transaction_custody.mjs` and `tool_offer_agent/cloudflare_custody.py`: separate seller-side custody Worker and Python client.
- **Current checkout/relay/wallet:** `bridge/checkout/` preserves the current sibling `../wallet-approval/` implementation from the separate outer checkout, with provenance and content hashes. The older inner `wallet-approval/` adapter is not a substitute. This release does not redeploy the checkout service.
- `tests/`, `site/tests/`: regression suites. `build_hosted.py`: flat Agentverse packaging; its Python manifest does not describe the complete system.
- `docs/RELEASE-READINESS.md`: evidence, outstanding findings, video facts and publication decision. The existing private development history is not a public judging package.

## Setup And Tests

Use Python 3.12 and Node 24. Python package metadata remains at its historical packaging version; the product release version is `machine/contract.json` and generated runtime constants, not the wheel filename.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
npm --prefix site ci
python -m unittest discover -s tests
TOOL_OFFER_TEST_PYTHON="$(command -v python)" npm --prefix site run check
python machine/discovery.py check
python build_hosted.py
npm --prefix bridge/checkout ci
npm --prefix bridge/checkout test
npm --prefix bridge/checkout run build
```

Tests use synthetic/mocked services and require no purchases. Original-checkout suites also retain private historical fixtures; those are deliberately excluded or replaced with labeled synthetic fixtures in the curated selection. Source directories and test dependencies must be selected together; do not ship caches, `.avctl`, `.wrangler`, `.env`, databases, raw customer exports or private acceptance credentials.

External runtime services are Agentverse hosting, ASI:One/native chat, the configured extraction/conversation provider, Cloudflare Worker/Durable Objects, and (only for optional evaluation) the existing checkout/relay and FAHCE service. Configure placeholders from `.env.example` through the appropriate secret stores. Never put gateway, custody, checkout or inference credentials in public discovery. Public documentation URLs must be accessible; private/local URLs and credentials are rejected. Provider availability and wallet eligibility are not guaranteed by this repository.

## Release Workflow

Authenticate using `avctl auth login --no-browser` and existing Wrangler login. Verify `git rev-parse --show-toplevel` is this inner repository before any commit. Capture fresh authenticated hosted source into a unique ignored `data/` directory. Generate **all intended authored modules**, not only the CLI's default chat/machine pair. Preserve captured hosted entrypoints and compare every module hash with readback.

```sh
python machine/release.py capture --work data/<unique-release>
python machine/release.py generate --work data/<unique-release> --modules <reviewed-authored-module-list>
python machine/release.py check --work data/<unique-release>
python machine/release.py deploy --work data/<unique-release>
python machine/release.py verify-site --work data/<unique-release>
```

`machine/registry-server.json` is generated server metadata, not a publication receipt. Its 1.4.9 name, version and endpoint match the completed publication recorded in `machine/registry-publication.json`. Do not republish this completed version; no publisher secret belongs in a product runtime.

Build the local-only judges' selection with `python judging/package.py data/judging-<unique-name>` after building the checkout bundle. It selects exact reviewed paths, verifies protected input hashes, applies explicitly labeled synthetic substitutions, and produces a manifest and ZIP with byte readback. It never reads the private acceptance directory or publishes a repository. The extracted package includes `scripts/test_offline.py` and its validated dependency constraints.

The deployed `release_id` binds runtime source, canonical inputs and generators; `discovery-surfaces.json` inventories exact public asset hashes. Agentverse source readback—not a displayed version—establishes byte correspondence. Publication across Agentverse and Cloudflare is not atomic; failed readback means incomplete release. Keep existing 1.4.7 signed acceptance associated with its original release. The readiness source-record hash is SHA-256 of canonical retained-document JSON, distinct from a source-text byte hash.

## Attribution And Publication

Kingan Logic and FAHCE are legitimate component identities. FAHCE engine, payment/receipt/attestation services and their keys are pre-existing external components, not newly implemented by these presentation changes. This work covers Tool Offer Agent's offer preparation, evidence retention, native/machine integration, review/readiness/export, gateway and companion integration. Original commit references and private signed evidence are retained; timestamps alone do not prove hackathon eligibility or independent execution.

Do not make the existing private repository public. A reviewed, complete source selection does not erase historical disclosures or establish that a curated snapshot meets judging rules. The owner must approve the sanitized publication scope and confirm the organizer's history requirements before any public repository or submission is created.
