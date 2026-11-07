import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { x402Client } from "@x402/core/client";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import * as policy from "../payment-policy.mjs";

class Element {
  constructor() {
    this.handlers = new Map(); this.value = ""; this.checked = false;
    this.disabled = false; this.hidden = false; this.textContent = ""; this.options = [{}];
  }
  addEventListener(name, handler) { this.handlers.set(name, handler); }
  replaceChildren() { this.options = []; }
  append(child) { this.options.push(child); if (!this.value && child.value) this.value = child.value; }
  async fire(name) { return this.handlers.get(name)?.(); }
}

async function fixture({ phase = "ready", pinned = false, reject = false, accounts = null } = {}) {
  const account = privateKeyToAccount(generatePrivateKey());
  const other = privateKeyToAccount(generatePrivateKey());
  const elements = new Map();
  const element = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  element("hide-wallets").checked = true;
  const calls = [];
  const walletCalls = [];
  const events = new Map();
  let currentAccounts = accounts ?? [account.address];
  let signatures = 0;
  let status = { phase, buyer: pinned ? other.address : null, requestSha256: "a".repeat(64),
    candidate: "Synthetic offline offer only", evidenceCount: 1, recipient: policy.RECIPIENT,
    termsHash: "b".repeat(64), legalUrls: {}, savedAuthorization: { canSubmit: false } };
  const required = { x402Version: 2, resource: { url: policy.ENDPOINT, mimeType: "application/json" },
    accepts: [{ scheme: "exact", network: policy.NETWORK, asset: policy.ASSET, amount: policy.AMOUNT,
      payTo: policy.RECIPIENT, maxTimeoutSeconds: 3600, extra: { name: "USD Coin", version: "2" } }] };
  const provider = {
    on: (name, handler) => events.set(name, handler),
    async request({ method }) {
      walletCalls.push(method);
      if (method === "eth_requestAccounts" && reject) throw { code: 4001 };
      if (["eth_accounts", "eth_requestAccounts"].includes(method)) return currentAccounts;
      if (method === "eth_chainId") return "0x2105";
      throw Error("Unexpected wallet request: " + method);
    },
  };
  const fetch = async (url, options) => {
    const path = url.slice(url.indexOf("/api/"));
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ path, method: options.method, body });
    if (path === "/api/challenge") {
      assert.equal(body.buyer, account.address);
      assert.equal(body.acceptTerms, true);
      status = { ...status, buyer: body.buyer, phase: "challenge_ready" };
      return Response.json({ required, buyer: body.buyer });
    }
    if (path === "/api/authorize") status.phase = "awaiting_wallet";
    else if (path === "/api/pay") {
      policy.validatePaymentPayload(body.paymentPayload, required, account.address);
      status = { ...status, phase: "response_received", httpStatus: 200, result: { synthetic: true } };
    } else assert.ok(["/api/config", "/api/status"].includes(path), "Unexpected route: " + path);
    return Response.json(status);
  };
  const source = readFileSync(new URL("../browser.mjs", import.meta.url), "utf8").replace(/^import .*;\n/gm, "");
  const environment = {
    document: { getElementById: element, createElement: () => new Element() },
    location: { pathname: "/checkout/synthetic-only/", hash: "#access=synthetic", search: "" },
    sessionStorage: { setItem() {}, getItem() { return "synthetic"; } }, history: { replaceState() {} },
    window: { addEventListener() {}, dispatchEvent() {} }, setTimeout() {}, fetch,
    createBaseAccountSDK: () => ({ getProvider: () => provider }), base: { id: 8453 },
    createWalletClient: () => ({ signTypedData: parameters => { signatures++; return account.signTypedData(parameters); } }),
    custom: () => null, x402Client, ExactEvmScheme, ...policy,
  };
  const execute = Object.getPrototypeOf(async function() {}).constructor;
  await new execute(...Object.keys(environment), source)(...Object.values(environment));
  return { element, calls, walletCalls, account, other, events, signatures: () => signatures,
    switchAccount: address => { currentAccounts = [address]; },
    changePhase: value => { status.phase = value; } };
}

test("connecting shares the buyer account locally, masks it, and never requests payment", async () => {
  const page = await fixture();
  assert.equal(page.element("pay").disabled, true);
  assert.equal(page.element("connect-wallet").disabled, false);
  assert.equal(page.walletCalls.length, 0);
  await page.element("connect-wallet").fire("click");
  assert.deepEqual(page.walletCalls, ["eth_requestAccounts"]);
  assert.equal(page.calls.length, 1);
  assert.equal(page.calls[0].path, "/api/config");
  assert.equal(page.signatures(), 0);
  assert.equal(page.element("accept-terms").checked, false);
  assert.equal(page.element("pay").disabled, true);
  assert.equal(page.element("buyer").textContent, "[Wallet hidden for recording]");
  page.element("hide-wallets").checked = false;
  await page.element("hide-wallets").fire("change");
  assert.equal(page.element("buyer").textContent, page.account.address);
  page.element("hide-wallets").checked = true;
  await page.element("hide-wallets").fire("change");
  assert.ok(!page.element("connected-wallet").textContent.includes(page.account.address));
});

test("synthetic full checkout requires connection, separate consent and one pay click", async () => {
  const page = await fixture();
  page.element("accept-terms").checked = true;
  await page.element("accept-terms").fire("change");
  assert.equal(page.element("pay").disabled, true);
  await page.element("connect-wallet").fire("click");
  assert.equal(page.element("accept-terms").checked, false);
  page.element("accept-terms").checked = true;
  await page.element("accept-terms").fire("change");
  assert.equal(page.element("pay").disabled, false);
  await Promise.all([page.element("pay").fire("click"), page.element("pay").fire("click")]);
  assert.equal(page.signatures(), 1);
  assert.equal(page.calls.filter(call => call.path === "/api/pay").length, 1);
  assert.equal(page.walletCalls.filter(method => method === "eth_requestAccounts").length, 1);
  assert.equal(page.element("connect-wallet").disabled, true);
  assert.equal(page.element("pay").disabled, true);
  assert.equal(page.element("result-card").hidden, false);
  await page.element("refresh").fire("click");
  assert.equal(page.signatures(), 1);
});

test("wallet account changes invalidate connection and consent before any payment", async () => {
  const page = await fixture();
  await page.element("connect-wallet").fire("click");
  page.element("accept-terms").checked = true;
  await page.element("accept-terms").fire("change");
  page.events.get("accountsChanged")([page.other.address]);
  assert.equal(page.element("pay").disabled, true);
  assert.equal(page.element("accept-terms").checked, false);
  assert.equal(page.calls.length, 1);
});

test("account changes without provider events are caught before the payment challenge", async () => {
  const page = await fixture();
  await page.element("connect-wallet").fire("click");
  page.element("accept-terms").checked = true;
  await page.element("accept-terms").fire("change");
  page.switchAccount(page.other.address);
  await page.element("pay").fire("click");
  assert.equal(page.calls.filter(call => call.method === "POST").length, 0);
  assert.match(page.element("error").textContent, /account changed/);
  assert.equal(page.signatures(), 0);
  assert.equal(page.element("pay").disabled, true);
});

for (const options of [{ pinned: true }, { reject: true }, { accounts: [] }, { accounts: ["not-an-address"] }]) {
  test("failed or mismatched wallet connection never exposes a pinned wallet or starts a purchase: " + JSON.stringify(options), async () => {
    const page = await fixture(options);
    await page.element("connect-wallet").fire("click");
    assert.equal(page.element("pay").disabled, true);
    assert.ok(page.element("error").textContent);
    assert.ok(!page.element("error").textContent.includes(page.other.address));
    assert.equal(page.calls.length, 1);
    assert.equal(page.signatures(), 0);
  });
}

for (const phase of ["input_blocked", "input_review", "awaiting_wallet", "submitting", "unresolved", "response_received", "unknown"]) {
  test("setup cannot restart an unsafe or completed checkout: " + phase, async () => {
    const page = await fixture({ phase });
    assert.equal(page.element("connect-wallet").disabled, true);
    await page.element("connect-wallet").fire("click");
    assert.equal(page.walletCalls.length, 0);
    assert.equal(page.calls.length, 1);
  });
}

test("selecting a provider or disconnecting clears the prior account and policy consent", async () => {
  const page = await fixture();
  for (const reset of [() => page.element("wallet").fire("change"), () => page.events.get("disconnect")()]) {
    await page.element("connect-wallet").fire("click");
    page.element("accept-terms").checked = true;
    await page.element("accept-terms").fire("change");
    await reset();
    assert.equal(page.element("accept-terms").checked, false);
    assert.equal(page.element("pay").disabled, true);
  }
  assert.equal(page.signatures(), 0);
  assert.equal(page.calls.length, 1);
});
