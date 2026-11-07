# Tool Offer Agent — deployed correction release

Deployment completed November 7, 2026 UTC. This deployment note supplements the exact tested source selection; it does not rewrite its historical implementation reports or publication evidence.

## Current deployment

- Public product/application version: **Tool Offer Agent 1.4.9**.
- Release identifier: `66979784d826683d48d83d6639e924078a3a3476c3ab488a93a9a57519767f19`.
- Agentverse runtime revision: **86**, compiled and running at authenticated readback.
- Hosted code digest: `069ccf5af608fe56605d350725fb61122a96746e9ee20ac90e48fb9420b4f437`.
- Cloudflare Worker: `kingan-tooloffer-site`.
- Worker version: `53fc2243-7f8e-4ed0-b795-8009c060a787`.
- Production deployment: `51d7a4a1-e1a3-455b-8ddd-c5f45e36bb80`, 100% traffic, created `2026-11-07T06:57:12.860474Z`.
- All 29 hosted Python members match the tested candidate. Full Agentverse profile and website/discovery outputs match the same release. No candidate runtime or website changes remain undeployed.

`evidence/deployed-corrections.json` is the sanitized, unsigned engineering verification record. `evidence/releases/revision-86/hosted-source.json.gz` retains the exact deployed Python source, excluding the hosted environment; its adjacent manifest records every member hash. Those files are not a new registry receipt or an independent attestation.

The separate registry publication remains `com.kinganlogic/tool-offer-agent` **1.4.9**, published `2026-11-07T03:32:16.914361Z`, active/latest at the owner-supplied official readback. Its historical source correspondence is retained in `machine/registry-publication.json`. This correction deployment did not republish, reenroll or rotate keys.

## Tested package and publication preparation

The immutable tested source archive is `judging-corrections-20261107-final.zip`, SHA-256 `ff48375c18cc16e5071541e5fbbf8b9bfdd91456c8dc336eb55f85ba9a5367e3`.

This prepared directory preserves every file from that archive byte-for-byte and adds only the explicit deployment supplements inventoried by `evidence/publication-preparation.json`. The original `evidence/package-manifest.json` continues to describe its 231 selected files. The supplemental inventory records the original package manifest and the deployment additions without relabeling either. No production source edits were needed during deployment, so there is no replacement tested archive.

The source was tested as a working-tree candidate based on commit `03c58e64c890b53bdcc9b003de42f8d3567eb403`; that commit is not claimed to contain these uncommitted corrections. No Git repository or original private Git history is included, and no source publication has occurred.

`docs/CORRECTIONS-2026-11-07.md` and `docs/RELEASE-READINESS.md` retain their predeployment/historical scope. Where they describe this candidate as local or undeployed, this later deployment record supplies its current status; it does not turn historical tests into fresh live acceptance.

## Run and service boundaries

Follow **Setup And Tests** in `README.md` for Python 3.12, Node 24, installation and synthetic tests. `scripts/test_offline.py` and `constraints-validated.txt` provide the retained offline-check path. These installation/test commands do not establish live hosting or purchase authorization.

- `tool_offer_agent/`, hosted build tooling and the revision-86 source archive cover the agent implementation. Agentverse hosting and ASI:One delivery are separate platform services; a local process is not the deployed agent.
- `site/src/` and `site/public/` contain the Cloudflare gateway, identity handling, Durable Object implementation and matching website/discovery assets. Existing production bindings and migration state were preserved, not reset.
- `bridge/checkout/` contains the current reviewed checkout/relay/wallet implementation, dependencies, tests and bundle provenance. `bridge/custody/` contains the separate custody Worker and tests. See `docs/BRIDGE.md` for boundaries and setup. Neither service was redeployed by this correction release.
- The extraction/conversation provider is separately configured. FAHCE execution and settlement infrastructure are external, not source implementations supplied here. No FAHCE or purchase calls were executed during deployment checks.
- `.env.example` contains placeholders only. The selected `.avctl/config.toml` is a public identity/profile reference, not authentication. Actual `.avctl` credentials, `.wrangler` state, private keys, databases, customer exports and operational logs are excluded.
- Configure your own local environment and authorized service accounts. Production addresses identify the verified deployment; they are not permission to overwrite it or a substitute for private credentials. Do not run production release or payment commands merely to inspect or judge the source.

## Completed checks and remaining limitations

- Prior exact-byte candidate tests: 550 Python tests, three skips; 163 staged tests; 51 site tests; clean package 550 Python tests with the same three skips. No broad suite was repeated for deployment because selected source bytes were unchanged.
- Deployment checks: all 29 hosted members verified; 108 public path/mode checks passed; full public Agentverse JSON profile matched; one isolated, signed `get_status` operation and same-request replay passed with zero model, payment or FAHCE calls. Existing client credentials were reused unchanged.
- Twelve HTML checks include the previously recorded Cloudflare WebMCP script insertion. Removing only that exact insertion gives the candidate bytes. Script execution and ASI display were not certified by these readbacks.
- Startup and post-health runtime logs showed no error/warning/exception matches in the inspected postdeployment window. This bounded observation is not a guarantee of future service availability.
- The three explicitly configured local-Wrangler custody checks remain skipped. The inherited outer-wallet dependency advisory and missing `verify_new_tooloffer.mjs` failure remain unresolved.
- The separate ASI database-pool/history-delivery incident remains unresolved. Signed machine completion, generated replies and transport status are not proof of ASI history persistence or display.
- This directory is prepared for a separate judging repository, not published. Original repository visibility and private history remain unchanged; organizer/history and owner disclosure decisions are not presumed approved.
