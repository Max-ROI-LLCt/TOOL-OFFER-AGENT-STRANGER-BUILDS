import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { request as httpRequest } from "node:http";
import test from "node:test";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { verifyTypedData } from "viem";
import { x402Client } from "@x402/core/client";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { encodePaymentRequiredHeader, encodePaymentResponseHeader } from "@x402/core/http";
import { AMOUNT, ASSET, ENDPOINT, NETWORK, RECIPIENT, selectRequirement, validatePaymentPayload } from "../payment-policy.mjs";
import { createApprovalServer, createPurchase } from "../server.mjs";

const TERMS = "a".repeat(64);
const LEGAL_NAMES = ["terms", "refunds", "privacy", "acceptable-use", "data-handling", "security"];

function requiredPayment() {
  return {
    x402Version: 2,
    resource: { url: ENDPOINT, description: "Synthetic offline test", mimeType: "application/json" },
    accepts: [{ scheme: "exact", network: NETWORK, asset: ASSET, amount: AMOUNT, payTo: RECIPIENT, maxTimeoutSeconds: 3600, extra: { name: "USD Coin", version: "2" } }],
  };
}

async function sign(account, required = requiredPayment()) {
  const client = new x402Client();
  client.register(NETWORK, new ExactEvmScheme(account));
  return client.createPaymentPayload(required);
}

function fixture(context, { paidFailure = false, responseStatus = 200, price = AMOUNT, challengeTimeout = 3600 } = {}) {
  const folder = mkdtempSync(join(tmpdir(), "tool-offer-wallet-test-"));
  context.after(() => rmSync(folder, { recursive: true, force: true }));
  const account = privateKeyToAccount(generatePrivateKey());
  const requestBytes = Buffer.from(JSON.stringify({ schema: "FAHCE_MACHINE_REQUEST_V1", candidate_output: "Synthetic test only", evidence: [] }));
  const statePath = join(folder, "purchase.json");
  const calls = [];
  const options = {
    requestBytes, buyer: account.address, statePath, signatureVerifier: verifyTypedData,
    async fetcher(url, request) {
      calls.push({ url, request });
      if (request.method !== "POST") {
        return Response.json({
          legal_documents: { publication_hash: TERMS, urls: Object.fromEntries(LEGAL_NAMES.map(name => [name, "https://fahce.kinganlogic.com/legal/" + name])) },
          payment: { protocol: "x402-v2" },
          pricing_terms: { prices: { diagnose: { atomic_units: price, scheme: "exact" } } },
        });
      }
      if (!request.headers["PAYMENT-SIGNATURE"]) {
        const required = requiredPayment();
        required.accepts[0].maxTimeoutSeconds = challengeTimeout;
        return Response.json(required, { status: 402, headers: { "PAYMENT-REQUIRED": encodePaymentRequiredHeader(required) } });
      }
      if (paidFailure) throw new Error("Synthetic ambiguous network failure");
      return Response.json({ schema: "FAHCE_MACHINE_RESPONSE_V1", operation: "diagnose", request_id: "synthetic-test-only", verification: { verified: false } }, {
        status: responseStatus,
        headers: {
          "FAHCE-Recovery-Token": "synthetic-secret-recovery-token",
          "PAYMENT-RESPONSE": encodePaymentResponseHeader({ success: true, transaction: "0x" + "ab".repeat(32), network: NETWORK, payer: account.address }),
        },
      });
    },
  };
  return { account, calls, statePath, options, purchase: createPurchase(options) };
}

async function ready(purchase, buyer) {
  await purchase.challenge({ acceptTerms: true, termsHash: TERMS });
  purchase.beginAuthorization({ buyer });
}

test("SDK creates a verifiable authorization with pinned terms", async () => {
  const account = privateKeyToAccount(generatePrivateKey());
  const payload = await sign(account);
  const typedData = validatePaymentPayload(payload, requiredPayment(), account.address);
  assert.equal(await verifyTypedData({ ...typedData, address: account.address, signature: payload.payload.signature }), true);
  assert.equal(payload.payload.authorization.value, AMOUNT);
});

test("accepts FAHCE's one-hour challenge without changing the accepted requirements", async () => {
  const required = requiredPayment();
  const account = privateKeyToAccount(generatePrivateKey());
  const payload = await sign(account, required);
  validatePaymentPayload(payload, required, account.address);
  assert.equal(selectRequirement(required).maxTimeoutSeconds, 3600);
  assert.deepEqual(payload.accepted, required.accepts[0]);
  const lifetime = Number(payload.payload.authorization.validBefore) - Math.floor(Date.now() / 1000);
  assert.ok(lifetime > 300 && lifetime <= 3600);
  for (const timeout of [0, -1, 3601, 3600.5, "3600"]) {
    const invalid = requiredPayment();
    invalid.accepts[0].maxTimeoutSeconds = timeout;
    assert.throws(() => selectRequirement(invalid), /authorization window/);
  }
});

test("rejects changed merchant, network, token, amount, domain, endpoint, or excessive duration", () => {
  const changes = [
    option => { option.amount = "150001"; },
    option => { option.network = "eip155:1"; },
    option => { option.asset = "0x" + "12".repeat(20); },
    option => { option.payTo = "0x" + "12".repeat(20); },
    option => { option.extra.name = "Untrusted Token"; },
    option => { option.extra.assetTransferMethod = "permit2"; },
    option => { option.maxTimeoutSeconds = 86400; },
  ];
  for (const change of changes) {
    const required = requiredPayment();
    change(required.accepts[0]);
    assert.throws(() => selectRequirement(required));
  }
  const required = requiredPayment();
  required.resource.url = "https://example.com/pay";
  assert.throws(() => selectRequirement(required));
});

test("cannot sign another payer or alter the selected authorization", async () => {
  const account = privateKeyToAccount(generatePrivateKey());
  const payload = await sign(account);
  assert.throws(() => validatePaymentPayload(payload, requiredPayment(), "0x" + "12".repeat(20)));
  const changed = structuredClone(payload);
  changed.payload.authorization.value = "150001";
  assert.throws(() => validatePaymentPayload(changed, requiredPayment(), account.address));
  changed.payload.authorization.value = AMOUNT;
  changed.payload.authorization.validBefore = String(Math.floor(Date.now() / 1000) + 86400);
  assert.throws(() => validatePaymentPayload(changed, requiredPayment(), account.address));
});

test("opening and reading status cannot call the paid endpoint", async context => {
  const { purchase, calls } = fixture(context);
  assert.equal(purchase.status().phase, "ready");
  await purchase.discovery();
  assert.equal(calls.filter(call => call.request.method === "POST").length, 0);
});

test("requires acceptance of the exact legal publication", async context => {
  const { purchase, calls } = fixture(context);
  await assert.rejects(purchase.challenge({ acceptTerms: false, termsHash: TERMS }));
  await assert.rejects(purchase.challenge({ acceptTerms: true, termsHash: "b".repeat(64) }));
  assert.equal(calls.filter(call => call.request.method === "POST").length, 0);
  assert.equal(purchase.status().phase, "ready");
});

test("published price changes stop before any purchase request", async context => {
  const { purchase, calls } = fixture(context, { price: "200000" });
  await assert.rejects(purchase.challenge({ acceptTerms: true, termsHash: TERMS }));
  assert.equal(calls.filter(call => call.request.method === "POST").length, 0);
});

test("unsupported challenge windows report the precise safe failure without signing", async context => {
  const { purchase, calls } = fixture(context, { challengeTimeout: 3601 });
  await assert.rejects(purchase.challenge({ acceptTerms: true, termsHash: TERMS }), error => error.status === 502 && /authorization window/.test(error.message));
  assert.equal(purchase.status().phase, "ready");
  assert.equal(calls.filter(call => call.request.headers?.["PAYMENT-SIGNATURE"]).length, 0);
});

test("sends the identical reviewed body once, retaining secrets only in private state", async context => {
  const { purchase, account, calls, statePath, options } = fixture(context);
  await ready(purchase, account.address);
  const paymentPayload = await sign(account);
  const result = await purchase.pay({ paymentPayload });
  assert.equal(result.phase, "response_received");
  assert.equal(result.result.verification.verified, false);
  const posts = calls.filter(call => call.request.method === "POST");
  assert.equal(posts.length, 2);
  assert.deepEqual(posts[0].request.body, posts[1].request.body);
  assert.equal(posts[0].request.headers["Idempotency-Key"], posts[1].request.headers["Idempotency-Key"]);
  assert.equal(posts[1].request.redirect, "error");
  assert.equal(JSON.stringify(result).includes("synthetic-secret-recovery-token"), false);
  assert.equal(JSON.stringify(result).includes(paymentPayload.payload.signature), false);
  assert.equal(JSON.parse(readFileSync(statePath, "utf8")).recoveryToken, "synthetic-secret-recovery-token");
  assert.equal(statSync(statePath).mode & 0o777, 0o600);
  await assert.rejects(purchase.pay({ paymentPayload }));
  await assert.rejects(createPurchase(options).challenge({ acceptTerms: true, termsHash: TERMS }));
  assert.equal(calls.filter(call => call.request.headers?.["PAYMENT-SIGNATURE"]).length, 1);
});

test("concurrent paid submissions cannot send two authorizations", async context => {
  const { purchase, account, calls } = fixture(context);
  await ready(purchase, account.address);
  const paymentPayload = await sign(account);
  const results = await Promise.allSettled([purchase.pay({ paymentPayload }), purchase.pay({ paymentPayload })]);
  assert.equal(results.filter(result => result.status === "fulfilled").length, 1);
  assert.equal(calls.filter(call => call.request.headers?.["PAYMENT-SIGNATURE"]).length, 1);
});

test("ambiguous delivery blocks reauthorization across restart", async context => {
  const { purchase, account, calls, options } = fixture(context, { paidFailure: true });
  await ready(purchase, account.address);
  await assert.rejects(purchase.pay({ paymentPayload: await sign(account) }));
  assert.equal(purchase.status().phase, "unresolved");
  const restarted = createPurchase(options);
  await assert.rejects(restarted.challenge({ acceptTerms: true, termsHash: TERMS }));
  assert.equal(calls.filter(call => call.request.headers?.["PAYMENT-SIGNATURE"]).length, 1);
});

test("restart during the wallet popup conservatively blocks a fresh payment", async context => {
  const { purchase, account, options } = fixture(context);
  await ready(purchase, account.address);
  const restarted = createPurchase(options);
  assert.equal(restarted.status().phase, "unresolved");
  await assert.rejects(restarted.challenge({ acceptTerms: true, termsHash: TERMS }));
});

test("explicit wallet rejection before a signature allows another review", async context => {
  const { purchase, account, calls } = fixture(context);
  await ready(purchase, account.address);
  assert.throws(() => purchase.rejected({ code: -1 }));
  purchase.rejected({ code: 4001 });
  assert.equal(purchase.status().phase, "challenge_ready");
  await purchase.challenge({ acceptTerms: true, termsHash: TERMS });
  assert.equal(calls.filter(call => call.request.headers?.["PAYMENT-SIGNATURE"]).length, 0);
});

test("invalid signatures and unexpected paid HTTP responses never trigger another payment", async context => {
  const invalid = fixture(context);
  await ready(invalid.purchase, invalid.account.address);
  const payload = await sign(privateKeyToAccount(generatePrivateKey()));
  await assert.rejects(invalid.purchase.pay({ paymentPayload: payload }));
  assert.equal(invalid.calls.filter(call => call.request.headers?.["PAYMENT-SIGNATURE"]).length, 0);
  const refused = fixture(context, { responseStatus: 402 });
  await ready(refused.purchase, refused.account.address);
  await refused.purchase.pay({ paymentPayload: await sign(refused.account) });
  assert.equal(refused.purchase.status().phase, "unresolved");
  assert.equal(refused.calls.filter(call => call.request.headers?.["PAYMENT-SIGNATURE"]).length, 1);
});

test("changing the saved purchase or buyer cannot reuse existing payment state", context => {
  const { options } = fixture(context);
  assert.throws(() => createPurchase({ ...options, buyer: "0x" + "12".repeat(20) }));
  const changed = JSON.parse(options.requestBytes);
  changed.candidate_output = "Another request";
  assert.throws(() => createPurchase({ ...options, requestBytes: Buffer.from(JSON.stringify(changed)) }));
});

test("HTTP boundary rejects unauthorized, cross-origin, and rebinding requests", async context => {
  const { purchase, calls } = fixture(context);
  const allowedHosts = new Set();
  const allowedOrigins = new Set();
  const server = createApprovalServer({ purchase, accessToken: "test-access", allowedHosts, allowedOrigins });
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  context.after(() => new Promise(resolve => server.close(resolve)));
  const origin = "http://127.0.0.1:" + server.address().port;
  allowedHosts.add(new URL(origin).host);
  allowedOrigins.add(origin);
  const anonymous = await fetch(origin + "/api/status");
  assert.equal(anonymous.status, 401);
  const page = await fetch(origin + "/");
  assert.equal(page.status, 200);
  assert.match(page.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  const wrongOrigin = await fetch(origin + "/api/challenge", {
    method: "POST", headers: { Authorization: "Bearer test-access", Origin: "https://example.com", "Content-Type": "application/json" }, body: "{}",
  });
  assert.equal(wrongOrigin.status, 403);
  const noOrigin = await fetch(origin + "/api/challenge", {
    method: "POST", headers: { Authorization: "Bearer test-access", "Content-Type": "application/json" }, body: "{}",
  });
  assert.equal(noOrigin.status, 403);
  const rebindingStatus = await new Promise((resolve, reject) => {
    const request = httpRequest(origin + "/api/status", { headers: { Host: "evil.example", Authorization: "Bearer test-access" } }, response => {
      response.resume();
      resolve(response.statusCode);
    });
    request.once("error", reject);
    request.end();
  });
  assert.equal(rebindingStatus, 403);
  const status = await fetch(origin + "/api/status", { headers: { Authorization: "Bearer test-access" } });
  assert.equal(status.status, 200);
  assert.equal(calls.length, 0);
});
