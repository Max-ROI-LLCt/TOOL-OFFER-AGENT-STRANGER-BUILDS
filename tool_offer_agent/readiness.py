"""Deterministic preparation checks over retained state; never an authorization."""

import copy
import hashlib
import json
import re
from typing import Literal

from pydantic.v1 import BaseModel, Field

from .export_delivery import MAX_EXPORT_BYTES, REPLY_BYTES, deliver
from .offer_representation import representation
from .restrictions import empty as empty_restrictions
from .readiness_cards import evidence_summary

POLICY_VERSION = "1.2.0"
COMMANDS = {"readiness", "readiness json", "readiness text"}
BASIS_FIELDS = ("fields", "documents", "draft", "revision", "outdated", "restrictions", "planning", "approved_offer", "guided_actions", "document_fetch_outcomes")
REQUIRED_FIELDS = ("tool_url", "docs", "customer", "pricing", "payment", "access", "invocation")


def readiness_command(message):
    text = " ".join(message.casefold().strip().lstrip("/").split()).rstrip(".!?")
    if text in COMMANDS:
        return text
    if re.search(r"\b(?:don't|do not|not asking|explain the command|how to|how do i|what if|hypothetically)\b", text):
        return None
    request = re.match(r"^(?:please )?(?:(?:can|could|would) you )?(?:assess|check|evaluate|review|show|give|report|tell)\b.{0,90}\breadiness\b", text)
    question = re.match(r"^(?:is (?:this|my|the) (?:offer|draft) ready|how ready is (?:this|my|the) (?:offer|draft)|what is (?:this|my|the) (?:offer|draft)(?:'s|’s) readiness)\b", text)
    if request or question:
        return "readiness"
    return None


def review_status(state):
    draft = state.get("draft")
    reviews = [action for action in (state.get("guided_actions") or {}).values()
               if action.get("kind") == "offer"]
    draft_hash = hashlib.sha256(json.dumps(draft, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if draft and any(action.get("draft_sha256") == draft_hash for action in reviews):
        return "saved_draft_reviewed_with_pending_changes" if state.get("outdated") else "current_draft_reviewed"
    return "superseded_draft_reviewed" if reviews else "not_recorded"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


class Record(BaseModel):
    class Config:
        extra = "forbid"


class EvidenceSource(Record):
    id: str
    url: str
    sha256: str


class Fact(Record):
    pointer: str
    value: str
    basis: Literal["verbatim_quote", "source_backed_derived", "derived_schema_or_unaligned", "seller_or_record_declaration"]
    evidence_refs: list[str]
    source_pointers: list[str] = Field(default_factory=list)


class Finding(Record):
    code: str
    pointer: str
    detail: str
    next_step: str
    evidence_refs: list[str] = Field(default_factory=list)


class PlanningItem(Record):
    id: str
    kind: str
    text: str
    status: str
    requirement_id: str
    origin: str
    message_id: str


class Basis(Record):
    snapshot_sha256: str
    draft_sha256: str
    revision: int
    release_id: str
    policy_version: Literal["1.2.0"]


class Authorization(Record):
    commercial: Literal["not_established", "explicitly_restricted"]
    seller_approval: Literal["not_recorded", "current_sender_bound", "stale_or_different_sender"]
    independently_verified: Literal[False]


class ReadinessReport(Record):
    schema_version: Literal["TOOL_OFFER_READINESS_V1"]
    scope: Literal["preparation_for_review_only"]
    status: Literal["prelaunch", "needs_information", "needs_revision", "reviewable_with_caveats"]
    basis: Basis
    authorization: Authorization
    sources: list[EvidenceSource]
    facts: list[Fact]
    findings: list[Finding]
    planning: list[PlanningItem]
    checks_performed: list[str]
    not_assessed: list[str]
    next_step: str
    human_readable: str


def assess(state, sender, release_id):
    basis = {name: copy.deepcopy(state.get(name)) for name in BASIS_FIELDS}
    if len(encoded(basis).encode("utf-8")) > MAX_EXPORT_BYTES:
        raise ValueError("readiness_snapshot_too_large")
    fields = basis["fields"] or {}
    documents = basis["documents"] or []
    draft = basis["draft"]
    restrictions = basis["restrictions"] or (draft or {}).get("restrictions") or empty_restrictions()
    demonstration = restrictions.get("demonstration_only", False)
    planning = basis["planning"] or {}
    prelaunch = planning.get("mode") == "prelaunch"
    findings = []

    def finding(code, pointer, detail, next_step, refs=None):
        findings.append(Finding(code=code, pointer=pointer, detail=detail, next_step=next_step, evidence_refs=refs or []))

    for name in REQUIRED_FIELDS:
        value = fields.get(name)
        if value is None or value == "" or value == []:
            finding("INTAKE_MISSING", "/fields/" + name, name + " is not recorded.",
                    "Record the proposed " + name + " decision when known; no public endpoint is required for planning." if prelaunch else
                    "Record an explicitly fictional " + name + " value or leave it undecided; keep the exercise non-commercial." if demonstration else
                    "Ask the seller for " + name + "; do not invent it.")
        elif isinstance(value, str) and value.strip().casefold() in {"undecided", "unknown", "tbd", "not decided"}:
            finding("INTAKE_UNDECIDED", "/fields/" + name, name + " is explicitly undecided.", "Choose a fictional " + name + " value for this exercise, or keep it explicitly undecided." if demonstration else "Resolve " + name + " with the seller before presenting settled terms.")
    sources = [EvidenceSource(id=f"doc_{index + 1}", url=doc["source_url"], sha256=digest(doc)) for index, doc in enumerate(documents)]
    if not documents:
        finding("DOCUMENTS_MISSING", "/documents", "No retained documentation evidence.",
                "Continue selecting proposed requirements; add real evidence later." if prelaunch else "Obtain authorized documentation before claiming documented capabilities.")
    for index, outcome in enumerate(basis["document_fetch_outcomes"] or []):
        if outcome["result"] == "fetch_failed":
            finding("DOCUMENT_FETCH_FAILED", "/document_fetch_outcomes/" + str(index),
                    outcome["url"] + ": " + outcome["reason"] + (" Previously retained text remains available; it was not refreshed." if outcome.get("retained_previous") else " No text retained for this URL."),
                    "Correct or retry this documentation URL; do not claim it was successfully read.")
    if not draft:
        finding("DRAFT_MISSING", "/draft", "No saved offer draft was assessed.",
                "Continue the saved product plan; it is not a commercial offer." if prelaunch else "Prepare a draft from supplied facts when ready; this assessment does not build one.")
    if basis["outdated"]:
        finding("DRAFT_OUTDATED", "/outdated", "Saved draft revision " + str((draft or {}).get("revision", "unknown")) + " does not reflect current intake revision " + str(basis["revision"]) + ". Corrections are pending.", "Use draft limited to rebuild the fictional offer, then review offer; keep it non-commercial." if demonstration else "Rebuild and review the draft before relying on its terms.")
    facts = []
    if draft:
        mapped = representation(draft, documents, restrictions=restrictions, outdated=bool(basis["outdated"]))
        for item in mapped["claims"]:
            if item["role"] != "documentation_claim" or not item["draft_pointer"].endswith("/text"):
                continue
            alignment = "verbatim_quote" if item.get("quote_alignment") == "verbatim" else "source_backed_derived" if item.get("quote_alignment") == "source_backed_derived" else "derived_schema_or_unaligned"
            pointer = "/draft" + item["draft_pointer"]
            facts.append(Fact(pointer=pointer, value=str(item["value"]), basis=alignment, evidence_refs=item["evidence_refs"], source_pointers=item.get("source_pointers", [])))
            if alignment == "derived_schema_or_unaligned":
                finding("ALIGNMENT_UNRESOLVED", pointer, "Not an exact retained quote; may be schema-derived. Semantic support is not assessed.", "Review this statement against its source before reuse.", item["evidence_refs"])
        facts.append(Fact(pointer='/draft/revision', value=str(draft.get('revision', 'unknown')),
                          basis='seller_or_record_declaration', evidence_refs=[]))
        unknowns = draft.get("offer", {}).get("unknown_or_unextracted")
        from .customer_recovery import evidence, evidence_text
        assessment = evidence(draft.get("offer", {}), fields, documents)
        if assessment["status"] == "insufficient":
            finding("DOCUMENTATION_INSUFFICIENT", "/draft/documentation_evidence", evidence_text(assessment), "Select product-relevant public documentation or continue an explicitly incomplete draft.")
        if unknowns:
            finding("EXTRACTION_INCOMPLETE", "/draft/offer/unknown_or_unextracted", encoded(unknowns), "Review the unextracted categories; missing extraction is not proof a feature is absent.")
        for name in ("model_extraction", "deterministic_extraction"):
            coverage = draft.get(name)
            if coverage:
                finding("EXTRACTION_COVERAGE", "/draft/" + name, encoded(coverage), "Treat extraction coverage as recorded, not an exhaustive audit.")
    for name in sorted(fields):
        value = fields[name]
        facts.append(Fact(pointer="/fields/" + name.replace("~", "~0").replace("/", "~1"), value=value if isinstance(value, str) else encoded(value), basis="seller_or_record_declaration", evidence_refs=[]))
    restricted = restrictions.get("commercial_authorization") == "explicitly_restricted" or any(restrictions.get(name) for name in ("demonstration_only", "third_party_non_ownership", "not_representing_maintainers"))
    commercial = "explicitly_restricted" if restricted else "not_established"
    finding("COMMERCIAL_RESTRICTION" if restricted else "AUTHORIZATION_NOT_ESTABLISHED", "/restrictions", encoded(restrictions), "Keep this fictional exercise non-commercial; review does not lift its restrictions." if demonstration else "Keep this material non-authorizing; obtain and separately review seller permissions before commercial use.")
    approval = basis["approved_offer"]
    approval_status = "not_recorded" if not approval else "current_sender_bound" if draft and not basis["outdated"] and approval.get("hash") == digest(draft) and approval.get("by") == sender else "stale_or_different_sender"
    if approval_status == "stale_or_different_sender":
        finding("APPROVAL_NOT_CURRENT", "/approved_offer", "Recorded approval does not cover this current sender/draft.", "Do not represent the draft as currently seller-approved.")
    plan = [PlanningItem(id=item["id"], kind=item["kind"], text=item["text"], status=item["status"], requirement_id=item.get("requirement_id") or "", origin=item.get("origin", ""), message_id=item.get("message_id") or "") for item in planning.get("items", [])]
    for index, item in enumerate(plan):
        if item.kind == "decision":
            finding("OPEN_DECISION", "/planning/items/" + str(index), item.text, "Resolve saved decision " + item.id + " without treating a proposal as implemented.")
    status = "prelaunch" if prelaunch else "needs_revision" if basis["outdated"] else "needs_information" if not draft or not documents or any(item.code in {"INTAKE_MISSING", "INTAKE_UNDECIDED", "DOCUMENTATION_INSUFFICIENT"} for item in findings) else "reviewable_with_caveats"
    next_step = "Review the saved proposed requirements and resolve one open decision; no public URL is required." if prelaunch else next((item.next_step for item in findings if item.code in {"DRAFT_OUTDATED", "INTAKE_MISSING", "INTAKE_UNDECIDED", "DOCUMENTS_MISSING", "DRAFT_MISSING"}), "Review source alignment and permissions with the seller; this is not commercial clearance.")
    if demonstration and not prelaunch:
        next_step = next((item.next_step for item in findings if item.code in {"DRAFT_OUTDATED", "INTAKE_MISSING", "INTAKE_UNDECIDED"}), "Use draft limited to prepare the fictional offer, then review offer; keep the exercise non-commercial." if not draft else "Use review offer to inspect the fictional terms and Finish review for this exercise only. No commercial permission or payment follows.")
    reviewed = review_status(basis)
    if draft:
        facts.append(Fact(pointer="/guided_actions", value=reviewed, basis="seller_or_record_declaration", evidence_refs=[]))
    if draft and not basis["outdated"] and not prelaunch:
        if reviewed == "current_draft_reviewed":
            next_step = "Review of the current draft is already finished. Address the listed gaps with review intake, or use buyer explanation / export json to inspect or retain it. Review is not commercial permission."
        elif reviewed == "superseded_draft_reviewed":
            next_step = "Only a superseded draft was reviewed. Use review offer, then Finish review for the rebuilt current draft; earlier review does not cover it. Review is not commercial permission."
        if demonstration:
            next_step += " Keep this fictional exercise non-commercial."
    report = ReadinessReport(schema_version="TOOL_OFFER_READINESS_V1", scope="preparation_for_review_only", status=status,
        basis=Basis(snapshot_sha256=digest({"state": basis, "sender_sha256": digest(sender), "policy_version": POLICY_VERSION, "release_id": release_id}), draft_sha256=digest(draft) if draft else "", revision=basis["revision"] or 0, release_id=release_id, policy_version=POLICY_VERSION),
        authorization=Authorization(commercial=commercial, seller_approval=approval_status, independently_verified=False),
        sources=sources, facts=facts, findings=findings, planning=plan,
        checks_performed=["retained_intake", "quote_alignment", "recorded_extraction_coverage", "draft_currency", "recorded_restrictions", "sender_bound_approval", "saved_planning"],
        not_assessed=["claim_truth_or_general_semantic_entailment", "live_tool_behavior", "seller_identity_or_resale_rights", "exhaustive_contradiction_detection", "FAHCE", "payment_eligibility_or_readiness"], next_step=next_step, human_readable="")
    report.human_readable = readable(report)
    if len(encoded(report.dict()).encode("utf-8")) > MAX_EXPORT_BYTES:
        raise ValueError("readiness_report_too_large")
    return report.dict()


def readable(report):
    saved_revision = next((fact.value for fact in report.facts if fact.pointer == '/draft/revision'), 'none')
    stale = next((item for item in report.findings if item.code == 'DRAFT_OUTDATED'), None)
    lines = ["Offer readiness: " + report.status.replace("_", " "), "Preparation for review only — not certification, seller permission, approval or payment readiness.",
             "Snapshot: " + report.basis.snapshot_sha256, "Assessed intake revision: " + str(report.basis.revision),
             "Saved draft revision: " + saved_revision,
             stale.detail + ' ' + stale.next_step if stale else 'No pending intake corrections.',
             "Release: " + report.basis.release_id,
             "Commercial authorization: " + report.authorization.commercial, "Recorded seller approval: " + report.authorization.seller_approval,
             "", "Recorded facts and source alignment (quotations are not verified truth):"]
    lines.extend(f"- {item.pointer} [{item.basis}; {', '.join(item.evidence_refs) or 'no document reference'}]: {item.value}" for item in report.facts)
    if not report.facts:
        lines.append("- No recorded facts.")
    lines.extend(["", "Sources:"])
    lines.extend(f"- {item.id}: {item.url} [SHA-256 {item.sha256}]" for item in report.sources)
    lines.extend(["", "Findings and missing information:"])
    lines.extend(f"- {item.code} at {item.pointer}: {item.detail}\n  Next: {item.next_step}" for item in report.findings)
    lines.extend(["", "Saved planning (not implemented or commercial facts):"])
    lines.extend(f"- {item.id} [{item.kind}; {item.status}]: {item.text}" + (f" [criterion for {item.requirement_id}; not executed]" if item.requirement_id else "") for item in report.planning)
    lines.extend(["", "Checks performed: " + ", ".join(report.checks_performed), "Not assessed: " + ", ".join(report.not_assessed), "", "One next step: " + report.next_step])
    return "\n\n".join(lines)


def human_summary(report):
    def compact(value, limit=260):
        text = " ".join(str(value).split())
        return text if len(text) <= limit else text[:limit] + "… (full value in detailed report)"

    findings = report["findings"]
    restrictions = next((json.loads(item["detail"]) for item in findings if item["pointer"] == "/restrictions"), {})
    customer = next((fact["value"] for fact in report["facts"] if fact["pointer"] == "/fields/customer"), "Not recorded")
    outdated = next((item["detail"] for item in findings if item["code"] == "DRAFT_OUTDATED"), None)
    saved_revision = next((fact['value'] for fact in report['facts'] if fact['pointer'] == '/draft/revision'), 'none')
    lines = ["## Offer readiness: " + report["status"].replace("_", " "),
             "Preparation for review only — not certification, approval or payment readiness.",
             "**Assessed intake revision:** " + str(report["basis"]["revision"]),
             "Revision is the shared saved-state counter: changed intake and explicit draft rebuilds both advance it. Draft v counts generated drafts separately.",
             "**Customer (seller statement):** " + compact(customer),
             "**Draft:** " + (outdated or ("No saved draft." if any(item["code"] == "DRAFT_MISSING" for item in findings) else "Saved draft revision " + saved_revision + "; current; no pending intake corrections.")),
             "### Evidence boundaries", evidence_summary(report),
             "Commercial authorization: " + report["authorization"]["commercial"].replace("_", " ") + ". Seller approval: " + report["authorization"]["seller_approval"].replace("_", " ") + "."]
    if restrictions.get("demonstration_only"):
        lines.append("**Demonstration only — no commercial use.** Lifecycle current_product identifies the current record, not a real or commercially authorized product.")
    missing = [item["pointer"].rsplit("/", 1)[-1] for item in findings if item["code"] in {"INTAKE_MISSING", "INTAKE_UNDECIDED"}]
    caveats = []
    if missing:
        caveats.append("Missing or undecided intake: " + ", ".join(missing) + ".")
    codes = {item["code"] for item in findings}
    if codes & {"DOCUMENTS_MISSING", "DOCUMENTATION_INSUFFICIENT"}:
        caveats.append("Documentation is missing or insufficient for this offer; do not infer supported behavior.")
    if "DOCUMENT_FETCH_FAILED" in codes:
        caveats.extend(compact(item["detail"]) for item in findings if item["code"] == "DOCUMENT_FETCH_FAILED")
    if codes & {"EXTRACTION_INCOMPLETE", "EXTRACTION_COVERAGE"}:
        caveats.append("Extraction has recorded coverage limits; unextracted information is not proof of absence.")
    if "OPEN_DECISION" in codes:
        caveats.append("Saved planning decisions remain unresolved; proposals are not implemented facts.")
    lines.extend(["### Meaningful caveats", "\n".join("- " + text for text in caveats + ["Identity, resale rights, live behavior, payment eligibility and semantic claim truth are not verified."]),
                  "### Next action", report["next_step"],
                  "**Detailed interfaces:** readiness text / readiness json include all facts, source paths, hashes and findings; large reports intentionally use multipart exports. export json retains the offer audit.",
                  "Assessment snapshot: " + report["basis"]["snapshot_sha256"]])
    text = "\n\n".join(lines)
    if len(text.encode("utf-8")) > REPLY_BYTES:
        raise ValueError("readiness_summary_too_large")
    return text


def machine_result(store, sender, session, release_id):
    key = store.key(sender, session)
    report = assess(store.load(key), sender, release_id)
    payload = encoded(report)
    summary = {"status": report["status"], "scope": report["scope"], "basis": report["basis"],
               "authorization": report["authorization"], "finding_count": len(report["findings"]), "next_step": report["next_step"]}
    delivery = {"schema_version": "TOOL_OFFER_READINESS_DELIVERY_V1", "snapshot_sha256": report["basis"]["snapshot_sha256"], "report_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "summary": summary}
    if len(payload.encode("utf-8")) + len(report["human_readable"].encode("utf-8")) <= 18000 and len(report["human_readable"].encode("utf-8")) <= REPLY_BYTES:
        return {"status": "complete", "text": report["human_readable"], "readiness": {**delivery, "delivery": "inline", "report": report}, "model_attempts": 0}
    manifest = json.loads(deliver(store, key, payload, report["basis"]["revision"], "readiness")) if len(payload.encode("utf-8")) > REPLY_BYTES else None
    if manifest is None:
        return {"status": "complete", "text": payload, "readiness": {**delivery, "delivery": "text_json"}, "model_attempts": 0}
    return {"status": "complete", "text": encoded(manifest), "readiness": {**delivery, "delivery": "multipart", "manifest": manifest}, "model_attempts": 0}


class ReadinessText(str):
    def __new__(cls, text, metadata=None):
        value = super().__new__(cls, text)
        value.metadata = metadata
        return value


def native_reply(store, sender, session, release_id, command, request_id=None):
    from .readiness_cards import card_metadata

    key = store.key(sender, session)
    journal_key = "readiness_requests_" + key
    journal = store.load(journal_key).get("requests", {})
    if request_id and request_id in journal:
        prior = journal[request_id]
        if prior["command"] != command:
            return ReadinessText("This readiness request ID was already used for different arguments; nothing was changed.")
        return ReadinessText(prior["text"], prior["metadata"])
    if request_id and len(journal) >= 100:
        return ReadinessText("Readiness request journal is full for this conversation; retained reports remain available. Nothing was overwritten.")
    report = assess(store.load(key), sender, release_id)
    payload = human_summary(report) if command == "readiness" else encoded(report) if command == "readiness json" else report["human_readable"]
    text = deliver(store, key, payload, report["basis"]["revision"], "readiness_json" if command == "readiness json" else "readiness_text")
    try:
        metadata = card_metadata(report) if command == "readiness" and not sender.startswith("machine:") else None
    except Exception:
        metadata = None
    if request_id:
        journal[request_id] = {"command": command, "text": text, "metadata": metadata}
        store.save(journal_key, {"requests": journal})
    return ReadinessText(text, metadata)
