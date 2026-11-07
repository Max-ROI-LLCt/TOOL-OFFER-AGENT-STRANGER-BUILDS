"""Optional ACP forms/review cards with session-local, revision-bound selections."""

import json
import hashlib
import re
from uuid import uuid4
from urllib.parse import urlsplit

from .customer_recovery import discovery_text, suggestions, evidence_text
from .readiness import ReadinessText
from .restrictions import describe as describe_restrictions

COMMANDS = {"recovery form", "review intake", "review offer", "source suggestions", "suggest docs"}
FIELDS = ("customer", "job", "pricing", "payment", "access", "invocation", "docs", "tool_url", "seller_name")
FINISH = {"finish review", "confirm review", "finish review (no approval or purchase)"}
WELCOME_LABELS = {
    "Start with my tool": "welcome_start", "Try a fictional example": "welcome_demo",
    "Continue intake": "welcome_start", "Review current draft": "welcome_review",
    "Review intake": "welcome_intake", "Build a limited draft": "welcome_build",
}
WELCOME_PROMPTS = (
    "what do you do", "what can you do", "hi", "hello", "start",
    "help me turn my api documentation into a commercial offer draft",
    "i have an mcp tool. what information do you need to prepare its listing",
)


def welcome_request(text):
    phrases = {**dict.fromkeys(WELCOME_PROMPTS, "welcome"),
               **{label.casefold(): action for label, action in WELCOME_LABELS.items() if label != "Review intake"}}
    for phrase in sorted(phrases, key=len, reverse=True):
        match = re.fullmatch(re.escape(phrase) + r"(?:[.!?](?=\s|$)|(?=$)|(?=\n)|:(?=\s)|(?=\s+(?:https?://|(?:" + '|'.join(FIELDS) + r")\s*:)))\s*(.*)", text.strip(), re.I | re.S)
        if match:
            return phrases[phrase], match[1].strip()
    return None


def demo_available(state):
    return not any(state.get(name) for name in (
        "fields", "documents", "draft", "product_history", "offer_lineage", "planning",
        "fahce_checkout", "pending_payment", "commercial_transactions", "approved_offer"))


def welcome(workflow, state, note=""):
    from .customer_recovery import INTRO
    if demo_available(state):
        choices = ["Start with my tool", "Try a fictional example"]
        text = (workflow.name + '\n\n' if workflow.name != 'Tool Offer Agent' else '') + INTRO
        fallback = "Or paste your public tool URL here to get started."
    else:
        missing = workflow.missing(state)
        if state.get("draft"):
            choices = ["Review current draft", "Continue intake" if missing else
                       "Build a limited draft" if state.get("outdated") else "Review intake"]
            text = "Your saved draft is preserved." + (" Corrections are not yet incorporated." if state.get("outdated") else "")
        else:
            choices = ["Continue intake" if missing else "Build a limited draft", "Review intake"]
            text = "Your saved intake is preserved."
        fallback = workflow._question(state, concise=True) if missing else "Type a choice to continue in plain chat."
    state["onboarding_shown"] = True
    text = (note + "\n\n" if note else "") + text + "\n\n" + "\n".join("- " + label for label in choices) + "\n\n" + fallback
    return issue(state, "welcome", text, choices=choices)


def welcome_action(workflow, state, action, key, sender):
    if action == "welcome_demo":
        if not demo_available(state):
            return welcome(workflow, state, "The fictional example needs a fresh conversation; your existing work was not replaced.")
        from dataclasses import asdict
        from .documents import Document
        from .parcel_fixture import URL, SPEC, FIELDS as PARCEL_FIELDS, RESTRICTION
        from .restrictions import capture
        state["restrictions"] = capture(state.get("restrictions"), RESTRICTION, origin="selected_fictional_example")
        state["fields"] = workflow._validate_updates(PARCEL_FIELDS)
        state["documents"] = [asdict(Document(URL, URL, json.dumps(SPEC, ensure_ascii=False), "application/json"))]
        workflow._invalidate(state)
        state["awaiting"] = None
        state["onboarding_shown"] = True
        workflow.store.save(key, state)
        result = workflow._build(state, limited=True)
        if not state.get("draft"):
            return result
        return issue(state, "offer", "Fictional parcel draft ready. " + RESTRICTION +
                     "\n\nBundled documentation and fictional seller terms—not a fetched or running service. No model call or payment."
                     "\n\n" + review_summary(state))
    if action == "welcome_intake":
        return handle_guided(workflow, state, "review intake", key, sender)
    if action == "welcome_review":
        return handle_guided(workflow, state, "review offer", key, sender)
    if workflow.missing(state):
        return workflow._question(state, concise=True)
    if state.get("draft") and not state.get("outdated"):
        return handle_guided(workflow, state, "review offer", key, sender)
    if action == "welcome_build":
        return workflow._handle(state, "draft limited", key, sender)
    return "Intake values saved. Use Build a limited draft to prepare a reviewable offer without a model call."


def handle_welcome(workflow, state, request, key, sender):
    action, remainder = request
    if remainder:
        from .documents import DocumentError
        try:
            first, separator, rest = remainder.partition('\n')
            direct = workflow._direct_url_input(state, first)
            normalized = direct + separator + rest if direct else remainder
            if not direct and not normalized.lstrip().startswith('{') and not re.search(r'(?m)^(?:revise )?[a-zA-Z_ ]+:', normalized):
                return "No intake values changed. Paste a public tool URL or use field: value lines."
            updates = workflow._updates(state, normalized)
        except (ValueError, DocumentError) as error:
            return str(error) + " Nothing changed. Use field: value lines or paste a public tool URL."
        workflow._capture_restrictions(state)
        state.pop("guided_card", None)
        state["onboarding_shown"] = True
        return workflow._handle(state, json.dumps(updates), key, sender, limited=True)
    if action == "welcome":
        return welcome(workflow, state)
    state.pop("guided_card", None)
    return welcome_action(workflow, state, action, key, sender)


def is_guided_request(state, text):
    if welcome_request(text):
        return True
    command = text.strip().lower().rstrip('.!')
    if command in COMMANDS | FINISH | {"cancel review", "cancel form", "cancel card", "correct a value", "edit review"}:
        return True
    if re.fullmatch(r'revise (' + '|'.join(FIELDS) + r'):\s*[^\r\n]*', text.strip(), re.I):
        return True
    if text.lstrip().startswith('{'):
        try:
            value = json.loads(text)
            return isinstance(value, dict) and bool({'card_id', 'action'} & set(value))
        except ValueError:
            return False
    card = state.get('guided_card', {})
    if card.get('kind') in {'intake', 'correction'}:
        return bool(re.fullmatch(r'(?:please )?(?:set|change|update) (?:the |my )?(customer|job|pricing|payment|access|invocation|docs|tool_url|seller_name) to (.+)', text.strip(), re.I))
    return card.get('kind') == 'recovery' and bool(re.fullmatch(r'(?:please )?(?:retry the same saved urls|retry the previous documentation(?: url)?|retry the same (?:url|documentation)|(?:select|use|read) (?:source|suggestion|option) [1-3])', command))


def preview(value, budget=340):
    text = str(value)
    raw = text.encode("utf-8")
    if len(raw) <= budget:
        return text
    prefix = raw[:budget].decode("utf-8", errors="ignore")
    prefix = prefix.rsplit(' ', 1)[0] if ' ' in prefix else '[Long value]'
    return prefix + "… [preview]"


def fact_preview(entries, documents, *, projected=False):
    from .drafting import presentation_fact
    from .offer_representation import human_highlight
    details = []
    for entry in entries:
        if entry.get('presentation_example'):
            continue
        if re.fullmatch(r'https?://\S+', entry['text']):
            continue
        item = entry if projected else presentation_fact(entry, documents)
        if item.get('evidence_status') == 'legacy_fragment_requires_review':
            continue
        text = human_highlight(item, documents, concise=True)
        if text not in details:
            details.append(text)
    if not details:
        return "No descriptive facts extracted; retained references are not capabilities."
    selected = []
    for detail in details:
        if len(('\n'.join(selected + [detail])).encode()) > 560:
            continue
        selected.append(detail)
        if len(selected) == 3:
            break
    notice = '\nLegacy fragments require review; original excerpts remain in audit.' if not projected and any(presentation_fact(entry, documents).get('evidence_status') == 'legacy_fragment_requires_review' for entry in entries) else ''
    remaining = len(details) - len(selected)
    return ('\n'.join(selected) or 'Detailed schema retained.') + (f"\n{remaining} more {'detail' if remaining == 1 else 'details'} in the complete offer." if remaining else '') + notice


def rebuild_instruction(state):
    return ('Use draft limited to rebuild the fictional offer; keep it demonstration-only.'
            if state.get('restrictions', {}).get('demonstration_only') else
            'Use draft to generate a new version when ready.')


def review_summary(state):
    draft = state.get("draft") or {}
    offer = draft.get("offer", {})
    label = 'Draft v' + str(draft['draft_version']) if draft.get('draft_version') else 'Saved draft (legacy numbering)'
    lines = [label + ' — review summary, not the complete offer; saved draft revision ' + str(draft.get('revision', state['revision'])) + '; current intake revision ' + str(state['revision']) + ('. OUTDATED: corrections pending. ' + rebuild_instruction(state) if state.get('outdated') else '.'),
             'The card summarizes retained documentation claims and seller statements, not verified behavior. ' + describe_restrictions(state.get('restrictions')),
             'Concise human view: buyer explanation. Detailed offer: export buyer readable. Exact schemas and source history: export json. For multipart exports, retrieve every part and verify the hash; a manifest is not the document.',
             'State revision advances for changed intake and explicit draft rebuilds; Draft v counts generated drafts.',
             'Review does not approve, publish, purchase or prepare checkout. Plain chat: finish review, revise field: value, or cancel review.']
    return "\n\n".join(lines)


def intake_summary(state, *, correction_form=False):
    lines = ["## Current retained intake — state revision " + str(state['revision']),
             "These are current seller-stated values, not a replacement form or commercial authorization. Missing values are shown explicitly."]
    for field in FIELDS:
        value = state['fields'].get(field)
        rendered = "\n".join("- " + item for item in value) if isinstance(value, list) else str(value) if value else "Not supplied."
        lines.append("### " + field + "\n\n" + rendered)
    if state.get('draft'):
        lines.append("Saved draft revision " + str(state['draft']['revision']) + (" is outdated; corrections have not been incorporated." if state.get('outdated') else " is current."))
    path = "Use the one-field replacement form, or type revise field: value. This form has no separate cancel button; type cancel review to exit without saving." if correction_form else "Choose Correct a value to open the one-field replacement form, or type revise field: value. Cancel review leaves all values unchanged; plain-chat fallback: cancel review."
    lines.append(path + " An identical replacement does not advance revision or stale the draft. State revision also advances for explicit draft rebuilds.")
    return "\n\n".join(lines)


def valid_metadata(metadata):
    try:
        if not isinstance(metadata, dict) or not all(isinstance(value, str) for value in metadata.values()):
            return False
        if (metadata.get("card_protocol_version") != "1" or metadata.get("requires_card_interaction") != "true"
                or metadata.get("card_kind") not in {"form", "review", "custom"} or "is_terminal" in metadata):
            return False
        if len(metadata["card_payload"].encode()) > 8000:
            return False
        payload = json.loads(metadata["card_payload"])
        def cta(value):
            return (isinstance(value, dict) and isinstance(value.get("label"), str)
                    and isinstance(value.get("selection"), dict)
                    and set(value["selection"]) == {"action", "card_id"}
                    and value["selection"]["action"] in {"recover", "correct", "reviewed", "edit", "edit_intake", "cancel"} | set(WELCOME_LABELS.values())
                    and bool(re.fullmatch(r"[a-f0-9]{32}", value["selection"]["card_id"])))
        if metadata["card_kind"] == "custom":
            root = payload.get("root", {})
            if (set(payload) != {"root"} or set(root) != {"type", "title", "children"}
                    or root["type"] != "section" or not isinstance(root["title"], str)
                    or not isinstance(root["children"], list) or not 3 <= len(root["children"]) <= 16):
                return False
            sections, buttons = root["children"][:-2], root["children"][-2:]
            for section in sections:
                if (not isinstance(section, dict) or set(section) != {"type", "title", "children"}
                        or section["type"] != "section" or not isinstance(section["title"], str)
                        or not isinstance(section["children"], list) or len(section["children"]) != 1):
                    return False
                child = section["children"][0]
                if not isinstance(child, dict) or set(child) != {"type", "value"} or child["type"] != "text" or not isinstance(child["value"], str):
                    return False
            for button in buttons:
                if (not isinstance(button, dict) or set(button) != {"type", "label", "action"}
                        or button["type"] != "button" or not isinstance(button["action"], dict)
                        or set(button["action"]) != {"selection"}
                        or not cta({"label": button["label"], **button["action"]})):
                    return False
            actions = tuple(button["action"]["selection"]["action"] for button in buttons)
            welcome_pairs = {("welcome_start", "welcome_demo"), ("welcome_start", "welcome_intake"),
                             ("welcome_build", "welcome_intake"), ("welcome_review", "welcome_start"),
                             ("welcome_review", "welcome_intake"), ("welcome_review", "welcome_build")}
            if actions != ("reviewed", "edit") and actions not in welcome_pairs:
                return False
            return buttons[0]["action"]["selection"]["card_id"] == buttons[1]["action"]["selection"]["card_id"]
        if not isinstance(payload.get("title"), str):
            return False
        if metadata["card_kind"] == "review":
            return (set(payload) == {"title", "summary_rows", "approve_cta", "reject_cta"}
                    and len(payload["summary_rows"]) <= 12
                    and all(set(row) == {"label", "value"} and all(isinstance(v, str) for v in row.values()) for row in payload["summary_rows"])
                    and cta(payload["approve_cta"]) and cta(payload["reject_cta"]))
        if set(payload) != {"title", "fields", "submit_cta"} or not cta(payload["submit_cta"]) or not 1 <= len(payload["fields"]) <= 3:
            return False
        for field in payload["fields"]:
            if (not set(field).issubset({"name", "kind", "label", "required", "options"})
                    or field.get("kind") not in {"text", "select"}
                    or not all(isinstance(field.get(k), str) for k in ("name", "label"))):
                return False
            if field["kind"] == "select" and (not field.get("options") or not all(set(o) == {"label", "value"} and all(isinstance(v, str) for v in o.values()) for o in field["options"])):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def issue(state, kind, text, *, choices=None):
    card_id = uuid4().hex
    state["guided_card"] = {"id": card_id, "kind": kind, "revision": state["revision"], "candidates": suggestions(state),
                            "draft_sha256": hashlib.sha256(json.dumps(state.get("draft"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    def cta(label, action):
        return {"label": label, "selection": {"action": action, "card_id": card_id}}
    if kind == "welcome":
        state["guided_card"]["actions"] = [WELCOME_LABELS[label] for label in choices]
        payload = {"root": {"type": "section", "title": "Choose a next step", "children": [
            {"type": "section", "title": "Buttons or plain chat", "children": [
                {"type": "text", "value": "You can also type a choice from the message."}]}] + [
            {"type": "button", "label": label, "action": {"selection": cta(label, WELCOME_LABELS[label])["selection"]}}
            for label in choices]}}
    elif kind == "recovery":
        options = [{"value": "retry", "label": "Retry the same saved URLs"}, {"value": "replace", "label": "Read a replacement URL"}, {"value": "continue", "label": "Continue in plain chat"}]
        options += [{"value": str(i), "label": item["url"]} for i, item in enumerate(suggestions(state), 1)]
        payload = {"title": "Recover documentation", "fields": [
            {"name": "choice", "kind": "select", "label": "Next step (references remain unverified)", "required": True, "options": options},
            {"name": "url", "kind": "text", "label": "Replacement public documentation URL (only for replace)", "required": False}],
            "submit_cta": cta("Apply documentation choice", "recover")}
    elif kind == "intake":
        payload = {"title": "Current retained intake", "summary_rows": [
            {"label": field, "value": preview("; ".join(state['fields'][field]) if isinstance(state['fields'].get(field), list) else state['fields'].get(field, "Not supplied."), 500)}
            for field in FIELDS], "approve_cta": cta("Correct a value", "edit_intake"), "reject_cta": cta("Cancel review", "cancel")}
    elif kind == "correction":
        payload = {"title": "Correct one intake value", "fields": [
            {"name": "field", "kind": "select", "label": "Field to correct", "required": True, "options": [{"value": f, "label": f} for f in FIELDS]},
            {"name": "value", "kind": "text", "label": "New public value (never credentials)", "required": True}],
            "submit_cta": cta("Save correction", "correct")}
    else:
        from .offer_representation import display_facts
        draft = state.get("draft") or {}
        offer = draft.get("offer", {})
        documents = state.get('draft_documents', state.get('documents', []))
        projected, _ = display_facts(offer, documents)
        rows = [{"label": "Draft and intake revisions", "value": 'Saved draft revision ' + str(draft.get('revision', 'unknown')) + '; current intake revision ' + str(state['revision']) + ('. OUTDATED: corrections pending. ' + rebuild_instruction(state) if state.get('outdated') else '. Current; no pending corrections.')},
                {"label": "Documentation", "value": preview(evidence_text(draft.get("documentation_evidence", {})))}]
        labels = {'capabilities': 'What it does', 'inputs': 'Required inputs', 'outputs': 'Expected results',
                  'limitations': 'Limitations', 'documented_commercial_terms': 'Third-party terms'}
        rows += [{"label": labels[name] + " (documentation claims)", "value": fact_preview(projected[name], documents, projected=True) if projected[name] else "Not extracted; unknown"} for name in labels]
        rows += [{"label": "Seller-stated " + f + (' (pending intake, not saved draft)' if state.get('outdated') else ''), "value": preview(state["fields"].get(f, "not supplied"))} for f in ("customer", "pricing", "payment", "access", "invocation")]
        rows.append({"label": "Sources and boundaries", "value": describe_restrictions(state.get('restrictions')) + '\n' + preview('; '.join(draft.get('seller', {}).get('source_urls', [])), 240) + '\nDerived documentation claims. Other operations and illustrative examples are not added to this offer. Exact sources: export json. Drafting needs no wallet; optional FAHCE evaluation is separate.'})
        rows.append({"label": "Complete details", "value": "Send buyer explanation for the concise view; export buyer readable for full details; export json for the audit. Large detailed exports may be multipart."})
        payload = {"root": {"type": "section", "title": "Review sources and seller statements", "children": [
            {"type": "section", "title": row["label"], "children": [{"type": "text", "value": row["value"]}]} for row in rows] + [
            {"type": "button", "label": "Finish review (no approval or purchase)", "action": {"selection": cta("Finish", "reviewed")["selection"]}},
            {"type": "button", "label": "Correct a value", "action": {"selection": cta("Correct", "edit")["selection"]}}]}}
    metadata = {"card_protocol_version": "1", "requires_card_interaction": "true", "card_id": card_id, "card_kind": "custom" if kind in {"offer", "welcome"} else "review" if kind == "intake" else "form", "card_payload": json.dumps(payload, ensure_ascii=False), "preferred_drawer_width_px": "540"}
    return ReadinessText(text, metadata) if valid_metadata(metadata) else str(text)


def attach_recovery(state, text):
    return issue(state, "recovery", str(text) + "\nOptional recovery card available. Plain chat: retry, docs: <public URL>, source suggestions, or continue intake.")


def handle_guided(workflow, state, text, key, sender):
    request = welcome_request(text)
    if request:
        return handle_welcome(workflow, state, request, key, sender)
    command = text.strip().lower().rstrip('.!')
    revision = re.fullmatch(r'revise (' + '|'.join(FIELDS) + r'):\s*([^\r\n]*)', text.strip(), re.I)
    if revision:
        return correction(workflow, state, revision[1].lower(), revision[2])
    if command in {"source suggestions", "suggest docs"} or re.fullmatch(r"(?:can you |please )?(?:suggest|recommend|offer) (?:another|alternative|public|relevant)(?: documentation| docs| sources?| links?| urls?)+(?:\?)?", command):
        return discovery_text(state)
    if command == "recovery form":
        return attach_recovery(state, discovery_text(state))
    if command == "review intake":
        return issue(state, "intake", intake_summary(state))
    if command == "review offer":
        return issue(state, "offer", review_summary(state)) if state.get("draft") else "No draft yet. Continue intake, then use draft and review offer."
    card = state.get("guided_card")
    if command in {"cancel review", "cancel form", "cancel card"}:
        if not card:
            return "No active card to cancel. Existing draft and intake preserved; no approval, checkout or publication."
        state.pop("guided_card", None)
        return "Card cancelled. Existing draft and intake preserved; no approval, checkout or publication. Continue in plain chat."
    selection = None
    if text.lstrip().startswith("{"):
        try:
            def unique(pairs):
                value = {}
                for name, item in pairs:
                    if name in value:
                        raise ValueError('Duplicate selection key')
                    value[name] = item
                return value
            candidate = json.loads(text, object_pairs_hook=unique)
        except ValueError:
            return "Invalid card selection JSON. No changes made. Request a fresh card or use plain field: value."
        if isinstance(candidate, dict) and ("card_id" in candidate or "action" in candidate):
            selection = candidate
    elif card or command.rstrip('.!') in FINISH:
        if card is None:
            card = next(reversed(state.get('guided_actions', {}).values()), None)
        if card is None:
            return "No active review to finish. Request review offer; no approval, checkout or publication was created."
        # Planner prose is resolved against this conversation's current card only.
        normalized = command.rstrip(".!")
        correction_match = re.fullmatch(r"(?:please )?(?:set|change|update) (?:the |my )?(customer|job|pricing|payment|access|invocation|docs|tool_url|seller_name) to (.+)", text.strip(), re.I)
        if card["kind"] in {"intake", "correction"} and correction_match:
            selection = {"action": "correct", "card_id": card["id"], "field": correction_match[1].lower(), "value": correction_match[2]}
        elif card["kind"] == "intake" and normalized in {"correct a value", "edit review"}:
            selection = {"action": "edit_intake", "card_id": card["id"]}
        if card["kind"] == "recovery":
            if re.fullmatch(r"(?:please )?(?:retry the same saved urls|retry the previous documentation(?: url)?|retry the same (?:url|documentation))", normalized):
                selection = {"action": "recover", "card_id": card["id"], "choice": "retry"}
            match = re.fullmatch(r"(?:please )?(?:select|use|read) (?:source|suggestion|option) ([1-3])", normalized)
            if match:
                selection = {"action": "recover", "card_id": card["id"], "choice": match[1]}
        elif card["kind"] == "offer" and normalized in FINISH:
            selection = {"action": "reviewed", "card_id": card["id"]}
        elif card["kind"] == "offer" and normalized in {"correct a value", "edit review"}:
            selection = {"action": "edit", "card_id": card["id"]}
    if selection is None:
        return "No matching active card. Request review offer or review intake; no changes made." if command.rstrip('.!') in FINISH | {'correct a value', 'edit review'} else None
    action = selection.get("action")
    allowed = {"recover": {"action", "card_id", "choice", "url"}, "correct": {"action", "card_id", "field", "value"}, "reviewed": {"action", "card_id"}, "edit": {"action", "card_id"}}
    allowed.update({name: {"action", "card_id"} for name in ("edit_intake", "cancel")})
    allowed.update({name: {"action", "card_id"} for name in WELCOME_LABELS.values()})
    draft_hash = hashlib.sha256(json.dumps(state.get('draft'), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    bound = bool(card and selection.get('card_id') == card['id'] and card['revision'] == state['revision']
                 and card.get('draft_sha256') == draft_hash)

    def rejected(message):
        text = message + ' Intake revision ' + str(state['revision']) + '. Use review intake for a fresh correction form, or revise field: value.'
        return issue(state, card['kind'], text) if bound and card['kind'] in {'intake', 'correction', 'recovery'} else text

    if not isinstance(action, str):
        return rejected("Invalid card selection schema. No changes made.")
    if 'approved' in selection:
        if action not in allowed or type(selection['approved']) is not bool or (action not in {'edit', 'cancel'} and not selection['approved']):
            return rejected("Invalid card selection schema. No changes made.")
        selection = {name: value for name, value in selection.items() if name != 'approved'}
    if (action not in allowed or set(selection) - allowed[action] or not {'action', 'card_id'} <= set(selection)
            or not all(isinstance(value, str) and len(value) <= 6000 for value in selection.values())):
        return rejected("Invalid card selection schema. No changes made.")
    if any(isinstance(value, str) and workflow.selection_contains_secret(value) for value in selection.values()):
        return rejected("Do not send credentials or tokens in form selections. Nothing was saved; use public instructions and placeholders.")
    completed = state.get('guided_actions', {}).get(selection['card_id'])
    if completed and completed['kind'] == 'offer' and action == 'reviewed' and completed['revision'] == state['revision'] and completed['draft_sha256'] == draft_hash:
        return "Review already finished for saved draft revision " + str(completed.get('draft_revision', completed['revision'])) + ("; pending intake revision " + str(state['revision']) + " is not incorporated" if state.get('outdated') else '') + ". No commercial approval, checkout, publication or payment was created."
    selection_hash = hashlib.sha256(json.dumps(selection, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if (completed and completed['kind'] == 'welcome' and completed.get('selection_sha256') == selection_hash
            and completed['revision'] == state['revision'] and completed['draft_sha256'] == draft_hash):
        return 'Choice already handled; no work repeated. ' + (workflow._question(state, concise=True) if workflow.missing(state)
                                                              else 'Use review offer for your saved draft.')
    if (completed and action == 'correct' and completed.get('selection_sha256') == selection_hash
            and completed['revision'] == state['revision'] and completed['draft_sha256'] == draft_hash):
        return 'Correction already handled; not reapplied. ' + completed['reply']
    if not bound:
        return "This card is stale or belongs to another conversation. No changes made. Request review offer for a fresh review, review intake for a correction, or recovery form for documentation."
    if action == "cancel":
        state.pop('guided_card', None)
        return "Card cancelled. Existing draft and intake preserved; no approval, checkout or publication. Continue in plain chat."
    if card['kind'] == 'welcome':
        if action not in card['actions']:
            return rejected("Invalid card selection schema. No changes made.")
        state.pop('guided_card', None)
        result = welcome_action(workflow, state, action, key, sender)
        completed = state.setdefault('guided_actions', {})
        completed[card['id']] = {'id': card['id'], 'kind': 'welcome', 'revision': state['revision'],
            'draft_sha256': hashlib.sha256(json.dumps(state.get('draft'), sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'selection_sha256': selection_hash}
        while len(completed) > 16:
            del completed[next(iter(completed))]
        return result
    if action not in {"recovery": {"recover"}, "intake": {"correct", "edit_intake"}, "correction": {"correct"}, "offer": {"reviewed", "edit"}}[card["kind"]]:
        return rejected("Invalid card selection schema. No changes made.")
    if action == "edit_intake":
        return issue(state, "correction", "Choose one field and supply its complete new public value.\n\n" + intake_summary(state, correction_form=True))
    if action == "recover":
        choice = selection.get("choice")
        if choice == "retry":
            previous = list(state.get("documents", []))
            result = workflow._read_documents(state, refresh=True)
            if state.get("documents", []) != previous:
                workflow._invalidate(state)
            result += "\n\n" + workflow._question(state)
        elif choice == "continue":
            result = "Continuing in plain chat. " + workflow._question(state)
        elif choice == "replace" or choice in {str(i) for i in range(1, len(card["candidates"]) + 1)}:
            url = selection.get("url", "") if choice == "replace" else card["candidates"][int(choice) - 1]["url"]
            result = correction(workflow, state, "docs", url)
            if result.startswith('Correction rejected:'):
                return rejected(result)
        else:
            return rejected("Select retry, replace with a public URL, continue, or a numbered source suggestion. No changes made.")
    elif action == "correct":
        if selection.get("field") not in FIELDS or not selection.get("value") or "\n" in selection["value"] or "\r" in selection["value"]:
            return rejected("Choose one supported field and a nonempty single-line value. No changes made.")
        result = correction(workflow, state, selection["field"], selection["value"])
        if result.startswith('Correction rejected:'):
            return rejected(result)
        completed = state.setdefault('guided_actions', {})
        completed[card['id']] = {'id': card['id'], 'kind': card['kind'], 'revision': state['revision'],
            'draft_sha256': draft_hash, 'selection_sha256': selection_hash, 'reply': result}
        while len(completed) > 16:
            del completed[next(iter(completed))]
    elif action == "edit":
        return issue(state, "correction", "Correct one seller-stated value using the form or revise field: value.\n\n" + intake_summary(state, correction_form=True))
    else:
        revision = (state.get('draft') or {}).get('revision', card['revision'])
        result = "Review finished for saved draft revision " + str(revision) + ("; pending intake revision " + str(state['revision']) + " is not incorporated" if state.get('outdated') else '') + ". No commercial approval, checkout, publication or payment was created. " + (rebuild_instruction(state) + ' ' if state.get('outdated') else '') + "Use buyer explanation for the concise human view, export buyer readable for full detail, or revise field: value."
        completed = state.setdefault('guided_actions', {})
        completed[card['id']] = {name: card[name] for name in ('id', 'kind', 'revision', 'draft_sha256')}
        completed[card['id']]['draft_revision'] = revision
        while len(completed) > 16:
            del completed[next(iter(completed))]
    state.pop("guided_card", None)
    return result


def correction(workflow, state, field, value):
    """Validate and save a single choice without chaining extraction after a form."""
    from .customer_recovery import field_notes
    try:
        if field not in FIELDS:
            raise ValueError('Unsupported field')
        updates = workflow._validate_updates({field: value})
        if field == 'tool_url' and state['fields'].get(field):
            previous, replacement = urlsplit(state['fields'][field]), urlsplit(updates[field])
            if (previous.scheme, previous.netloc) != (replacement.scheme, replacement.netloc):
                return 'Correction rejected: tool_url identifies a different origin. Nothing changed; intake revision ' + str(state['revision']) + '. A product switch must not silently reuse these seller terms. Use tool_url: <new URL> to start the existing archived-product intake flow, or review intake to correct this product.'
    except ValueError:
        return "Correction rejected: " + str(field) + ". Invalid public value; nothing changed. Intake revision " + str(state['revision']) + ". Use review intake or revise field: value with a supported public URL where required."
    if all(state['fields'].get(name) == item for name, item in updates.items()):
        return field + " unchanged; the same value is already saved. Intake revision " + str(state['revision']) + ("; saved draft revision " + str(state['draft']['revision']) + (" remains outdated" if state['outdated'] else " is current") if state.get('draft') else "; no draft yet") + ". No fetch, model call, approval, checkout or publication. Use buyer explanation for the saved draft, or review intake."
    notes = field_notes(state, updates, state.get("awaiting"))
    if field == 'payment':
        notes = notes.replace(updates[field], '[saved seller wording; see export json]')
    if any(state["fields"].get(name) != item for name, item in updates.items()):
        state["fields"].update(updates)
        workflow._invalidate(state)
    read = ''
    if field == 'docs':
        workflow._read_documents(state)
        read = 'Documentation retrieval was not fully successful. ' + state['documentation_error'] + '\nSaved URLs and per-URL outcomes remain available. Use recovery form or retry.' if state.get('documentation_error') else 'Read ' + str(len(state.get('documents', []))) + ' documentation source(s); retained sources and coverage are available in export json.'
    return "Saved your " + field + ". Intake revision " + str(state['revision']) + ("; saved draft revision " + str(state['draft']['revision']) + " is outdated and unchanged" if state.get('draft') else "; no draft yet") + ". " + notes + "\n" + read + "\n" + rebuild_instruction(state) + " Review intake shows the saved correction. No extraction-model call, commercial approval, publication or checkout was made by this correction."
