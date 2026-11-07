const element = id => document.getElementById(id);
try {
  const token = new URLSearchParams(location.hash.slice(1)).get("access")
    || sessionStorage.getItem("fahce-approval-access");
  const base = location.pathname.startsWith("/checkout/") ? location.pathname.replace(/\/$/, "") : "";
  const response = await fetch(base + "/api/status", {
    headers: { Authorization: "Bearer " + (token ?? "") }, redirect: "error",
  });
  const status = await response.json();
  if (!response.ok) throw new Error(status.error || "Purchase details could not be loaded.");
  element("buyer").textContent = status.buyer ? "[Wallet hidden for recording]" : "Your wallet — connect below";
  element("recipient").textContent = "[Merchant wallet hidden for recording]";
  element("request-hash").textContent = status.requestSha256;
  element("candidate").textContent = status.candidate;
  element("evidence").textContent = status.evidenceCount + " source documents included with this request.";
  element("status").textContent = "Purchase details loaded. Loading wallet controls…";
  await import("/app.js?startup=2");
} catch (error) {
  element("status").textContent = "Approval could not load. No payment requested.";
  element("error").textContent = "Reload using the full private approval link in a normal browser tab. Browser startup: "
    + String(error?.message ?? "unknown error").slice(0, 240);
}
