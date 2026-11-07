# Tool Offer Agent — public judging snapshot

Publication handoff: **November 7, 2026 UTC**. This is an owner-authorized public snapshot, not the original private development repository or its Git history. Its initial commit records publication, not the dates when the underlying work or historical transactions occurred. A later owner-authorized follow-up adds [PolyForm Noncommercial 1.0.0](LICENSE), [attribution and judging permission](NOTICE), and [third-party notices](THIRD-PARTY-NOTICES.md). It does not relicense dependencies or external services.

The **initial** public snapshot, commit `12f2362c93e88684673fdede649e88b315099ce4`, preserved all 237 prepared files byte-for-byte and added this quickstart, for 238 files. The first documentation follow-up produced 239 files. The subsequent license/feedback follow-up produces **244 files**: the three top-level guides are updated and five license/notice/feedback files are added. All 236 other initial files, including executable source, dependency locks, tests and historical evidence, are unchanged. The dated preparation reports describe their status when written; statements that publication had not occurred are historical. See [publication history](PUBLICATION-HISTORY.md) for the verified repository creation timestamp and the exact scope of each update.

## Live product and source identity

- **Tool Offer Agent 1.4.9** prepares source-attributed API/MCP offers, retains seller terms, supports correction/review/readiness and exports complete records. It does not certify sellers, grant commercial rights, publish offers or spend for a buyer.
- Native ASI:One handle: **`@tool-offer-builder`**.
- [Agentverse entry point](https://agentverse.ai/agents/details/agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a/profile).
- [Homepage](https://tooloffer.kinganlogic.com/) and [canonical machine profile](https://tooloffer.kinganlogic.com/manifest.json).
- MCP: `POST https://tooloffer.kinganlogic.com/mcp` (also `/mcp/`). REST: `POST https://tooloffer.kinganlogic.com/api/machine/{tool_name}`. See [machine access](https://tooloffer.kinganlogic.com/machine/) and [OpenAPI](https://tooloffer.kinganlogic.com/openapi.json) for identity-bound invocation; public discovery alone does not authorize calls.
- Deployed release: **`66979784d826683d48d83d6639e924078a3a3476c3ab488a93a9a57519767f19`**; Agentverse runtime **revision 86**.
- Cloudflare Worker version: `53fc2243-7f8e-4ed0-b795-8009c060a787`; deployment: `51d7a4a1-e1a3-455b-8ddd-c5f45e36bb80`.

[DEPLOYED-RELEASE.md](DEPLOYED-RELEASE.md) records deployment/readback, and `evidence/releases/revision-86/manifest.json` binds all 29 hosted Python members. The adjacent gzip contains that exact Python source, not hosted secrets or conversation storage. The application version, Git snapshot commit, hosted revision, release identifier and registry publication are distinct identities. Python wheel and companion npm package versions are historical packaging versions, not application release identifiers.

## Install and run locally

Use **Python 3.12 and Node 24** in a clean shell without production credentials. Run from this repository's root:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints-validated.txt -e '.[test]'
npm --prefix site ci
npm --prefix bridge/checkout ci
tool-offer --state data/judging-local.sqlite3 --sender judging-local --session inspect --message help
```

For the local interactive workflow, use the same isolated state and omit `--message help`:

```sh
tool-offer --state data/judging-local.sqlite3 --sender judging-local --session inspect
```

Type `help` for supported commands and `quit` to exit. Local storage is separate from production conversations. In an unconfigured clean shell, this CLI is not the hosted Agentverse/ASI service and has no production payment authority. Documentation retrieval needs suitable public URLs; provider-backed behavior requires your own configuration. Do not submit credentials in chat or documentation URLs; this project does not control ASI or other platforms' retention.

To inspect packaging without uploading or deploying:

```sh
python scripts/build_local.py
```

The local service entry point is `agent.py`; starting it or any Cloudflare/checkout service requires your own identity and appropriate configuration. Do not reuse the published production identity, private credentials or production release commands to judge this snapshot. `.env.example` has placeholders. `.avctl/config.toml` is the deliberately selected public identity/profile reference, not an authenticated account; real CLI authentication is excluded.

## Tests and integrity

These are instructions for reviewers, not a claim that publication reran the suites:

```sh
python scripts/test_offline.py
TOOL_OFFER_TEST_PYTHON="$(command -v python)" npm --prefix site run check
npm --prefix bridge/checkout test
```

Tests use synthetic/mocked services; the offline Python runner blocks external socket connections. Do not execute live acceptance, payment, deployment or external-service mutation scripts as routine tests.

**Integrity scope:** `scripts/verify_package.py` checks the original selected-file manifest, which includes the original README, and the retained revision-79 archive. That historical manifest and `evidence/publication-preparation.json` are intentionally unchanged. Running the historical verifier directly against the updated README will correctly report that selected content changed; it is not the integrity command for this documentation overlay. In a full Git clone, verify that every non-overlay file still matches the audited initial public snapshot:

```sh
git diff --exit-code 12f2362c93e88684673fdede649e88b315099ce4 -- . ':!README.md' ':!START-HERE.md' ':!PUBLICATION-HISTORY.md' ':!LICENSE' ':!NOTICE' ':!THIRD-PARTY-NOTICES.md' ':!LICENSES/Apache-2.0.txt' ':!docs/COMPETITION-FEEDBACK-2026-11-07.md'
git status --short
```

An empty diff confirms tracked non-overlay bytes match; inspect any untracked files separately. To run the original manifest verifier without changing your working tree, extract the initial public commit into a new temporary directory, using the Python environment installed above:

```sh
baseline_dir="$(mktemp -d)"
git archive 12f2362c93e88684673fdede649e88b315099ce4 | tar -x -C "$baseline_dir"
python "$baseline_dir/scripts/verify_package.py"
```

The current Git commit records the documentation/license overlay; historical inventories are not relabeled as current documentation hashes. [Publication history](PUBLICATION-HISTORY.md) lists its exact eight-path scope relative to the initial commit. These integrity checks are not a rerun of product tests or a new deployment attestation.

Retained results for the unchanged candidate: **550 Python tests with three skips**, **163 staged tests**, **51 site tests**, and clean-package **550 Python tests with the same three skips**. Deployment separately verified **29/29 hosted members**, all seven changed members, the full Agentverse profile, **108 public-surface checks** and the established non-payment signed-result/replay health check. See the dated evidence rather than treating these as fresh tests of future dependencies or services.

## Payment bridge and external services

`tool_offer_agent/` contains the agent; `site/src/` and `site/public/` contain its gateway, identity handling, Durable Objects and website/discovery outputs. The current separately maintained checkout/relay/wallet implementation is included in `bridge/checkout/`, with source provenance, lockfile and tests. `bridge/custody/` contains the custody Worker and tests. See [docs/BRIDGE.md](docs/BRIDGE.md) for the request, review, wallet authorization, retained submission, reconciliation and result boundaries.

Agentverse hosting, ASI delivery, the configured model provider, Cloudflare services, buyer wallets, Base/USDC, FAHCE execution/settlement and attestation infrastructure are separate services. FAHCE engine source and external private signing infrastructure are not included or newly claimed as this project's work. The active bridge is external x402, not native Fetch Payment Protocol. Offer preparation/readiness is free of purchases; optional evaluation requires separate explicit buyer authorization. A checkout, wallet connection, challenge or successful HTTP response is not by itself authorization, settlement or a positive determination. Never repeat an uncertain payment.

The current bridge source is provided for review; its service and the custody/FAHCE infrastructure were **not redeployed** by this correction release or this publication. No payment, key rotation, enrollment, registry publication or service deployment is part of this repository publication.

## Historical evidence and limits

- The retained **November 1, 2026** payment/service observations describe that earlier transaction and negative determination, **not a transaction on release `66979784…` or runtime revision 86**. Sanitized summaries are not the original signed receipt or a fresh execution.
- MCP Registry `com.kinganlogic/tool-offer-agent` **1.4.9** was published at **`2026-11-07T03:32:16.914361Z`**. `machine/registry-publication.json` preserves the owner-supplied official readback and its historical source correspondence. The correction release and public Git snapshot are not new registry publications.
- The **ASI delivery incident remains unresolved**: MetaConnector database-pool timeout, unconfirmed transport and absent ASI history, despite fast hosted replies and working manual Agentverse Testing. Generated replies, envelope submission, transport status and confirmed ASI display are different. See [the sanitized incident summary](docs/ASI-DELIVERY-INCIDENT-2026-11-07.md); its predeployment language is historical, not evidence that deployment fixed the incident.
- Three explicitly configured custody integration checks remain skipped. Four inherited high-severity dependency entries from the dated review and the missing `verify_new_tooloffer.mjs` harness finding remain limitations, not fixed or rerun by publication.
- Twelve public HTML comparisons required removal of the already recorded Cloudflare WebMCP insertion; 96 checks were byte-exact. Those observations do not certify the inserted script or ASI rendering.
- No credentials, private Git objects/history, raw operational logs, customer records, private purchase payloads or unrelated service implementations are selected. The bounded disclosure review is not an independent security certification. Historical commit/hash references remain attribution evidence, not imported private Git history or proof of judging eligibility.
