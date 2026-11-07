export const ENDPOINT = "https://fahce.kinganlogic.com/api/v1/diagnose";
export const DISCOVERY = "https://fahce.kinganlogic.com/capabilities/machines.json";
export const NETWORK = "eip155:8453";
export const ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
export const RECIPIENT = "0x22cf7241E3e24ed0d22d710C86a497084da625cd";
export const AMOUNT = "150000";
export const MAX_AUTHORIZATION_SECONDS = 3600;
export class PaymentPolicyError extends Error {}
export const AUTHORIZATION_TYPES = {
  TransferWithAuthorization: [
    { name: "from", type: "address" },
    { name: "to", type: "address" },
    { name: "value", type: "uint256" },
    { name: "validAfter", type: "uint256" },
    { name: "validBefore", type: "uint256" },
    { name: "nonce", type: "bytes32" },
  ],
};

export function sameAddress(left, right) {
  return typeof left === "string" && typeof right === "string"
    && /^0x[0-9a-f]{40}$/i.test(left) && left.toLowerCase() === right.toLowerCase();
}

export function stableJson(value) {
  if (Array.isArray(value)) return "[" + value.map(stableJson).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + stableJson(value[key])).join(",") + "}";
  }
  return JSON.stringify(value);
}

export function selectRequirement(required) {
  if (required?.x402Version !== 2 || required.resource?.url !== ENDPOINT || !Array.isArray(required.accepts)) {
    throw new PaymentPolicyError("Unexpected payment protocol or purchase endpoint. Nothing authorized.");
  }
  const selected = required.accepts.find(option => option.scheme === "exact"
    && option.network === NETWORK && sameAddress(option.asset, ASSET)
    && sameAddress(option.payTo, RECIPIENT) && option.amount === AMOUNT
    && option.extra?.name === "USD Coin" && option.extra?.version === "2"
    && [undefined, "eip3009"].includes(option.extra?.assetTransferMethod));
  if (!selected) throw new PaymentPolicyError("FAHCE did not offer the pinned 0.15 USDC / Base payment. Nothing authorized.");
  if (!Number.isInteger(selected.maxTimeoutSeconds) || selected.maxTimeoutSeconds <= 0
    || selected.maxTimeoutSeconds > MAX_AUTHORIZATION_SECONDS) {
    throw new PaymentPolicyError("FAHCE requested an authorization window outside the supported 1–3600 seconds. No signature was sent.");
  }
  return selected;
}

export function authorizationTypedData(authorization, buyer, requirement, now = Math.floor(Date.now() / 1000)) {
  const fields = ["from", "to", "value", "validAfter", "validBefore", "nonce"];
  if (!authorization || stableJson(Object.keys(authorization).sort()) !== stableJson(fields.sort())
    || !sameAddress(authorization.from, buyer) || !sameAddress(authorization.to, RECIPIENT)
    || String(authorization.value) !== AMOUNT || !/^0x[0-9a-f]{64}$/i.test(authorization.nonce)) {
    throw new Error("Wallet authorization does not match the reviewed buyer, merchant, or amount.");
  }
  for (const name of ["value", "validAfter", "validBefore"]) {
    if (!/^\d{1,20}$/.test(String(authorization[name]))) throw new Error("Invalid authorization number.");
  }
  const validAfter = BigInt(authorization.validAfter);
  const validBefore = BigInt(authorization.validBefore);
  if (validAfter > BigInt(now) || validBefore <= BigInt(now)
    || validBefore > BigInt(now + requirement.maxTimeoutSeconds + 30) || validAfter >= validBefore) {
    throw new Error("Wallet authorization is expired or has an excessive time window.");
  }
  return {
    domain: { name: "USD Coin", version: "2", chainId: 8453, verifyingContract: ASSET },
    types: AUTHORIZATION_TYPES,
    primaryType: "TransferWithAuthorization",
    message: { ...authorization, value: BigInt(AMOUNT), validAfter, validBefore },
  };
}

export function validatePaymentPayload(payload, required, buyer, now) {
  const selected = selectRequirement(required);
  if (payload?.x402Version !== 2 || stableJson(payload.accepted) !== stableJson(selected)
    || stableJson(payload.resource) !== stableJson(required.resource)
    || payload.extensions !== undefined || !/^0x(?:[0-9a-f]{2}){65,8192}$/i.test(payload.payload?.signature)) {
    throw new Error("Payment payload differs from the reviewed challenge.");
  }
  return authorizationTypedData(payload.payload.authorization, buyer, selected, now);
}
