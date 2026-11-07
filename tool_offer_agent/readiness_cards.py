"""Optional terminal ACP card. No inputs, links, buttons or action selections."""

import json


def valid_metadata(metadata):
    try:
        if not isinstance(metadata, dict) or not all(isinstance(value, str) for value in metadata.values()):
            return False
        if any(metadata.get(key) != value for key, value in {"card_protocol_version": "1", "requires_card_interaction": "true", "card_kind": "custom", "is_terminal": "true"}.items()):
            return False
        if len(metadata["card_payload"].encode("utf-8")) > 8000:
            return False
        payload = json.loads(metadata["card_payload"])

        def valid_node(node, depth):
            if not isinstance(node, dict) or depth > 3:
                return False
            if node.get("type") == "text":
                return set(node) == {"type", "value"} and isinstance(node["value"], str)
            if node.get("type") != "section" or not set(node).issubset({"type", "title", "subtitle", "children"}):
                return False
            return all(isinstance(node.get(key, ""), str) for key in ("title", "subtitle")) and isinstance(node.get("children"), list) and all(valid_node(child, depth + 1) for child in node["children"])

        return set(payload) == {"root"} and valid_node(payload["root"], 1)
    except (KeyError, TypeError, ValueError):
        return False


def compact(value, limit=420):
    value = str(value)
    raw = value.encode("utf-8")
    return value if len(raw) <= limit else raw[:limit].decode("utf-8", errors="ignore") + "… [excerpt]"


def evidence_summary(report):
    counts = {basis: sum(fact["basis"] == basis for fact in report["facts"]) for basis in ("verbatim_quote", "source_backed_derived", "derived_schema_or_unaligned")}
    quotes = str(counts["verbatim_quote"]) + " exact retained document quotations" if counts["verbatim_quote"] else "No exact retained document quotations"
    return (quotes + "; " + str(counts["source_backed_derived"]) + " source-backed derived statements (including schema extractions, not verbatim quotes); "
            + str(counts["derived_schema_or_unaligned"]) + " statements with unresolved alignment. These counts assess saved claims, not the buyer view's recovered schema summaries. None is independently verified truth or execution evidence.")


def card_metadata(report):
    try:
        sources = {source["id"]: source["url"] for source in report["sources"]}
        quoted = [fact for fact in report["facts"] if fact["basis"] == "verbatim_quote"]
        missing = [item for item in report["findings"] if item["code"] in {"INTAKE_MISSING", "INTAKE_UNDECIDED", "DRAFT_MISSING", "DOCUMENTS_MISSING"}]
        decisions = [item for item in report["planning"] if item["kind"] == "decision"]
        facts = "\n".join(compact(fact["value"], 180) + " — " + ", ".join(ref + ": " + sources[ref] for ref in fact["evidence_refs"]) for fact in quoted[:2]) or "No exact retained document quotations."
        sections = [
            ("Readiness", report["status"].replace("_", " ")),
            ("Saved state", "Assessed intake revision " + str(report["basis"]["revision"]) + ". " + next((item["detail"] for item in report["findings"] if item["code"] in {"DRAFT_OUTDATED", "DRAFT_MISSING"}), "Current draft; no pending intake corrections.")),
            ("Evidence types", evidence_summary(report)),
            ("Document-supported quotations, not verified truth", facts),
            ("Missing / undecided information", "; ".join(item["detail"] for item in missing) or "No missing intake detected; other evidence caveats still apply."),
            ("Unverified permissions and claims", report["authorization"]["commercial"] + "; identity, resale rights and semantic claim truth are not verified. Seller approval: " + report["authorization"]["seller_approval"]),
            ("Unresolved decisions", "; ".join(item["id"] + ": " + item["text"] for item in decisions) or "No saved open decisions. This does not establish completeness."),
            ("One next step", report["next_step"]),
            ("Assessment snapshot", report["basis"]["snapshot_sha256"]),
        ]
        payload = {"root": {"type": "section", "title": "Tool Offer readiness", "subtitle": "Informational summary only. No approval, purchase or payment action.",
                    "children": [{"type": "section", "title": title, "children": [{"type": "text", "value": compact(value, 760 if title == "Evidence types" else 420)}]} for title, value in sections]}}
        payload["root"]["children"].append({"type": "section", "title": "Complete assessment", "children": [{"type": "text", "value":
            (f"Showing {min(2, len(quoted))} of {len(quoted)} exact quotations. " if quoted else "") + "Send readiness text for the detailed assessment, or readiness json for all facts, paths and hashes. Large detailed results may be multipart."}]})
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) > 8000:
            return None
        return {"card_protocol_version": "1", "requires_card_interaction": "true", "card_kind": "custom", "card_payload": raw, "is_terminal": "true", "preferred_drawer_width_px": "540"}
    except (KeyError, TypeError, ValueError):
        return None
