import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { AMOUNT, ASSET, ENDPOINT, NETWORK, RECIPIENT, authorizationTypedData, stableJson } from "../payment-policy.mjs";
import { proveExpiredUnusedAuthorization } from "../expired-authorization.mjs";

const now = 1800000000;
const providers = ["base-mainnet.g.alchemy.com", "base-rpc.publicnode.com"];

async function retainedAttempt() {
  const account = privateKeyToAccount(generatePrivateKey());
  const request = { schema: "FAHCE_MACHINE_REQUEST_V1", candidate_output: "Test offer", evidence: [] };
  const requestBytes = stableJson(request);
  const accepted = { scheme: "exact", network: NETWORK, asset: ASSET, amount: AMOUNT, payTo: RECIPIENT,
    maxTimeoutSeconds: 3600, extra: { name: "USD Coin", version: "2" } };
  const required = { x402Version: 2, resource: { url: ENDPOINT }, accepts: [accepted] };
  const authorization = { from: account.address, to: RECIPIENT, value: AMOUNT, validAfter: "0",
    validBefore: String(now - 60), nonce: "0x" + "11".repeat(32) };
  const signature = await account.signTypedData(authorizationTypedData(authorization, account.address, accepted, now - 600));
  const paymentPayload = { x402Version: 2, resource: required.resource, accepted, payload: { authorization, signature } };
  const result = { error: "PAYMENT_WORK_NON_BILLABLE", request_id: "request-test", receipt_id: "receipt-test",
    purchase_id: "purchase-test", private_content_released: false, billing: { billable: false }, recovery_status: "PENDING_RECONCILIATION" };
  return { phase: "unresolved", httpStatus: 422, signedAt: new Date((now - 600) * 1000).toISOString(),
    idempotencyKey: "12345678-1234-1234-1234-123456789abc", buyer: account.address,
    request, requestBytes, requestSha256: createHash("sha256").update(requestBytes).digest("hex"),
    required, paymentPayload, pendingValidationPayload: structuredClone(paymentPayload), result, responseText: JSON.stringify(result) };
}

function observation(provider) {
  return { provider: new URL(provider).hostname, chainId: 8453, finalized: true, blockNumber: "12345",
    blockHash: "0x" + "33".repeat(32), timestamp: String(now - 30), usedOrCanceled: false };
}

test("two finalized observations establish expired-unused without changing the original attempt", async () => {
  const state = await retainedAttempt();
  const original = structuredClone(state);
  const calls = [];
  const proof = await proveExpiredUnusedAuthorization(state, { now, observe: async (provider, authorization) => {
    calls.push(new URL(provider).hostname);
    assert.deepEqual(authorization, state.paymentPayload.payload.authorization);
    return observation(provider);
  } });
  assert.deepEqual(calls, providers);
  assert.equal(proof.outcome, "EXPIRED_UNUSED");
  assert.equal(proof.requestSha256, state.requestSha256);
  assert.equal(proof.observations.length, 2);
  assert.equal(JSON.stringify(proof).includes(state.paymentPayload.payload.signature), false);
  assert.equal(JSON.stringify(proof).includes(state.buyer), false);
  assert.deepEqual(state, original);
});

for (const scenario of ["active", "completed", "billable", "released", "gateway", "response-header", "recovery", "missing-receipt", "different-input", "different-response", "different-authorization", "unexpired"]) {
  test("keeps " + scenario + " attempt locked before observing chain state", async () => {
    const state = await retainedAttempt();
    if (scenario === "active") state.phase = "submitting";
    if (scenario === "completed") state.httpStatus = 200;
    if (scenario === "billable") state.result.billing.billable = true;
    if (scenario === "released") state.result.private_content_released = true;
    if (scenario === "gateway") state.gateway = { success: true };
    if (scenario === "response-header") state.paymentResponse = "retained-header";
    if (scenario === "recovery") state.recoveryToken = "retained-capability";
    if (scenario === "missing-receipt") delete state.result.receipt_id;
    if (scenario === "different-input") state.requestBytes += " ";
    if (scenario === "different-response") state.responseText = "{}";
    if (scenario === "different-authorization") state.pendingValidationPayload.payload.authorization.nonce = "0x" + "44".repeat(32);
    if (scenario === "unexpired") {
      state.paymentPayload.payload.authorization.validBefore = String(now + 60);
      state.pendingValidationPayload = structuredClone(state.paymentPayload);
    }
    let observed = false;
    await assert.rejects(proveExpiredUnusedAuthorization(state, { now, observe: async () => { observed = true; throw Error("Unexpected RPC"); } }));
    assert.equal(observed, false);
  });
}

for (const scenario of ["used", "pre-expiry", "future-block", "unfinalized", "wrong-chain", "wrong-provider", "invalid-hash", "unavailable"]) {
  test("does not reconcile when one provider reports " + scenario, async () => {
    const state = await retainedAttempt();
    const original = structuredClone(state);
    await assert.rejects(proveExpiredUnusedAuthorization(state, { now, observe: async provider => {
      const result = observation(provider);
      if (result.provider === providers[1]) {
        if (scenario === "used") result.usedOrCanceled = true;
        if (scenario === "pre-expiry") result.timestamp = String(now - 61);
        if (scenario === "future-block") result.timestamp = String(now + 1);
        if (scenario === "unfinalized") result.finalized = false;
        if (scenario === "wrong-chain") result.chainId = 1;
        if (scenario === "wrong-provider") result.provider = providers[0];
        if (scenario === "invalid-hash") result.blockHash = "not-a-hash";
        if (scenario === "unavailable") throw Error("Offline RPC failure");
      }
      return result;
    } }));
    assert.deepEqual(state, original);
  });
}
