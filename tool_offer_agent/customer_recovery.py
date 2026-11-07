"""Bounded, deterministic customer recovery; no inference, checkout or tool calls."""

import json
import re
from urllib.parse import urlsplit

from .documents import validate_url

INTRO = ("I turn public API or MCP documentation into an offer a buyer can review. "
         "I show what the docs support, add the terms you provide, and flag what’s still missing.")

DIRECTORY = "https://mcpservers.org/servers/ticketlens/ticketlens-experiences-mcp"
# Public references researched for this acceptance case, never fetched or selected implicitly.
REFERENCES = (
    "https://mcp.ticketlens.com/.well-known/mcp/server-card.json",
    "https://api.ticketlens.com/v1/openapi.json",
)


def suggestions(state):
    candidates = []
    if DIRECTORY in state.get("fields", {}).get("docs", []) or any(
            item.get("url") == DIRECTORY for item in state.get("document_attempts", [])):
        candidates.extend({"url": url, "provenance": DIRECTORY,
                           "status": "publicly_referenced_not_runtime_verified"} for url in REFERENCES)
    for doc in state.get("documents", []):
        for match in re.finditer(r'https?://[^\s<>"\)]+', doc.get("text", "")):
            url = match.group().rstrip(".,;")
            if not re.search(r"openapi|swagger|server-card\.json", url, re.I):
                continue
            try:
                url = validate_url(url)
            except ValueError:
                continue
            if not any(item["url"] == url for item in candidates):
                candidates.append({"url": url, "provenance": doc["source_url"],
                                   "status": "retained_source_reference_not_runtime_verified"})
    return candidates[:3]


def discovery_text(state):
    candidates = suggestions(state)
    lines = ["Source suggestions are references, not verified live contracts or seller ownership. Nothing was substituted or fetched."]
    lines.extend(f"{index}. {item['url']} — referenced by {item['provenance']}" for index, item in enumerate(candidates, 1))
    lines.append("Select explicitly with docs: <public URL>, or use recovery form. A server card may help discovery but does not necessarily contain request/response schemas." if candidates else
                 "Ask the maintainer for public OpenAPI or MCP tool-schema documentation, then send docs: <public URL>. You can continue intake or export the saved record.")
    return "\n".join(lines)


def broad_customer(value):
    return bool(re.search(r"\b(?:regular people|everyone|anyone|all users|general public)\b", value or "", re.I))


def background_article(document):
    path = urlsplit(document.get("source_url", "")).path
    article = bool(re.search(r"/(?:magazine|blog|news|articles?)(?:/|$)", path, re.I))
    interface = bool(re.search(r"openapi|swagger|tools/list|inputSchema|outputSchema|API endpoint|request\s+(?:body|schema)|response\s+schema|(?:GET|POST|PUT|DELETE)\s+/[a-z]", document.get("text", ""), re.I))
    return article and not interface


def field_notes(state, updates, awaiting=None):
    notes = []
    if awaiting == "access" and "invocation" in updates and "access" not in updates:
        notes.append("That describes invocation, so I saved it under invocation rather than access. To correct it, use revise invocation: <value>. Access still needs an answer.")
    if "payment" in updates and re.search(r"\b(?:probably|maybe|likely|considering|might)\b", str(updates["payment"]), re.I):
        notes.append("Payment is tentative and seller-stated: " + updates["payment"] + ". Operational Stripe acceptance is not verified.")
    if "customer" in updates and broad_customer(updates["customer"]):
        notes.append("I kept your original customer wording. Which specific group needs what outcome? Use customer: <group> and job: <one outcome>; you can keep going with these unresolved.")
    return "\n".join(notes)


def evidence(facts, fields, documents):
    missing = [name for name in ("capabilities", "inputs", "outputs") if not facts.get(name)]
    mismatches = []
    tool_host = urlsplit(fields.get("tool_url", "")).hostname
    for doc in documents:
        try:
            spec = json.loads(doc["text"])
        except (ValueError, TypeError):
            continue
        if not isinstance(spec, dict):
            continue
        raw_servers = spec.get("servers")
        servers = [item.get("url", "") for item in raw_servers if isinstance(item, dict) and isinstance(item.get("url"), str)] if isinstance(raw_servers, list) else []
        if servers and tool_host and not any(urlsplit(url).hostname == tool_host for url in servers):
            mismatches.append(doc["source_url"])
    issues = (["Missing source-grounded " + ", ".join(missing) + "."] if missing else [])
    if any(background_article(doc) for doc in documents):
        issues.append("Article content without tool-interface details is retained as background; it does not establish the offered API/MCP request/response schemas.")
    if mismatches:
        issues.append("Documented server differs from the offered tool; confirm the source relationship: " + ", ".join(mismatches))
    if broad_customer(fields.get("customer")) and not fields.get("job"):
        issues.append("The intended customer is too general to establish one commercially meaningful job; original wording retained.")
    return {"status": "insufficient" if issues else "documented_for_review",
            "buyer_ready": False, "missing_core_categories": missing, "issues": issues,
            "scope": "Source-grounded claims for review, not independent verification or commercial authorization."}


def evidence_text(value):
    if value.get("status") == "insufficient":
        return "INCOMPLETE DRAFT — evidence insufficient; not buyer-ready. " + " ".join(value.get("issues", []))
    return "Documented details available for review; behavior, payment operation and seller authorization remain unverified."


def mixed_retry(state, text):
    """Only clear retry language. Suggestions and replacements never become retries."""
    match = re.search(r"\b(?:you can\s+|please\s+)?retry\s+(?:reading\s+)?(?:the\s+)?(?:prior|previous|same|earlier|link I sent earlier)\b.*$", text, re.I)
    if match is None:
        match = re.search(r"\b(?:you can\s+|please\s+)?retry\s+reading\s+the\s+link\s+I\s+sent\s+earlier\b.*$", text, re.I)
    if match is None or re.search(r"\b(?:don't|do not|should|could|suggest)\b|https?://|\?", text, re.I):
        return None
    answer = text[:match.start()].rstrip(" ,;.!\n")
    if not answer or state.get("awaiting") not in {"customer", "pricing", "payment", "access", "invocation"}:
        return None
    if not state.get("fields", {}).get("docs"):
        return None
    return answer
