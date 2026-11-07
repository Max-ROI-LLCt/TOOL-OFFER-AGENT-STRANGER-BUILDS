import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

class Element {
  constructor(id) {
    this.id = id; this.handlers = new Map(); this.value = ""; this.checked = false;
    this.disabled = false; this.hidden = false; this.textContent = ""; this.options = [{}];
  }
  addEventListener(name, handler) { this.handlers.set(name, handler); }
  replaceChildren() { this.options = []; }
  append(child) { this.options.push(child); if (!this.value && child.value) this.value = child.value; }
  async fire(name) { return this.handlers.get(name)?.(); }
}

async function browserFixture(reject = false, savedApproval = false) {
  const elements = new Map();
  const element = id => { if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id); };
  element("hide-wallets").checked = true;
  const calls = [];
  let walletCalls = 0;
  let status = { phase: "input_review", candidate: "Original <untrusted> offer", requestSha256: "a".repeat(64),
    evidenceCount: 2, recipient: "test-merchant", termsHash: "t".repeat(64), legalUrls: {},
    inputRevision: { candidate: "Reviewed <untrusted> offer", requestSha256: "b".repeat(64), sourceRequestSha256: "a".repeat(64),
      summary: "Review all wording changes.", preflight: { status: "NO_KNOWN_BLOCKER" } } };
  if (savedApproval) status = { ...status, phase: "unresolved", inputRevision: null, savedAuthorization: { canSubmit: true },
    reconciliation: { outcome: "EXPIRED_UNUSED" }, validationFailure: reject === "legacy-note" ? null : { code: "SIGNATURE_CHECK_RATE_LIMITED" } };
  const fetch = async (url, options) => {
    const path = url.slice(url.indexOf("/api/"));
    calls.push({ path, method: options.method, body: options.body ? JSON.parse(options.body) : null });
    if (path === "/api/submit-saved-authorization") {
      assert.equal(options.method, "POST");
      assert.deepEqual(JSON.parse(options.body), { submitSavedAuthorization: true, requestSha256: "a".repeat(64), acceptTerms: true, termsHash: "t".repeat(64) });
      status = { ...status, phase: reject ? "unresolved" : "response_received", savedAuthorization: { canSubmit: false }, validationFailure: null };
      if (reject) throw new TypeError("Lost delivery response");
    } else if (path === "/api/accept-input-revision") {
      if (reject === true) return Response.json({ error: "Revised input no longer clears preflight." }, { status: 422 });
      assert.equal(options.method, "POST");
      assert.deepEqual(JSON.parse(options.body), { acceptRevision: true, sourceRequestSha256: "a".repeat(64), requestSha256: "b".repeat(64) });
      status = { ...status, phase: "ready", candidate: status.inputRevision.candidate, requestSha256: status.inputRevision.requestSha256, inputRevision: null };
      if (reject === "lost-response") throw new TypeError("Synthetic lost acceptance response");
    } else assert.ok(["/api/config", "/api/status"].includes(path), "Unexpected payment or network route: " + path);
    return Response.json(status);
  };
  const source = readFileSync(new URL("../browser.mjs", import.meta.url), "utf8").replace(/^import .*;\n/gm, "");
  const execute = Object.getPrototypeOf(async function() {}).constructor;
  const run = new execute("document", "location", "sessionStorage", "history", "window", "setTimeout", "fetch", "createBaseAccountSDK", "base", source);
  await run({ getElementById: element, createElement: tag => new Element(tag) },
    { pathname: "/checkout/test/", hash: "#access=test-only-capability", search: "" },
    { setItem() {}, getItem() { return "test-only-capability"; } }, { replaceState() {} },
    { addEventListener() {}, dispatchEvent() {} }, () => {}, fetch,
    () => ({ getProvider: () => ({ request: async () => { walletCalls++; throw Error("Wallet must not be called during input review"); } }) }), { id: 8453 });
  return { element, calls, walletCalls: () => walletCalls };
}

test("input review displays both versions and explicit acceptance never opens a wallet or pays", async () => {
  const fixture = await browserFixture();
  assert.equal(fixture.element("revision-card").hidden, false);
  assert.equal(fixture.element("revision-original").textContent, "Original <untrusted> offer");
  assert.equal(fixture.element("revision-candidate").textContent, "Reviewed <untrusted> offer");
  assert.equal(fixture.element("apply-revision").disabled, true);
  assert.equal(fixture.element("pay").disabled, true);
  await fixture.element("apply-revision").fire("click");
  assert.equal(fixture.calls.length, 1);
  fixture.element("accept-revision").checked = true;
  await fixture.element("accept-revision").fire("change");
  assert.equal(fixture.element("apply-revision").disabled, false);
  fixture.element("accept-terms").checked = true;
  await fixture.element("apply-revision").fire("click");
  assert.equal(fixture.element("revision-card").hidden, true);
  assert.equal(fixture.element("candidate").textContent, "Reviewed <untrusted> offer");
  assert.equal(fixture.element("accept-terms").checked, false);
  assert.equal(fixture.element("pay").disabled, true);
  assert.equal(fixture.calls.filter(call => call.method === "POST").length, 1);
  assert.equal(fixture.walletCalls(), 0);
});

test("failed input acceptance retains original and does not automatically retry or pay", async () => {
  const fixture = await browserFixture(true);
  fixture.element("accept-revision").checked = true;
  await fixture.element("accept-revision").fire("change");
  await fixture.element("apply-revision").fire("click");
  assert.equal(fixture.element("revision-card").hidden, false);
  assert.equal(fixture.element("candidate").textContent, "Original <untrusted> offer");
  assert.equal(fixture.element("pay").disabled, true);
  assert.match(fixture.element("error").textContent, /no longer clears/);
  assert.equal(fixture.calls.filter(call => call.method === "POST").length, 1);
  assert.equal(fixture.walletCalls(), 0);
});

test("lost acceptance response still resets payment consent when refresh sees a new request", async () => {
  const fixture = await browserFixture("lost-response");
  fixture.element("accept-terms").checked = true;
  fixture.element("accept-revision").checked = true;
  await fixture.element("accept-revision").fire("change");
  await fixture.element("apply-revision").fire("click");
  assert.equal(fixture.element("candidate").textContent, "Reviewed <untrusted> offer");
  assert.equal(fixture.element("accept-terms").checked, false);
  assert.equal(fixture.element("pay").disabled, true);
  assert.equal(fixture.calls.filter(call => call.method === "POST").length, 1);
  assert.equal(fixture.walletCalls(), 0);
});

for (const lostResponse of [false, true]) {
  test("saved approval requires two explicit consents and never signs or auto-retries: lostResponse=" + lostResponse, async () => {
    const fixture = await browserFixture(lostResponse, true);
    assert.equal(fixture.element("saved-approval").hidden, false);
    assert.equal(fixture.element("pay").hidden, true);
    assert.match(fixture.element("status").textContent, /rate-limiting/);
    await fixture.element("refresh").fire("click");
    await fixture.element("submit-saved-approval").fire("click");
    assert.equal(fixture.calls.filter(call => call.method === "POST").length, 0);
    fixture.element("accept-terms").checked = true;
    await fixture.element("accept-terms").fire("change");
    assert.equal(fixture.element("submit-saved-approval").disabled, true);
    fixture.element("accept-saved-approval").checked = true;
    await fixture.element("accept-saved-approval").fire("change");
    assert.equal(fixture.element("submit-saved-approval").disabled, false);
    await Promise.all([fixture.element("submit-saved-approval").fire("click"), fixture.element("submit-saved-approval").fire("click")]);
    await fixture.element("refresh").fire("click");
    await fixture.element("submit-saved-approval").fire("click");
    assert.equal(fixture.calls.filter(call => call.method === "POST").length, 1);
    assert.equal(fixture.element("submit-saved-approval").disabled, true);
    assert.equal(fixture.element("accept-saved-approval").checked, false);
    assert.equal(fixture.walletCalls(), 0);
  });
}

test("saved approval wording distinguishes an older expired attempt without asking for another signature", async () => {
  const fixture = await browserFixture("legacy-note", true);
  assert.match(fixture.element("status").textContent, /no signed payment has been sent/);
  assert.match(fixture.element("status").textContent, /older, separate authorization/);
  assert.match(fixture.element("status").textContent, /does not refer to your current saved approval/);
  assert.equal(fixture.calls.filter(call => call.method === "POST").length, 0);
});
