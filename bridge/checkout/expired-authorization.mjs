import { createPublicClient, http } from "viem";
import { base } from "viem/chains";
import { ASSET, NETWORK, stableJson, validatePaymentPayload } from "./payment-policy.mjs";

const providers = ["https://base-mainnet.g.alchemy.com/public", "https://base-rpc.publicnode.com"];
const authorizationAbi = [{ type: "function", name: "authorizationState", stateMutability: "view",
  inputs: [{ name: "authorizer", type: "address" }, { name: "nonce", type: "bytes32" }], outputs: [{ type: "bool" }] }];
const hash = async value => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)))].map(byte => byte.toString(16).padStart(2, "0")).join("");
const failure = (code, message) => Object.assign(Error(message), { code: "EXPIRED_PROOF_" + code });

async function observeAuthorization(rpc, authorization) {
  const client = createPublicClient({ chain: base, transport: http(rpc, { retryCount: 0, timeout: 12000 }) });
  let stage = "chain_id";
  try {
    if (await client.getChainId() !== base.id) throw Error("Authorization chain mismatch.");
    stage = "finalized_block";
    const block = await client.getBlock({ blockTag: "finalized" });
    stage = "authorization_state";
    const usedOrCanceled = await client.readContract({ address: ASSET, abi: authorizationAbi,
      functionName: "authorizationState", args: [authorization.from, authorization.nonce], blockNumber: block.number });
    stage = "recheck_block";
    const rechecked = await client.getBlock({ blockNumber: block.number });
    if (rechecked.hash !== block.hash) throw Error("Finalized block changed.");
    return { provider: new URL(rpc).hostname, chainId: base.id, finalized: true,
      blockNumber: String(block.number), blockHash: block.hash, timestamp: String(block.timestamp), usedOrCanceled };
  } catch (error) {
    const errors = [];
    for (let cause = error; cause && errors.length < 5; cause = cause.cause) {
      errors.push({ name: /^[A-Za-z][A-Za-z0-9]{0,80}$/.test(cause.name) ? cause.name : "Error",
        status: Number.isInteger(cause.status) ? cause.status : null,
        code: Number.isInteger(cause.code) ? cause.code : null });
    }
    throw Object.assign(Error("Authorization observation failed."), {
      diagnostic: { provider: new URL(rpc).hostname, stage, errors },
    });
  }


}

export async function proveExpiredUnusedAuthorization(state, { now = Math.floor(Date.now() / 1000), observe = observeAuthorization } = {}) {
  if (state?.phase !== "unresolved" || state.httpStatus !== 422 || !state.signedAt
      || state.result?.error !== "PAYMENT_WORK_NON_BILLABLE" || state.result.billing?.billable !== false
      || state.result.private_content_released !== false || state.paymentResponse || state.gateway || state.recoveryToken
      || state.receiptProof || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(state.idempotencyKey)) {
    throw failure("INELIGIBLE", "This attempt is not eligible for expired-authorization reconciliation.");
  }
  for (const field of ["request_id", "receipt_id", "purchase_id"]) {
    if (typeof state.result[field] !== "string" || !state.result[field] || state.result[field].length > 256) throw failure("RECEIPT_IDENTITY", "Original receipt identity is missing.");
  }
  if (typeof state.requestBytes !== "string" || await hash(state.requestBytes) !== state.requestSha256
      || stableJson(JSON.parse(state.requestBytes)) !== stableJson(state.request)
      || typeof state.responseText !== "string" || stableJson(JSON.parse(state.responseText)) !== stableJson(state.result)
      || state.pendingValidationPayload && stableJson(state.pendingValidationPayload) !== stableJson(state.paymentPayload)) {
    throw failure("EVIDENCE_MISMATCH", "Retained request or payment evidence differs.");
  }
  const signedAt = Math.floor(Date.parse(state.signedAt) / 1000);
  if (!Number.isSafeInteger(signedAt) || signedAt > now) throw failure("SIGNING_TIME", "Original signing time is unavailable.");
  try { validatePaymentPayload(state.paymentPayload, state.required, state.buyer, signedAt); }
  catch { throw failure("PAYMENT_EVIDENCE", "Original payment evidence does not match its reviewed challenge."); }
  const authorization = state.paymentPayload.payload.authorization;
  const expiry = BigInt(authorization.validBefore);
  if (expiry >= BigInt(now)) throw failure("UNEXPIRED", "Authorization has not expired. Another payment remains blocked.");
  const observations = await Promise.all(providers.map(async (provider, index) => {
    try { return await observe(provider, authorization); }
    catch (error) {
      throw Object.assign(failure("RPC_" + (index + 1) + "_UNAVAILABLE", "An independent finalized authorization observation is unavailable."), { diagnostic: error?.diagnostic ?? null });
    }
  }));
  for (const [index, observation] of observations.entries()) {
    if (observation?.provider !== new URL(providers[index]).hostname || observation.chainId !== base.id
        || observation.finalized !== true || observation.usedOrCanceled !== false
        || !/^[1-9][0-9]*$/.test(observation.blockNumber) || !/^0x[a-f0-9]{64}$/i.test(observation.blockHash)
        || !/^[1-9][0-9]*$/.test(observation.timestamp)
        || BigInt(observation.timestamp) <= expiry || BigInt(observation.timestamp) > BigInt(now)) {
      throw failure("FINALIZED_UNUSED", "Both providers must confirm an unused authorization in finalized blocks after expiry.");
    }
  }
  return { schema: "FAHCE_EXPIRED_AUTHORIZATION_PROOF_V1", outcome: "EXPIRED_UNUSED",
    checkedAt: new Date(now * 1000).toISOString(), requestSha256: state.requestSha256,
    authorizationSha256: await hash(stableJson(authorization)), authorizationExpiresAt: new Date(Number(expiry) * 1000).toISOString(),
    network: NETWORK, asset: ASSET, observations,
    scope: "This authorization expired unused. Original origin accounting is retained, not rewritten. No refund, credit, new signature, or payment is created." };
}
