"""Local, source-dated distribution guidance. No network calls or submissions."""

from copy import deepcopy
from datetime import date
import json
import re


CHECKED_ON = "2026-11-02"
REVIEW_AFTER = "2026-11-30"
OFFER = "Would you like a listing preparation checklist for your tool, with requirements and next steps?"
PROFILES = {"mcp", "api", "agent", "unknown"}

# Priority reflects this builder's preferences and channel fit, not measured traffic.
# The official registry is an upstream dependency for VerifyMCP despite its rank.
DESTINATIONS = (
    {
        "id": "openapi", "name": "OpenAPI REST documentation", "url": "https://spec.openapis.org/oas/v3.1.1.html", "profiles": ["api"],
        "value": "REST request/response documentation, not an MCP server or a directory listing.",
        "basis": "documented_interface_format", "depends_on": [],
        "requirements": ["Publish accurate request, response, authentication and error schemas.", "Verify actual routes independently; documentation grants no usage or resale rights."],
        "route": "Prepare a canonical OpenAPI contract and link it from developer documentation; no submission implied.",
        "sources": ["https://spec.openapis.org/oas/v3.1.1.html"],
    },
    {
        "id": "llms_txt", "name": "llms.txt documentation entrance", "url": "https://llmstxt.org/", "profiles": ["api", "mcp", "agent", "unknown"],
        "value": "A machine-readable guide linking canonical instructions; not a callable transport or guaranteed discovery.",
        "basis": "documentation_proposal", "depends_on": [],
        "requirements": ["Publish a concise Markdown introduction with links to instructions, contracts and examples.", "Generate with the same release and never include client credentials."],
        "route": "Link the guide from human/machine entrances. Test actual callable endpoints separately.",
        "sources": ["https://llmstxt.org/"],
    },
    {
        "id": "verifymcp", "name": "VerifyMCP", "url": "https://verifymcp.io/", "profiles": ["mcp"],
        "value": "First priority for this builder because they reported strong results here; independent MCP discovery and published technical checks.",
        "basis": "owner_reported_value_and_platform_documentation",
        "requirements": ["An actual MCP server; a REST API or chat agent alone does not qualify.",
                         "Publish or update the server in the official MCP Registry, which VerifyMCP says it syncs.",
                         "Review the resulting page, endpoint/package checks, descriptions and client setup; address findings and recheck."],
        "depends_on": ["mcp_registry"],
        "route": "Registry sync, followed by reviewing the resulting VerifyMCP page; no direct submission API is assumed.",
        "sources": ["https://verifymcp.io/about"],
    },
    {
        "id": "mcp_registry", "name": "Official MCP Registry", "url": "https://registry.modelcontextprotocol.io/", "profiles": ["mcp"],
        "value": "Upstream MCP metadata distribution; do this before expecting downstream VerifyMCP discovery.",
        "basis": "upstream_distribution_dependency",
        "requirements": ["An actual MCP server and server.json with a stable name, version, description and declared transport.",
                         "Prove ownership of the publishing namespace using a supported authentication method.",
                         "For a remote server, declare a publicly accessible Streamable HTTP URL in remotes; secret Authorization headers may describe owner-issued credentials.",
                         "Each remote URL belongs to one registry server name. Namespace ownership is checked, not remote URL ownership. Verify publication by registry readback."],
        "depends_on": [], "route": "Review and publish metadata using the official mcp-publisher workflow. The registry does not host your service.",
        "sources": ["https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/remote-servers.mdx"],
    },
    {
        "id": "glama", "name": "Glama", "url": "https://glama.ai/mcp/servers", "profiles": ["mcp"],
        "value": "Additional MCP discovery through server, connector, tool and category pages.",
        "basis": "documented_mcp_discovery_channel",
        "requirements": ["Choose the right route: an open-source server in a GitHub repository, or a deployed remote connector.",
                         "Supply a name, description and repository or HTTPS Streamable HTTP endpoint as appropriate.",
                         "Review indexing and health results. Configure any test credentials privately on the destination, never in this chat."],
        "depends_on": [], "route": "Use Add MCP Server on Glama; select the repository or connector route that matches the implementation.",
        "sources": ["https://glama.ai/mcp/faq"],
    },
    {
        "id": "agentverse", "name": "Agentverse / ASI:One", "url": "https://agentverse.ai/", "profiles": ["agent"],
        "value": "Agent-native discovery and conversational access for a registered, operational agent.",
        "basis": "documented_agent_discovery_channel",
        "requirements": ["Register/connect the agent and enable Agent Chat Protocol for conversational discovery.",
                         "Prepare an accurate README, description, handle, avatar and working example prompts.",
                         "Run representative conversation tests and keep the agent responsive; associate any verified domain you control."],
        "depends_on": [], "route": "Complete the agent's Profile, Testing and Verifications setup. A plain API needs an agent integration before this route fits.",
        "sources": ["https://docs.agentverse.ai/documentation/agent-discovery/setup-guide"],
    },
    {
        "id": "github", "name": "GitHub repository / public developer docs", "url": "https://github.com/", "profiles": ["mcp", "api", "agent"],
        "value": "A developer-facing reference and onboarding destination; useful groundwork for directory submissions.",
        "basis": "developer_onboarding_foundation",
        "requirements": ["Use a repository you own or are authorized to maintain; choose what can be public.",
                         "Add a clear README, relevant topics, working invocation/install examples and a link to canonical docs.",
                         "State pricing, access, limits, support and maintenance expectations; use credential placeholders."],
        "depends_on": [], "route": "Prepare repository metadata and public documentation. No existing repository or open-source license is assumed.",
        "sources": ["https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics"],
    },
    {
        "id": "bazaar", "name": "Coinbase x402 Bazaar", "url": "https://docs.cdp.coinbase.com/x402/buyer/discover-services", "profiles": [],
        "value": "Potential paid-endpoint discovery only when the service is compatible with current x402/Bazaar requirements.",
        "basis": "conditional_payment_protocol_fit",
        "requirements": ["Confirm this service actually implements compatible x402 payments; mentioning x402 in seller terms is not evidence of implementation.",
                         "Check the current facilitator, network, resource type and discovery-metadata requirements against the linked documentation.",
                         "Verify that the resource is indexed before reporting a listing as live. This checklist does not initiate payments or settle funds."],
        "depends_on": [], "route": "Check current x402 discovery eligibility and indexing; do not treat Bazaar as a universal manual-submit marketplace.",
        "sources": ["https://docs.cdp.coinbase.com/x402/buyer/discover-services", "https://docs.cdp.coinbase.com/api-reference/v2/rest-api/x402-facilitator/browse-the-catalog"],
    },
)


def build_checklist(state, *, today=None):
    today = today or date.today()
    expired = today >= date.fromisoformat(REVIEW_AFTER)
    profile = state.get("listing_profile", "unknown")
    if profile not in PROFILES:
        profile = "unknown"
    basis = "seller_declared" if profile != "unknown" else "not_supplied"
    if profile == "unknown" and "listing_profile" not in state:
        for document in state.get("documents", []):
            try:
                specification = json.loads(document.get("text", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(specification, dict) and specification.get("openapi") and isinstance(specification.get("paths"), dict):
                profile, basis = "api", "retained_OpenAPI_document_not_runtime_verification"
                break
    destinations = []
    for original in DESTINATIONS:
        if profile not in original["profiles"] and not (original["id"] == "bazaar" and profile != "unknown" and "x402" in json.dumps(state.get("fields", {})).lower()):
            continue
        item = deepcopy(original)
        item.update(channel_class={"openapi": "documentation_standard", "llms_txt": "documentation_proposal",
                                   "github": "developer_visibility", "bazaar": "conditional_paid_endpoint_discovery"}.get(item["id"], "directory"),
                    transactional_marketplace=False, seller_eligibility="UNKNOWN",
                    submission_permission="not_established", publication_evidence="not_supplied")
        if item["id"] == "bazaar":
            applicability = "conditional_x402_eligibility"
            statements = [str(v) for v in state.get("fields", {}).values()]
            statements += [turn.get("content", "") for turn in state.get("conversation", []) if turn.get("role") == "user"]
            seller_text = "\n".join(s for s in statements if "?" not in s and not re.search(r"\b(?:what if|suppose|hypothetical|do not (?:say|claim)|don't (?:say|claim))\b", s, re.I))
            unavailable = bool(re.search(r"(?:\b(?:unavailable|not available|cannot (?:sell|list)|not eligible)\b[^\n.!?]{0,100}\bBazaar\b|\bBazaar\b[^\n.!?]{0,100}\b(?:unavailable|not available|not eligible)\b)", seller_text, re.I))
            item["eligibility_state"] = "seller_unavailable" if unavailable else "conditional_unverified"
            item["seller_eligibility"] = "UNAVAILABLE_BY_SELLER" if unavailable else "UNKNOWN"
            item["eligibility_reason"] = ("Respect the seller's statement of unavailability; do not recommend submission." if unavailable else
                "A published x402 endpoint is not Bazaar indexing. Cloudflare Monetization Gateway interoperability with Bazaar is not established.")
            item["route"] = ("No submission recommended while seller unavailability applies." if unavailable else item["route"])
            item["requirements"].append("Cloudflare Monetization Gateway to Bazaar interoperability is unestablished. Require independent indexing readback before claiming a listing; no submission, acceptance or marketplace ranking is implied.")
        elif profile == "unknown":
            applicability = "confirm_tool_type"
        elif profile in item["profiles"]:
            applicability = "fits_declared_tool_type"
        else:
            applicability = "requires_different_integration"
        item.setdefault("eligibility_state", "unknown")
        item.update(applicability=applicability, priority=len(destinations) + 1,
                    status="recheck_required" if expired else "preparation_only",
                    last_checked=CHECKED_ON if item["id"] in {"openapi", "llms_txt", "mcp_registry", "verifymcp"} else "2026-10-31")
        destinations.append(item)
    # Put channels matching the declared implementation first; keep user-preferred
    # VerifyMCP first for MCPs and the upstream dependency explicitly separate.
    order = {"fits_declared_tool_type": 0, "confirm_tool_type": 1,
             "conditional_x402_eligibility": 2, "requires_different_integration": 3}
    preferred = {"mcp": "verifymcp", "api": "openapi", "agent": "agentverse"}.get(profile)
    destinations.sort(key=lambda item: (item["id"] != preferred, order[item["applicability"]], item["priority"]))
    for rank, item in enumerate(destinations, 1):
        item["priority"] = rank
    fields = state.get("fields", {})
    assets = [
        {"name": label, "status": "seller_supplied" if fields.get(field) else "needed"}
        for field, label in (("tool_url", "Public tool URL"), ("docs", "Public documentation"),
                             ("customer", "Intended customer"), ("job", "One clear use case"),
                             ("pricing", "Price or explicit undecided terms"), ("payment", "Payment terms or undecided"),
                             ("access", "Access instructions"), ("invocation", "Invocation example"))
    ]
    assets.extend({"name": label, "status": "needs_review"} for label in
                  ("Product name, short description, category and keywords", "Logo and screenshots where the destination supports them",
                   "Ownership proof, license/terms, support and privacy information", "One working install/call example per destination"))
    return {
        "schema": "TOOL_OFFER_LISTING_CHECKLIST_V1", "status": "preparation_only",
        "evidence_states": {"documentation": "source_read" if state.get("documents") else "not_read",
                            "tool_type_basis": basis, "seller_identity": "not_authenticated",
                            "commercial_permission": "not_established", "operational_verification": "not_performed",
                            "actual_listing": "not_established"},
        "knowledge_checked_on": CHECKED_ON, "review_after": REVIEW_AFTER, "knowledge_expired": expired,
        "tool_type": profile, "tool_type_basis": basis,
        "publication_status": "not_verified",
        "capability_distinctions": {"OpenAPI": "REST documentation, not MCP compatibility", "remote_MCP": "Requires actual protocol and transport tests", "registry": "Metadata publication, not hosting or acceptance guarantee", "independent_indexes": "Separate indexing; verify actual appearance", "llms.txt": "Documentation, not invocation"},
        "offer_revision": state.get("revision", 0), "draft_revision": (state.get("draft") or {}).get("revision"),
        "draft_outdated": state.get("outdated", False),
        "ranking_basis": "Builder-reported value for VerifyMCP, implementation fit and known dependencies; no measured traffic or ROI ranking.",
        "destinations": destinations, "asset_checklist": assets,
        "commercial_marketplace_coverage": "UNKNOWN: no verified transactional API marketplace eligibility, seller permission or acceptance is established by this checklist.",
        "execution_order": ["Prepare canonical docs, examples and reusable listing copy."] +
                           (["Prepare accurate OpenAPI documentation, a llms.txt entrance and authorized GitHub developer visibility; these are not commercial marketplace listings."] if profile == "api" else []) +
                           (["For an MCP: review seller permission, publish/update the official MCP Registry entry, then verify registry readback and VerifyMCP sync; prepare Glama in parallel."] if profile in {"mcp", "unknown"} else []) +
                           (["For an agent: complete Agentverse profile and conversation testing with permission."] if profile in {"agent", "unknown"} else []) +
                           (["Consider Bazaar only after confirming current x402 eligibility."] if any(item["id"] == "bazaar" for item in destinations) else []),
        "excluded": [{"id": "smithery", "reason": "Excluded from this builder's recommendations by request. Smithery announced shutdown of proxy/managed connection services on 2026-10-31 while retaining a public directory; no working submission route is assumed.",
                      "sources": ["https://smithery.ai/future"]}],
        "next_question": "Is this an MCP server, a REST API, or a chat agent?" if profile == "unknown" else None,
    }


def render_checklist(plan):
    lines = ["Listing preparation checklist", f"Guidance checked {plan['knowledge_checked_on']}; tool type: {plan['tool_type']}.",
             plan["ranking_basis"], plan["commercial_marketplace_coverage"], "Prepared guidance only; nothing has been submitted or published."]
    if plan["knowledge_expired"]:
        lines.append("Directory guidance needs a fresh check before use; submission routes and requirements may have changed.")
    if plan["draft_outdated"]:
        lines.append("Your saved revisions are newer than the existing draft; rebuild before preparing final submission copy.")
    for item in plan["destinations"]:
        lines.extend([f"\n{item['priority']}. {item['name']} — {item['applicability'].replace('_', ' ')}", item["url"],
                      "Why: " + item["value"], "Eligibility: " + item["eligibility_state"], "Next: " + item["route"]])
        lines.extend("[ ] " + requirement for requirement in item["requirements"])
        lines.append("Source: " + ", ".join(item["sources"]))
    lines.append("\nReusable listing assets:")
    lines.extend(f"[ ] {asset['name']} — {asset['status'].replace('_', ' ')}" for asset in plan["asset_checklist"])
    lines.append("\nSuggested order:\n" + "\n".join(plan["execution_order"]))
    lines.append("\nSmithery is excluded from your recommendations. Bazaar remains conditional, not a default launch requirement.")
    if plan["next_question"]:
        lines.append("\n" + plan["next_question"] + " You can say: listing profile mcp / api / agent.")
    lines.append("Use listing checklist json for the structured plan, or export listing to include it with your offer.")
    return "\n".join(lines)


def normalize_listing_message(message):
    return " ".join(message.strip().casefold().split()).rstrip(".!?").lstrip("/")


def listing_action(message):
    """Recognize complete affirmative requests, not keywords inside other requests."""
    normalized = normalize_listing_message(message).removeprefix("please ")
    if re.fullmatch(r"export (?:my |the )?listing(?: package)?", normalized):
        return "export listing"
    tool = r"(?:(?:my|our|this|the|an?) )?(?:tool|api|rest api|mcp(?: server)?|chat agent|agent)|this|it"
    checklist = r"(?:listing checklist(?: json)?|high[- ]value checklist|checklist)"
    request = r"(?:(?:show|give)(?: me)?|prepare|create|generate|(?:can|could|would) you (?:show|give)(?: me)?|(?:can|could) i (?:get|have)) (?:a |the |my )?"
    patterns = (
        rf"(?:{request})?{checklist}(?: for (?:{tool}))?",
        rf"where (?:should|can|could|do) i (?:list|promote|submit) (?:{tool})(?: for free)?",
        rf"(?:which|what) (?:channels|directories|marketplaces|listing sites|listing websites) (?:should|can|could) i (?:list|promote|submit) (?:{tool}) (?:on|to)",
        rf"(?:recommend|suggest) (?:the |some )?(?:best |high[- ]value )?(?:directories|marketplaces|listing sites|listing websites|discovery channels)(?: for (?:{tool}))?",
        r"help me get discovered",
    )
    if any(re.fullmatch(pattern, normalized) for pattern in patterns):
        return "listing checklist"
    return None


def handle_listing_request(state, message):
    """Return None for unrelated messages, especially a bare yes without an offer."""
    normalized = normalize_listing_message(message)
    flags = state.get("listing_checklist", {})
    pending = flags.pop("awaiting_acceptance", False)
    if pending and normalized in {"no", "no thanks", "not now", "later", "skip", "skip it"}:
        flags.update(offered=True, declined=True)
        return "No problem. Ask for a listing checklist whenever you want; your offer is unchanged."
    accepted = pending and normalized in {"yes", "yes please", "sure", "show me", "go ahead", "please do", "yep"}
    profile = re.fullmatch(r"listing profile (mcp|api|agent|unknown)", normalized)
    if re.fullmatch(r"listing profile \S+", normalized) and not profile:
        return "Choose listing profile mcp, api, agent, or unknown. This describes your tool; it does not verify eligibility or publish anything."
    natural_profile = re.fullmatch(r"(?:show me (?:a |the )?)?(?:high[- ]value )?listing checklist for (?:my |an? )?(mcp server|mcp|rest api|api|chat agent|agent)", normalized)
    if profile or natural_profile:
        value = (profile or natural_profile).group(1)
        state["listing_profile"] = {"mcp server": "mcp", "rest api": "api", "chat agent": "agent"}.get(value, value)
    if not (accepted or profile or natural_profile or listing_action(message) == "listing checklist"):
        return None
    flags = state.setdefault("listing_checklist", {})
    flags.update(offered=True, viewed=True, declined=False)
    plan = build_checklist(state)
    return json.dumps(plan, ensure_ascii=False, indent=2) if normalized == "listing checklist json" else render_checklist(plan)


def offer_checklist(state, reply):
    flags = state.setdefault("listing_checklist", {})
    if not flags.get("offered"):
        flags.update(offered=True, awaiting_acceptance=True)
        return reply + "\n\n" + OFFER
    return reply
