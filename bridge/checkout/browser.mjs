import { x402Client } from "@x402/core/client";
import { createBaseAccountSDK } from "@base-org/account";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { createWalletClient, custom } from "viem";
import { base } from "viem/chains";
import { ASSET, NETWORK, authorizationTypedData, sameAddress, selectRequirement, stableJson, validatePaymentPayload } from "./payment-policy.mjs";

const element = id => document.getElementById(id);
const apiBase = location.pathname.startsWith("/checkout/") ? location.pathname.replace(/\/$/, "") : "";
const providers = new Map();
const observedProviders = new WeakSet();
const allowedPhases = new Set(["ready", "challenge_ready"]);
let config = null;
let busy = false;
let connectedWallet = null;
let displayedRevision = null;
let accessToken = new URLSearchParams(location.hash.slice(1)).get("access");
if (accessToken) {
  sessionStorage.setItem("fahce-approval-access", accessToken);
  history.replaceState(null, "", location.pathname + location.search);
} else {
  accessToken = sessionStorage.getItem("fahce-approval-access");
}

class DisplayError extends Error {}

async function api(path, body) {
  const response = await fetch(apiBase + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { Authorization: "Bearer " + (accessToken ?? ""), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    redirect: "error",
  });
  const result = await response.json();
  if (!response.ok) throw new DisplayError(result.error ?? "The checkout service could not complete this step.");
  return result;
}

function updateButton() {
  element("wallet").disabled = busy;
  element("connect-wallet").disabled = busy || !allowedPhases.has(config?.phase)
    || !providers.has(element("wallet").value);
  element("apply-revision").disabled = busy || config?.phase !== "input_review" || !config?.inputRevision
    || !element("accept-revision").checked;
  element("pay").disabled = busy || !config?.termsHash || !allowedPhases.has(config.phase)
    || !element("accept-terms").checked || !providers.has(element("wallet").value)
    || connectedWallet?.identifier !== element("wallet").value
    || (!!config.buyer && !sameAddress(connectedWallet?.address, config.buyer));
  const savedAvailable = !!apiBase && config?.savedAuthorization?.canSubmit === true;
  element("saved-approval").hidden = !savedAvailable;
  element("pay").hidden = savedAvailable;
  element("submit-saved-approval").disabled = busy || !savedAvailable || !config?.termsHash
    || !element("accept-terms").checked || !element("accept-saved-approval").checked;
}

function renderWallet() {
  const hidden = element("hide-wallets").checked;
  const buyer = config?.buyer ?? connectedWallet?.address;
  element("buyer").textContent = buyer ? (hidden ? "[Wallet hidden for recording]" : buyer) : "Your wallet — connect below";
  element("connected-wallet").textContent = connectedWallet
    ? "Connected: " + (hidden ? "[Wallet hidden for recording]" : connectedWallet.address) + ". Connection is not payment approval."
    : "No wallet connected by this page. No payment authorized by connecting.";
}

function clearWallet() {
  connectedWallet = null;
  element("accept-terms").checked = false;
  element("accept-saved-approval").checked = false;
  renderWallet();
  updateButton();
}

element("connect-wallet").addEventListener("click", async () => {
  if (element("connect-wallet").disabled) return;
  busy = true;
  clearWallet();
  element("error").textContent = "";
  const identifier = element("wallet").value;
  const provider = providers.get(identifier).provider;
  try {
    const accounts = await provider.request({ method: "eth_requestAccounts" });
    if (!sameAddress(accounts?.[0], accounts?.[0])) throw new DisplayError("Your wallet did not return a valid public account. Nothing was signed or paid.");
    if (config.buyer && !sameAddress(accounts[0], config.buyer)) {
      throw new DisplayError("Choose the buyer account already pinned to this checkout. Temporarily unhide the Buyer field to inspect it privately. No payment was requested.");
    }
    connectedWallet = { identifier, provider, address: accounts[0] };
    if (typeof provider.on === "function" && !observedProviders.has(provider)) {
      observedProviders.add(provider);
      provider.on("accountsChanged", accounts => {
        if (connectedWallet?.provider === provider && !sameAddress(accounts?.[0], connectedWallet.address)) clearWallet();
      });
      provider.on("disconnect", () => { if (connectedWallet?.provider === provider) clearWallet(); });
    }
    renderWallet();
  } catch (error) {
    element("error").textContent = walletRejected(error) ? "Wallet connection declined. Nothing was signed or paid."
      : error instanceof DisplayError ? error.message : "Wallet connection could not complete. Nothing was signed or paid. Choose your wallet and try connecting again.";
  } finally {
    busy = false;
    updateButton();
  }
});

function discoverWallet(name, provider, identifier) {
  if (!provider || typeof provider.request !== "function" || providers.has(identifier)) return;
  if ([...providers.values()].some(entry => entry.provider === provider)) return;
  providers.set(identifier, { name, provider });
  const selection = element("wallet").value;
  element("wallet").replaceChildren();
  for (const [key, entry] of providers) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = entry.name;
    element("wallet").append(option);
  }
  if (providers.has(selection)) element("wallet").value = selection;
  element("wallet-help").textContent = "Connect your own account first; no payment signature is requested. Review the purchase separately before Pay now.";
  updateButton();
}

window.addEventListener("eip6963:announceProvider", event => {
  const detail = event.detail;
  if (typeof detail?.info?.uuid === "string" && typeof detail.info.name === "string") {
    discoverWallet(detail.info.name.slice(0, 80), detail.provider, detail.info.uuid);
  }
});
window.dispatchEvent(new Event("eip6963:requestProvider"));
const popupWallet = createBaseAccountSDK({ appName: "Tool Offer Agent", appChainIds: [base.id], preference: { telemetry: false } });
discoverWallet("Coinbase / Base account — popup (no extension needed)", popupWallet.getProvider(), "base-popup");
element("wallet-help").textContent = "The Coinbase / Base option opens its own connection popup, or select an installed wallet. Connection and one-time payment approval are separate steps.";
setTimeout(() => {
  if (window.ethereum) {
    const available = window.ethereum.providers ?? [window.ethereum];
    available.forEach((provider, index) => discoverWallet("Browser wallet " + (index + 1), provider, "injected-" + index));
  }
  if (!providers.size) {
    element("wallet").options[0].textContent = "No wallet connection detected in this browser";
    element("wallet-help").textContent = "Open this private link in your wallet-enabled browser, or choose the Coinbase / Base popup. This checkout does not support every mobile wallet. Never paste keys or seed phrases.";
  }
}, 500);

function renderStatus(status) {
  if (config?.requestSha256 && config.requestSha256 !== status.requestSha256) {
    element("accept-terms").checked = false;
    element("accept-saved-approval").checked = false;
  }
  config = { ...config, ...status };
  const hideWallets = element("hide-wallets")?.checked !== false;
  renderWallet();
  element("recipient").textContent = hideWallets ? "[Merchant wallet hidden for recording]" : status.recipient;
  element("request-hash").textContent = status.requestSha256;
  element("candidate").textContent = status.candidate;
  element("evidence").textContent = status.evidenceCount + (apiBase ? " source documents included with this hosted agent draft. Send check in the same agent conversation after approval to retrieve the result." : " freshly fetched source documents included. The pasted readable draft is used; the hosted agent is not modified.");
  const labels = {
    ready: "Ready for your review. No wallet authorization has been requested.",
    input_blocked: "FAHCE needs an input-format repair before payment. Your draft and evidence are preserved.",
    input_review: "Review the proposed input repair before proceeding. No payment is authorized.",
    requesting_challenge: "Requesting the exact payment details. No signature sent.",
    challenge_ready: "Payment details checked. Ready for wallet approval.",
    awaiting_wallet: "An approval request is active. Finish or reject it in your wallet; do not start another payment.",
    validating_authorization: "Checking the approved signature against this purchase.",
    submitting: "Submitting this payment once. Keep this page open; do not pay again.",
    unresolved: "This attempt needs reconciliation. Another payment is blocked.",
    response_received: "FAHCE returned a result. No further payment will be attempted.",
  };
  element("status").textContent = status.note ?? labels[status.phase] ?? "Unknown state: do not authorize another payment.";
  if (status.savedAuthorization?.canSubmit === true) {
    element("status").textContent = "Your wallet approval is saved; no signed payment has been sent. Use the separate saved-approval controls only if you still want this purchase. Do not sign again.";
  }
  if (status.validationFailure?.code === "SIGNATURE_CHECK_RATE_LIMITED") {
    element("status").textContent = "The Base verification providers are rate-limiting requests. This does not establish an invalid wallet signature. No signed payment was sent. Your existing approval is preserved; do not sign again.";
  }
  if (status.reconciliation?.outcome === "EXPIRED_UNUSED") {
    element("status").textContent += status.savedAuthorization?.canSubmit === true
      ? " An older, separate authorization expired unused; its history is preserved. That does not refer to your current saved approval."
      : " Previous authorization expired unused; its receipt and accounting history are preserved. Any new purchase still requires your approval.";
  }
  const revision = status.inputRevision;
  element("revision-card").hidden = !revision;
  if (displayedRevision !== revision?.requestSha256) element("accept-revision").checked = false;
  displayedRevision = revision?.requestSha256;
  if (revision) {
    element("revision-summary").textContent = revision.summary;
    element("revision-original").textContent = status.candidate;
    element("revision-candidate").textContent = revision.candidate;
    element("revision-preflight").textContent = revision.preflight?.status === "NO_KNOWN_BLOCKER"
      ? "Free preflight: no known input blockers. This is not a truth determination or a guarantee of billability; the check runs again before acceptance."
      : "Free preflight has not cleared this revision. Acceptance will recheck it without payment.";
  }
  element("result-card").hidden = !(status.result || status.httpStatus);
  if (status.result || status.httpStatus) {
    element("result-card").hidden = false;
    element("result-note").textContent = status.note ?? "Response retained; settlement has not been independently verified.";
    element("result").textContent = JSON.stringify(status.result, null, 2);
    element("transaction").textContent = status.transaction
      ? "Gateway-reported transaction (not independently verified): " + status.transaction
      : "No gateway transaction reference is available. An HTTP response alone does not establish the charge.";
  }
  updateButton();
}

async function refresh() {
  const status = await api("/api/status");
  renderStatus(status.phase === "input_blocked" && apiBase
    ? await api("/api/preflight", {}) : status);
}

element("accept-revision").addEventListener("change", updateButton);
element("apply-revision").addEventListener("click", async () => {
  if (element("apply-revision").disabled) return;
  const revision = config.inputRevision;
  busy = true;
  updateButton();
  element("error").textContent = "";
  try {
    const status = await api("/api/accept-input-revision", { acceptRevision: true,
      sourceRequestSha256: revision.sourceRequestSha256, requestSha256: revision.requestSha256 });
    element("accept-terms").checked = false;
    renderStatus(status);
  } catch (error) {
    element("error").textContent = error instanceof DisplayError ? error.message : "Input acceptance could not be confirmed. Refresh status; no wallet authorization was requested.";
    try { await refresh(); } catch {}
  } finally {
    busy = false;
    updateButton();
  }
});

function walletRejected(error) {
  return error?.code === 4001 || error?.cause?.code === 4001 || error?.cause?.cause?.code === 4001;
}

element("pay").addEventListener("click", async () => {
  if (element("pay").disabled) return;
  busy = true;
  updateButton();
  element("error").textContent = "";
  let authorizationRequested = false;
  let walletPromptStarted = false;
  let signatureCreated = false;
  try {
    const connected = connectedWallet;
    const provider = connected.provider;
    const accounts = await provider.request({ method: "eth_accounts" });
    if (!sameAddress(accounts?.[0], connected.address)) {
      clearWallet();
      throw new DisplayError("Your wallet account changed. Connect again and review the purchase. No payment was requested.");
    }
    if (config.buyer && !sameAddress(accounts?.[0], config.buyer)) {
      clearWallet();
      throw new DisplayError("Select the buyer account pinned to this checkout. Unhide the Buyer field only when viewing privately. No payment was authorized.");
    }
    const wallet = createWalletClient({ account: accounts[0], chain: base, transport: custom(provider, { retryCount: 0 }) });
    if (Number(await provider.request({ method: "eth_chainId" })) !== base.id) {
      element("status").textContent = "Your wallet may ask to switch to Base. No payment yet.";
      await wallet.switchChain({ id: base.id });
    }
    element("status").textContent = "Checking FAHCE’s exact payment requirements…";
    const { required, buyer } = await api("/api/challenge", { acceptTerms: true, termsHash: config.termsHash, buyer: accounts[0] });
    config.buyer = buyer ?? config.buyer;
    const selected = selectRequirement(required);
    const signer = {
      address: accounts[0],
      async signTypedData(parameters) {
        const expected = authorizationTypedData(parameters.message, config.buyer, selected);
        if (parameters.primaryType !== expected.primaryType || stableJson(parameters.types) !== stableJson(expected.types)
          || parameters.domain.name !== "USD Coin" || parameters.domain.version !== "2"
          || Number(parameters.domain.chainId) !== base.id || !sameAddress(parameters.domain.verifyingContract, ASSET)) {
          throw new DisplayError("The requested wallet authorization does not match this purchase.");
        }
        const current = await provider.request({ method: "eth_accounts" });
        if (!sameAddress(current?.[0], config.buyer) || Number(await provider.request({ method: "eth_chainId" })) !== base.id) {
          throw new DisplayError("The wallet account or network changed. No signature requested.");
        }
        authorizationRequested = true;
        await api("/api/authorize", { buyer: config.buyer });
        element("status").textContent = "Approve the one-time 0.15 USDC payment in your wallet popup. No unlimited allowance is requested.";
        walletPromptStarted = true;
        const signature = await wallet.signTypedData(parameters);
        signatureCreated = true;
        return signature;
      },
    };
    const client = new x402Client();
    client.register(NETWORK, new ExactEvmScheme(signer));
    const paymentPayload = await client.createPaymentPayload({ x402Version: 2, resource: required.resource, accepts: [selected] });
    validatePaymentPayload(paymentPayload, required, config.buyer);
    element("status").textContent = "Submitting the approved payment once. Please wait; do not pay again.";
    renderStatus(await api("/api/pay", { paymentPayload }));
  } catch (error) {
    if (walletRejected(error) && !signatureCreated) {
      if (authorizationRequested && walletPromptStarted) {
        try { renderStatus(await api("/api/rejected", { code: 4001 })); } catch {}
      }
      element("error").textContent = "You declined the wallet request. No signed payment was submitted by this page.";
    } else {
      element("error").textContent = error instanceof DisplayError ? error.message
        : "The wallet or connection could not complete this step. Refresh status before continuing. Do not approve another payment if this attempt is unresolved.";
    }
    try { await refresh(); } catch {}
  } finally {
    busy = false;
    updateButton();
  }
});

element("submit-saved-approval").addEventListener("click", async () => {
  if (element("submit-saved-approval").disabled) return;
  busy = true;
  updateButton();
  element("error").textContent = "";
  element("status").textContent = "Rechecking your saved approval before its first paid submission. Do not start another payment.";
  try {
    renderStatus(await api("/api/submit-saved-authorization", { submitSavedAuthorization: true,
      requestSha256: config.requestSha256, acceptTerms: true, termsHash: config.termsHash }));
  } catch (error) {
    element("error").textContent = error instanceof DisplayError ? error.message
      : "Submission status is uncertain. Do not sign again or repeat submission; refresh status first.";
    try { await refresh(); } catch {}
  } finally {
    element("accept-saved-approval").checked = false;
    busy = false;
    updateButton();
  }
});

element("accept-saved-approval").addEventListener("change", updateButton);
element("wallet").addEventListener("change", clearWallet);
element("hide-wallets")?.addEventListener("change", () => { if (config) renderStatus(config); });
element("accept-terms").addEventListener("change", updateButton);
element("refresh").addEventListener("click", () => refresh().catch(error => {
  element("error").textContent = error instanceof DisplayError ? error.message : "Status unavailable. Do not authorize another payment.";
}));

try {
  config = await api("/api/config");
  renderStatus(config);
  for (const [name, url] of Object.entries(config.legalUrls)) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = name.replaceAll("-", " ");
    item.append(link);
    element("legal").append(item);
  }
  element("accept-terms").disabled = false;
  updateButton();
} catch (error) {
  element("status").textContent = "Approval is not enabled. No payment has been requested.";
  element("error").textContent = error instanceof DisplayError ? error.message : "Current payment configuration could not be loaded. No payment requested.";
}
