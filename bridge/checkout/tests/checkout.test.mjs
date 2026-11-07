import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { verifyTypedData } from "viem";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { x402Client } from "@x402/core/client";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { encodePaymentRequiredHeader } from "@x402/core/http";
import { AMOUNT, ASSET, ENDPOINT, NETWORK, RECIPIENT, authorizationTypedData } from "../payment-policy.mjs";
import { proveExpiredUnusedAuthorization } from "../expired-authorization.mjs";

// Execute the production action logic with in-memory durable storage and offline
// network/signature dependencies. No real wallet or upstream service is used.
let source = readFileSync(new URL("../checkout-worker.mjs", import.meta.url), "utf8")
  .replace('import { DurableObject } from "cloudflare:workers";', "class DurableObject {}")
  .replace('import { proveExpiredUnusedAuthorization } from "./expired-authorization.mjs";', "const proveExpiredUnusedAuthorization = state => globalThis.__checkoutOfflineReconcile(state);")
  .replace(/from "([^\"]+)"/g, (_, spec) => `from ${JSON.stringify(import.meta.resolve(spec.startsWith("./") ? "../" + spec.slice(2) : spec))}`)
  .replace(/const client = createPublicClient\([^\n]+\);/, "const client = { verifyTypedData: args => globalThis.__checkoutOfflineVerify(args) };")
  .replace(/const verifier = createPublicClient\([^\n]+\);/, "const verifier = globalThis.__checkoutOfflineClient(rpc);");
globalThis.__checkoutOfflineVerify = verifyTypedData;
globalThis.__checkoutOfflineClient = () => ({ getChainId: async () => 8453, verifyTypedData: args => globalThis.__checkoutOfflineVerify(args) });
const { FahceCheckout, FahcePaymentRelay, default: worker } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const TERMS = "a".repeat(64);
const ORIGIN = "https://checkout.example";

function fixture(t, fail = false, initialPreflight = "clear") {
  const account = privateKeyToAccount(generatePrivateKey());
  const namespace = new Map();
  const env = { FAHCE_BRIDGE_TOKEN: "test-only-server-token", CHECKOUTS: { getByName(id) {
    if (!namespace.has(id)) {
      const map = new Map();
      const ctx = { storage: {
        async get(key) { return structuredClone(map.get(key)); },
        async put(key, value) { map.set(key, structuredClone(value)); },
        async transaction(callback) {
          const before = structuredClone([...map]);
          try { return await callback(this); }
          catch (error) { map.clear(); for (const [key, value] of before) map.set(key, value); throw error; }
        },
      } };
      namespace.set(id, new FahceCheckout(ctx, env));
    }
    return namespace.get(id);
  } } };
  env.PAYMENT_RELAY = { getByName() { return new FahcePaymentRelay({}, env); } };
  const previousFetch = globalThis.fetch;
  let paidCalls = 0;
  let publishedTerms = TERMS;
  let preflightMode = initialPreflight;
  let challengeCalls = 0;
  const preflightBodies = [];
  let sentBody;
  let sentPaymentHeader;
  const required = { x402Version: 2, resource: { url: ENDPOINT, description: "Offline test", mimeType: "application/json" }, accepts: [
    { scheme: "exact", network: NETWORK, asset: ASSET, amount: AMOUNT, payTo: RECIPIENT, maxTimeoutSeconds: 3600, extra: { name: "USD Coin", version: "2" } },
  ] };
  globalThis.fetch = async (url, options) => {
    if (url.endsWith("/machines.json")) return Response.json({ legal_documents: { publication_hash: publishedTerms, urls: Object.fromEntries(["terms", "refunds", "privacy", "acceptable-use", "data-handling", "security"].map(n => [n, "https://fahce.kinganlogic.com/legal/" + n])) }, payment: { protocol: "x402-v2" }, pricing_terms: { prices: { diagnose: { atomic_units: AMOUNT, scheme: "exact" } } } });
    if (url === "https://fahce.kinganlogic.com/api/v1/machine/preflight") {
      assert.equal(options.headers.has("PAYMENT-SIGNATURE"), false);
      assert.equal(options.headers.has("Authorization"), false);
      preflightBodies.push(JSON.parse(options.body));
      if (preflightMode === "unavailable") throw Error("Offline preflight unavailable");
      if (preflightMode === "malformed") return Response.json({ syntax_valid: true });
      return Response.json({ schema: "FAHCE_MACHINE_PREFLIGHT_V1", syntax_valid: true,
        engine_executed: false, payment_authority: false, capability_screen: {
          semantic_status: preflightMode === "semantic" ? "SEMANTICALLY_UNSUPPORTED" : "NOT_ESTABLISHED",
          structural_status: preflightMode === "structural" ? "STRUCTURAL_LIMITATION" : "STRUCTURALLY_INTERPRETABLE",
          candidate_limitations: preflightMode === "semantic" ? [{ operator: "UNRECOGNIZED_PROPOSITION_FORM" }] : [],
          limitations: preflightMode === "structural" ? [{ code: "EVIDENCE_INTERPRETATION_UNAVAILABLE" }] : [],
        } });
    }
    if (url !== ENDPOINT) throw Error("Offline trust unavailable");
    if (!options.headers.has("PAYMENT-SIGNATURE")) { challengeCalls++; return Response.json({}, { status: 402, headers: { "PAYMENT-REQUIRED": encodePaymentRequiredHeader(required) } }); }
    paidCalls++; sentBody = options.body; sentPaymentHeader = options.headers.get("PAYMENT-SIGNATURE");
    await new Promise(resolve => setTimeout(resolve, 10));
    if (fail === "nonbillable") return Response.json({ error: "PAYMENT_WORK_NON_BILLABLE", request_id: "offline-request", purchase_id: "offline-purchase", receipt_id: "offline-receipt", recovery_status: "PENDING_RECONCILIATION", billing: { billable: false, free_retry: true } }, { status: 422 });
    if (fail) throw Error("Synthetic uncertain delivery");
    return Response.json({ schema: "FAHCE_MACHINE_RESPONSE_V1", operation: "diagnose", request_id: "test-only", verification: { verified: false } });
  };
  t.after(() => { globalThis.fetch = previousFetch; });
  const machine = { schema: "FAHCE_MACHINE_REQUEST_V1", candidate_output: "Offline test candidate", evidence: [] };
  const prepare = async (key = "b".repeat(64)) => worker.fetch(new Request(ORIGIN + "/v1/checkouts", { method: "POST", headers: { Authorization: "Bearer " + env.FAHCE_BRIDGE_TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ request: machine, draftHash: "c".repeat(64), checkoutKey: key }) }), env).then(r => r.json());
  const call = async (checkout, action, body, token = checkout.accessToken) => worker.fetch(new Request(ORIGIN + "/checkout/" + checkout.id + "/api/" + action, { method: body ? "POST" : "GET", headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) }), env);
  return { account, prepare, call, required, machine, env, preflightBodies, setPreflight: mode => { preflightMode = mode; },
    setPublishedTerms: hash => { publishedTerms = hash; }, challengeCalls: () => challengeCalls,
    paidCalls: () => paidCalls, sentBody: () => sentBody, sentPaymentHeader: () => sentPaymentHeader };
}

test("durable checkout allows arbitrary buyers, isolates tokens and recovers preparation", async t => {
  const f = fixture(t); const first = await f.prepare(); const repeat = await f.prepare();
  assert.equal(first.accessToken, repeat.accessToken);
  assert.equal((await f.call(first, "status").then(r => r.json())).buyer, null);
  assert.equal((await f.call(first, "status", undefined, "wrong")).status, 401);
  const second = await f.prepare("d".repeat(64));
  assert.notEqual(second.accessToken, first.accessToken);
  assert.equal((await f.call(second, "status", undefined, first.accessToken)).status, 401);
  const challenge = await f.call(first, "challenge", { buyer: f.account.address, acceptTerms: true, termsHash: TERMS }).then(r => r.json());
  assert.equal(challenge.buyer, f.account.address);
  assert.equal(f.paidCalls(), 0);
});

test("wallet authorization and exact request are submitted once under concurrent calls", async t => {
  const f = fixture(t); const checkout = await f.prepare();
  await f.call(checkout, "challenge", { buyer: f.account.address, acceptTerms: true, termsHash: TERMS });
  assert.equal((await f.call(checkout, "authorize", { buyer: privateKeyToAccount(generatePrivateKey()).address })).status, 409);
  await f.call(checkout, "authorize", { buyer: f.account.address });
  const sdk = new x402Client(); sdk.register(NETWORK, new ExactEvmScheme(f.account));
  const paymentPayload = await sdk.createPaymentPayload(f.required);
  const responses = await Promise.all([f.call(checkout, "pay", { paymentPayload }), f.call(checkout, "pay", { paymentPayload })]);
  assert.deepEqual(responses.map(r => r.status).sort(), [200, 409]);
  assert.equal(f.paidCalls(), 1);
  assert.deepEqual(JSON.parse(f.sentBody()), f.machine);
  const status = await f.call(checkout, "status").then(r => r.json());
  assert.equal(status.phase, "response_received");
  assert.equal(status.receiptProof.verified, false);
  assert.equal(status.result.verification.verified, false);
  assert.equal(status.paymentPayload, undefined);
  assert.equal(status.accessToken, undefined);
});

test("ambiguous signed delivery prevents another authorization or submission", async t => {
  const f = fixture(t, true); const checkout = await f.prepare();
  await f.call(checkout, "challenge", { buyer: f.account.address, acceptTerms: true, termsHash: TERMS });
  await f.call(checkout, "authorize", { buyer: f.account.address });
  const sdk = new x402Client(); sdk.register(NETWORK, new ExactEvmScheme(f.account));
  const paymentPayload = await sdk.createPaymentPayload(f.required);
  assert.equal((await f.call(checkout, "pay", { paymentPayload })).status, 502);
  assert.equal((await f.call(checkout, "status").then(r => r.json())).phase, "unresolved");
  assert.equal((await f.call(checkout, "challenge", { buyer: f.account.address, acceptTerms: true, termsHash: TERMS })).status, 409);
  assert.equal((await f.call(checkout, "pay", { paymentPayload })).status, 409);
  assert.equal(f.paidCalls(), 1);
});

async function expiredCheckout(testContext) {
  const setup = fixture(testContext, "nonbillable");
  const checkout = await setup.prepare();
  const storage = setup.env.CHECKOUTS.getByName(checkout.id).ctx.storage;
  await setup.call(checkout, "challenge", { buyer: setup.account.address, acceptTerms: true, termsHash: TERMS });
  await setup.call(checkout, "authorize", { buyer: setup.account.address });
  const sdk = new x402Client().register(NETWORK, new ExactEvmScheme(setup.account));
  const paymentPayload = await sdk.createPaymentPayload(setup.required);
  await setup.call(checkout, "pay", { paymentPayload });
  const retained = await storage.get("purchase");
  const now = Math.floor(Date.now() / 1000);
  retained.signedAt = new Date((now - 600) * 1000).toISOString();
  retained.paymentPayload.payload.authorization.validBefore = String(now - 60);
  retained.paymentPayload.payload.signature = await setup.account.signTypedData(authorizationTypedData(
    retained.paymentPayload.payload.authorization, setup.account.address, setup.required.accepts[0], now - 600));
  retained.pendingValidationPayload = structuredClone(retained.paymentPayload);
  retained.result.private_content_released = false;
  retained.responseText = JSON.stringify(retained.result);
  await storage.put("purchase", retained);
  const previous = globalThis.__checkoutOfflineReconcile;
  globalThis.__checkoutOfflineReconcile = state => proveExpiredUnusedAuthorization(state, { now, observe: async provider => ({
    provider: new URL(provider).hostname, chainId: 8453, finalized: true, blockNumber: "12345",
    blockHash: "0x" + "33".repeat(32), timestamp: String(now - 30), usedOrCanceled: false,
  }) });
  testContext.after(() => { globalThis.__checkoutOfflineReconcile = previous; });
  const reconcile = (token = setup.env.FAHCE_BRIDGE_TOKEN, method = "POST", expected = {}) => worker.fetch(new Request(
    ORIGIN + "/v1/diagnostics/reconcile-expired-authorization/" + checkout.id, { method,
      headers: { Authorization: "Bearer " + token }, ...(method === "POST" ? {
        body: JSON.stringify({ requestSha256: retained.requestSha256, receiptId: retained.result.receipt_id, ...expected }),
      } : {}),
    }), setup.env);
  return { setup, checkout, storage, retained, reconcile };
}

test("expired authorization diagnostic is owner-only, read-only and redacts RPC failures", async testContext => {
  const { setup, checkout, storage, retained } = await expiredCheckout(testContext);
  const inspect = (token = setup.env.FAHCE_BRIDGE_TOKEN, method = "GET") => worker.fetch(new Request(
    ORIGIN + "/v1/diagnostics/expired-authorization-proof/" + checkout.id,
    { method, headers: { Authorization: "Bearer " + token } }), setup.env);
  assert.equal((await inspect(checkout.accessToken)).status, 401);
  assert.equal((await inspect("wrong")).status, 401);
  assert.equal((await inspect(setup.env.FAHCE_BRIDGE_TOKEN, "POST")).status, 405);
  const response = await inspect();
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.readOnly, true);
  assert.equal(result.proof.outcome, "EXPIRED_UNUSED");
  assert.equal(JSON.stringify(result).includes(retained.paymentPayload.payload.signature), false);
  globalThis.__checkoutOfflineReconcile = async () => {
    throw Object.assign(Error("Sensitive RPC request contents"), { code: "EXPIRED_PROOF_RPC_1_UNAVAILABLE" });
  };
  const failure = await inspect();
  assert.equal(failure.status, 409);
  const diagnostic = await failure.json();
  assert.equal(diagnostic.code, "EXPIRED_PROOF_RPC_1_UNAVAILABLE");
  assert.equal(JSON.stringify(diagnostic).includes("Sensitive"), false);
  globalThis.__checkoutOfflineReconcile = async () => { throw Error("Sensitive upstream error"); };
  assert.equal((await inspect().then(response => response.json())).code, "EXPIRED_PROOF_UNAVAILABLE");
  assert.deepEqual(await storage.get("purchase"), retained);
  assert.equal(await storage.get("attempt:" + retained.idempotencyKey), undefined);
  assert.equal(setup.paidCalls(), 1);
});

test("owner reconciliation preserves original signed evidence and same checkout without paying", async testContext => {
  const { setup, checkout, storage, retained, reconcile } = await expiredCheckout(testContext);
  assert.equal((await reconcile(checkout.accessToken)).status, 401);
  assert.equal((await reconcile("wrong")).status, 401);
  assert.equal((await reconcile(setup.env.FAHCE_BRIDGE_TOKEN, "GET")).status, 405);
  assert.equal((await reconcile(setup.env.FAHCE_BRIDGE_TOKEN, "POST", { receiptId: "other-receipt" })).status, 409);
  assert.deepEqual(await storage.get("purchase"), retained);
  setup.setPreflight("semantic");
  const response = await reconcile();
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.reconciled, true);
  assert.equal(result.newPaymentSubmitted, false);
  assert.equal(result.phase, "input_blocked");
  const current = await storage.get("purchase");
  for (const field of ["request", "requestBytes", "requestSha256", "draftHash", "buyer", "accessToken"]) assert.deepEqual(current[field], retained[field]);
  assert.notEqual(current.idempotencyKey, retained.idempotencyKey);
  for (const field of ["paymentPayload", "pendingValidationPayload", "signedAt", "required", "responseText", "result"]) assert.equal(current[field], undefined);
  const archive = await storage.get("attempt:" + retained.idempotencyKey);
  assert.deepEqual(archive.attempt.paymentPayload, retained.paymentPayload);
  assert.deepEqual(archive.attempt.result, retained.result);
  assert.equal(archive.reconciliation.outcome, "EXPIRED_UNUSED");
  assert.equal((await reconcile()).status, 409);
  const publicStatus = await setup.call(checkout, "status").then(response => response.json());
  assert.equal(publicStatus.reconciliation.originRecoveryStatus, "PENDING_RECONCILIATION");
  assert.equal(JSON.stringify(publicStatus).includes(retained.paymentPayload.payload.signature), false);
  assert.equal((await setup.call(checkout, "pay", { paymentPayload: retained.paymentPayload })).status, 409);
  setup.setPreflight("clear");
  assert.equal((await setup.call(checkout, "preflight", {}).then(response => response.json())).phase, "ready");
  assert.equal(setup.paidCalls(), 1);
});

test("reconciliation rolls back the archive and checkout together on storage failure", async testContext => {
  const { setup, storage, retained, reconcile } = await expiredCheckout(testContext);
  const originalPut = storage.put;
  storage.put = async function (key, value) {
    if (key === "purchase") throw Error("Synthetic transaction failure");
    return originalPut.call(this, key, value);
  };
  assert.equal((await reconcile()).status, 502);
  assert.deepEqual(await storage.get("purchase"), retained);
  assert.equal(await storage.get("attempt:" + retained.idempotencyKey), undefined);
  assert.equal(setup.paidCalls(), 1);
});

test("retained signature diagnostic never unlocks, pays or exposes authorization material", async testContext => {
  const setup = fixture(testContext);
  const checkout = await setup.prepare();
  const storage = setup.env.CHECKOUTS.getByName(checkout.id).ctx.storage;
  const inspect = (token = setup.env.FAHCE_BRIDGE_TOKEN, method = "GET") => worker.fetch(new Request(
    ORIGIN + "/v1/diagnostics/validation-proof/" + checkout.id,
    { method, headers: { Authorization: "Bearer " + token } }), setup.env);
  assert.equal((await inspect()).status, 409);
  assert.equal((await inspect(checkout.accessToken)).status, 401);
  assert.equal((await inspect("wrong")).status, 401);
  assert.equal((await inspect(setup.env.FAHCE_BRIDGE_TOKEN, "POST")).status, 405);
  await setup.call(checkout, "challenge", { buyer: setup.account.address, acceptTerms: true, termsHash: TERMS });
  await setup.call(checkout, "authorize", { buyer: setup.account.address });
  const sdk = new x402Client().register(NETWORK, new ExactEvmScheme(setup.account));
  const paymentPayload = await sdk.createPaymentPayload(setup.required);
  const originalVerify = globalThis.__checkoutOfflineVerify;
  testContext.after(() => { globalThis.__checkoutOfflineVerify = originalVerify; });
  globalThis.__checkoutOfflineVerify = async () => { throw Object.assign(Error("Sensitive signature and URL"), {
    name: "HttpRequestError", status: 503, cause: Object.assign(Error("Secret RPC request"), { code: -32000 }),
  }); };
  assert.equal((await setup.call(checkout, "pay", { paymentPayload })).status, 409);
  const before = await storage.get("purchase");
  const failed = await inspect().then(response => response.json());
  assert.equal(failed.verification.valid, false);
  assert.deepEqual(failed.verification.attempts[0].causes, [{ errorClass: "HttpRequestError", httpStatus: 503 }, { errorClass: "Error", rpcCode: -32000 }]);
  assert.equal(JSON.stringify(failed).includes("Sensitive"), false);
  assert.equal(JSON.stringify(failed).includes("Secret"), false);
  globalThis.__checkoutOfflineVerify = originalVerify;
  const proof = await inspect().then(response => response.json());
  assert.equal(proof.verification.valid, true);
  assert.equal(proof.readOnly, true);
  assert.equal(proof.paidDeliveryAttempted, false);
  assert.equal(proof.checkoutUnlocked, false);
  assert.equal(JSON.stringify(proof).includes(paymentPayload.payload.signature), false);
  assert.equal(JSON.stringify(proof).includes(setup.account.address), false);
  assert.equal(JSON.stringify(proof).includes(checkout.accessToken), false);
  assert.equal(JSON.stringify(proof).includes(setup.env.FAHCE_BRIDGE_TOKEN), false);
  assert.deepEqual(await storage.get("purchase"), before);
  assert.equal(setup.paidCalls(), 0);
  await storage.put("purchase", { ...before, signedAt: new Date().toISOString() });
  assert.equal((await inspect()).status, 409);
  await storage.put("purchase", { ...before, pendingValidationPayload: { ...paymentPayload, x402Version: 1 } });
  assert.equal((await inspect()).status, 409);
  assert.equal(setup.paidCalls(), 0);
});

test("signature verification survives two rate-limited providers without skipping chain or signature checks", async testContext => {
  const setup = fixture(testContext);
  const checkout = await setup.prepare();
  await setup.call(checkout, "challenge", { buyer: setup.account.address, acceptTerms: true, termsHash: TERMS });
  await setup.call(checkout, "authorize", { buyer: setup.account.address });
  const sdk = new x402Client().register(NETWORK, new ExactEvmScheme(setup.account));
  const paymentPayload = await sdk.createPaymentPayload(setup.required);
  const originalClient = globalThis.__checkoutOfflineClient;
  testContext.after(() => { globalThis.__checkoutOfflineClient = originalClient; });
  const visited = [];
  let fallbackChain = 1;
  let fallbackValid = true;
  let allUnavailable = false;
  let signatureChecks = 0;
  globalThis.__checkoutOfflineClient = rpc => ({
    async getChainId() {
      visited.push(rpc);
      if (rpc !== "https://base.drpc.org" || allUnavailable) throw Object.assign(Error("rate limited"), { status: 429 });
      return fallbackChain;
    },
    async verifyTypedData(args) { signatureChecks++; return fallbackValid && verifyTypedData(args); },
  });
  assert.equal((await setup.call(checkout, "pay", { paymentPayload })).status, 409);
  assert.equal(signatureChecks, 0);
  assert.equal(setup.paidCalls(), 0);
  const before = await setup.env.CHECKOUTS.getByName(checkout.id).ctx.storage.get("purchase");
  const inspect = () => worker.fetch(new Request(ORIGIN + "/v1/diagnostics/validation-proof/" + checkout.id,
    { headers: { Authorization: "Bearer " + setup.env.FAHCE_BRIDGE_TOKEN } }), setup.env).then(response => response.json());
  fallbackChain = 8453;
  fallbackValid = false;
  assert.equal((await inspect()).verification.valid, false);
  fallbackValid = true;
  const proof = await inspect();
  assert.equal(proof.verification.valid, true);
  assert.deepEqual([...new Set(visited)], ["https://mainnet.base.org", "https://base-rpc.publicnode.com", "https://base.drpc.org"]);
  assert.equal(proof.verification.attempts[2].valid, true);
  allUnavailable = true;
  assert.equal((await inspect()).verification.code, "SIGNATURE_CHECK_RATE_LIMITED");
  assert.equal(setup.paidCalls(), 0);
  assert.deepEqual(await setup.env.CHECKOUTS.getByName(checkout.id).ctx.storage.get("purchase"), before);
});

async function retainedApproval(testContext, deliveryFailure = false) {
  const setup = fixture(testContext, deliveryFailure);
  const checkout = await setup.prepare();
  await setup.call(checkout, "challenge", { buyer: setup.account.address, acceptTerms: true, termsHash: TERMS });
  await setup.call(checkout, "authorize", { buyer: setup.account.address });
  const sdk = new x402Client().register(NETWORK, new ExactEvmScheme(setup.account));
  const paymentPayload = await sdk.createPaymentPayload(setup.required);
  const originalVerify = globalThis.__checkoutOfflineVerify;
  testContext.after(() => { globalThis.__checkoutOfflineVerify = originalVerify; });
  globalThis.__checkoutOfflineVerify = async () => { throw Object.assign(Error("Rate limited"), { status: 429 }); };
  assert.equal((await setup.call(checkout, "pay", { paymentPayload })).status, 409);
  globalThis.__checkoutOfflineVerify = originalVerify;
  const storage = setup.env.CHECKOUTS.getByName(checkout.id).ctx.storage;
  const retained = await storage.get("purchase");
  const approval = { submitSavedAuthorization: true, requestSha256: retained.requestSha256, acceptTerms: true, termsHash: TERMS };
  return { setup, checkout, storage, retained, paymentPayload, approval };
}

test("buyer explicitly submits the identical retained approval once, without another signature", async testContext => {
  const { setup, checkout, storage, retained, paymentPayload, approval } = await retainedApproval(testContext);
  const status = await setup.call(checkout, "status").then(response => response.json());
  assert.equal(status.savedAuthorization.canSubmit, true);
  assert.equal(status.validationFailure.code, "SIGNATURE_CHECK_RATE_LIMITED");
  assert.equal(JSON.stringify(status).includes(paymentPayload.payload.signature), false);
  assert.equal(setup.paidCalls(), 0);
  assert.equal((await setup.call(checkout, "pay", { paymentPayload })).status, 409);
  const reset = await worker.fetch(new Request(ORIGIN + "/v1/diagnostics/reconcile-validation/" + checkout.id,
    { method: "POST", headers: { Authorization: "Bearer " + setup.env.FAHCE_BRIDGE_TOKEN } }), setup.env);
  assert.equal(reset.status, 409);
  for (const invalid of [{}, { submitSavedAuthorization: false }, { acceptTerms: false }, { termsHash: "b".repeat(64) },
    { requestSha256: "a".repeat(64) }, { paymentPayload }]) {
    const body = Object.keys(invalid).length ? { ...approval, ...invalid } : {};
    assert.equal((await setup.call(checkout, "submit-saved-authorization", body)).status, 409);
  }
  assert.deepEqual(await storage.get("purchase"), retained);
  const responses = await Promise.all([setup.call(checkout, "submit-saved-authorization", approval), setup.call(checkout, "submit-saved-authorization", approval)]);
  assert.deepEqual(responses.map(response => response.status).sort(), [200, 409]);
  assert.equal(setup.paidCalls(), 1);
  assert.equal(setup.sentBody(), retained.requestBytes);
  assert.deepEqual(JSON.parse(Buffer.from(setup.sentPaymentHeader(), "base64").toString()), retained.pendingValidationPayload);
  const after = await storage.get("purchase");
  assert.deepEqual(after.paymentPayload, retained.pendingValidationPayload);
  assert.equal(after.idempotencyKey, retained.idempotencyKey);
  assert.equal(after.requestSha256, retained.requestSha256);
  assert.equal((await setup.call(checkout, "status").then(response => response.json())).savedAuthorization.canSubmit, false);
});

test("saved approval cannot bypass fresh input, policy, integrity or signature checks", async testContext => {
  const { setup, checkout, storage, retained, approval } = await retainedApproval(testContext);
  setup.setPreflight("semantic");
  assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 422);
  assert.equal((await storage.get("purchase")).phase, "unresolved");
  setup.setPreflight("clear");
  setup.setPublishedTerms("c".repeat(64));
  assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 409);
  setup.setPublishedTerms(TERMS);
  await storage.put("purchase", { ...retained, requestBytes: retained.requestBytes + " " });
  assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 409);
  await storage.put("purchase", { ...retained, request: { ...retained.request, candidate_output: "Changed input" } });
  assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 409);
  await storage.put("purchase", retained);
  globalThis.__checkoutOfflineVerify = async () => false;
  assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 409);
  assert.equal((await storage.get("purchase")).phase, "unresolved");
  assert.equal(setup.paidCalls(), 0);
});

test("expired or delivered authorizations never become eligible for saved submission", async testContext => {
  const { setup, checkout, storage, retained, approval } = await retainedApproval(testContext);
  for (const field of ["signedAt", "paymentPayload", "httpStatus", "responseText", "result", "gateway", "paymentResponse", "recoveryToken", "receiptProof", "inputRevision"]) {
    await storage.put("purchase", { ...retained, [field]: "retained evidence" });
    assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 409, field);
  }
  const expired = structuredClone(retained);
  expired.pendingValidationPayload.payload.authorization.validBefore = String(Math.floor(Date.now() / 1000) - 1);
  await storage.put("purchase", expired);
  assert.equal((await setup.call(checkout, "status").then(response => response.json())).savedAuthorization.canSubmit, false);
  assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 409);
  assert.equal(setup.paidCalls(), 0);
});

test("uncertain delivery after saved submission remains locked and never sends again", async testContext => {
  const { setup, checkout, storage, approval } = await retainedApproval(testContext, true);
  assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 502);
  assert.equal(setup.paidCalls(), 1);
  const retained = await storage.get("purchase");
  assert.ok(retained.signedAt);
  assert.equal((await setup.call(checkout, "status").then(response => response.json())).savedAuthorization.canSubmit, false);
  assert.equal((await setup.call(checkout, "submit-saved-authorization", approval)).status, 409);
  assert.deepEqual(await storage.get("purchase"), retained);
  assert.equal(setup.paidCalls(), 1);
});

test("owner payment evidence is read-only, excludes capabilities and keeps signed 422 locked", async testContext => {
  const fixtureData = fixture(testContext, "nonbillable");
  const checkout = await fixtureData.prepare();
  await fixtureData.call(checkout, "challenge", { buyer: fixtureData.account.address, acceptTerms: true, termsHash: TERMS });
  await fixtureData.call(checkout, "authorize", { buyer: fixtureData.account.address });
  const sdk = new x402Client();
  sdk.register(NETWORK, new ExactEvmScheme(fixtureData.account));
  const paymentPayload = await sdk.createPaymentPayload(fixtureData.required);
  await fixtureData.call(checkout, "pay", { paymentPayload });
  const storage = fixtureData.env.CHECKOUTS.getByName(checkout.id).ctx.storage;
  const before = await storage.get("purchase");
  const inspect = (token, method = "GET") => worker.fetch(new Request(ORIGIN + "/v1/diagnostics/payment-evidence/" + checkout.id, { method, headers: { Authorization: "Bearer " + token } }), fixtureData.env);
  assert.equal((await inspect(checkout.accessToken)).status, 401);
  assert.equal((await inspect("wrong")).status, 401);
  assert.equal((await inspect(fixtureData.env.FAHCE_BRIDGE_TOKEN, "POST")).status, 405);
  const response = await inspect(fixtureData.env.FAHCE_BRIDGE_TOKEN);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  const evidence = await response.json();
  assert.deepEqual(evidence.authorization, paymentPayload.payload.authorization);
  assert.equal(evidence.phase, "unresolved");
  assert.equal(evidence.httpStatus, 422);
  assert.equal(evidence.reconciliationEligibility.idempotencyFormat, "uuid");
  assert.equal(evidence.origin.billable, false);
  assert.equal(evidence.origin.recoveryStatus, "PENDING_RECONCILIATION");
  assert.equal(evidence.gateway, null);
  assert.equal(JSON.stringify(evidence).includes(paymentPayload.payload.signature), false);
  assert.equal(JSON.stringify(evidence).includes(checkout.accessToken), false);
  assert.equal(JSON.stringify(evidence).includes(fixtureData.env.FAHCE_BRIDGE_TOKEN), false);
  assert.deepEqual(await storage.get("purchase"), before);
  const reconcile = await worker.fetch(new Request(ORIGIN + "/v1/diagnostics/reconcile-validation/" + checkout.id, { method: "POST", headers: { Authorization: "Bearer " + fixtureData.env.FAHCE_BRIDGE_TOKEN } }), fixtureData.env);
  assert.equal(reconcile.status, 409);
  assert.equal((await fixtureData.call(checkout, "challenge", { buyer: fixtureData.account.address, acceptTerms: true, termsHash: TERMS })).status, 409);
  assert.equal((await fixtureData.call(checkout, "pay", { paymentPayload })).status, 409);
  assert.deepEqual(await storage.get("purchase"), before);
  assert.equal(fixtureData.paidCalls(), 1);
});

for (const failure of ["semantic", "structural", "unavailable", "malformed"]) {
  test("free preflight blocks " + failure + " before challenge or authorization", async testContext => {
    const setup = fixture(testContext, false, failure);
    const checkout = await setup.prepare();
    const status = await setup.call(checkout, "status").then(response => response.json());
    assert.equal(status.phase, "input_blocked");
    assert.equal(status.preflight.billabilityGuaranteed, false);
    assert.equal(status.preflight.requestSha256, checkout.requestSha256);
    assert.equal(status.candidate, setup.machine.candidate_output);
    assert.deepEqual(setup.preflightBodies[0], { operation: "diagnose", request: setup.machine });
    assert.equal((await setup.call(checkout, "challenge", { buyer: setup.account.address, acceptTerms: true, termsHash: TERMS })).status, 422);
    assert.equal((await setup.call(checkout, "authorize", { buyer: setup.account.address })).status, 409);
    assert.equal((await setup.call(checkout, "pay", {})).status, 409);
    assert.equal(setup.challengeCalls(), 0);
    assert.equal(setup.paidCalls(), 0);
    setup.setPreflight("clear");
    const refreshed = await setup.call(checkout, "preflight", {}).then(response => response.json());
    assert.equal(refreshed.phase, "ready");
    assert.equal(refreshed.preflight.status, "NO_KNOWN_BLOCKER");
    assert.equal(refreshed.note, null);
    assert.equal(setup.challengeCalls(), 0);
  });
}

test("preflight is rechecked before wallet authorization when engine capability changes", async testContext => {
  const setup = fixture(testContext);
  const checkout = await setup.prepare();
  assert.equal((await setup.call(checkout, "challenge", { buyer: setup.account.address, acceptTerms: true, termsHash: TERMS })).status, 200);
  setup.setPreflight("semantic");
  assert.equal((await setup.call(checkout, "authorize", { buyer: setup.account.address })).status, 422);
  const state = await setup.env.CHECKOUTS.getByName(checkout.id).ctx.storage.get("purchase");
  assert.equal(state.phase, "input_blocked");
  assert.equal(state.required, undefined);
  assert.equal(state.paymentPayload, undefined);
  assert.equal(setup.paidCalls(), 0);
});

test("free preflight cannot reset active or signed attempts", async testContext => {
  const setup = fixture(testContext);
  const checkout = await setup.prepare();
  const storage = setup.env.CHECKOUTS.getByName(checkout.id).ctx.storage;
  const initial = await storage.get("purchase");
  const callsBefore = setup.preflightBodies.length;
  for (const phase of ["awaiting_wallet", "validating_authorization", "submitting", "unresolved", "response_received"]) {
    const retained = { ...initial, phase, note: "Retain existing payment evidence", signedAt: "2026-10-31T21:41:12.180Z" };
    await storage.put("purchase", retained);
    assert.equal((await setup.call(checkout, "preflight", {})).status, 409);
    await setup.prepare();
    assert.deepEqual(await storage.get("purchase"), retained);
  }
  assert.equal(setup.preflightBodies.length, callsBefore);
  assert.equal(setup.paidCalls(), 0);
});

async function proposeInput(fixture, checkout, changes = {}, token = fixture.env.FAHCE_BRIDGE_TOKEN) {
  const body = { requestSha256: checkout.requestSha256, candidate: "Revised offline candidate", summary: "Same terms, revised presentation.", ...changes };
  return worker.fetch(new Request(ORIGIN + "/v1/diagnostics/propose-input-revision/" + checkout.id,
    { method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" }, body: JSON.stringify(body) }), fixture.env);
}
async function prepareReview(fixture) {
  const checkout = await fixture.prepare();
  fixture.setPreflight("clear");
  assert.equal((await proposeInput(fixture, checkout)).status, 200);
  const status = await fixture.call(checkout, "status").then(response => response.json());
  return { checkout, status, approval: { acceptRevision: true, sourceRequestSha256: status.requestSha256, requestSha256: status.inputRevision.requestSha256 } };
}

test("input revision requires owner authority, original binding and valid complete input", async context => {
  const fixtureValue = fixture(context, false, "semantic");
  const checkout = await fixtureValue.prepare();
  assert.equal((await proposeInput(fixtureValue, checkout, {}, checkout.accessToken)).status, 401);
  assert.equal((await proposeInput(fixtureValue, checkout, { requestSha256: "0".repeat(64) })).status, 409);
  assert.equal((await proposeInput(fixtureValue, checkout, { candidate: "" })).status, 400);
  assert.equal((await proposeInput(fixtureValue, checkout)).status, 422);
  const status = await fixtureValue.call(checkout, "status").then(response => response.json());
  assert.equal(status.phase, "input_blocked");
  assert.equal(status.requestSha256, checkout.requestSha256);
  assert.equal(status.inputRevision, null);
  assert.equal(fixtureValue.paidCalls(), 0);
});

test("staging is idempotent, keeps original bytes and evidence, and blocks payment before review", async context => {
  const fixtureValue = fixture(context, false, "semantic");
  const { checkout, status } = await prepareReview(fixtureValue);
  assert.equal(status.phase, "input_review");
  assert.equal(status.candidate, fixtureValue.machine.candidate_output);
  assert.equal(status.requestSha256, checkout.requestSha256);
  assert.deepEqual(fixtureValue.preflightBodies.at(-1).request.evidence, fixtureValue.machine.evidence);
  assert.equal((await proposeInput(fixtureValue, checkout)).status, 200);
  assert.equal((await proposeInput(fixtureValue, checkout, { candidate: "Different proposal" })).status, 409);
  for (const action of ["challenge", "authorize", "pay", "preflight"]) {
    assert.equal((await fixtureValue.call(checkout, action, { buyer: fixtureValue.account.address, acceptTerms: true, termsHash: TERMS })).status, 409);
  }
  assert.equal(fixtureValue.challengeCalls(), 0);
  assert.equal(fixtureValue.paidCalls(), 0);
});

test("explicit exact revision acceptance archives original and preserves link, buyer, draft and evidence", async context => {
  const fixtureValue = fixture(context, false, "semantic");
  const { checkout, approval } = await prepareReview(fixtureValue);
  const storage = fixtureValue.env.CHECKOUTS.getByName(checkout.id).ctx.storage;
  const before = await storage.get("purchase");
  for (const invalid of [{ ...approval, acceptRevision: false }, { ...approval, sourceRequestSha256: "0".repeat(64) }, { ...approval, requestSha256: "0".repeat(64) }]) {
    assert.equal((await fixtureValue.call(checkout, "accept-input-revision", invalid)).status, 409);
  }
  const response = await fixtureValue.call(checkout, "accept-input-revision", approval);
  assert.equal(response.status, 200);
  const status = await response.json();
  const after = await storage.get("purchase");
  assert.equal(status.phase, "ready");
  assert.equal(status.requestSha256, approval.requestSha256);
  assert.equal(status.representationRevision.sourceRequestSha256, checkout.requestSha256);
  assert.equal(status.representationRevision.evidenceUnchanged, true);
  assert.equal(status.inputRevision, null);
  assert.equal(after.accessToken, before.accessToken);
  assert.equal(after.buyer, before.buyer);
  assert.equal(after.draftHash, before.draftHash);
  assert.notEqual(after.idempotencyKey, before.idempotencyKey);
  assert.deepEqual(after.request.evidence, before.request.evidence);
  assert.deepEqual(await storage.get(after.previousInputKeys[0]), before);
  assert.equal(after.paymentPayload, undefined);
  assert.equal(after.required, undefined);
  assert.equal(fixtureValue.paidCalls(), 0);
  assert.equal(fixtureValue.challengeCalls(), 0);
  assert.equal((await fixtureValue.call(checkout, "accept-input-revision", approval)).status, 409);
});

test("revision acceptance rechecks preflight and leaves original active when unavailable", async context => {
  const fixtureValue = fixture(context, false, "semantic");
  const { checkout, approval } = await prepareReview(fixtureValue);
  fixtureValue.setPreflight("unavailable");
  assert.equal((await fixtureValue.call(checkout, "accept-input-revision", approval)).status, 422);
  const status = await fixtureValue.call(checkout, "status").then(response => response.json());
  assert.equal(status.phase, "input_review");
  assert.equal(status.requestSha256, checkout.requestSha256);
  assert.equal(status.inputRevision.preflight.status, "UNAVAILABLE");
  assert.equal(fixtureValue.paidCalls(), 0);
});

test("input revision refuses retained signatures, delivery or unreconciled archived attempts", async context => {
  const fixtureValue = fixture(context, false, "semantic");
  const checkout = await fixtureValue.prepare();
  const storage = fixtureValue.env.CHECKOUTS.getByName(checkout.id).ctx.storage;
  const clean = await storage.get("purchase");
  const dangerous = [{ signedAt: "earlier" }, { paymentPayload: {} }, { pendingValidationPayload: {} }, { responseText: "received" },
    { gateway: {} }, { receiptProof: {} }, { result: {} }, { recoveryToken: "test-only" }, { previousAttemptKeys: ["unreconciled"] }];
  for (const extra of dangerous) {
    await storage.put("purchase", { ...clean, ...extra });
    assert.equal((await proposeInput(fixtureValue, checkout)).status, 409);
  }
  await storage.put("purchase", clean);
  fixtureValue.setPreflight("clear");
  assert.equal((await proposeInput(fixtureValue, checkout)).status, 200);
  assert.equal(fixtureValue.paidCalls(), 0);
});

test("concurrent input acceptance commits once and transaction failure preserves original", async context => {
  const fixtureValue = fixture(context, false, "semantic");
  const { checkout, approval } = await prepareReview(fixtureValue);
  const storage = fixtureValue.env.CHECKOUTS.getByName(checkout.id).ctx.storage;
  const originalPut = storage.put.bind(storage);
  storage.put = async (key, value) => {
    if (key === "purchase" && value.phase === "ready") throw Error("Synthetic storage failure");
    return originalPut(key, value);
  };
  assert.equal((await fixtureValue.call(checkout, "accept-input-revision", approval)).status, 502);
  assert.equal((await storage.get("purchase")).requestSha256, checkout.requestSha256);
  storage.put = originalPut;
  const responses = await Promise.all([fixtureValue.call(checkout, "accept-input-revision", approval), fixtureValue.call(checkout, "accept-input-revision", approval)]);
  assert.deepEqual(responses.map(response => response.status).sort(), [200, 409]);
  assert.equal(fixtureValue.paidCalls(), 0);
});

test("accepted revision sends only the reviewed request once after separate terms and wallet approval", async context => {
  const fixtureValue = fixture(context, false, "semantic");
  fixtureValue.machine.evidence.push({ id: "offline-doc", source_label: "Synthetic documentation", text: "Unchanged source evidence" });
  const { checkout, approval } = await prepareReview(fixtureValue);
  assert.equal((await fixtureValue.call(checkout, "accept-input-revision", approval)).status, 200);
  assert.equal(fixtureValue.paidCalls(), 0);
  assert.equal((await fixtureValue.call(checkout, "challenge", { buyer: fixtureValue.account.address, acceptTerms: false, termsHash: TERMS })).status, 400);
  assert.equal((await fixtureValue.call(checkout, "challenge", { buyer: fixtureValue.account.address, acceptTerms: true, termsHash: TERMS })).status, 200);
  assert.equal((await fixtureValue.call(checkout, "authorize", { buyer: fixtureValue.account.address })).status, 200);
  const sdk = new x402Client();
  sdk.register(NETWORK, new ExactEvmScheme(fixtureValue.account));
  const paymentPayload = await sdk.createPaymentPayload(fixtureValue.required);
  const results = await Promise.all([
    fixtureValue.call(checkout, "pay", { paymentPayload }),
    fixtureValue.call(checkout, "pay", { paymentPayload }),
  ]);
  assert.deepEqual(results.map(response => response.status).sort(), [200, 409]);
  assert.equal(fixtureValue.paidCalls(), 1);
  assert.deepEqual(JSON.parse(fixtureValue.sentBody()), { ...fixtureValue.machine, candidate_output: "Revised offline candidate" });
  const status = await fixtureValue.call(checkout, "status").then(response => response.json());
  assert.equal(status.phase, "response_received");
  assert.equal(status.requestSha256, approval.requestSha256);
  assert.equal(status.representationRevision.sourceRequestSha256, checkout.requestSha256);
  assert.equal(status.result.verification.verified, false);
  assert.equal(status.paymentPayload, undefined);
});
