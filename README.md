# Tool Offer Agent

**Turn public API/MCP documentation and your seller terms into a source-attributed offer draft you can review, correct, assess and export.** Tool Offer Agent is by Kingan Logic; this public judging repository is maintained under the GitHub organization **Max-ROI-LLCt**.

## Try It In ASI:One

Open [Tool Offer Agent](https://tooloffer.kinganlogic.com/), choose **Launch Agent**, and send **`start`** to **`@tool-offer-builder`**. Choose **Start with my tool**, supply public documentation and the requested seller terms, then ask for **`draft`**, **`review intake`**, **`readiness`** or **`buyer explanation`**. **Try a fictional example** is a restricted demonstration, not a live Parcel API or permission to sell it.

- [Native Agentverse profile](https://agentverse.ai/agents/details/agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a/profile)
- Agent address: `agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a`
- **For code review and local setup:** [Start here](START-HERE.md), [source layout](#source-layout), [dated verification and publication history](PUBLICATION-HISTORY.md).

**Known live limitation:** ASI:One delivery remains under investigation. Some requests stay on “Reasoning…” despite generated hosted replies; Agentverse manual Testing returned responses. A read receipt or outgoing envelope is not confirmed ASI display. Use the included local instructions to inspect the implementation; this documentation update does not resolve or conceal the [delivery incident](docs/ASI-DELIVERY-INCIDENT-2026-11-07.md).

## Feedback Into Corrections

Testers reported an introductory-only natural-language readiness response, intake review opening a blank replacement form, and crowded draft headings. The corrected agent routes supported readiness requests to the substantive assessment, displays retained intake with a correction/cancellation path, and separates draft headings and fields. Identical replacements preserve revision; fictional restrictions remain enforced. [The dated correction report](docs/CORRECTIONS-2026-11-07.md) explains the routing, parsing, review and evidence changes and their checks.

**Deployed product:** Tool Offer Agent **1.4.9**, Agentverse **revision 86**, release **`66979784d826683d48d83d6639e924078a3a3476c3ab488a93a9a57519767f19`**. [Deployment evidence](DEPLOYED-RELEASE.md) is separate from registry publication and this public Git history. Below, “later local source corrections are not thereby deployed” describes the limits of the historical registry receipt, not the status of revision 86.

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

The dedicated MCP Registry publisher authenticates publication only. Its credentials and signing infrastructure are separate from product runtimes and from FAHCE execution, receipts and attestations. Registry publication does not certify an offer or authorize a purchase. No operator credentials or signing material are needed for public code review.

The official Registry identity `com.kinganlogic/tool-offer-agent` was published as 1.4.9 at `2026-11-07T03:32:16.914361Z`, active/latest at the verified post-publication readback. Publication is complete. `machine/registry-publication.json` records the owner-supplied official readback and baseline source correspondence; later local corrections are not thereby deployed. Publication does not guarantee indexing, adoption, certification or hackathon acceptance.

## Source Layout

- `tool_offer_agent/`: Python runtime, retained evidence, restrictions, cards, readiness and native/machine operations.
- `machine/contract.json`, `machine/public-profile.txt`, `machine/public-profile.json`, `machine/guide.txt`: canonical release inputs. `machine/release.py`, `machine/discovery.py`, `machine/surfaces.py`: release generation, mirror consistency and public-asset inventory.
- `site/src/`: existing Cloudflare gateway, identity registry, signing and HTTP routes. `site/public/`: authored homepage/styles/assets plus generated profiles, examples, schemas and instructions.
- `bridge/custody/` and `tool_offer_agent/cloudflare_custody.py`: separate seller-side custody Worker, tests and Python client.
- **Current checkout/relay/wallet:** `bridge/checkout/` contains the reviewed companion implementation, dependency lockfile, tests and provenance. It connects to separate wallet, custody and FAHCE services; this correction release did not redeploy those services. See [the bridge architecture](docs/BRIDGE.md).
- `tests/`, `site/tests/`: regression suites. `build_hosted.py`: flat Agentverse packaging; its Python manifest does not describe the complete system.
- `docs/RELEASE-READINESS.md`: retained historical readiness report. [Publication history](PUBLICATION-HISTORY.md) explains which later deployment/publication records supersede its status language without rewriting its evidence.

## Setup And Tests

Use Python 3.12 and Node 24. Python package metadata remains at its historical packaging version; the product release version is `machine/contract.json` and generated runtime constants, not the wheel filename.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints-validated.txt -e '.[test]'
npm --prefix site ci
npm --prefix bridge/checkout ci
tool-offer --state data/judging-local.sqlite3 --sender judging-local --session inspect --message help
python scripts/test_offline.py
TOOL_OFFER_TEST_PYTHON="$(command -v python)" npm --prefix site run check
npm --prefix bridge/checkout test
```

Tests use synthetic/mocked services and require no purchases. The selected fixtures are explicitly labeled where synthetic. `.avctl/config.toml` is intentionally included as a **public identity/profile reference**, not authenticated CLI state; `.env.example` contains placeholders. Real authentication, `.env` files, private caches, databases and raw customer exports are not part of the judging snapshot. Configure your own identity for a separately hosted instance; do not reuse production credentials or deploy merely to review the code.

**Already completed for the unchanged executable candidate:** 550 Python tests with three skips, 163 staged tests, 51 site tests, and clean-package 550 Python tests with the same three skips. [The dated report](docs/CORRECTIONS-2026-11-07.md) and [deployment readback](evidence/deployed-corrections.json) record their scope. These are retained results, not fresh tests from this documentation commit. No GitHub Actions run was present at the November 7 publication review; no green CI result is claimed.

External runtime services are Agentverse hosting, ASI:One/native chat, the configured extraction/conversation provider, Cloudflare Worker/Durable Objects, and (only for optional evaluation) the existing checkout/relay and FAHCE service. Configure placeholders from `.env.example` through the appropriate secret stores. Never put gateway, custody, checkout or inference credentials in public discovery. Public documentation URLs must be accessible; private/local URLs and credentials are rejected. Provider availability and wallet eligibility are not guaranteed by this repository.

## Attribution, History And Limits

This is the **owner-authorized public judging snapshot** of Tool Offer Agent, not a publication of the private development repository. The GitHub repository was created on **November 7, 2026 at 07:44:32 UTC**. Its initial snapshot commit was created locally at **07:38:42 UTC** before that repository was created. [Publication history](PUBLICATION-HISTORY.md) distinguishes those timestamps from deployment, tests and historical transactions; they are not independent proof of original development dates or organizer eligibility.

Tool Offer Agent's reviewed contribution covers offer preparation, source attribution, retained intake, native/machine integration, correction, readiness, exports, its gateway and companion integration. Kingan Logic branding and the external FAHCE engine/payment/receipt/attestation infrastructure pre-exist these corrections; the repository does not claim to implement those external services. The **November 1, 2026** transaction evidence remains historical, not a transaction on revision 86. No license is added or changed by this publication.

The ASI delivery incident, **three skipped custody integration checks**, **four inherited high-severity dependency entries** from the dated review and missing `verify_new_tooloffer.mjs` harness remain explicit limitations. Source inspection and local tests do not certify live delivery, service execution, commercial rights or hackathon acceptance. Do not submit credentials in chat or documentation URLs; we do not control retention by ASI or other platform components.

Future updates are separately reviewed, owner-approved snapshots, not an automatic mirror of private working files. Historical manifests and frozen ZIPs remain unchanged; [the quickstart](START-HERE.md#tests-and-integrity) explains integrity checks after this documentation-only update.
