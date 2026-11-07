import { DurableObject } from "cloudflare:workers";
import { createPublicClient, http } from "viem";
import { base } from "viem/chains";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { ENDPOINT, DISCOVERY, AMOUNT, ASSET, RECIPIENT, NETWORK, PaymentPolicyError, sameAddress, selectRequirement, stableJson, validatePaymentPayload } from "./payment-policy.mjs";
import { verifyReceiptEvidence } from "./attestation-verifier.mjs";
import { proveExpiredUnusedAuthorization } from "./expired-authorization.mjs";

const json = (body, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff" } });
const random = () => [...crypto.getRandomValues(new Uint8Array(32))].map(x => x.toString(16).padStart(2, "0")).join("");
const digest = async text => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)))].map(x => x.toString(16).padStart(2, "0")).join("");
const equal = (a, b) => {
  if (typeof a !== "string" || typeof b !== "string") return false;
  let d = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) d |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return d === 0;
};
const client = createPublicClient({ chain: base, transport: http("https://mainnet.base.org", { retryCount: 0, timeout: 15000 }) });
const locked = new Set(["requesting_challenge", "awaiting_wallet", "validating_authorization", "submitting", "unresolved", "response_received"]);

function verificationError(error) {
  const causes = [];
  for (let current = error; current && causes.length < 6; current = current.cause) {
    causes.push({ errorClass: typeof current.name === "string" && /^[A-Za-z][A-Za-z0-9]{0,79}$/.test(current.name) ? current.name : "Error",
      ...(Number.isInteger(current.status) ? { httpStatus: current.status } : {}),
      ...(Number.isInteger(current.code) ? { rpcCode: current.code } : {}) });
  }
  return causes;
}

async function remote(url, options = {}) {
  const headers = new Headers(options.headers);
  headers.set("User-Agent", "ToolOfferAgent/0.2");
  const response = await fetch(url, { ...options, headers, redirect: "manual", signal: AbortSignal.timeout(45000) });
  if (response.status >= 300 && response.status < 400) throw Error("Upstream redirect rejected.");
  return response;
}
async function readJson(request, limit = 600000) {
  const text = await request.text();
  if (new TextEncoder().encode(text).length > limit) throw Error("Request too large.");
  return JSON.parse(text);
}
async function discovery() {
  const response = await remote(DISCOVERY);
  if (!response.ok) throw Error("FAHCE discovery unavailable. No payment authorized.");
  const document = await response.json();
  const legal = document.legal_documents;
  if (!/^[a-f0-9]{64}$/.test(legal?.publication_hash) || document.pricing_terms?.prices?.diagnose?.atomic_units !== AMOUNT
      || document.pricing_terms?.prices?.diagnose?.scheme !== "exact" || document.payment?.protocol !== "x402-v2") {
    throw Error("FAHCE price or policy configuration changed. No payment authorized.");
  }
  for (const name of ["terms", "refunds", "privacy", "acceptable-use", "data-handling", "security"]) {
    if (legal.urls?.[name] !== "https://fahce.kinganlogic.com/legal/" + name) throw Error("Unexpected policy URL.");
  }
  return { termsHash: legal.publication_hash, legalUrls: legal.urls };
}

export class FahceCheckout extends DurableObject {
  constructor(ctx, env) { super(ctx, env); this.ctx = ctx; this.env = env; this.queue = Promise.resolve(); }
  async save(state) { await this.ctx.storage.put("purchase", state); }
  async evaluateInput(machine, requestSha256) {
    let screen;
    try {
      const response = await remote("https://fahce.kinganlogic.com/api/v1/machine/preflight", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation: "diagnose", request: machine }),
      });
      const result = await response.json();
      screen = result.capability_screen;
      if (!response.ok || result.schema !== "FAHCE_MACHINE_PREFLIGHT_V1" || result.syntax_valid !== true
          || result.engine_executed !== false || result.payment_authority !== false
          || !["NOT_ESTABLISHED", "SEMANTICALLY_UNSUPPORTED"].includes(screen?.semantic_status)
          || !["STRUCTURALLY_INTERPRETABLE", "STRUCTURAL_LIMITATION"].includes(screen?.structural_status)
          || !Array.isArray(screen.candidate_limitations) || !Array.isArray(screen.limitations)) throw Error("Invalid preflight");
    } catch { screen = null; }
    const blocked = !screen || screen.semantic_status === "SEMANTICALLY_UNSUPPORTED"
      || screen.structural_status === "STRUCTURAL_LIMITATION" || screen.candidate_limitations.length > 0 || screen.limitations.length > 0;
    return { checkedAt: new Date().toISOString(), requestSha256,
      status: !screen ? "UNAVAILABLE" : blocked ? "INPUT_UNSUPPORTED" : "NO_KNOWN_BLOCKER", billabilityGuaranteed: false,
      candidateBlockers: screen?.candidate_limitations.length ?? null, evidenceBlockers: screen?.limitations.length ?? null };
  }
  async screenInput(state) {
    state.preflight = await this.evaluateInput(state.request, state.requestSha256);
    const blocked = state.preflight.status !== "NO_KNOWN_BLOCKER";
    if (blocked) {
      state.phase = "input_blocked";
      state.note = state.preflight.status !== "UNAVAILABLE" ? "FAHCE cannot currently interpret this draft. No wallet signature or payment requested. The complete draft and evidence are preserved."
        : "FAHCE's free input check is unavailable. No wallet signature or payment requested. Refresh to check again.";
      delete state.required;
    } else {
      if (state.phase === "input_blocked") state.phase = "ready";
      state.note = null;
    }
    await this.save(state);
    return !blocked;
  }
  canReviewInput(state) {
    return !!state && ["input_blocked", "input_review"].includes(state.phase)
      && !state.representationRevision
      && !["signedAt", "paymentPayload", "pendingValidationPayload", "httpStatus", "responseText", "result", "gateway", "paymentResponse", "recoveryToken", "receiptProof"].some(key => state[key])
      && (!(state.previousAttemptKeys?.length) || state.reconciliation?.outcome === "EXPIRED_UNUSED");
  }
  async paymentRequest(options) {
    const headers = new Headers(options.headers);
    headers.set("Authorization", "Bearer " + this.env.FAHCE_BRIDGE_TOKEN);
    return this.env.PAYMENT_RELAY.getByName("fahce-us-payment-egress-v1", { locationHint: "enam" })
      .fetch(new Request("https://internal/diagnose", { ...options, headers }));
  }
  canSubmitSavedAuthorization(state) {
    if (!state || state.phase !== "unresolved"
        || state.note !== "Authorization validation failed. No signed request sent; reconcile before retry."
        || !state.pendingValidationPayload || state.inputRevision
        || ["signedAt", "paymentPayload", "httpStatus", "responseText", "result", "gateway", "paymentResponse", "recoveryToken", "receiptProof"].some(key => state[key])) return false;
    try { validatePaymentPayload(state.pendingValidationPayload, state.required, state.buyer); return true; }
    catch { return false; }
  }
  async fetch(request) {
    // Serialize the complete action, including upstream I/O, to prevent duplicate signed delivery.
    const action = this.queue.then(async () => {
      try { return await this.handle(request); }
      catch { return json({ error: "Checkout step could not complete. Refresh status before any further authorization." }, 502); }
    });
    this.queue = action.catch(() => {});
    return action;
  }
  async handle(request) {
    const path = new URL(request.url).pathname;
    let state = await this.ctx.storage.get("purchase");
    if (path === "/admin/validation-proof") {
      if (!this.env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + this.env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
      if (request.method !== "GET") return json({ error: "Read-only diagnostic." }, 405);
      if (!state || state.phase !== "unresolved" || !state.pendingValidationPayload
          || state.signedAt || state.paymentPayload || state.httpStatus || state.responseText) {
        return json({ code: "NO_RETAINED_PREDELIVERY_AUTHORIZATION", readOnly: true }, 409);
      }
      let typed;
      try { typed = validatePaymentPayload(state.pendingValidationPayload, state.required, state.buyer); }
      catch { return json({ code: "AUTHORIZATION_POLICY_REJECTED", requestSha256: state.requestSha256, readOnly: true }, 409); }
      try {
        const response = await this.env.PAYMENT_RELAY.getByName("fahce-us-payment-egress-v1", { locationHint: "enam" }).fetch(new Request("https://internal/verify", {
          method: "POST", headers: { Authorization: "Bearer " + this.env.FAHCE_BRIDGE_TOKEN, "Content-Type": "application/json" },
          body: JSON.stringify({ buyer: state.buyer, typedData: typed, signature: state.pendingValidationPayload.payload.signature }, (_, value) => typeof value === "bigint" ? value.toString() : value),
        }));
        const verification = await response.json();
        return json({ requestSha256: state.requestSha256, verification, relayStatus: response.status,
          authorizationExpiresAt: String(typed.message.validBefore), signatureBytes: (state.pendingValidationPayload.payload.signature.length - 2) / 2,
          readOnly: true, paidDeliveryAttempted: false, checkoutUnlocked: false });
      } catch (error) { return json({ code: "SIGNATURE_CHECK_UNAVAILABLE", causes: verificationError(error), readOnly: true }, 502); }
    }
    if (path === "/admin/payment-evidence" || path === "/admin/expired-authorization-proof") {
      if (!this.env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + this.env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
      if (request.method !== "GET") return json({ error: "Read-only diagnostic." }, 405);
      if (!state) return json({ error: "Checkout not found." }, 404);
      if (path === "/admin/expired-authorization-proof") {
        try { return json({ proof: await proveExpiredUnusedAuthorization(state), readOnly: true }); }
        catch (error) {
          return json({ error: "Expired-unused authorization is not established. Original attempt remains locked.",
            code: /^EXPIRED_PROOF_[A-Z0-9_]+$/.test(error?.code) ? error.code : "EXPIRED_PROOF_UNAVAILABLE",
            diagnostic: error?.diagnostic ?? null, readOnly: true }, 409);
        }
      }

      const authorization = state.paymentPayload?.payload?.authorization;
      return json({
        phase: state.phase, requestSha256: state.requestSha256, signedAt: state.signedAt ?? null,
        httpStatus: state.httpStatus ?? null, paymentPayloadRecorded: !!state.paymentPayload,
        paymentResponsePresent: !!state.paymentResponse, recoveryTokenPresent: !!state.recoveryToken,
        reconciliationEligibility: {
          idempotencyFormat: /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(state.idempotencyKey) ? "uuid" : /^[a-f0-9]{64}$/i.test(state.idempotencyKey) ? "hex64" : "other",
          privateContentReleased: state.result?.private_content_released ?? null,
          receiptProofPresent: !!state.receiptProof,
          requestBytesRecorded: typeof state.requestBytes === "string",
          responseTextRecorded: typeof state.responseText === "string",
          matchingPendingPayload: !state.pendingValidationPayload || stableJson(state.pendingValidationPayload) === stableJson(state.paymentPayload),
        },
        authorization: authorization ? Object.fromEntries(["from", "to", "value", "validAfter", "validBefore", "nonce"].map(key => [key, authorization[key]])) : null,
        gateway: state.gateway ? { success: state.gateway.success === true, transaction: state.gateway.transaction ?? null, network: state.gateway.network ?? null } : null,
        origin: {
          error: state.result?.error ?? null, requestId: state.result?.request_id ?? null,
          purchaseId: state.result?.purchase_id ?? null, receiptId: state.result?.receipt_id ?? null,
          recoveryStatus: state.result?.recovery_status ?? null, billable: state.result?.billing?.billable ?? null,
        },
        scope: "Read-only retained delivery evidence. No signature or recovery capability released. No settlement conclusion or retry authorization.",
      });
    }
    if (path === "/admin/propose-input-revision") {
      if (!this.env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + this.env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
      if (request.method !== "POST") return json({ error: "POST required." }, 405);
      if (!this.canReviewInput(state)) return json({ error: "Only an unsigned blocked input can be proposed for review. Signed attempts are preserved." }, 409);
      const input = await readJson(request);
      if (input.requestSha256 !== state.requestSha256) return json({ error: "Original request changed." }, 409);
      if (typeof input.candidate !== "string" || !input.candidate.trim() || input.candidate.length > 200000
          || typeof input.summary !== "string" || !input.summary.trim() || input.summary.length > 4000) return json({ error: "A complete candidate and review summary are required." }, 400);
      const machine = { ...state.request, candidate_output: input.candidate };
      const requestBytes = stableJson(machine);
      if (new TextEncoder().encode(requestBytes).length > 524288) return json({ error: "Revised request exceeds the size limit." }, 400);
      const requestSha256 = await digest(requestBytes);
      if (requestSha256 === state.requestSha256) return json({ error: "Proposed input is unchanged." }, 409);
      if (state.inputRevision) {
        if (state.inputRevision.requestSha256 !== requestSha256 || state.inputRevision.summary !== input.summary) return json({ error: "Another proposal already awaits review." }, 409);
        return json({ proposed: true, phase: state.phase, requestSha256, newPaymentSubmitted: false });
      }
      const preflight = await this.evaluateInput(machine, requestSha256);
      if (preflight.status !== "NO_KNOWN_BLOCKER") return json({ error: "Proposed input did not pass free preflight. Original input is unchanged.", preflight }, 422);
      state.inputRevision = { request: machine, requestBytes, requestSha256, sourceRequestSha256: state.requestSha256,
        summary: input.summary, preflight, proposedAt: new Date().toISOString() };
      state.phase = "input_review";
      state.note = "A revised input is ready for your review. The original is still active; accepting the revision does not authorize payment.";
      await this.save(state);
      return json({ proposed: true, phase: state.phase, requestSha256, newPaymentSubmitted: false });
    }
    if (path === "/admin/request" && state && equal(request.headers.get("Authorization"), "Bearer " + this.env.FAHCE_BRIDGE_TOKEN)) {
      return json({ requestBytes: state.requestBytes, requestSha256: state.requestSha256, phase: state.phase, challengeFailure: state.challengeFailure ?? null,
        signedDeliveryRecorded: !!state.signedAt, paymentPayloadRecorded: !!state.paymentPayload, validationFailure: state.validationFailure ?? null });
    }
    if (path === "/admin/reconcile-expired-authorization") {
      if (!this.env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + this.env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
      if (request.method !== "POST") return json({ error: "POST required." }, 405);
      if (!state) return json({ error: "Checkout not found." }, 404);
      const expected = await readJson(request, 1024);
      if (expected.requestSha256 !== state.requestSha256 || expected.receiptId !== state.result?.receipt_id) return json({ error: "Original request and receipt must match." }, 409);
      let proof;
      try { proof = await proveExpiredUnusedAuthorization(state); }
      catch { return json({ error: "Expired-unused authorization is not established. Original attempt remains locked." }, 409); }
      const archived = { ...state };
      delete archived.request;
      delete archived.requestBytes;
      const archiveKey = "attempt:" + state.idempotencyKey;
      const reconciliation = { outcome: proof.outcome, checkedAt: proof.checkedAt,
        previousReceiptId: state.result.receipt_id, previousPurchaseId: state.result.purchase_id,
        authorizationSha256: proof.authorizationSha256, originRecoveryStatus: state.result.recovery_status ?? null,
        scope: proof.scope };
      const next = { phase: "input_blocked", request: state.request, requestBytes: state.requestBytes,
        requestSha256: state.requestSha256, draftHash: state.draftHash, buyer: state.buyer,
        accessToken: state.accessToken, createdAt: state.createdAt, idempotencyKey: crypto.randomUUID(),
        previousAttemptKeys: [...(state.previousAttemptKeys ?? []), archiveKey], reconciliation,
        note: "Previous authorization expired unused. The original attempt is archived. A fresh input check and explicit wallet approval are required; no new payment has been made." };
      await this.ctx.storage.transaction(async storage => {
        if (await storage.get(archiveKey)) throw Error("Attempt already archived.");
        await storage.put(archiveKey, { attempt: archived, reconciliation: proof });
        await storage.put("purchase", next);
      });
      await this.screenInput(next);
      return json({ reconciled: true, phase: next.phase, requestSha256: next.requestSha256,
        reconciliation, newPaymentSubmitted: false });
    }
    if (path === "/admin/reconcile-validation" && state && equal(request.headers.get("Authorization"), "Bearer " + this.env.FAHCE_BRIDGE_TOKEN)) {
      if (state.phase !== "unresolved" || state.note !== "Authorization validation failed. No signed request sent; reconcile before retry."
          || state.signedAt || state.paymentPayload || state.pendingValidationPayload || state.httpStatus || state.responseText) return json({ error: "No unsigned pre-delivery failure to reset. Retained signatures must not create a second authorization." }, 409);
      state.validationHistory = [...(state.validationHistory || []), { reconciledAt: new Date().toISOString(), outcome: "NO_SIGNED_DELIVERY", note: state.note }];
      state.phase = "challenge_ready"; state.note = "Previous signature validation failed before any signed delivery. Corrected verifier is ready for wallet approval.";
      await this.save(state); return json({ reconciled: true, signedDelivery: false, phase: state.phase });
    }
    if (path === "/create") {
      if (state) return json({ error: "Checkout already exists." }, 409);
      state = await readJson(request);
      await this.save(state);
      return json({ created: true });
    }
    if (!state || !equal(request.headers.get("Authorization"), "Bearer " + state.accessToken)) return json({ error: "Open the complete private checkout link supplied by your agent." }, 401);
    const status = () => ({ phase: state.phase, buyer: state.buyer, requestSha256: state.requestSha256, requestBytes: new TextEncoder().encode(state.requestBytes).length,
      endpoint: ENDPOINT, amount: "0.15", currency: "USDC", network: NETWORK, recipient: RECIPIENT, asset: ASSET,
      candidate: state.request.candidate_output, evidenceCount: state.request.evidence.length,
      transaction: state.gateway?.transaction ?? null, gatewayReportsSuccess: state.gateway?.success === true,
      httpStatus: state.httpStatus ?? null, result: state.result ?? null, note: state.note ?? null,
      receiptProof: state.receiptProof ?? null, draftHash: state.draftHash, challengeFailure: state.challengeFailure ?? null, preflight: state.preflight ?? null, reconciliation: state.reconciliation ?? null,
      representationRevision: state.representationRevision ?? null,
      savedAuthorization: { canSubmit: this.canSubmitSavedAuthorization(state),
        expiresAt: state.pendingValidationPayload?.payload?.authorization ? String(state.pendingValidationPayload.payload.authorization.validBefore) : null },
      validationFailure: state.phase === "unresolved" && !state.signedAt && state.validationFailure
        ? { code: state.validationFailure.code, checkedAt: state.validationFailure.checkedAt } : null,
      inputRevision: state.inputRevision ? { candidate: state.inputRevision.request.candidate_output,
        requestSha256: state.inputRevision.requestSha256, sourceRequestSha256: state.inputRevision.sourceRequestSha256,
        summary: state.inputRevision.summary, preflight: state.inputRevision.preflight } : null });
    if (request.method === "GET" && path === "/api/status") return json(status());
    if (request.method === "GET" && path === "/api/config") return json({ ...status(), ...await discovery() });
    if (request.method !== "POST") return json({ error: "Not found." }, 404);
    const input = await readJson(request, 65536);
    if (path === "/api/accept-input-revision") {
      const proposal = state.inputRevision;
      if (!this.canReviewInput(state) || state.phase !== "input_review" || !proposal
          || input.acceptRevision !== true || input.sourceRequestSha256 !== state.requestSha256
          || input.requestSha256 !== proposal.requestSha256) return json({ error: "Review and explicitly accept the exact pending revision. No payment authorized." }, 409);
      const preflight = await this.evaluateInput(proposal.request, proposal.requestSha256);
      if (preflight.status !== "NO_KNOWN_BLOCKER") {
        proposal.preflight = preflight;
        await this.save(state);
        return json({ error: "The revised input no longer clears free preflight. Original request unchanged.", preflight }, 422);
      }
      const archiveKey = "input:" + state.idempotencyKey;
      const next = { phase: "ready", request: proposal.request, requestBytes: proposal.requestBytes,
        requestSha256: proposal.requestSha256, draftHash: state.draftHash, buyer: state.buyer,
        accessToken: state.accessToken, createdAt: state.createdAt, idempotencyKey: crypto.randomUUID(),
        previousAttemptKeys: state.previousAttemptKeys ?? [], previousInputKeys: [...(state.previousInputKeys ?? []), archiveKey],
        reconciliation: state.reconciliation ?? null, preflight,
        representationRevision: { sourceRequestSha256: state.requestSha256, requestSha256: proposal.requestSha256,
          acceptedAt: new Date().toISOString(), summary: proposal.summary, evidenceUnchanged: true, scope: "BUYER_REVIEWED_REPRESENTATION" },
        note: "Revised input accepted and free preflight passed. No payment made. Review the policies and separately choose Pay now if you wish to purchase this check." };
      await this.ctx.storage.transaction(async storage => {
        if (await storage.get(archiveKey)) throw Error("Input already archived.");
        await storage.put(archiveKey, state);
        await storage.put("purchase", next);
      });
      state = next;
      return json(status());
    }
    if (path === "/api/preflight") {
      if (!["ready", "challenge_ready", "input_blocked"].includes(state.phase)) return json({ error: "Existing signed or active attempt is preserved. No preflight reset permitted." }, 409);
      await this.screenInput(state);
      return json(status());
    }
    if (path === "/api/challenge") {
      if (state.inputRevision || locked.has(state.phase)) return json({ error: "Existing attempt is active or needs reconciliation. No new authorization permitted." }, 409);
      if (!await this.screenInput(state)) return json({ error: state.note, preflight: state.preflight }, 422);
      const buyer = state.buyer || input.buyer;
      if (!sameAddress(buyer, buyer) || (input.buyer && !sameAddress(input.buyer, buyer))) return json({ error: "A valid, matching buyer wallet is required." }, 400);
      const legal = await discovery();
      if (input.acceptTerms !== true || input.termsHash !== legal.termsHash) return json({ error: "Review and accept the current FAHCE policies." }, 400);
      state = { ...state, phase: "requesting_challenge", buyer };
      await this.save(state);
      const diagnostic = { upstreamStatus: null, paymentRequiredPresent: false };
      try {
        const response = await this.paymentRequest({ method: "POST", body: state.requestBytes, headers: { "Content-Type": "application/json", "FAHCE-Terms-Accepted": legal.termsHash, "Idempotency-Key": state.idempotencyKey } });
        diagnostic.upstreamStatus = response.status;
        diagnostic.paymentRequiredPresent = !!response.headers.get("payment-required");
        if (response.status !== 402) {
          diagnostic.contentType = response.headers.get("content-type");
          diagnostic.server = response.headers.get("server");
          diagnostic.cfRay = response.headers.get("cf-ray");
          try {
            const text = await response.text();
            const title = text.match(/<title[^>]*>([^<]{1,180})<\/title>/i)?.[1];
            if (title) diagnostic.pageTitle = title;
            const body = JSON.parse(text);
            if (typeof body?.error === "string") diagnostic.upstreamCode = body.error.slice(0, 160);
            else if (typeof body?.error?.code === "string") diagnostic.upstreamCode = body.error.code.slice(0, 160);
            const reason = body?.message ?? body?.detail ?? body?.error?.message;
            if (typeof reason === "string") diagnostic.upstreamReason = reason.replace(/0x[a-f0-9]{40}/gi, "[wallet hidden]").slice(0, 300);
          } catch {}
        }
        if (response.status !== 402) throw Error("No challenge");
        const required = decodePaymentRequiredHeader(response.headers.get("payment-required"));
        diagnostic.requirements = required?.accepts?.map(option => ({ scheme: option.scheme, network: option.network, amount: option.amount, maxTimeoutSeconds: option.maxTimeoutSeconds,
          recipientMatches: sameAddress(option.payTo, RECIPIENT), assetMatches: sameAddress(option.asset, ASSET) }));
        selectRequirement(required);
        state = { ...state, phase: "challenge_ready", required, termsHash: legal.termsHash, challengeFailure: null };
        await this.save(state);
        return json({ required, buyer });
      } catch (error) {
        state.phase = "ready";
        state.challengeFailure = diagnostic;
        if (error instanceof PaymentPolicyError) diagnostic.policyError = error.message;
        await this.save(state);
        return json({ error: "A supported payment challenge was not available. No signature sent.", diagnostic }, 502);
      }
    }
    if (path === "/api/authorize") {
      if (state.phase !== "challenge_ready" || !sameAddress(input.buyer, state.buyer)) return json({ error: "Buyer or checkout state mismatch." }, 409);
      if (!await this.screenInput(state)) return json({ error: state.note, preflight: state.preflight }, 422);
      state.phase = "awaiting_wallet"; await this.save(state); return json({ phase: state.phase });
    }
    if (path === "/api/rejected") {
      if (state.phase !== "awaiting_wallet" || input.code !== 4001) return json({ error: "Only an explicit unsigned wallet rejection releases this attempt." }, 409);
      state.phase = "challenge_ready"; await this.save(state); return json(status());
    }
    if (path === "/api/submit-saved-authorization") {
      if (!this.canSubmitSavedAuthorization(state) || input.submitSavedAuthorization !== true
          || input.requestSha256 !== state.requestSha256 || input.acceptTerms !== true || input.termsHash !== state.termsHash
          || input.paymentPayload !== undefined) return json({ error: "No matching saved approval is available for explicit submission. No payment sent." }, 409);
      if (await digest(state.requestBytes) !== state.requestSha256
          || stableJson(JSON.parse(state.requestBytes)) !== stableJson(state.request)) return json({ error: "Prepared request integrity mismatch. No payment sent." }, 409);
      const legal = await discovery();
      if (legal.termsHash !== state.termsHash) return json({ error: "The published policies changed. This saved approval cannot be submitted." }, 409);
      state.preflight = await this.evaluateInput(state.request, state.requestSha256);
      await this.save(state);
      if (state.preflight.status !== "NO_KNOWN_BLOCKER") return json({ error: "The current input check did not clear. Saved approval remains locked; no payment sent." }, 422);
      input.paymentPayload = state.pendingValidationPayload;
    }
    if (path === "/api/pay" || path === "/api/submit-saved-authorization") {
      if (path === "/api/pay" && state.phase !== "awaiting_wallet") return json({ error: "Payment is not authorized or was already submitted. No retry sent." }, 409);
      state.phase = "validating_authorization"; await this.save(state);
      let signatureVerification;
      try {
        const typed = validatePaymentPayload(input.paymentPayload, state.required, state.buyer);
        state.pendingValidationPayload = input.paymentPayload;
        await this.save(state);
        signatureVerification = await this.env.PAYMENT_RELAY.getByName("fahce-us-payment-egress-v1", { locationHint: "enam" }).fetch(new Request("https://internal/verify", {
          method: "POST", headers: { Authorization: "Bearer " + this.env.FAHCE_BRIDGE_TOKEN, "Content-Type": "application/json" },
          body: JSON.stringify({ buyer: state.buyer, typedData: typed, signature: input.paymentPayload.payload.signature }, (_, value) => typeof value === "bigint" ? value.toString() : value),
        })).then(r => r.json());
        if (signatureVerification.valid !== true) throw Error("Signature verification failed");
      } catch {
        state.phase = "unresolved"; state.note = "Authorization validation failed. No signed request sent; reconcile before retry.";
        state.validationFailure = { checkedAt: new Date().toISOString(),
          code: signatureVerification?.code ?? "AUTHORIZATION_CHECK_UNAVAILABLE", verification: signatureVerification ?? null };
        await this.save(state); return json({ error: state.note }, 409);
      }
      state = { ...state, phase: "submitting", paymentPayload: input.paymentPayload, signedAt: new Date().toISOString() };
      await this.save(state);
      try {
        const response = await this.paymentRequest({ method: "POST", body: state.requestBytes, headers: { "Content-Type": "application/json", "FAHCE-Terms-Accepted": state.termsHash, "Idempotency-Key": state.idempotencyKey, "PAYMENT-SIGNATURE": encodePaymentSignatureHeader(state.paymentPayload) } });
        state.httpStatus = response.status;
        state.recoveryToken = response.headers.get("fahce-recovery-token");
        state.paymentResponse = response.headers.get("payment-response");
        await this.save(state);
        const text = await response.text();
        if (new TextEncoder().encode(text).length > 4194304) throw Error("Oversized response");
        state.responseText = text;
        try { state.result = JSON.parse(text); } catch {}
        try { if (state.paymentResponse) state.gateway = decodePaymentResponseHeader(state.paymentResponse); } catch {}
        const received = response.status === 200 && state.result?.schema === "FAHCE_MACHINE_RESPONSE_V1" && state.result.operation === "diagnose";
        state.phase = received ? "response_received" : "unresolved";
        state.note = received ? "FAHCE response received for this submitted request. Inspect the determination; a completed negative result is billable. Gateway settlement and attestation are separate evidence." : "FAHCE did not deliver a completed result. Do not pay again; reconcile this attempt.";
        await this.save(state);
        if (received) {
          try {
            const [trustResponse, keysResponse] = await Promise.all([remote("https://fahce.kinganlogic.com/.well-known/fahce-attestation.json"), remote("https://sharedeus.eus.attest.azure.net/certs")]);
            if (!trustResponse.ok || !keysResponse.ok) throw Error("Trust unavailable");
            state.receiptProof = await verifyReceiptEvidence(state.result, await trustResponse.json(), (await keysResponse.json()).keys);
          } catch { state.receiptProof = { verified: false, scope: "NOT_ESTABLISHED", originalResponsePreserved: true }; }
          await this.save(state);
        }
        return json(status());
      } catch {
        state.phase = "unresolved"; state.note = "Delivery is uncertain after signing. Do not authorize another payment. Evidence retained for reconciliation.";
        await this.save(state); return json({ error: state.note }, 502);
      }
    }
    return json({ error: "Not found." }, 404);
  }
}

// Payment calls originate from this US-placed service rather than from the
// conversation storage object's location. No visitor IP/country is forged.
// Placement hints are best-effort: the real gateway response remains decisive.
// This relay cannot change the URL, terms, request bytes, amount or authorization.
export class FahcePaymentRelay extends DurableObject {
  constructor(ctx, env) { super(ctx, env); this.env = env; }
  async fetch(request) {
    if (!this.env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + this.env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
    const path = new URL(request.url).pathname;
    if (path === "/verify" && request.method === "POST") {
      try {
        const input = await readJson(request, 65536);
        if (!sameAddress(input.buyer, input.buyer) || input.typedData?.domain?.name !== "USD Coin" || input.typedData?.domain?.version !== "2"
            || Number(input.typedData?.domain?.chainId) !== base.id || !sameAddress(input.typedData?.domain?.verifyingContract, ASSET)) return json({ valid: false, code: "DOMAIN_MISMATCH" }, 400);
        const attempts = [];
        for (const rpc of ["https://mainnet.base.org", "https://base-rpc.publicnode.com", "https://base.drpc.org"]) {
          let stage = "chain";
          try {
            const verifier = createPublicClient({ chain: base, transport: http(rpc, { retryCount: 0, timeout: 6000 }) });
            if (await verifier.getChainId() !== base.id) { attempts.push({ provider: new URL(rpc).hostname, code: "CHAIN_MISMATCH" }); continue; }
            stage = "signature";
            const valid = await verifier.verifyTypedData({ ...input.typedData, address: input.buyer, signature: input.signature });
            attempts.push({ provider: new URL(rpc).hostname, valid });
            if (valid) return json({ valid: true, attempts });
          } catch (error) { attempts.push({ provider: new URL(rpc).hostname, stage, causes: verificationError(error) }); }
        }
        const rateLimited = attempts.every(attempt => attempt.causes?.some(cause => cause.httpStatus === 429 || cause.rpcCode === -32005));
        return json({ valid: false, code: rateLimited ? "SIGNATURE_CHECK_RATE_LIMITED"
          : attempts.some(attempt => attempt.valid === false) ? "SIGNATURE_NOT_VERIFIED" : "SIGNATURE_CHECK_UNAVAILABLE", attempts });
      } catch (error) { return json({ valid: false, code: "SIGNATURE_CHECK_UNAVAILABLE", causes: verificationError(error) }); }
    }
    if (path === "/diagnostics") {
      const response = await remote("https://www.cloudflare.com/cdn-cgi/trace");
      const trace = Object.fromEntries((await response.text()).trim().split("\n").map(line => line.split("=")));
      return json({ country: trace.loc, colo: trace.colo, placementHint: "enam", endpoint: ENDPOINT });
    }
    if (path !== "/diagnose" || request.method !== "POST") return json({ error: "Not found." }, 404);
    const body = await request.text();
    if (new TextEncoder().encode(body).length > 524288) return json({ error: "Request too large." }, 413);
    const headers = new Headers();
    for (const name of ["Content-Type", "FAHCE-Terms-Accepted", "Idempotency-Key", "PAYMENT-SIGNATURE"]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    return remote(ENDPOINT, { method: "POST", body, headers });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const inputRevision = url.pathname.match(/^\/v1\/diagnostics\/propose-input-revision\/([a-f0-9]{64})$/);
    if (inputRevision) {
      if (!env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
      if (request.method !== "POST") return json({ error: "POST required." }, 405);
      return env.CHECKOUTS.getByName(inputRevision[1]).fetch(new Request("https://internal/admin/propose-input-revision", {
        method: "POST", headers: { Authorization: request.headers.get("Authorization") }, body: await request.text(),
      }));
    }
    const expiredAuthorization = url.pathname.match(/^\/v1\/diagnostics\/reconcile-expired-authorization\/([a-f0-9]{64})$/);
    if (expiredAuthorization) {
      if (!env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
      if (request.method !== "POST") return json({ error: "POST required." }, 405);
      return env.CHECKOUTS.getByName(expiredAuthorization[1]).fetch(new Request("https://internal/admin/reconcile-expired-authorization", {
        method: "POST", headers: { Authorization: request.headers.get("Authorization") }, body: await request.text(),
      }));
    }
    const paymentEvidence = url.pathname.match(/^\/v1\/diagnostics\/(payment-evidence|expired-authorization-proof|validation-proof)\/([a-f0-9]{64})$/);
    if (paymentEvidence) {
      if (!env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
      if (request.method !== "GET") return json({ error: "Read-only diagnostic." }, 405);
      return env.CHECKOUTS.getByName(paymentEvidence[2]).fetch(new Request("https://internal/admin/" + paymentEvidence[1], { headers: { Authorization: request.headers.get("Authorization") } }));
    }
    if (url.pathname === "/v1/diagnostics/verify" && request.method === "POST" && env.FAHCE_BRIDGE_TOKEN && equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) {
      return env.PAYMENT_RELAY.getByName("fahce-us-payment-egress-v1", { locationHint: "enam" }).fetch(new Request("https://internal/verify", request));
    }
    const reconcile = url.pathname.match(/^\/v1\/diagnostics\/reconcile-validation\/([a-f0-9]{64})$/);
    if (reconcile && request.method === "POST" && env.FAHCE_BRIDGE_TOKEN && equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) {
      return env.CHECKOUTS.getByName(reconcile[1]).fetch(new Request("https://internal/admin/reconcile-validation", { method: "POST", headers: { Authorization: request.headers.get("Authorization") } }));
    }
    if (url.pathname === "/v1/diagnostics/egress" && env.FAHCE_BRIDGE_TOKEN && equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) {
      return env.PAYMENT_RELAY.getByName("fahce-us-payment-egress-v1", { locationHint: "enam" })
        .fetch(new Request("https://internal/diagnostics", { headers: { Authorization: request.headers.get("Authorization") } }));
    }
    const inspect = url.pathname.match(/^\/v1\/diagnostics\/request\/([a-f0-9]{64})$/);
    if (inspect && env.FAHCE_BRIDGE_TOKEN && equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) {
      return env.CHECKOUTS.getByName(inspect[1]).fetch(new Request("https://internal/admin/request", { headers: { Authorization: request.headers.get("Authorization") } }));
    }
    if (url.pathname === "/wallet-api.json") return json({
      service: "Tool Offer Agent FAHCE wallet checkout", protocol: "x402-v2", network: NETWORK, amountAtomicUnits: AMOUNT,
      authentication: "Purchase-specific Bearer capability from the private checkout link. Never publish it.",
      apiBase: "/checkout/{checkout_id}/api", steps: [
        "GET config: review candidate, requestSha256, legalUrls, amount and termsHash.",
        "When phase is input_review, compare candidate with inputRevision.candidate. Explicit POST accept-input-revision: {acceptRevision:true, sourceRequestSha256, requestSha256} adopts only that revision; no wallet or payment action occurs. Refresh config and separately review terms before continuing.",
        "POST challenge: {buyer, acceptTerms:true, termsHash}. Buyer must authorize the exact current terms. Returns required x402 v2 payment requirements.",
        "POST authorize: {buyer}. Persist awaiting_wallet before requesting an EIP-3009 signature.",
        "Sign the returned requirement with an x402 v2 ExactEvmScheme wallet. Do not change merchant, network, token, amount or body.",
        "POST pay: {paymentPayload}. Exactly one signed delivery attempt; ambiguity locks checkout.",
        "Only when status.savedAuthorization.canSubmit is true, the buyer may explicitly POST submit-saved-authorization: {submitSavedAuthorization:true, requestSha256, acceptTerms:true, termsHash}. This makes the FIRST paid delivery of the retained approval after fresh checks; it never opens a wallet or creates another signature. Never automate it, and never use it after any signed delivery.",
        "GET status: retrieve phase, HTTP status, result, receiptProof and separate gateway transaction evidence. No automatic paid retries.",
        "Only explicit pre-sign wallet rejection may POST rejected: {code:4001}. Never use this after signing."
      ], supportedWallets: "EOA and compatible ERC-1271 smart wallets on Base, subject to actual signature verification. No private keys accepted by this service.",
      separateFromFetchPaymentProtocol: true
    });
    if (url.pathname === "/v1/diagnostics" && equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) {
      try {
        const response = await remote(DISCOVERY);
        let document; try { document = await response.json(); } catch {}
        return json({ upstreamStatus: response.status, schema: document?.schema ?? null, legalPublished: !!document?.legal_documents?.publication_hash,
          price: document?.pricing_terms?.prices?.diagnose?.atomic_units ?? null, paymentProtocol: document?.payment?.protocol ?? null });
      } catch (error) { return json({ upstreamStatus: "FETCH_FAILED", errorClass: error?.name, errorMessage: String(error?.message).slice(0, 200) }); }
    }
    if (url.pathname === "/health") return json({ service: "Tool Offer Agent FAHCE wallet checkout", status: "ready", payment: "x402-v2", network: NETWORK, amountUSDC: "0.15", supported: "Compatible EIP-3009 wallets, including ERC-1271 smart wallets where verification succeeds" });
    if (url.pathname === "/v1/checkouts" && request.method === "POST") {
      if (!env.FAHCE_BRIDGE_TOKEN || !equal(request.headers.get("Authorization"), "Bearer " + env.FAHCE_BRIDGE_TOKEN)) return json({ error: "Unauthorized." }, 401);
      try {
        const input = await readJson(request);
        const machine = input.request;
        const requestBytes = stableJson(machine);
        if (machine?.schema !== "FAHCE_MACHINE_REQUEST_V1" || typeof machine.candidate_output !== "string" || !machine.candidate_output.length || machine.candidate_output.length > 200000 || !Array.isArray(machine.evidence) || machine.evidence.length > 12 || new TextEncoder().encode(requestBytes).length > 524288
            || !/^[a-f0-9]{64}$/.test(input.draftHash) || !/^[a-f0-9]{64}$/.test(input.checkoutKey)
            || machine.evidence.some(item => typeof item.text !== "string" || item.text.length > 200000 || typeof item.id !== "string" || typeof item.source_label !== "string" || item.source_label.length > 160)
            || (input.buyer && !sameAddress(input.buyer, input.buyer))) return json({ error: "Invalid request." }, 400);
        // The authenticated agent owns checkout identity. Retries recover the same checkout, never a new purchase.
        const id = input.checkoutKey;
        const accessToken = await digest(env.FAHCE_BRIDGE_TOKEN + ":checkout:" + id);
        const stub = env.CHECKOUTS.getByName(id);
        const state = { phase: "ready", request: machine, requestBytes, requestSha256: await digest(requestBytes), draftHash: input.draftHash,
          buyer: input.buyer || null, accessToken, idempotencyKey: crypto.randomUUID(), createdAt: new Date().toISOString() };
        const created = await stub.fetch(new Request("https://internal/create", { method: "POST", body: JSON.stringify(state) }));
        if (!created.ok && created.status !== 409) throw Error("Storage unavailable");
        let current = await stub.fetch(new Request("https://internal/api/status", { headers: { Authorization: "Bearer " + accessToken } })).then(r => r.json());
        if (current.requestSha256 !== state.requestSha256 || current.draftHash !== state.draftHash) return json({ error: "Checkout key conflicts with a different draft." }, 409);
        if (["ready", "challenge_ready", "input_blocked"].includes(current.phase)) {
          current = await stub.fetch(new Request("https://internal/api/preflight", { method: "POST", headers: { Authorization: "Bearer " + accessToken }, body: "{}" })).then(response => response.json());
        }
        return json({ id, accessToken, requestSha256: state.requestSha256, draftHash: state.draftHash, url: url.origin + "/checkout/" + id + "/#access=" + accessToken });
      } catch { return json({ error: "Checkout preparation unavailable. No payment made." }, 502); }
    }
    const match = url.pathname.match(/^\/checkout\/([a-f0-9]{64})\/(.*)$/);
    if (match) {
      if (!match[2]) {
        const response = await env.ASSETS.fetch(new Request(url.origin + "/", request));
        const headers = new Headers(response.headers);
        headers.set("Cache-Control", "no-store");
        headers.set("Referrer-Policy", "no-referrer");
        headers.set("X-Content-Type-Options", "nosniff");
        headers.set("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://mainnet.base.org https://rpc.wallet.coinbase.com https://chain-proxy.wallet.coinbase.com; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
        return new Response(response.body, { status: response.status, headers });
      }
      if (match[2].startsWith("api/")) {
        const origin = request.headers.get("Origin");
        if (origin && origin !== url.origin) return json({ error: "Cross-origin request rejected." }, 403);
        const headers = new Headers(request.headers);
        const rewritten = new Request("https://internal/" + match[2], { method: request.method, headers, ...(request.method === "POST" ? { body: request.body, duplex: "half" } : {}) });
        return env.CHECKOUTS.getByName(match[1]).fetch(rewritten);
      }
    }
    if (["/app.js", "/bootstrap.js", "/style.css"].includes(url.pathname)) {
      const response = await env.ASSETS.fetch(request);
      const headers = new Headers(response.headers); headers.set("Cache-Control", "no-store"); headers.set("Referrer-Policy", "no-referrer");
      return new Response(response.body, { status: response.status, headers });
    }
    return json({ error: "Use the private checkout link supplied by Tool Offer Agent." }, 404);
  },
};
