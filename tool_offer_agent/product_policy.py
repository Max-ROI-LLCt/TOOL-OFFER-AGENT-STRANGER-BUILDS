"""Bounded product knowledge and explicitly selected, noncommercial planning state."""

import json
import re
from datetime import datetime, timezone


PLAN_LIMIT = 24
PLAN_ITEM_CHARACTERS = 1000
PLAN_HELP = (
    "Pre-launch planning — proposed, not implemented or seller-approved. No public URL is needed.\n"
    "Use plan requirement: <selected requirement>, plan decision: <open decision>, "
    "plan exercise: <fictional material>, or plan test R1: <acceptance criterion>.\n"
    "Only these explicit commands save planning items; ordinary brainstorming does not. "
    "Use plan status or export plan to inspect exact wording and test lineage. "
    "At most 24 items of 1,000 characters are retained per isolated conversation. "
    "Use mode evidence when ready for evidence-backed offer intake; planning never supplies commercial facts."
)


def publication_request(message):
    # Analytical reviews are read-only, not requests for publishable artifacts.
    if re.search(r"commercial analysis|five.part|(?:self.audit|assess|evaluate)[\s\S]*[1-6][.)]", message, re.I) and not re.search(r"\b(?:marketing_copy|source_endpoint)\b", message):
        return False
    return bool(re.search(r"\b(?:marketing_copy|source_endpoint)\b|marketing|publication.safe|publishable|publication.ready|evidence_status|sales copy|safe (?:replacement|wording)|revised wording|seller claim|claim.{0,30}(?:audit|evidence|source)|(?:audit|rewrite|repair|replac|correct).{0,50}(?:claim|copy|sentence|wording|previous|prior)", message, re.I))


def current_source_draft(message):
    """Verbatim current-message endpoint draft; documentation grants no approval."""
    if not (re.search(r"\bjson\b", message, re.I) and publication_request(message)):
        return None
    if re.search(r"self.audit|audit (?:your |the )?(?:previous|prior)|audit marketing copy|can we claim", message, re.I):
        return None
    regions = re.findall(r"<source>(.*?)</source>|```(?:text|json)?\s*\n(.*?)```", message, re.I | re.S)
    source = "\n".join(a or b for a, b in regions) if regions else message
    endpoint = r"(?:GET|POST|PUT|PATCH|DELETE) /[A-Za-z0-9_/{}/.-]+"
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    fields = identifier + r"(?:,? and " + identifier + r"|, " + identifier + r")*"
    pattern = (r"(?:" + endpoint + r" accepts " + fields + r"\.|"
               r"A successful response contains " + identifier + r" and " + identifier + r": " + identifier + r"\.|"
               r"On successful response, " + endpoint + r" returns " + identifier + r" and " + identifier + r": " + identifier + r"\.|"
               + endpoint + r" returns the current status for the specified ticket ID\.)")
    sentences = []
    for match in re.finditer(pattern, source):
        prefix = source[:match.start()].rstrip()
        if prefix and prefix[-1] not in '.!?\n\"“:>':
            continue
        sentences.append(match.group(0))
    endpoints = re.findall(endpoint, " ".join(sentences))
    if not sentences or len(set(endpoints)) != 1:
        return None
    value = {"marketing_copy": " ".join(sentences),
             "claims": [{"assertion": sentence, "exact_source_quote": sentence,
                         "evidence_status": "SUPPORTED"} for sentence in sentences],
             "publication_safe": False}
    if re.search(r"\bsource_endpoint\b", message):
        value["source_endpoint"] = endpoints[0]
    assert all(c["assertion"] == c["exact_source_quote"] and c["exact_source_quote"] in source
               for c in value["claims"])
    payload = json.dumps(value, ensure_ascii=False)
    if len(payload.encode("utf-8")) > 5500:
        return json.dumps({"marketing_copy": "", "claims": [], "publication_safe": False,
                           "error": {"code": "OUTPUT_LIMIT", "message": "Current source draft exceeds the delivery limit; supply a smaller source excerpt."},
                           **({"source_endpoint": endpoints[0]} if "source_endpoint" in value else {})})
    return payload


def publication_output(reply, state, message):
    """Fail closed on semantic rewrites; only complete source sentences may pass.

    Exact quotation is deliberately narrower than semantic entailment. Source text
    is attributed documentation, never independent authorization or runtime proof.
    This gate does not infer contradiction from missing evidence.
    """
    if not publication_request(message):
        return reply
    bounded = current_source_draft(message)
    if bounded is not None:
        return bounded
    current_sources = re.findall(r"<source>(.*?)</source>", message, re.I | re.S)
    current_sources += re.findall(r"```(?:text|json)?\s*\n(.*?)```", message, re.S)
    if not current_sources and re.search(r"\b(?:GET|POST|PUT|PATCH|DELETE) /", message):
        current_sources = [message]
    sources = current_sources or [document.get("text", "") for document in state.get("documents", [])]
    sentences = {part.strip() for source in sources for part in re.split(r"(?<=[.!?])\s+|\n+", source) if part.strip()}
    # Source quotations can themselves contain instructions or financial claims.
    # The bounded verifier only accepts these declarative endpoint shapes. All
    # other semantics need review; documentation never supplies payment proof.
    def endpoint_statement(assertion):
        return bool(re.fullmatch(
            r"(?:GET /[A-Za-z0-9_/{}/.-]+ returns the current status for the specified ticket ID\.|"
            r"On successful response, POST /[A-Za-z0-9_/{}/.-]+ returns ticket_id and status: received\.)",
            assertion))
    wants_json = bool(re.search(r"\bjson\b", message, re.I))
    def document(value):
        if re.search(r"\bsource_endpoint\b", message) and "source_endpoint" not in value:
            value["source_endpoint"] = None
            value["publication_safe"] = False
            value["error"] = {"code": "SOURCE_ENDPOINT_UNRESOLVED", "message": "The requested current source endpoint could not be validated."}
        payload = json.dumps(value, ensure_ascii=False)
        if len(payload.encode("utf-8")) > 5500:
            payload = json.dumps({"marketing_copy": "", "claims": [], "publication_safe": False,
                                  "error": {"code": "OUTPUT_LIMIT", "message": "Validated response exceeds the delivery size limit."},
                                  **({"source_endpoint": None} if "source_endpoint" in value else {})})
        # Validate the actual serialized delivery, not the model's visual format.
        json.loads(payload)
        return payload
    audit = []
    if re.search(r"self.audit|(?:audit|correct|repair|rewrite) (?:your |the )?(?:previous|prior)|you (?:said|wrote)", message, re.I):
        previous = next((item["content"] for item in reversed(state.get("conversation", [])) if item.get("role") == "assistant"), "")
        try:
            prior = json.loads(previous)
        except (ValueError, TypeError):
            prior = None
        if isinstance(prior, dict) and isinstance(prior.get("marketing_copy"), str):
            previous = prior["marketing_copy"]
            if not previous:
                return document({"marketing_copy": "", "claims": [], "publication_safe": False}) if wants_json else "The previous response withheld publication copy. No replacement sentence was emitted as publication-safe."
        audit = [{"assertion": part, "exact_source_quote": part if part in sentences else "", "evidence_status": "UNVERIFIED"}
                 for part in re.split(r"(?<=[.!?])\s+|\n+", previous) if part.strip()]
    if audit:
        if wants_json:
            return document({"marketing_copy": "", "claims": audit, "publication_safe": False})
        return ("Self-audit of the retained prior response excerpt; source support is not established. "
                "These actual assertions remain UNVERIFIED, not CONTRADICTED. Publication copy withheld:\n" +
                "\n".join(item["assertion"] + " — UNVERIFIED" for item in audit))
    try:
        value = json.loads(reply)
    except (ValueError, TypeError):
        value = None
    valid = isinstance(value, dict) and set(value) == {"marketing_copy", "claims", "publication_safe"}
    valid = valid and isinstance(value["marketing_copy"], str) and type(value["publication_safe"]) is bool and isinstance(value["claims"], list)
    if valid:
        for claim in value["claims"]:
            if (not isinstance(claim, dict) or set(claim) != {"assertion", "exact_source_quote", "evidence_status"}
                    or not all(isinstance(item, str) for item in claim.values())
                    or claim["evidence_status"] not in {"SUPPORTED", "UNVERIFIED", "CONTRADICTED"}):
                valid = False
                break
            # An exact whole source sentence is the only deterministic supported
            # assertion here. Rephrasing, partial quotation and contradiction
            # require semantic verification this executor does not possess.
            supported = claim["assertion"] == claim["exact_source_quote"] and claim["assertion"] in sentences and endpoint_statement(claim["assertion"])
            claim["evidence_status"] = "SUPPORTED" if supported else "UNVERIFIED"
            if claim["exact_source_quote"] not in sentences:
                claim["exact_source_quote"] = ""
        if valid:
            copy = value["marketing_copy"]
            safe = bool(copy and copy in sentences and any(c["assertion"] == copy and c["evidence_status"] == "SUPPORTED" for c in value["claims"]))
            value["publication_safe"] = safe
            if not safe:
                value["marketing_copy"] = ""
            if wants_json and not value["marketing_copy"]:
                value["error"] = {"code": "EMPTY_GENERATION", "message": "No source-bound draft or claim analysis was generated."}
            return document(value) if wants_json else (
                "Source-attributed documentation only, not verified behavior: " + copy if safe else
                "Publication copy withheld: the final assertions do not have complete source support. Missing authorization, timing, dispatch, notification, reliability or completion evidence is UNVERIFIED, not CONTRADICTED.")
    # Preserve the actual previous output when asked to self-audit. Never substitute
    # a hypothetical error, or treat assistant history as supporting evidence.
    result = {"marketing_copy": "", "claims": [], "publication_safe": False,
              "error": {"code": "SOURCE_CONTRACT_UNSUPPORTED",
                        "message": "No validated draft: complete current endpoint documentation and exact claim support are required."}}
    if re.search(r"\bsource_endpoint\b", message):
        result["source_endpoint"] = None
    if wants_json:
        return document(result)
    detail = "\nActual prior assertions requiring source verification:\n" + "\n".join(item["assertion"] + " — UNVERIFIED" for item in audit) if audit else ""
    return ("Publication copy withheld: I cannot validate each final assertion against complete, explicitly attributed source sentences. "
            "Endpoint existence does not establish customer permissions, dispatch, notifications, speed, availability or completed repairs. "
            "A received status alone leaves completion UNVERIFIED; it does not prove completion impossible. "
            "Supply documentation in <source>...</source> for exact quotation. No publication safety is established." + detail)


def planning_context(state, message=""):
    return state.get("planning", {}).get("mode") == "prelaunch" or bool(re.search(
        r"\b(?:hypothetical|fictional|pre-launch|prelaunch|no (?:public )?(?:endpoint|documentation)|"
        r"(?:do not|don't|don’t) (?:ask|demand|require).{0,35}(?:url|endpoint))\b", message, re.I))


def planning_command(state, text, *, message_id=None, timestamp=None):
    command = text.strip().lower().lstrip("/")
    if command in {"mode prelaunch", "mode evidence"}:
        planning = state.setdefault("planning", {"schema": "TOOL_OFFER_PLAN_V1", "items": []})
        planning["mode"] = command.split()[1]
        return PLAN_HELP if planning["mode"] == "prelaunch" else "Evidence mode selected. Proposed requirements remain separate; actual offer intake and authorization gates still apply."
    if command in {"plan status", "export plan"}:
        planning = state.get("planning", {"schema": "TOOL_OFFER_PLAN_V1", "mode": "evidence", "items": []})
        record = {**planning, "commercial_facts": False, "implemented": False,
                  "intake_fields_saved": sorted(state.get("fields", {})),
                  "documentation_status": "unverified source material" if state.get("documents") else "not supplied"}
        if command == "export plan":
            return json.dumps(record, ensure_ascii=False, indent=2)
        return PLAN_HELP + "\n\n" + ("\n".join(
            f"{item['id']} — {item['kind']}: {item['text']}" +
            (f" [tests {item['requirement_id']}; not executed]" if item.get("requirement_id") else "")
            for item in planning["items"]) or "No proposed requirements or decisions saved.")
    matched = re.fullmatch(r"plan (requirement|decision|exercise|test)(?: (R[1-9][0-9]*))?:\s*(.+)", text.strip(), re.I | re.S)
    if not matched:
        return "Use an explicit plan command. " + PLAN_HELP if command.startswith("plan ") else None
    if state.get("planning", {}).get("mode") != "prelaunch":
        return "Send mode prelaunch before saving proposed requirements. Existing intake is unchanged."
    kind, requirement_id, value = matched.groups()
    kind = kind.lower()
    value = value.strip()
    items = state["planning"]["items"]
    if not 1 <= len(value) <= PLAN_ITEM_CHARACTERS or len(items) >= PLAN_LIMIT:
        return "Planning storage limit reached: 24 items, each 1–1,000 characters. Existing items are unchanged; export plan preserves them."
    requirement_id = requirement_id.upper() if requirement_id else None
    if kind == "test" and not any(item["kind"] == "requirement" and item["id"] == requirement_id for item in items):
        return "A test must reference an existing requirement, for example plan test R1: <criterion>. Nothing saved."
    if kind != "test" and requirement_id:
        return "Only tests accept a requirement reference. Nothing saved."
    if any(item["kind"] == kind and item["text"] == value and item.get("requirement_id") == requirement_id for item in items):
        return "That exact planning item is already saved; no duplicate created."
    prefix = {"requirement": "R", "decision": "D", "exercise": "F", "test": "T"}[kind]
    identifier = prefix + str(1 + sum(item["kind"] == kind for item in items))
    items.append({"id": identifier, "kind": kind, "text": value, "source_quote": value,
                  "origin": "explicit_current_user_command", "message_id": message_id,
                  "recorded_at": timestamp or datetime.now(timezone.utc).isoformat(),
                  "requirement_id": requirement_id, "status": "fictional" if kind == "exercise" else
                  "unresolved" if kind == "decision" else "not_executed" if kind == "test" else "proposed"})
    return f"Saved {identifier} as {items[-1]['status']} planning material, not implemented functionality or commercial evidence."


def machine_knowledge():
    from .machine_contract import CONTRACT, RELEASE_ID
    return {"authority": "release-generated product contract, not live runtime introspection",
            "release_id": RELEASE_ID, "origin": CONTRACT["origin"],
            "authentication": CONTRACT["authentication"], "scope": CONTRACT["scope"],
            "limitations": CONTRACT["limitations"], "limits": CONTRACT["limits"],
            "tools": [tool["name"] for tool in CONTRACT["tools"]],
            "recovery": {
                "replay": "Retain original application request_id for identical operation and arguments; changed arguments conflict.",
                "poll": "get_result uses submitted job_id under original authenticated owner, not a new operation ID.",
                "states": "pending, processing and uncertain are not completion; never duplicate uncertain work.",
                "delivery": "Complete transport job is not complete document delivery. Retrieve every manifest part and verify individual and aggregate hashes.",
                "guarantees": "No undocumented retry guarantees or error codes; documentation is not live security validation."}}


def requirement_command_guidance(message):
    """Read-only syntax advice; actual plan writes stay in planning_command."""
    if re.match(r"\s*plan (?:requirement|decision|exercise|test)(?: R[1-9][0-9]*)?:", message, re.I):
        return None
    unsupported = bool(re.match(r"\s*/?save\s+requirement\s*:", message, re.I))
    if re.search(r"\balso\b|[1-6][.)]", message, re.I):
        return None
    syntax_question = bool(re.search(r"(?:what exact command saves|(?:save|plan) requirement:)", message, re.I))
    if not unsupported and not syntax_question and not re.fullmatch(r"\s*(?:how (?:do|can) I save (?:a |my )?requirement\??|(?:what|which) (?:is the )?command (?:saves|to save) (?:a |my )?requirement\??)\s*", message, re.I):
        return None
    return (("Unsupported command: save requirement: is not an accepted alias. Nothing saved.\n" if unsupported else "") +
            "To save a proposed requirement, send these as two separate messages:\n"
            "mode prelaunch\n"
            "plan requirement: <your requirement text>\n"
            "Replace <your requirement text> with your own words. If already in prelaunch mode, send only the second message. "
            "The built-in planning help lists plan requirement: and the executor recognizes that exact prefix. "
            "save requirement: is unsupported; earlier advice to use it or avoid plan requirement: was incorrect. "
            "A successful save confirms Saved R1 as proposed (then R2, R3, and so on for additional requirements). "
            "Existing requirements, decisions and tests are retained; proposed does not mean implemented or approved. "
            "Use plan status or export plan to inspect saved items. This guidance executes no command and saves nothing; "
            "it establishes supported syntax, not that a requirement was saved in this conversation.")


def product_answer(message):
    guidance = requirement_command_guidance(message)
    if guidance is not None:
        return guidance
    text = message.casefold()
    # Specific source and multi-part questions require the full conversational route.
    if re.search(r"documentation|previously saved|self.audit|[1-6][.)]|do not (?:initiate|start|make|explain) pay", text):
        return None
    if re.search(r"\b(?:job|request_id|get_result)\b", text) and re.search(r"recover|retry|retried|uncertain|pending|conflict", text):
        return ("Recovery procedure (documented implementation, not a live execution test):\n"
                "1. Retain the original application request_id, session and submitted job_id. Retry identical operations with identical arguments; changed arguments with the same request_id conflict.\n"
                "2. Poll get_result with the submitted job_id under the same authenticated client. A different client is not authorized by possession of an ID.\n"
                "3. pending, processing and uncertain are not completion. Do not submit a duplicate operation to resolve uncertainty; inspect the original job. No undocumented retry or error-code guarantee is established.\n"
                "4. A complete job can contain an incomplete document or export manifest. Retrieve every indexed part, verify each part hash and the manifest aggregate before declaring delivery complete. Missing or invalid parts prevent success.\n"
                "MCP: https://tooloffer.kinganlogic.com/mcp; REST: https://tooloffer.kinganlogic.com/api/machine/<tool_name>. Native ASI:One chat is separate from machine quotas.")
    question = "?" in text or re.match(r"\s*(?:explain|describe|what|how|does|can|tell|give|list|provide|are|resolve)\b", text)
    if not question:
        return None
    # Resolve requested business intent before incidental interface vocabulary.
    if re.search(r"\b(?:fet|fet_direct|fetch)\b", text) and re.search(r"\b(?:pay\w*|usdc|x402|interchangeable)\b", text):
        return ("No. fet_direct and x402 are not interchangeable. FAHCE's existing buyer checkout requires USDC on Base; FET does not satisfy that requirement. "
                "A conceptual FET payment method for a seller offer does not change FAHCE's accepted asset, network or authorization. "
                "This agent does not convert FET, route payments automatically, or establish that a payment occurred.")
    if re.search(r"\b(?:external|marketplace\w*|distribution|listing\w*|director\w*)\b", text) and re.search(
            r"\b(?:capabilit\w*|inventory|execute|execution|submit\w*|publish\w*|can|able|support\w*)\b", text):
        return ("External distribution capability inventory:\n"
                "1. Prepare source-attributed listing copy and checklists: supported; offer export requires a saved draft.\n"
                "2. Assess destination eligibility: preparation guidance only; seller eligibility remains UNKNOWN until verified.\n"
                "3. Submit or register externally: not implemented; seller permission alone is not execution evidence.\n"
                "4. Obtain marketplace acceptance evidence: not implemented; no publication is established.\n"
                "5. Monitor external listings or communicate with external agents to distribute them: not implemented.\n"
                "Documentation standards, developer visibility, directories and transactional marketplaces are different channels. "
                "Use listing checklist or listing checklist json without a draft; nothing is submitted or published.")
    if re.search(r"\bdecision\w*\b|\bD[1-9][0-9]*\b", message, re.I) and re.search(r"resolv\w*|select\w*|history|implement\w*", text):
        return ("Planning decisions are stored as unresolved. Adding D2 records proposed decision text; it does not select or implement it, or resolve D1. "
                "There is no supported in-place resolution or decision-history command. Use plan status or export plan to inspect the original records; "
                "you may explicitly add a plan decision describing your preferred outcome, which also remains unresolved. "
                "Selection, implementation and a lifecycle transition require separate evidence or future product work.")
    if re.search(r"\b(?:mcp|rest|m2m|machine)\b", text) and re.search(
            r"\b(?:tool offer|tooloffer|your|actual deployed|machine interface|machine gateway)\b", text):
        contract = machine_knowledge()
        return ("Documented Tool Offer Agent machine interface (not a live runtime health check):\n"
                f"MCP: {contract['origin']}/mcp — legacy MCP 2025-11-25 Streamable HTTP; initialize and tools/list are public.\n"
                f"REST: {contract['origin']}/api/machine/<tool_name>.\n"
                + contract["authentication"] + "\nOperations: " + ", ".join(contract["tools"]) + ".\n"
                "start_session creates isolated adapter state; native Fetch/ASI:One conversations remain separate. "
                "send_message returns a job; poll get_result for the same job until complete. pending, processing and uncertain are not success. "
                "Keep the same application request_id when retrying identical work; changed arguments conflict. "
                "Verify completed Tool Offer agent signatures and multipart export hashes.\n"
                + contract["scope"] + "\nThis is release-generated documentation, not evidence that I inspected a live client, credential or runtime. "
                "Current contracts: /capabilities/machines, /openapi.json and /instructions.md.")
    if re.search(r"\b(?:seller|my customers|subscription|stripe)\b", text) and re.search(r"\b(?:pay|payment|billing|revenue|charge)\b", text):
        return ("Seller payment terms and buyer FAHCE checkout are separate. I can record seller-managed Stripe or other supplied billing instructions; "
                "I do not create a Stripe account, charge your customers, collect seller revenue or operate subscription billing. "
                "Five conceptual payment protocols are described by payment options, but the seller-side operational list is empty. "
                "A protocol definition or affiliate/paid-wrapper permission does not establish resale rights. "
                "The existing buyer-approved FAHCE checkout buys an evaluation, not your API. "
                "For $29 plus metered overages, the total is $29 + max(0, usage − included units) × the explicitly supplied overage price; "
                "unprovided units, rates and terms remain undecided.")
    return None


def output_risk(reply, state, message):
    text = reply.casefold()
    evidence = json.dumps({"message": message, "fields": state.get("fields", {}),
                           "documents": state.get("documents", [])}, ensure_ascii=False).casefold()
    for address in re.findall(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", reply, re.I):
        if address.casefold() not in evidence:
            return "An invented contact cannot be presented as extracted information."
    if re.search(r"\b(?:customers?|users?|tenants?) can (?:inspect|read|access|view) (?:any|all|every) tickets?\b", text):
        return "Endpoint existence does not establish access to every ticket; tenant and authorization scope must be sourced."
    if re.search(r"(?:public|api) doc(?:umentation|s) (?:grants?|gives?|provides?|means you have) .{0,50}(?:rights|permission)", text):
        return "Public documentation is not a license or seller authorization."
    if re.search(r"(?:standard[- ]plan|standard plan).{0,35}(?:includes?|guarantees?|provides?) .{0,25}review", text):
        return "A plan-specific review promise requires uncontradicted source support; do not turn a disputed claim into marketing."
    if re.search(r"\b(?:contact|recruit|interview|invite)\b", text) and "fictional" in message.casefold() and not re.search(r"\b(?:not|never|fictional|consent|hypothetical)\b", text):
        return "Fictional participants are not real-world recruitment targets."
    if re.search(r"\b(?:use|upload|share|send|collect) (?:the |your )?(?:real |actual )tenant reports\b", text) and not re.search(r"consent|permission|redact|synthetic|de-identif|minimi", text):
        return "Real tenant reports need explicit authorization and data minimization; prefer synthetic or redacted examples."
    return None
