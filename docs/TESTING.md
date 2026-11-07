# Credential-free reproduction

Use Python 3.12 and Node 24 in a disposable extracted package. Dependency installation needs package-registry access; tests require no production credentials, purchases or inference. Do not run Node tests before the Python install completes: the signature cross-check intentionally invokes the real Python SDK.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c constraints-validated.txt '.[test]'
.venv/bin/python scripts/verify_package.py
.venv/bin/python scripts/build_local.py
.venv/bin/python scripts/test_offline.py
npm --prefix site ci
TOOL_OFFER_TEST_PYTHON="$PWD/.venv/bin/python" NODE_OPTIONS="--import=$PWD/scripts/no-external-network.cjs" npm --prefix site run check
npm --prefix bridge/checkout ci
NODE_OPTIONS="--import=$PWD/scripts/no-external-network.cjs" npm --prefix bridge/checkout test
node --test bridge/custody/custody.test.mjs
npm --prefix bridge/checkout run build
```

If your Python distribution omits ensurepip, install its venv support or use a trusted existing pip with `--python` targeting that venv. Never substitute unsupported Python 3.14 for the declared Python range.

The package's integrity verifier checks every selected file plus the protected historical revision-79 source archive. Its hashes are integrity records, not external attestations. Run integrity before modifying package source. The local hosted builder never uploads or deploys.

Current measured results and deployment identity are in `docs/RELEASE-READINESS.md` and `evidence/release-1.4.9-summary.json`. Three Python custody tests skip without an explicitly configured local Wrangler endpoint/token. Five separate synthetic SQLite custody tests run without that endpoint. Skips do not establish live custody acceptance. Historical evidence describes only its stated revision; there is no new payment or native authenticated ASI rendering claim.

Known wallet dependency advisories remain open. Test success does not fix an advisory. The separate original checkout includes five FAHCE engine-grammar tests that are deliberately outside this checkout-only package; private engine repair scripts and purchase records are not needed for the included runtime.
