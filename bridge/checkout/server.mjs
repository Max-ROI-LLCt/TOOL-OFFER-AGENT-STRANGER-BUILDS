import { createHash, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createPublicClient, http } from "viem";
import { base } from "viem/chains";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { AMOUNT, ASSET, DISCOVERY, ENDPOINT, NETWORK, PaymentPolicyError, RECIPIENT, sameAddress, selectRequirement, validatePaymentPayload } from "./payment-policy.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const LEGAL_NAMES = ["terms", "refunds", "privacy", "acceptable-use", "data-handling", "security"];
const LOCKED_PHASES = new Set(["awaiting_wallet", "validating_authorization", "submitting", "unresolved", "response_received"]);
const verificationClient = createPublicClient({ chain: base, transport: http("https://mainnet.base.org", { retryCount: 0, timeout: 15000 }) });

export class SafeError extends Error {
  constructor(message, status = 400) {
    super(message);
    this.status = status;
  }
}

export async function limitedText(stream, limit) {
  const chunks = [];
  let size = 0;
  for await (const chunk of stream) {
    const bytes = Buffer.from(chunk);
    size += bytes.length;
    if (size > limit) throw new SafeError("Response or request exceeds the local safety limit.", 413);
    chunks.push(bytes);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function atomicState(path, value) {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = path + "." + randomUUID() + ".tmp";
  const descriptor = openSync(temporary, "wx", 0o600);
  try {
    writeFileSync(descriptor, JSON.stringify(value, null, 2) + "\n");
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
  renameSync(temporary, path);
  const directory = openSync(dirname(path), "r");
  try { fsyncSync(directory); } finally { closeSync(directory); }
}

export function createPurchase({ requestBytes, buyer, statePath, fetcher = fetch, signatureVerifier = parameters => verificationClient.verifyTypedData(parameters) }) {
  if (!sameAddress(buyer, buyer)) throw new Error("A valid intended buyer address is required.");
  const request = JSON.parse(requestBytes.toString("utf8"));
  if (request.schema !== "FAHCE_MACHINE_REQUEST_V1" || typeof request.candidate_output !== "string"
    || !request.candidate_output.length || request.candidate_output.length > 200000
    || !Array.isArray(request.evidence) || request.evidence.length > 12 || requestBytes.length > 524288) {
    throw new Error("The saved purchase request is not valid.");
  }
  const requestSha256 = createHash("sha256").update(requestBytes).digest("hex");
  let state = existsSync(statePath) ? JSON.parse(readFileSync(statePath, "utf8")) : {
    phase: "ready", buyer, requestSha256, idempotencyKey: randomUUID(), createdAt: new Date().toISOString(),
  };
  if (state.requestSha256 !== requestSha256 || !sameAddress(state.buyer, buyer)) {
    throw new Error("Existing purchase state belongs to another request or wallet; reconcile it before starting another purchase.");
  }
  if (state.phase === "requesting_challenge") state.phase = "ready";
  if (["awaiting_wallet", "validating_authorization", "submitting"].includes(state.phase)) state.phase = "unresolved";
  atomicState(statePath, state);
  const update = changes => {
    const next = { ...state, ...changes, updatedAt: new Date().toISOString() };
    atomicState(statePath, next);
    state = next;
  };
  const remote = (url, options = {}) => fetcher(url, {
    ...options, redirect: "error", signal: AbortSignal.timeout(45000),
  });
  async function discovery() {
    const response = await remote(DISCOVERY);
    if (response.status !== 200) throw new SafeError("Current FAHCE terms are unavailable. Nothing authorized.", 503);
    const document = JSON.parse(await limitedText(response.body, 262144));
    const legal = document.legal_documents;
    if (!/^[a-f0-9]{64}$/.test(legal?.publication_hash)
      || document.pricing_terms?.prices?.diagnose?.atomic_units !== AMOUNT
      || document.pricing_terms?.prices?.diagnose?.scheme !== "exact"
      || document.payment?.protocol !== "x402-v2") {
      throw new SafeError("FAHCE's published purchase configuration changed. Review is required.", 409);
    }
    for (const name of LEGAL_NAMES) {
      if (legal.urls?.[name] !== "https://fahce.kinganlogic.com/legal/" + name) {
        throw new SafeError("Unexpected legal-document location. Nothing authorized.", 409);
      }
    }
    return { termsHash: legal.publication_hash, legalUrls: legal.urls };
  }
  function status() {
    let transaction = null;
    if (/^0x[0-9a-f]{64}$/i.test(state.gateway?.transaction)) transaction = state.gateway.transaction;
    return {
      phase: state.phase, buyer, requestSha256, requestBytes: requestBytes.length,
      endpoint: ENDPOINT, amount: "0.15", currency: "USDC", network: NETWORK,
      recipient: RECIPIENT, asset: ASSET, candidate: request.candidate_output,
      evidenceCount: request.evidence.length, transaction,
      gatewayReportsSuccess: state.gateway?.success === true,
      httpStatus: state.httpStatus ?? null, result: state.result ?? null,
      note: state.note ?? null,
    };
  }
  async function challenge(input) {
    if (LOCKED_PHASES.has(state.phase) || state.phase === "requesting_challenge") {
      throw new SafeError("This purchase is already active or needs reconciliation. No new authorization allowed.", 409);
    }
    if (input.acceptTerms !== true) throw new SafeError("Review and accept the current FAHCE policies before continuing.");
    update({ phase: "requesting_challenge" });
    try {
      const legal = await discovery();
      if (input.termsHash !== legal.termsHash) throw new SafeError("FAHCE policies changed. Reload and review the current publication.", 409);
      const response = await remote(ENDPOINT, {
        method: "POST", body: requestBytes,
        headers: { "Content-Type": "application/json", "FAHCE-Terms-Accepted": legal.termsHash, "Idempotency-Key": state.idempotencyKey },
      });
      const text = await limitedText(response.body, 262144);
      if (response.status !== 402) throw new SafeError("The unsigned request did not return a payment challenge. No wallet signature was sent.", 502);
      const header = response.headers.get("payment-required");
      const required = header ? decodePaymentRequiredHeader(header) : JSON.parse(text);
      selectRequirement(required);
      update({ phase: "challenge_ready", required, termsHash: legal.termsHash, termsAcceptedAt: new Date().toISOString(), note: null });
      return { required };
    } catch (error) {
      update({ phase: "ready" });
      if (error instanceof SafeError) throw error;
      if (error instanceof PaymentPolicyError) throw new SafeError(error.message, 502);
      throw new SafeError("Unable to obtain a supported FAHCE payment challenge. No signature was sent.", 502);
    }
  }
  function beginAuthorization(input) {
    if (state.phase !== "challenge_ready" || !sameAddress(input.buyer, buyer)) {
      throw new SafeError("The wallet or purchase state does not match the reviewed payment.", 409);
    }
    update({ phase: "awaiting_wallet" });
    return { phase: state.phase };
  }
  function rejected(input) {
    if (state.phase !== "awaiting_wallet" || input.code !== 4001) throw new SafeError("Only an explicit unsigned wallet rejection can release this attempt.", 409);
    update({ phase: "challenge_ready", note: "Wallet request rejected; no signature submitted." });
    return status();
  }
  async function pay(input) {
    if (state.phase !== "awaiting_wallet") throw new SafeError("Payment is already submitted, unresolved, or not authorized. No retry sent.", 409);
    update({ phase: "validating_authorization" });
    try {
      const typedData = validatePaymentPayload(input.paymentPayload, state.required, buyer);
      const valid = await signatureVerifier({ ...typedData, address: buyer, signature: input.paymentPayload.payload.signature });
      if (!valid) throw new Error("Signature does not belong to the approved buyer.");
    } catch {
      update({ phase: "unresolved", note: "Signature validation failed; no signed request was sent. Review before another authorization." });
      throw new SafeError(state.note, 409);
    }
    update({ phase: "submitting", paymentPayload: input.paymentPayload, signedAt: new Date().toISOString() });
    try {
      const response = await remote(ENDPOINT, {
        method: "POST", body: requestBytes,
        headers: {
          "Content-Type": "application/json", "FAHCE-Terms-Accepted": state.termsHash,
          "Idempotency-Key": state.idempotencyKey,
          "PAYMENT-SIGNATURE": encodePaymentSignatureHeader(state.paymentPayload),
        },
      });
      const recoveryToken = response.headers.get("fahce-recovery-token");
      const paymentResponse = response.headers.get("payment-response");
      update({ httpStatus: response.status, recoveryToken, paymentResponse });
      const text = await limitedText(response.body, 4194304);
      update({ responseText: text });
      let result = null;
      let gateway = null;
      try { result = JSON.parse(text); } catch {}
      try { if (paymentResponse) gateway = decodePaymentResponseHeader(paymentResponse); } catch {}
      const received = response.status === 200 && result?.schema === "FAHCE_MACHINE_RESPONSE_V1" && result.operation === "diagnose";
      update({
        phase: received ? "response_received" : "unresolved", result, gateway,
        note: received
          ? "Result received. Attestation/input binding and on-chain settlement have not been independently verified. No result is attached to the hosted draft."
          : "The signed request has an uncertain or unsuccessful result. Do not pay again; preserve this attempt for reconciliation.",
      });
      return status();
    } catch {
      update({ phase: "unresolved", note: "Delivery is uncertain after signing. Do not pay again. Payment evidence is retained privately for reconciliation." });
      throw new SafeError(state.note, 502);
    }
  }
  return { status, discovery, challenge, beginAuthorization, rejected, pay };
}

export function createApprovalServer({ purchase, accessToken, allowedHosts, allowedOrigins }) {
  const accessDigest = createHash("sha256").update("Bearer " + accessToken).digest();
  const staticFiles = { "/": ["index.html", "text/html"], "/bootstrap.js": ["bootstrap.js", "text/javascript"], "/app.js": ["app.js", "text/javascript"], "/style.css": ["style.css", "text/css"] };
  return createServer(async (request, response) => {
    const headers = {
      "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://mainnet.base.org https://rpc.wallet.coinbase.com https://chain-proxy.wallet.coinbase.com; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
      "X-Frame-Options": "DENY",
    };
    function send(code, value, type = "application/json") {
      response.writeHead(code, { ...headers, "Content-Type": type + "; charset=utf-8" });
      response.end(type === "application/json" ? JSON.stringify(value) : value);
    }
    try {
      if (!allowedHosts.has(request.headers.host)) throw new SafeError("Unrecognized request host.", 403);
      const origin = request.headers.origin;
      if ((origin && !allowedOrigins.has(origin)) || (request.method === "POST" && !origin)) {
        throw new SafeError("Unrecognized request origin.", 403);
      }
      const path = new URL(request.url, "http://localhost").pathname;
      if (request.method === "GET" && staticFiles[path]) {
        const [file, type] = staticFiles[path];
        return send(200, readFileSync(join(HERE, "public", file)), type);
      }
      const incoming = createHash("sha256").update(request.headers.authorization ?? "").digest();
      if (!timingSafeEqual(incoming, accessDigest)) throw new SafeError("Open the private approval link printed by the server.", 401);
      if (request.method === "GET" && path === "/api/status") return send(200, purchase.status());
      if (request.method === "GET" && path === "/api/config") return send(200, { ...purchase.status(), ...await purchase.discovery() });
      if (request.method !== "POST") throw new SafeError("Not found.", 404);
      if (request.headers["content-type"] !== "application/json") throw new SafeError("JSON is required.", 415);
      const input = JSON.parse(await limitedText(request, 65536));
      const actions = { "/api/challenge": purchase.challenge, "/api/authorize": purchase.beginAuthorization, "/api/rejected": purchase.rejected, "/api/pay": purchase.pay };
      if (!actions[path]) throw new SafeError("Not found.", 404);
      send(200, await actions[path](input));
    } catch (error) {
      send(error instanceof SafeError ? error.status : 500, { error: error instanceof SafeError ? error.message : "Local processing failed. Check purchase status before continuing; do not authorize another payment." });
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT ?? 8787);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("PORT must be 1024–65535.");
  const folder = resolve(HERE, "../data/fahce-purchase");
  const manifest = JSON.parse(readFileSync(join(folder, "manifest.json"), "utf8"));
  const requestBytes = readFileSync(join(folder, "request.json"));
  if (createHash("sha256").update(requestBytes).digest("hex") !== manifest.request_sha256) throw new Error("Purchase request changed after preparation.");
  const attempt = process.env.FAHCE_PURCHASE_ATTEMPT;
  if (attempt && !/^[a-z0-9_-]{1,80}$/.test(attempt)) throw new Error("Invalid purchase attempt name.");
  const stateFolder = attempt ? join(HERE, "state", attempt) : join(HERE, "state");
  mkdirSync(stateFolder, { recursive: true, mode: 0o700 });
  const lockPath = join(stateFolder, "server.lock");
  const lock = openSync(lockPath, "wx", 0o600);
  writeFileSync(lock, String(process.pid));
  closeSync(lock);
  process.once("exit", () => { try { unlinkSync(lockPath); } catch {} });
  const purchase = createPurchase({ requestBytes, buyer: manifest.intended_buyer, statePath: join(stateFolder, "purchase.json") });
  const accessToken = randomBytes(32).toString("hex");
  const allowedHosts = new Set(["localhost:" + port, "127.0.0.1:" + port]);
  const allowedOrigins = new Set([...allowedHosts].map(host => "http://" + host));
  let browserOrigin = "http://127.0.0.1:" + port;
  const codespace = process.env.CODESPACE_NAME;
  const domain = process.env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN;
  if (codespace && domain && /^[a-z0-9-]+$/.test(codespace) && /^[a-z0-9.-]+$/.test(domain)) {
    const host = codespace + "-" + port + "." + domain;
    allowedHosts.add(host);
    browserOrigin = "https://" + host;
    allowedOrigins.add(browserOrigin);
  }
  const server = createApprovalServer({ purchase, accessToken, allowedHosts, allowedOrigins });
  server.listen(port, "127.0.0.1", () => {
    console.log("Private approval page: " + browserOrigin + "/#access=" + accessToken);
    console.log("Keep the forwarded port PRIVATE. No payment happens until the user accepts the terms and approves in their wallet.");
  });
  process.once("SIGINT", () => server.close(() => process.exit(0)));
  process.once("SIGTERM", () => server.close(() => process.exit(0)));
}
