// Derived from FAHCE public receipt verifier fetched 2026-10-31.
// src/verification/verify-receipt.ts


// src/worker/auth/crypto.ts
async function sha256Hex(data) {
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data instanceof Uint8Array ? data : new Uint8Array(data);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// src/worker/cases/result-contract.ts
var LEGACY_RESULT_HASH_SCHEME = "SHA256_CANONICAL_JSON_RESULT_WITH_EMPTY_RESULT_HASH_V1";
var RESULT_HASH_SCHEME = "SHA256_SORTED_JSON_RESULT_WITH_EMPTY_RESULT_HASH_V2";

// src/worker/integrations/npl-preflight.ts
var MAX_PAYLOAD_BYTES = 65536;
function canonicalJson(value, maxBytes = MAX_PAYLOAD_BYTES) {
  let nodes = 0;
  let bytes = 0;
  const parts = [];
  function emit(part) {
    bytes += new TextEncoder().encode(part).byteLength;
    if (bytes > maxBytes) throw new Error("PAYLOAD_TOO_LARGE");
    parts.push(part);
  }
  function serialize(v, depth) {
    if (++nodes > 2e4 || depth > 32) throw new Error("PAYLOAD_COMPLEXITY_EXCEEDED");
    if (v === null || typeof v === "boolean") {
      emit(JSON.stringify(v));
      return;
    }
    if (typeof v === "string") {
      if (v.length > maxBytes) throw new Error("PAYLOAD_TOO_LARGE");
      emit(JSON.stringify(v));
      return;
    }
    if (typeof v === "number" && Number.isFinite(v)) {
      emit(JSON.stringify(v));
      return;
    }
    if (Array.isArray(v)) {
      emit("[");
      for (let i = 0; i < v.length; i++) {
        if (i) emit(",");
        serialize(v[i], depth + 1);
      }
      emit("]");
      return;
    }
    if (typeof v !== "object" || !v || Object.getPrototypeOf(v) !== Object.prototype) throw new Error("JSON_REQUIRED");
    emit("{");
    Object.keys(v).sort().forEach((key, index) => {
      if (index) emit(",");
      emit(JSON.stringify(key));
      emit(":");
      serialize(v[key], depth + 1);
    });
    emit("}");
  }
  serialize(value, 0);
  return parts.join("");
}

// src/worker/http/json-members.ts
function duplicateNestedMember(raw) {
  JSON.parse(raw);
  const stack = [];
  let previous = "";
  for (const [token] of raw.matchAll(/"(?:[^"\\]|\\[\s\S])*"|[{}\[\]:,]/g)) {
    if (token === "{") stack.push(/* @__PURE__ */ new Set());
    else if (token === "[") stack.push(null);
    else if (token === "}" || token === "]") stack.pop();
    else if (token === ":" && previous.startsWith('"')) {
      const names = stack.at(-1);
      const name = JSON.parse(previous);
      if (names?.has(name)) return name;
      names?.add(name);
    }
    previous = token;
  }
  return null;
}

// src/worker/http/safe-json.ts
function unsafeJsonField(value) {
  const stack = [value];
  let visited = 0;
  while (stack.length) {
    const node = stack.pop();
    if (!node || typeof node !== "object") continue;
    if (++visited > 1e4) return "__excessive_structure__";
    for (const key of Object.keys(node)) {
      if (key === "__proto__" || key === "constructor" || key === "prototype") return key;
      stack.push(node[key]);
    }
  }
  return null;
}

// src/worker/machine/attestation-protocol.ts
var MAA_ISSUER = "https://sharedeus.eus.attest.azure.net";
var ATTESTATION_SCHEMA = "FAHCE_MACHINE_ATTESTATION_V1";
var RESULT_BINDING_SCHEMA = "FAHCE_MACHINE_RESULT_BINDING_V1";
var ATTESTED_HASH_SCHEME = "SHA256_SORTED_JSON_RESPONSE_WITHOUT_ATTESTATION_V3";
var CASE_ATTESTED_HASH_SCHEME = "SHA256_SORTED_JSON_RESULT_WITHOUT_ATTESTATION_V3";
var MAX_ATTESTED_BYTES = 4 * 1024 * 1024;
var MAX_ATTESTED_WIRE_BYTES = 6 * 1024 * 1024;
var encoder = new TextEncoder();
function protocolError(code) {
  throw new Error("MACHINE_ATTESTATION_" + code);
}
var canonical = (value) => canonicalJson(value, MAX_ATTESTED_BYTES);
function b64url(bytes) {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function fromB64url(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) protocolError("ENCODING_INVALID");
  const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
  const bytes = Uint8Array.from(raw, (c) => c.charCodeAt(0));
  if (b64url(bytes) !== value) protocolError("ENCODING_INVALID");
  return bytes;
}
function protocolJson(raw, maxBytes = MAX_ATTESTED_BYTES) {
  if (encoder.encode(raw).byteLength > maxBytes || duplicateNestedMember(raw)) protocolError("JSON_INVALID");
  const value = JSON.parse(raw);
  if (!value || typeof value !== "object" || Array.isArray(value) || unsafeJsonField(value)) protocolError("JSON_INVALID");
  return value;
}
var hex64 = (value) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
var exactKeys = (value, names) => Object.keys(value).sort().join() === names.slice().sort().join();
function parseAttestationPolicy(raw) {
  if (!raw) protocolError("POLICY_REQUIRED");
  const policy = protocolJson(raw);
  if (!exactKeys(policy, ["schema", "origin", "maa_issuer", "hostdata_sha256", "image_sha256", "engine_version", "gateway_public_key", "valid_from"]) || policy.schema !== "FAHCE_MACHINE_ATTESTATION_POLICY_V1" || policy.maa_issuer !== MAA_ISSUER || !hex64(policy.hostdata_sha256) || !hex64(policy.image_sha256) || typeof policy.engine_version !== "string" || !policy.engine_version || policy.engine_version.length > 200 || !Number.isFinite(Date.parse(policy.valid_from))) protocolError("POLICY_INVALID");
  const origin = new URL(policy.origin);
  if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password || origin.search || origin.hash || origin.pathname !== "/") protocolError("ORIGIN_INVALID");
  if (policy.origin !== origin.origin) protocolError("ORIGIN_INVALID");
  const key = policy.gateway_public_key;
  if (!key || !exactKeys(key, ["kty", "crv", "x"]) || key.kty !== "OKP" || key.crv !== "Ed25519" || typeof key.x !== "string" || fromB64url(key.x).length !== 32) protocolError("GATEWAY_KEY_INVALID");
  return policy;
}
async function boundedJson(response, maxBytes = MAX_ATTESTED_WIRE_BYTES) {
  if (!response.ok || !response.body) protocolError("UPSTREAM_UNAVAILABLE");
  const reader = response.body.getReader();
  const parts = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) protocolError("UPSTREAM_TOO_LARGE");
      parts.push(value);
    }
  } finally {
    await reader.cancel();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    bytes.set(part, offset);
    offset += part.length;
  }
  return protocolJson(new TextDecoder("utf-8", { fatal: true }).decode(bytes), maxBytes);
}
async function verifyMaaBinding(token, binding, policy, keys, at = Date.now() / 1e3) {
  if (typeof token !== "string" || token.length > 32768) protocolError("TOKEN_INVALID");
  const parts = token.split(".");
  if (parts.length !== 3) protocolError("TOKEN_INVALID");
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const header = protocolJson(decoder.decode(fromB64url(parts[0])));
  const claims = protocolJson(decoder.decode(fromB64url(parts[1])));
  if (!exactKeys(header, header.typ === void 0 ? ["alg", "kid", "jku"] : ["alg", "kid", "jku", "typ"]) || header.alg !== "RS256" || header.typ !== void 0 && header.typ !== "JWT" || header.jku !== MAA_ISSUER + "/certs") protocolError("SIGNER_INVALID");
  const matches = keys.filter((key2) => key2.kid === header.kid);
  if (matches.length !== 1) protocolError("SIGNER_UNTRUSTED");
  const material = matches[0];
  if (material.kty !== "RSA" || typeof material.n !== "string" || typeof material.e !== "string" || fromB64url(material.n).length < 256 || material.d !== void 0) protocolError("SIGNER_INVALID");
  const key = await crypto.subtle.importKey("jwk", { kty: "RSA", n: material.n, e: material.e }, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  if (!await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, fromB64url(parts[2]), encoder.encode(parts[0] + "." + parts[1]))) protocolError("SIGNATURE_INVALID");
  if (claims.iss !== MAA_ISSUER || claims["x-ms-attestation-type"] !== "sevsnpvm" || claims["x-ms-compliance-status"] !== "azure-compliant-uvm" || claims["x-ms-sevsnpvm-is-debuggable"] !== false || claims["x-ms-sevsnpvm-hostdata"] !== policy.hostdata_sha256) protocolError("WORKLOAD_MISMATCH");
  if (claims.aud !== void 0) protocolError("AUDIENCE_UNEXPECTED");
  if (![claims.iat, claims.nbf, claims.exp, binding.issued_at].every((v) => typeof v === "number" && Number.isSafeInteger(v)) || Number(claims.iat) > at + 5 || Number(claims.iat) < at - 120 || Number(claims.nbf) > at + 5 || Number(claims.exp) <= at || Math.abs(Number(claims.iat) - binding.issued_at) > 30 || binding.issued_at < at - 120 || binding.issued_at > at + 5 || Number(claims.iat) * 1e3 < Date.parse(policy.valid_from)) protocolError("TOKEN_NOT_CURRENT");
  if (binding.engine_version !== policy.engine_version || canonical(claims["x-ms-runtime"]) !== canonical(binding) || claims["x-ms-sevsnpvm-reportdata"] !== await sha256Hex(canonical(binding)) + "0".repeat(64)) protocolError("RUNTIME_BINDING_MISMATCH");
}
async function fetchMaaKeys() {
  const response = await fetch(MAA_ISSUER + "/certs", { redirect: "manual", signal: AbortSignal.timeout(1e4) });
  const value = await boundedJson(response, 131072);
  if (!Array.isArray(value.keys) || value.keys.length < 1 || value.keys.length > 32) protocolError("TRUST_KEYS_UNAVAILABLE");
  return value.keys;
}

// src/shared/signing-evidence.ts
var SIGNING_SCOPE_TEXT = "OCI artifact signing, Microsoft-signed runtime attestation, application receipts and payment settlement are separate evidence. OCI verification applies only to its exact artifact digest and trusted signing identity; it does not establish source/build provenance, deployment, external execution or permission to act. The downloaded receipt verifier checks runtime evidence, not OCI signatures. See /attestation for the dated, digest-scoped signing record and verifier limits.";
var HISTORICAL_OCI_SIGNING_EVIDENCE = {
  schema: "FAHCE_OCI_SIGNING_EVIDENCE_V1",
  repository: "kinganfahcece22c4.azurecr.io/fahce-core/validation",
  artifact_digest: "sha256:5e6e6f1305a40312827719478dc73e258f1dfbff94d1d825907d89f46bad2776",
  artifact_media_type: "application/vnd.oci.image.index.v1+json",
  signature_manifest_digest: "sha256:995726c7a1a96af44f50096ac11532914a938cb978bd3699a49f6a221df763f1",
  signed_at: "2026-10-23T13:38:05Z",
  verified_at: "2026-10-28T05:49:47.648Z",
  verification: "STRICT_SUCCESS",
  verifier: "Notation 1.3.2",
  trust_model: "FAHCE_ORGANIZATIONAL_PRIVATE_TRUST",
  trusted_identity: "x509.subject: CN=tlogandavisgmail.onmicrosoft.com, O=tlogandavisgmail.onmicrosoft.com, OU=FAHCE, S=Alabama, C=US",
  signing_root_sha256: "d549dc2314f7a16e496a515491b273bc9c098e40a070d61ef1602870f0c402d8",
  timestamp_root_sha256: "5367f20c7ade0e2bca790915056d086b720c33c1fa2a2661acf787e3292e1270",
  verification_policy_sha256: "09076380d1809682318d70239c10eb14c4abe169e8ee473bfe73ccb78bd13891",
  scope: SIGNING_SCOPE_TEXT,
  freshness: "Dated verification of the named artifact, not continuous verification or approval of other digests. Registry reads require their own authorized access.",
  historical_f10: { artifact_digest: "sha256:7ec647309708312007e86bdc99c25075d2275717c01d0a3a70c9514eb7a57d19", evidence: "Retained September 1, 2026 owner-returned strict PrivateTrust verification; preserved as a separate historical accomplishment, not transferred to this artifact." }
};
var OCI_SIGNING_EVIDENCE = { ...{
  "schema": "FAHCE_OCI_SIGNING_EVIDENCE_V1",
  "repository": "kinganfahcece22c4.azurecr.io/fahce-core/validation",
  "artifact_digest": "sha256:8a96a0af60e2c3a992ba431262463eb45493c0edcd6dce40f54867c616a1e6fa",
  "artifact_media_type": "application/vnd.oci.image.manifest.v1+json",
  "signature_manifest_digest": "sha256:dc96a6ea58883bffb73b2390fa12e5f34b373965b38e8d4faa3539754b6ce67f",
  "signed_at": "2026-10-31T10:04:00Z",
  "verified_at": "2026-10-31T10:04:09.408Z",
  "verification": "STRICT_SUCCESS",
  "verifier": "Notation 1.3.2",
  "trust_model": "FAHCE_ORGANIZATIONAL_PRIVATE_TRUST",
  "trusted_identity": "x509.subject: CN=tlogandavisgmail.onmicrosoft.com, O=tlogandavisgmail.onmicrosoft.com, OU=FAHCE, S=Alabama, C=US",
  "signing_root_sha256": "d549dc2314f7a16e496a515491b273bc9c098e40a070d61ef1602870f0c402d8",
  "timestamp_root_sha256": "5367f20c7ade0e2bca790915056d086b720c33c1fa2a2661acf787e3292e1270",
  "verification_policy_sha256": "09076380d1809682318d70239c10eb14c4abe169e8ee473bfe73ccb78bd13891",
  "freshness": "Dated exact-artifact verification, not evidence of deployment or universal public trust."
}, scope: SIGNING_SCOPE_TEXT, historical_artifacts: [HISTORICAL_OCI_SIGNING_EVIDENCE], historical_f10: { artifact_digest: "sha256:7ec647309708312007e86bdc99c25075d2275717c01d0a3a70c9514eb7a57d19", evidence: "Retained September 1, 2026 owner-returned strict PrivateTrust verification; preserved as a separate historical accomplishment, not transferred to this artifact." } };

// src/worker/cases/receipt-hash.ts
async function hashResultPayload(result) {
  const canonical2 = {
    ...result,
    receipt: { ...result.receipt, result_hash: "" }
  };
  if (result.receipt.hash_scheme === LEGACY_RESULT_HASH_SCHEME) return sha256Hex(JSON.stringify(canonical2));
  if (result.receipt.hash_scheme === CASE_ATTESTED_HASH_SCHEME) {
    const { attestation: _proof, ...payload } = canonical2;
    return sha256Hex(canonicalJson(JSON.parse(JSON.stringify(payload)), 10485760));
  }
  if (result.receipt.hash_scheme !== RESULT_HASH_SCHEME) throw new Error("RESULT_HASH_SCHEME_UNSUPPORTED");
  return sha256Hex(canonicalJson(JSON.parse(JSON.stringify(canonical2)), 10485760));
}

// src/worker/machine/receipt-hash.ts
var LEGACY_MACHINE_HASH_SCHEME = "SHA256_JSON_RESPONSE_WITH_EMPTY_RESPONSE_HASH_V1";
var MACHINE_HASH_SCHEME = "SHA256_SORTED_JSON_RESPONSE_WITH_EMPTY_RESPONSE_HASH_V2";
async function hashMachineResponse(response) {
  const receipt = response.receipt;
  if (!receipt) throw new Error("MACHINE_RECEIPT_MISSING");
  const projection = { ...response, receipt: { ...receipt, response_hash: "" } };
  if (receipt.response_hash_scheme === LEGACY_MACHINE_HASH_SCHEME) return sha256Hex(JSON.stringify(projection));
  if (receipt.response_hash_scheme === ATTESTED_HASH_SCHEME) {
    const { attestation: _envelope, ...payload } = projection;
    return sha256Hex(canonicalJson(JSON.parse(JSON.stringify(payload)), 10485760));
  }
  if (receipt.response_hash_scheme !== MACHINE_HASH_SCHEME) throw new Error("MACHINE_HASH_SCHEME_UNSUPPORTED");
  return sha256Hex(canonicalJson(JSON.parse(JSON.stringify(projection)), 10485760));
}

// src/worker/machine/payment-verification.ts
var MACHINE_PAYMENT_VERIFICATION = {
  status: "VERIFIED_END_TO_END",
  tested_on: "2026-10-14",
  evidence_scope: "HISTORICAL_PRODUCTION_PURCHASES_NOT_CURRENT_RELEASE_ACCEPTANCE",
  release_bound: false,
  origin: "https://fahce.kinganlogic.com",
  adapter: "cloudflare",
  protocol: "x402-v2",
  network: "eip155:8453",
  asset: "USDC",
  scope: ["buyer_payment", "purchased_result_delivery", "gateway_settlement", "seller_receipt"],
  tested_operations: ["diagnose", "repair", "verify", "repair-bundle"],
  evidence: "Successful HTTP 200 results and gateway PAYMENT-RESPONSE records, Cloudflare settled-payment activity and receiving-wallet receipts.",
  evidence_access: "Public Base transaction links are provided for each operation. Gateway payment responses and seller receiving records support the corresponding FAHCE request references.",
  recipient: "0x22cf7241E3e24ed0d22d710C86a497084da625cd",
  asset_contract: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  evidence_references: [
    { operation: "diagnose", request_id: "f05ee4ad-aa79-47f3-8cc6-f111366f8c60", scheme: "exact", settled_atomic_units: "150000", transaction_hash: "0xfdd1b9fe0cbab0760da509b2a2263238d6e35de8b54ab0ef417094b9c1093d51" },
    { operation: "repair", request_id: "b327a160-1295-4c96-b65c-7f4a0e1d5557", scheme: "exact", settled_atomic_units: "150000", transaction_hash: "0x3681e98bd9ed9369b35a734fe5846571810d490eed4d0223747313d2a23b7c8e" },
    { operation: "verify", request_id: "3b548a2f-5e8d-4537-8d08-c9c2808eb344", scheme: "exact", settled_atomic_units: "150000", transaction_hash: "0xac32ef5d24f3411594abe2fbaf0d7b4872da923801bfc6b66d1002dc63b14234" },
    { operation: "repair-bundle", request_id: "7dab5f16-81ed-4500-9d76-5e419aa8400b", scheme: "upto", settled_atomic_units: "390000", transaction_hash: "0xcff08d0e4a67bd28e17907d1ba489555d89013e600bc45f55c6132da3bdc4f10" }
  ].map((record) => ({ ...record, status: "SETTLED", transaction_url: `https://basescan.org/tx/${record.transaction_hash}` }))
};

// src/worker/machine/commercial-config.ts
var MACHINE_ORIGIN = "https://fahce.kinganlogic.com";
var MACHINE_LEGAL_URLS = Object.fromEntries(["terms", "refunds", "privacy", "acceptable-use", "data-handling", "security"].map((name) => [name, `${MACHINE_ORIGIN}/legal/${name}`]));

// src/worker/machine/attestation.ts
var encoder2 = new TextEncoder();
async function verifyAttestedResult(response, policy, keys, expected = {}) {
  const proof = response.attestation;
  const receipt = response.receipt;
  if (!proof || !exactKeys(proof, ["schema", "policy_sha256", "binding", "maa_token"]) || proof.schema !== ATTESTATION_SCHEMA || proof.policy_sha256 !== policy.hostdata_sha256 || !receipt || receipt.response_hash_scheme !== ATTESTED_HASH_SCHEME) protocolError("RESULT_PROOF_REQUIRED");
  const b = proof.binding;
  if (!b || !exactKeys(b, ["schema", "nonce", "request_id", "input_hash", "response_hash", "engine_version", "issued_at", "scope"]) || b.schema !== RESULT_BINDING_SCHEMA || b.scope !== "CONFIDENTIAL_DETERMINISTIC_COMPUTATION" || !hex64(b.nonce) || !hex64(b.input_hash) || !hex64(b.response_hash) || b.engine_version !== policy.engine_version || receipt.engine_version !== b.engine_version || b.request_id !== response.request_id || b.request_id !== receipt.case_id || b.request_id !== receipt.run_id || b.input_hash !== response.input_hash || b.input_hash !== receipt.input_hash || b.response_hash !== receipt.response_hash || expected.nonce !== void 0 && b.nonce !== expected.nonce || expected.request_id !== void 0 && b.request_id !== expected.request_id || expected.input_hash !== void 0 && b.input_hash !== expected.input_hash) protocolError("RESULT_BINDING_MISMATCH");
  if (await hashMachineResponse(response) !== b.response_hash) protocolError("RESULT_HASH_MISMATCH");
  const created = Date.parse(String(receipt.created_at)) / 1e3;
  if (!Number.isFinite(created) || Math.abs(created - b.issued_at) > 60) protocolError("RESULT_TIME_MISMATCH");
  await verifyMaaBinding(proof.maa_token, b, policy, keys, expected.at);
}
async function verifyAttestedEngineResult(result, policy, keys, expected = {}) {
  const proof = result.attestation;
  if (!proof || !exactKeys(proof, ["schema", "policy_sha256", "binding", "maa_token"]) || proof.schema !== "FAHCE_ENGINE_ATTESTATION_V1" || proof.policy_sha256 !== policy.hostdata_sha256 || result.receipt.hash_scheme !== CASE_ATTESTED_HASH_SCHEME) protocolError("ENGINE_PROOF_REQUIRED");
  const b = proof.binding;
  if (!b || !exactKeys(b, ["schema", "nonce", "case_id", "run_id", "input_hash", "effective_input_sha256", "result_hash", "engine_version", "issued_at", "scope"]) || b.schema !== "FAHCE_ENGINE_RESULT_BINDING_V1" || b.scope !== "CONFIDENTIAL_DETERMINISTIC_COMPUTATION" || ![b.nonce, b.input_hash, b.effective_input_sha256, b.result_hash].every(hex64) || b.case_id !== result.case_id || b.case_id !== result.receipt.case_id || b.run_id !== result.receipt.run_id || b.input_hash !== result.receipt.input_hash || b.result_hash !== result.receipt.result_hash || b.engine_version !== policy.engine_version || b.engine_version !== result.receipt.engine_version || expected.nonce !== void 0 && b.nonce !== expected.nonce || expected.effective_input_sha256 !== void 0 && b.effective_input_sha256 !== expected.effective_input_sha256) protocolError("ENGINE_BINDING_MISMATCH");
  if (await hashResultPayload(result) !== b.result_hash) protocolError("ENGINE_HASH_MISMATCH");
  const created = Date.parse(result.receipt.created_at) / 1e3;
  if (!Number.isFinite(created) || Math.abs(created - b.issued_at) > 60) protocolError("RESULT_TIME_MISMATCH");
  await verifyMaaBinding(proof.maa_token, b, policy, keys, expected.at);
}

// src/verification/receipt-evidence.ts
async function verifyReceiptEvidence(response, trust, independentKeys) {
  const proof = response.attestation;
  if (!proof) throw Error("HASH_ONLY_OR_MISSING_PROOF");
  if (!Array.isArray(trust.policies)) throw Error("PUBLISHED_POLICIES_REQUIRED");
  const policies = trust.policies.map((entry) => parseAttestationPolicy(JSON.stringify(entry?.policy)));
  const matches = policies.filter((policy2) => policy2.hostdata_sha256 === proof.policy_sha256);
  if (matches.length !== 1) throw Error("PINNED_PUBLISHED_POLICY_REQUIRED");
  if (!Array.isArray(independentKeys) || independentKeys.length < 1 || independentKeys.length > 32) throw Error("INDEPENDENT_MAA_KEYS_REQUIRED");
  const policy = matches[0];
  const receipt = response.receipt;
  const at = Date.parse(String(receipt?.created_at)) / 1e3;
  if (!Number.isFinite(at)) throw Error("ISSUANCE_TIME_REQUIRED");
  if (proof.schema === "FAHCE_ENGINE_ATTESTATION_V1") await verifyAttestedEngineResult(response, policy, independentKeys, { at });
  else await verifyAttestedResult(response, policy, independentKeys, { at });
  return {
    verified: true,
    scope: "CONFIDENTIAL_DETERMINISTIC_COMPUTATION",
    issuance_time: receipt.created_at,
    policy_sha256: policy.hostdata_sha256,
    image_sha256: policy.image_sha256,
    engine_version: policy.engine_version,
    historical_verification: true,
    fresh_execution_performed: false,
    external_actions_certified: false,
    caller_evidence_truth_verified: false,
    maa_service_tee_verified: false,
    caller_challenge_verified: false,
    caller_original_input_verified: false
  };
}

// src/verification/verify-receipt.ts

export { verifyReceiptEvidence };
