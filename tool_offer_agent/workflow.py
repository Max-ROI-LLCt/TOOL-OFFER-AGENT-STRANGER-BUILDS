"""Credential-free conversational intake, durable drafts, revision and recovery."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import re
import shlex
import threading
import hashlib
from uuid import uuid4

from .restrictions import empty as empty_restrictions, capture as capture_restrictions, blocked as restrictions_blocked, describe as describe_restrictions
from .export_delivery import deliver as deliver_export, retrieve as retrieve_export

from .documents import DocumentError, PublicDocumentFetcher, validate_url
from .commerce import PaymentTerms, RAILS, Stage, TransactionJournal, TransitionError, digest, receipt, request_intent_digest, select_rail, verify_receipt
from .drafting import ExtractionError, OpenAIQuoteExtractor, build_draft, render_draft
from .fahce import FahceClient, PENDING, SCOPE, fingerprint
from .storage import StateStore
from .buyer_guidance import WALLET_ADDRESS_GUIDANCE, brief_wallet_information, buyer_command, buyer_guide, is_wallet_address_message, wallet_information_question
from .listing_guidance import build_checklist, handle_listing_request, offer_checklist
from .product_policy import PLAN_HELP, output_risk, planning_command, planning_context, product_answer
from .customer_recovery import INTRO, mixed_retry, field_notes, discovery_text, evidence, evidence_text, background_article

QUESTIONS = {
    "tool_url": "What is the public API or MCP URL? (No credentials or private/local URLs.)",
    "docs": "What public documentation URL should be read? Supply up to three URLs, separated by spaces.",
    "customer": "Who is the intended customer for this offer?",
    "pricing": "What is the pricing, including currency and billing unit? Say undecided if not set.",
    "payment": "How should customers pay? Public instructions only; say none for a free tool or undecided if not set.",
    "access": "How does a customer obtain access? Describe the process, not actual keys or tokens.",
    "invocation": "How does a customer invoke the tool? Give a public example with placeholders, never credentials.",
}
ALIASES = {"api": "tool_url", "url": "tool_url", "mcp": "tool_url", "api_url": "tool_url", "documentation": "docs", "docs_url": "docs", "intended_customer": "customer", "payment_instructions": "payment", "access_instructions": "access", "invocation_instructions": "invocation", "name": "seller_name"}
FIELDS = set(QUESTIONS) | {"seller_name", "job"}
HELP = "Use one answer at a time, or field: value lines: tool_url, docs, customer, pricing, payment, access, invocation. Optional: seller_name, job. Commands: listing checklist, listing checklist json, listing profile mcp/api/agent, export listing, demo, status, draft, draft limited, revise field: value, retry, refresh docs, reextract, export json, export readable, export buyer, buyer explanation, export representation, export part <export_id> <index>, preflight, check, reset, offer approve, payment options, transaction open, transaction summary, transaction status, transaction approve, transaction send. Successful extraction is cached; retry does not repeat a failed model call. Draft limited uses bounded deterministic extraction with no model call. Only reextract deliberately bypasses a successful cache and may consume model quota. When conversation is available, describe revisions in ordinary language; explicit job: or revise field: value commands also remain available. Do not send secrets. Nothing is published or purchased by intake."

STARTER_PROMPTS = {
    "help me turn my api documentation into a commercial offer draft.": "I can prepare a source-attributed, revisable API offer. Provide public URLs and the seven fields below; no credentials, purchases or publication are required.",
    "i have an mcp tool. what information do you need to prepare its listing?": "For an MCP tool, describe the public tool URL, one to three public documentation URLs, intended customer, pricing, payment, access and invocation instructions. Tool schemas and documentation are claims, not independently verified behavior.",
    "show me how to revise my offer and export the structured record.": "Use review intake or revise pricing: <new terms> for a concise correction outcome. An unchanged value keeps its revision; a changed value updates intake only. Use draft or draft limited to rebuild, then buyer explanation for the concise human view, export buyer readable for full detail, or export json for the source-attributed record. Large detailed exports may use hashed, resumable parts. Correction and Finish review do not approve, publish or purchase anything.",
    "what can tool offer agent verify, and what remains seller-supplied?": "Documentation excerpts are checked against the retrieved source text, not against real service behavior. Seller identity, pricing, access and payment terms remain seller-supplied. FAHCE is separate and is not executed through the machine adapter; native checkout availability must be checked separately. No seller certification or financial settlement is claimed.",
}


def contains_secret(text):
    if re.search(r"\b(?:private[_ -]?key|seed[_ -]?phrase|mnemonic|wallet[_ -]?seed)\s*[:=]|\b[a-fA-F0-9]{64}\b", text, flags=re.I):
        return True
    return bool(re.search(r"-----BEGIN .*PRIVATE KEY|\b(?:sk-[A-Za-z0-9_-]{12,}|0x[a-fA-F0-9]{64})\b|(?:api[_ -]?key|private[_ -]?key|secret|access[_ -]?token)\s*[:=]\s*(?!<|\{|YOUR_|PLACEHOLDER)[A-Za-z0-9_+/.=-]{16,}|\bBearer\s+(?!<|\{|YOUR_|PLACEHOLDER)[A-Za-z0-9_+/.=-]{16,}", text, flags=re.I))


class Workflow:
    selection_contains_secret = staticmethod(contains_secret)

    def __init__(self, store=None, fetcher=None, fahce=None, extractor=None, name="Tool Offer Agent", local_test=False, transaction_store=None, demo_buyer_address=None, demo_recipient=None, conversation=None, checkout=None):
        self.store = store if store is not None else StateStore()
        self.commerce = TransactionJournal(transaction_store if transaction_store is not None else self.store)
        self.local_test = local_test
        self.demo_buyer_address = demo_buyer_address
        self.demo_recipient = demo_recipient
        self.fetcher = fetcher if fetcher is not None else PublicDocumentFetcher()
        self.fahce = fahce if fahce is not None else FahceClient()
        self.checkout = checkout
        self.extractor = extractor
        self.name = name
        self.conversation = conversation
        self.lock = threading.RLock()
        self._session_locks = {}
        self._request_context = threading.local()

    @contextmanager
    def _session_guard(self, key):
        with self.lock:
            lock = self._session_locks.get(key)
            if lock is None and len(self._session_locks) < 128:
                lock = self._session_locks.setdefault(key, threading.Lock())
            acquired = lock is not None and lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                with self.lock:
                    lock.release()
                    self._session_locks.pop(key, None)

    def handle(self, sender, session, message, *, message_id=None, message_timestamp=None):
        if not sender or not session:
            return "A sender and conversation/session ID are required. No shared fallback conversation was used."
        if not isinstance(message, str) or len(message) > 16000:
            return "Message too large; use at most 16000 characters. Existing draft preserved."
        if contains_secret(message) and not re.fullmatch(r"export part [a-f0-9]{64} [1-9][0-9]{0,5}", message.strip().lower()):
            return "Do not send credentials, wallet private keys, or tokens in chat. This message was not saved; use placeholders and server-side configuration."
        if is_wallet_address_message(message):
            return WALLET_ADDRESS_GUIDANCE
        try:
            message.encode("utf-8")
        except UnicodeError:
            return "Invalid text encoding. Existing draft preserved."
        key = self.store.key(sender, session)
        with self._session_guard(key) as acquired:
            if not acquired:
                if message.strip().lower().lstrip("/") == "status":
                    current = self.store.load(key)
                    return "An earlier operation is processing; no additional inference started.\n" + self._handle(current, "status", key, sender)
                return "An earlier operation is processing. No instruction or model request was repeated. Use status; resend a new instruction after completion."

            state = self.store.load(key)
            if re.match(r'^\s*(?:```(?:json)?\s*|>\s*)\{', message, re.I):
                return "Quoted JSON is not applied as intake. Send a bare intake object or field: value lines to update fields. Existing draft preserved."
            from .guided_cards import is_guided_request
            if is_guided_request(state, message):
                return self._guided_response(state, message, key, sender, message_id, message_timestamp)
            try:
                structured = self._structured_intake(message)
            except (ValueError, DocumentError) as error:
                return str(error) + " Existing draft preserved; no intake values changed."
            if " ".join(message.casefold().split()) in STARTER_PROMPTS:
                return self._handle(state, message, key, sender)
            from .conversation import source_json_example, literal_protocol_answer, json_only_request
            example = source_json_example(state, message)
            if example is not None:
                return example
            protocol = literal_protocol_answer(state, message)
            if protocol is not None:
                return protocol
            if (state.get("draft") and not json_only_request(message)
                    and re.search(r"\b(?:write|draft|produce|give|create|provide|rewrite)\b.{0,70}\b(?:buyer copy|buyer.facing copy|buyer paragraph|buyer explanation|sales copy|offer copy)\b", message, re.I)):
                from .offer_representation import buyer_explanation
                return buyer_explanation(state["draft"], state.get("restrictions"), outdated=state.get("outdated", False), documents=state.get('draft_documents', state.get('documents', [])), pending_fields=state['fields'], intake_revision=state['revision'])
            from .readiness import readiness_command, native_reply
            readiness = readiness_command(message) if structured is None else None
            if readiness:
                from .machine_contract import RELEASE_ID
                try:
                    return native_reply(self.store, sender, session, RELEASE_ID, readiness, message_id)
                except (ValueError, TypeError, KeyError):
                    return "Readiness could not be assessed within the retained-state/schema limits. No complete report or authorization claimed; existing product state is unchanged."
            technical_source = bool(state.get("documents")
                                    and re.search(r"\b(?:recovery|receipts?|headers?|authorization|credentials?|openapi)\b", message, re.I)
                                    and re.search(r"\b(?:source|documented|documentation|api|endpoint|request|response|protocol)\b|/[a-z][a-z0-9_/{}-]+", message, re.I))
            # Source questions are read-only: no intake, fetch, extraction or payment.
            if (not self._explicit(message)
                    and (state.get("documents") or re.search(r"\b(?:saved|retained|fetched|previously)\b", message, re.I))
                    and (technical_source or re.search(r"\b(?:documentation|documents|previously saved|source text)\b", message, re.I))
                    and re.search(r"\?|^(?:explain|assess|describe|what|how)\b", message, re.I)):
                from .conversation import documentation_context
                records = documentation_context(state, message)
                accessible = [record for record in records if record["status"] == "ACCESSIBLE"]
                if not accessible:
                    return "TEXT_UNAVAILABLE: no retained source passages are accessible for this question. Documentation status is not proof of accessible text; no quotation, fetch or extraction was manufactured."
                if self.conversation is not None:
                    answer = self._converse(state, message, key, sender, source_question=True)
                    attribution = "\n\nRetrieved sources (documentation claims; not execution or permission):\n" + "\n".join(
                        str(record.get("source_url") or record.get("requested_url") or "[URL unavailable]") for record in accessible)
                    from .conversation import json_only_request
                    return answer if json_only_request(message) else answer + attribution
                sections = ["Retained documentation evidence relevant to your question (literal excerpts, not live execution proof or commercial permission). Missing support in these excerpts remains UNKNOWN; no intake or payment was initiated."]
                for record in records:
                    url = record.get("source_url") or record.get("requested_url") or "[source URL unavailable]"
                    sections.append("Source: " + url + " — " + record["status"])
                    for passage in record["passages"]:
                        sections.append("Offset " + str(passage["offset"]) + ":\n" + passage["text"])
                return "\n\n".join(sections)
            documented = product_answer(message)
            if documented:
                return documented
            if message.strip().lower().startswith("export part "):
                return retrieve_export(self.store, key, message.strip().lower())
            self._request_context.restriction_input = (message, message_id, message_timestamp)
            # Only literal retained user text can recover a historical declaration.
            if "restrictions" not in state:
                recovered = empty_restrictions()
                for item in state.get("conversation", []):
                    if item.get("role") == "user":
                        recovered = capture_restrictions(recovered, item.get("content", ""), origin="retained_history")
                if recovered["sources"]:
                    state["restrictions"] = recovered
                    self._invalidate(state)
                    self.store.save(key, state)

            normalized_information = " ".join(message.casefold().strip().rstrip(".!?").split())
            if wallet_information_question(message) and normalized_information not in {
                    "how do i connect my wallet", "how do i pay", "how do i pay for this"}:
                return brief_wallet_information(state, self.checkout is not None)
            deliveries = state.get("deliveries", {})
            request_hash = hashlib.sha256(message.encode()).hexdigest()
            if message_id and message_id in deliveries:
                recorded = deliveries[message_id]
                if recorded["request_hash"] != request_hash:
                    return "This message ID was already used for different text. No operation was repeated."
                if recorded.get("metadata"):
                    from .readiness import ReadinessText
                    return ReadinessText(recorded["reply"], recorded["metadata"])
                return recorded.get("reply") or "The earlier delivery was interrupted or is still processing. No automatic retry was made. Use status to inspect preserved work."
            planned = planning_command(state, message, message_id=message_id, timestamp=message_timestamp)
            if planned is not None:
                if message.strip().lower() not in {"plan status", "export plan"}:
                    if message_timestamp and state.get("last_message_timestamp") and message_timestamp < state["last_message_timestamp"]:
                        return "An older planning command was not applied. Use plan status."
                    if message_id:
                        state.setdefault("deliveries", {})[message_id] = {"request_hash": request_hash, "reply": planned}
                        while len(state["deliveries"]) > 32:
                            del state["deliveries"][next(iter(state["deliveries"]))]
                    if message_timestamp:
                        state["last_message_timestamp"] = message_timestamp
                    self.store.save(key, state)
                return planned
            text = buyer_command(message) or message.strip()
            if text.casefold().rstrip(".! ") in {"build the draft", "build draft"}:
                text = "draft"
            simple = self._intake_literal(state, text) if structured is None else None
            if simple is not None:
                text = simple
            if not self._explicit(text):
                text = self._direct_url_input(state, text) or text
            readonly = text.lower().lstrip("/") in {"status", "help", "wallet", "purchase guide", "preflight", "export", "export json", "export readable", "export buyer", "export representation", "buyer explanation", "export buyer readable"}
            readonly = readonly or bool(re.fullmatch(r"transaction (?:status|summary)(?: \S+)?", text.lower())) or text.lower() == "export incomplete"
            if message_timestamp and not readonly:
                previous = state.get("last_message_timestamp")
                if previous and message_timestamp < previous:
                    return "This message arrived after a newer message in this conversation. No older instruction was applied. Use status, then resend an explicit revision if still intended."
            if message_id and not readonly:
                deliveries = state.setdefault("deliveries", {})
                deliveries[message_id] = {"request_hash": request_hash}
                while len(deliveries) > 32:
                    del deliveries[next(iter(deliveries))]
                self.store.save(key, state)
            self._request_context.prior_restrictions = json.loads(json.dumps(state.get("restrictions", empty_restrictions())))
            before_restrictions = state.get("restrictions")
            if not readonly:
                self._capture_restrictions(state)
            restrictions_changed = before_restrictions != state.get("restrictions") and restrictions_blocked(state.get("restrictions"))
            field_update = structured is not None or any(re.match(r"^(?:revise\s+)?(?:" + "|".join(FIELDS | set(ALIASES)) + r")\s*:", line.strip(), re.I)
                               for line in text.splitlines())
            if text.lower().lstrip("/") in {"wallet", "purchase guide", "purchase status"}:
                listing_reply = None
            elif field_update:
                state.get("listing_checklist", {}).pop("awaiting_acceptance", None)
                listing_reply = None
            else:
                listing_reply = handle_listing_request(state, text)
            product_reply = product_answer(text) if not field_update and not self._explicit(text) else None
            from .guided_cards import handle_guided
            last_attempt = list(state.get("document_attempts", []))
            guided = handle_guided(self, state, text, key, sender)
            retry_answer = mixed_retry(state, text)
            awaiting = state.get("awaiting")
            if guided is not None:
                result = guided
            elif retry_answer is not None:
                updates = self._updates(state, awaiting + ": " + retry_answer)
                if any(state["fields"].get(field) != value for field, value in updates.items()):
                    state["fields"].update(updates)
                    self._invalidate(state)
                result = ("Saved your " + awaiting + ".\n" + field_notes(state, updates, awaiting) + "\n\n"
                          + self._read_documents(state, refresh=True) + "\n\n" + self._question(state))
            elif restrictions_changed and not field_update and not re.search(r"https?://|\?|\b(?:price|pricing|access|invoke|customer)\b", text, re.I):
                result = "Saved your restrictions with their original wording. " + describe_restrictions(state["restrictions"]) + " Approval, publication and checkout are blocked."
            elif listing_reply is not None:
                result = listing_reply
            elif product_reply is not None:
                result = product_reply
            elif self.conversation is not None and not self._explicit(text):
                result = self._converse(state, text, key, sender)
            else:
                result = self._handle(state, text, key, sender)
            if readonly:
                return result
            if not state.get("onboarding_shown") and not state.get('draft') and (state["fields"].get("tool_url") or text.lower() in {"hi", "hello", "start"}) and not getattr(result, "metadata", None):
                if INTRO not in result:
                    result = INTRO + "\n\n" + result
                state["onboarding_shown"] = True
            if (state.get("documentation_error") and state.get("document_attempts", []) != last_attempt
                    and not sender.startswith("machine:") and not getattr(result, "metadata", None)):
                from .guided_cards import attach_recovery
                result = attach_recovery(state, result)
            if self.conversation is not None and text.lower().lstrip("/") != "reset":
                history = state.setdefault("conversation", [])
                history.extend([{"role": "user", "content": text[:1200]},
                                {"role": "assistant", "content": re.sub(r"https://[^\s]+/checkout/[^\s]+", "[private FAHCE checkout link omitted from model history]", result)[:1200]}])
                del history[:-8]
            if message_id:
                saved_reply = result if len(result) <= 16000 else "The earlier delivery completed. Use export json to retrieve the full preserved record; no operation was repeated."
                state.setdefault("deliveries", {})[message_id] = {"request_hash": request_hash, "reply": saved_reply, "metadata": getattr(result, "metadata", None)}
            if message_timestamp:
                state["last_message_timestamp"] = message_timestamp
            self.store.save(key, state)
            return result

    def _guided_response(self, state, text, key, sender, message_id, timestamp):
        from .guided_cards import handle_guided
        from .readiness import ReadinessText
        request_hash = hashlib.sha256(text.encode()).hexdigest()
        previous = state.get('deliveries', {}).get(message_id) if message_id else None
        if previous:
            if previous['request_hash'] != request_hash:
                return "This message ID was already used for different text. No operation was repeated."
            reply = previous.get('reply') or "The earlier delivery is uncertain. No automatic action was repeated; use status."
            return ReadinessText(reply, previous['metadata']) if previous.get('metadata') else reply
        if timestamp and state.get('last_message_timestamp') and timestamp < state['last_message_timestamp']:
            return "This card message is older than a newer instruction. No changes made; request a fresh card."
        before = json.dumps(state, ensure_ascii=False, sort_keys=True)
        self._request_context.restriction_input = (text, message_id, timestamp)
        self._request_context.prior_restrictions = json.loads(json.dumps(state.get("restrictions", empty_restrictions())))
        reply = handle_guided(self, state, text, key, sender)
        if before != json.dumps(state, ensure_ascii=False, sort_keys=True):
            if message_id:
                deliveries = state.setdefault('deliveries', {})
                deliveries[message_id] = {'request_hash': request_hash, 'reply': str(reply), 'metadata': getattr(reply, 'metadata', None)}
                while len(deliveries) > 32:
                    del deliveries[next(iter(deliveries))]
            if timestamp:
                state['last_message_timestamp'] = timestamp
            self.store.save(key, state)
        return reply

    def render_response(self, sender, session, payload, kind):
        from .export_delivery import REPLY_BYTES
        from .readiness import ReadinessText
        if len(payload.encode("utf-8")) <= REPLY_BYTES:
            return payload
        key = self.store.key(sender, session)
        state = self.store.load(key)
        kind = kind if kind in {"export", "export json", "export readable", "export buyer", "export representation", "export listing", "buyer explanation", "export buyer readable"} else "response"
        delivered = deliver_export(self.store, key, str(payload), (state.get("draft") or {}).get("revision", state["revision"]), kind)
        return ReadinessText(delivered, payload.metadata) if isinstance(payload, ReadinessText) else delivered

    @staticmethod
    def _direct_url_input(state, text):
        normalized = re.sub(r"\[([^\]]*)\]\((https?://[^\s]+)\)", r"\1 \2", text)
        normalized = re.sub(r",(?=https?://)", " ", normalized)
        matches = list(re.finditer(r"https?://[^\s<>]+", normalized))
        if not matches:
            return None
        remainder = re.sub(r"https?://[^\s<>]+", "", normalized)
        prefix = re.sub(r"[\s:,.!<>\[\]()]", " ", remainder).strip().lower()
        if prefix and not re.fullmatch(r"(?:(?:here(?:['’]s| is| are)?|these are|this is|my|the|please|read|process|use|api|documentation|docs|links?|at|are|is)\s*)+", prefix):
            return None
        urls = []
        for match in matches:
            url = match.group().rstrip(".,;!")
            while url.endswith(")") and url.count(")") > url.count("("):
                url = url[:-1]
            urls.append(url)
        known = state["fields"].get("docs", [])
        documentation = (state.get("awaiting") == "docs"
                         or bool(re.search(r"\b(?:docs|documentation|read|process)\b", prefix))
                         or all(url in known for url in urls)
                         or all(re.search(r"^https?://docs\.|/(?:docs|documentation|reference|api-reference|guide|guides)(?:[/?.#]|$)|/(?:openapi|swagger)\.(?:json|ya?ml)(?:[?#]|$)", url, re.I) for url in urls))
        if documentation:
            return "docs: " + " ".join(urls)
        if not prefix and len(urls) == 1 and not state["fields"].get("tool_url"):
            return "tool_url: " + urls[0]
        return None

    @staticmethod
    def _intake_literal(state, text):
        if Workflow._explicit(text) or mixed_retry(state, text) is not None:
            return None
        match = re.fullmatch(r"(?:look into this|you can refer this|try this)\s*:?\s*(https?://[^\s]+)", text, re.I)
        if match:
            field = "tool_url" if not state["fields"].get("tool_url") else "docs"
            return field + ": " + match[1]
        awaiting = state.get("awaiting")
        if awaiting == "access" and re.fullmatch(r"(?:users|customers) can use it as MCP .{1,250}", text, re.I):
            if re.search(r"\b(?:pay\w*|billing|purchase|USDC|USD)\b|\$\s*\d", text, re.I):
                return "access: " + text
            return "invocation: " + text
        if awaiting in {"pricing", "payment", "access"} and re.fullmatch(r"undecided|probably stripe|using the url itself", text, re.I):
            return awaiting + ": " + text
        return None

    def _read_documents(self, state, refresh=False):
        urls = state["fields"].get("docs", [])
        if not urls:
            return "No documentation URL is saved. Send docs: <public URL>; no fetch or model call was made."
        cached = not refresh and not state.get("documentation_error") and [document["requested_url"] for document in state["documents"]] == urls
        try:
            documents = state["documents"] if cached else self._fetch_documents(state, urls)
        except DocumentError as error:
            message = f"Documentation unavailable: {error} All supplied URLs are saved and any previous draft is preserved. Use retry or revise docs: <public URL>."
        except Exception:
            message = "Documentation unavailable: the fetch could not complete. The link is saved and any previous draft is preserved, but no successful read is claimed. Use retry or revise docs: <public URL>."
        else:
            state["documents"] = documents
            state.pop("documentation_error", None)
            if (state.get("error") or "").startswith("Documentation unavailable:"):
                state["error"] = None
            total = sum(len(document["text"]) for document in documents)
            action = "Documentation already read" if cached else f"Read {len(documents)} documentation page(s)"
            from .drafting import extract
            assessment = evidence(extract(documents), state["fields"], documents)
            state["documentation_evidence"] = assessment
            return (f"{action}; {total:,} source characters saved. URLs: " + ", ".join(urls) + ". No extraction-model call or payment was made for this read. "
                    "Reading documentation does not verify the API's behavior.\n" + evidence_text(assessment)
                    + ("\n" + discovery_text(state) if assessment["status"] == "insufficient" else ""))
        state["documentation_error"] = message
        state["error"] = message
        return message + "\n" + discovery_text(state)

    def _fetch_documents(self, state, urls):
        documents = []
        outcomes = []
        previous = state.get("documents", [])
        for url in urls:
            try:
                document = asdict(self.fetcher.fetch(url))
            except Exception as error:
                retained = next((record for record in previous if record["requested_url"] == url), None)
                outcomes.append({"url": url, "result": "fetch_failed", "reason": str(error) if isinstance(error, DocumentError) else "fetch_could_not_complete", "revision": state["revision"], "retained_previous": retained is not None})
                if retained is not None:
                    documents.append(retained)
            else:
                outcomes.append({"url": url, "result": "read_success", "source_url": document["source_url"], "revision": state["revision"]})
                documents.append(document)
        state.setdefault("document_attempts", []).extend(outcomes)
        del state["document_attempts"][:-30]
        state["document_fetch_outcomes"] = outcomes
        if not documents and any(outcome["result"] == "fetch_failed" for outcome in outcomes):
            documents = previous
        if previous and previous != documents:
            history = state.setdefault("document_history", [])
            history.append({"documents": previous, "revision": state["revision"]})
            del history[:-10]
        state["documents"] = documents
        if any(outcome["result"] == "fetch_failed" for outcome in outcomes):
            detail = "\n".join(
                outcome["url"] + ": " + ("read successfully; text retained" if outcome["result"] == "read_success" else
                "fetch failed (" + outcome["reason"] + "); " + ("previous text retained, not refreshed" if outcome["retained_previous"] else "no text retained"))
                for outcome in outcomes)
            state["documentation_error"] = detail
            raise DocumentError("Per-URL outcomes:\n" + detail)
        return documents

    @staticmethod
    def _explicit(text):
        if text.strip().lower() == "export incomplete":
            return True
        command = text.lower().lstrip("/")
        if command in {"wallet", "purchase guide", "purchase status"}:
            return True
        commands = {"", "hi", "hello", "start", "help", "status", "demo", "review intake", "review offer", "recovery form", "source suggestions", "suggest docs", "draft", "draft limited", "draft incomplete", "retry", "refresh docs", "preflight", "export buyer", "export representation", "buyer explanation", "export buyer readable",
                    "reextract", "export", "export json", "export readable", "export listing", "check", "reset"}
        return (text.lstrip().startswith("{") or command in commands or command in {"publish", "publish offer"} or command in {"offer approve", "payment options"} or command.startswith(("transaction ", "distribution select "))
                or any(re.match(r"^(?:revise\s+)?(?:" + "|".join(FIELDS | set(ALIASES)) + r")\s*:", line.strip(), re.I)
                       for line in text.splitlines()))

    def _converse(self, state, text, key, sender, source_question=False):
        from .conversation import ConversationError, explain_question, grounded_partial, separate_instruction_fields, retention_safe_reply, validate
        answer, allow_updates = explain_question(text, model_enabled=self.extractor is not None, fahce_configured=self.fahce.configured or self.checkout is not None, machine_adapter=hasattr(self, "machine_scope"))
        if source_question:
            answer, allow_updates = None, False
        if answer and not allow_updates:
            return answer
        try:
            # Explicit revisions have no semantic ambiguity. Handle them directly
            # so a model cannot rewrite a price or spend quota re-interpreting it.
            revision = re.fullmatch(r"(?:actually[, ]+)?(?:please )?(?:change|set|update) (?:the |my )?(price|pricing|customer|audience|access|invocation|job) to (.+?)[.!]?", text, re.I)
            undecided = re.search(r"\bmy (?:pricing|price) and (?:my )?payment(?: method)? (?:are )?(aren['’]t decided(?: yet)?|not decided(?: yet)?|undecided|not set)\b", text, re.I)
            if answer and allow_updates and undecided:
                literal = re.search(r"\bundecided\b", text, re.I)
                value = literal.group() if literal else undecided.group(1)
                plan = {"action": "update", "reply": answer, "updates": {"pricing": value, "payment": value}}
            elif revision and "?" not in text:
                field = {"price": "pricing", "audience": "customer"}.get(revision.group(1).lower(), revision.group(1).lower())
                plan = {"action": "update", "reply": "I understand the revision.", "updates": {field: revision.group(2)}}
            else:
                plan = self.conversation.interpret({**state, "runtime_capabilities": {
                    "machine_adapter": hasattr(self, "machine_scope"),
                    "wallet_checkout_configured": self.checkout is not None,
                    "direct_evaluation_configured": self.fahce.configured,
                    "existing_wallet_checkout": bool(state.get("fahce_checkout")),
                    "automatic_spending": False,
                }}, text)
            plan = separate_instruction_fields(validate(grounded_partial(plan, text), text))
            plan["reply"] = retention_safe_reply(plan["reply"])
            from .conversation import check_deliverable
            check_deliverable(plan, text, state)
            if source_question and (plan["action"] != "reply" or plan["updates"]):
                raise ConversationError("invalid update action")
            # Absence of supplied evidence cannot establish known absence.
            plan["reply"] = re.sub(
                r"KNOWN_ABSENT(?= from (?:this|the) conversation(?: only)?)",
                "NOT_SUPPLIED", plan["reply"], flags=re.I)
            if source_question:
                # Never let a generated quotation masquerade as retrieved source text.
                source_text = "\n".join(doc.get("text", "") for doc in state.get("documents", []))
                for quote in re.findall(r'[“"]([^“”"\n]{12,})[”"]', plan["reply"]):
                    if quote not in source_text:
                        raise ConversationError("ungrounded update")
                # Explicitly labelled single-quoted passages may contain apostrophes
                # (e.g. 10'000); match the final quote rather than a number separator.
                for match in reversed(list(re.finditer(r"(?i)(?:exact (?:passage|quote|quotation)[^\n:]*:\s*)'([^\n]+)'", plan["reply"]))):
                    if match.group(1) not in source_text:
                        plan["reply"] = (plan["reply"][:match.start()] +
                            "Quotation withheld: the proposed passage was not an exact retained-source quotation." +
                            plan["reply"][match.end():])
            state.pop("conversation_error", None)
            if contains_secret(plan["reply"]) or any(contains_secret(value) for value in plan["updates"].values()):
                raise ConversationError("unsafe output")
            from .product_policy import publication_output, publication_request
            if publication_request(text):
                return publication_output(plan["reply"], state, text)
            risk = output_risk(plan["reply"], state, text)
            if risk:
                return "Final-output evidence check: " + risk + " The proposed response was withheld; no facts, approval or offer were changed."
            if plan["action"] == "update":
                if planning_context(state, text) or re.search(r"\b(?:what if|hypothetically|suppose|don't change|do not change)\b", text, re.I):
                    return plan["reply"] + "\n\nNo intake or commercial facts changed. Send mode prelaunch to save explicitly selected proposed requirements separately."
                # Reuse URL, field-length and documentation-count validation atomically.
                updates = self._updates(state, "\n".join(field + ": " + value for field, value in plan["updates"].items()))
                changed = [field for field, value in updates.items() if state["fields"].get(field) != value]
                if changed:
                    self._product_switch(state, updates)
                    state["fields"].update(updates)
                    self._invalidate(state)
                notes = field_notes(state, updates, state.get("awaiting"))
                missing = self.missing(state)
                state["awaiting"] = missing[0] if missing else None
                # Avoid chaining two model calls in a hosted execution (90s hard limit).
                unresolved = plan.get("clarify_fields", [])
                next_step = (("I did not save " + ", ".join(unresolved) + ". " + ("How should the customer invoke the tool: which endpoint or MCP tool, method and request body/placeholders? Payment/access terms alone do not specify the request." if unresolved[0] == "invocation" else "Please restate " + unresolved[0] + " in your own words."))
                             if unresolved else QUESTIONS[missing[0]] if missing else "Intake values saved. Documentation sufficiency still needs review. Say ‘build the draft’ for a reviewable record, which may be incomplete.")
                documentation_note = self._read_documents(state) + "\n\n" if "docs" in updates else ""
                labels = {"tool_url": "tool URL", "docs": "documentation", "customer": "intended customer",
                          "seller_name": "seller name", "job": "desired outcome"}
                # Preserve answers to mixed-intent messages while the executor owns
                # the acknowledgement and the single next intake question.
                explanation = answer or (plan["reply"] if text.rstrip().endswith("?") else "")
                return ((explanation + "\n\n") if explanation else "") + ("Saved your " + ", ".join(labels.get(field, field) for field in changed) + ".\n\n" if changed else "Those details are already saved.\n\n") + (notes + "\n\n" if notes else "") + documentation_note + next_step
            if plan["action"] == "reply":
                return answer or plan["reply"]
            if plan["action"] == "listing checklist":
                return handle_listing_request(state, "listing checklist")
            return self._handle(state, plan["action"], key, sender)
        except (ConversationError, ValueError, DocumentError) as error:
            code = error.code if isinstance(error, ConversationError) else "CHAT_INVALID_INPUT"
            from .model_runtime import TRACE
            events = getattr(TRACE, "events", None)
            if events and code.startswith("CHAT_"):
                events[-1]["answer_outcome"] = code
            state["conversation_error"] = code
            from .product_policy import publication_output, publication_request
            if publication_request(text):
                return publication_output("Generation could not be validated (" + code + ").", state, text)
            if code in {"CHAT_TRUNCATED", "CHAT_INCOMPLETE"}:
                partial = getattr(error, "partial", "")
                state["incomplete_response"] = {"complete": False, "reason": code,
                                                "text": partial if not contains_secret(partial) else "[unsafe partial withheld]"}
                return "The generated response is INCOMPLETE (" + code + "), not a completed document. No interpretation was applied. Use export incomplete for the retained partial response, or request a shorter complete section. No automatic model retry was made."
            if code in {"CHAT_SOURCE_UNSUPPORTED", "CHAT_BUDGET"}:
                explanation = ("The generated instructions did not pass the retained-source check. Request one endpoint's exact headers and steps with source quotations."
                               if code == "CHAT_SOURCE_UNSUPPORTED" else
                               "Inference is blocked by the operator spending guard. The operator must supply current billing bounds, a daily budget and durable accounting, or reconcile uncertain usage.")
                return explanation + " (" + code + ") Your saved offer is unchanged. Use status, export json or draft limited without inference. No automatic model retry was made."
            if code in {"CHAT_AUTH", "CHAT_QUOTA", "CHAT_TIMEOUT", "CHAT_PROVIDER"}:
                explanation = {
                    "CHAT_AUTH": "The agent's language provider rejected its configured credential or permissions. This requires an operator check; a shorter message or wallet login will not fix it.",
                    "CHAT_QUOTA": "The language provider blocked this request for quota, billing or rate limits. For hosted ASI inference, the operator should check the Agentverse account's Stats/quota page. Repeated unchanged requests do not restore exhausted quota; this is separate from wallet approval.",
                    "CHAT_TIMEOUT": "The language provider did not finish in time. No interpretation was applied.",
                    "CHAT_PROVIDER": "The language provider could not return a usable response. No interpretation was applied.",
                }[code]
                return ((answer + "\n\nI couldn't reliably save new details. ") if answer else "") + f"{explanation} ({code}) Your saved offer is unchanged. Use status, help or export json to inspect existing work."
            if answer:
                return answer + "\n\nI couldn't reliably save new details from that message; your existing offer is unchanged.\n\n" + self._question(state)
            return (f"I couldn't reliably interpret that message ({code}), so I kept your offer unchanged. "
                    "Try a shorter request, or use help for direct commands.\n\n" + self._question(state))

    def _capture_restrictions(self, state):
        text, message_id, timestamp = self._request_context.restriction_input
        previous = state.get("restrictions")
        current = capture_restrictions(previous, text, message_id=message_id, timestamp=timestamp)
        if current != previous and current["sources"]:
            state["restrictions"] = current
            self._invalidate(state)

    def _product_switch(self, state, updates):
        old = state["fields"].get("tool_url")
        if not old or "tool_url" not in updates or updates["tool_url"] == old:
            return
        # Preserve complete custody before clearing terms belonging to another product.
        state.setdefault("product_history", []).append({
            "fields": dict(state["fields"]), "restrictions": {**self._request_context.prior_restrictions, "lifecycle": "archived_product"}, "draft": state.get("draft"),
            "documents": state.get("documents", []), "revision": state["revision"],
            "check": state.get("check"), "approved_offer": state.get("approved_offer"),
        })
        state["fields"] = {}
        state["restrictions"] = empty_restrictions()
        self._capture_restrictions(state)
        state["documents"] = []
        state.pop("extraction_cache", None)

    @staticmethod
    def missing(state):
        return [key for key in QUESTIONS if not state["fields"].get(key)]

    def _question(self, state, *, concise=False):
        if planning_context(state):
            state["awaiting"] = None
            return PLAN_HELP
        missing = self.missing(state)
        state["awaiting"] = missing[0] if missing else None
        if missing:
            if self.conversation is not None or concise:
                return QUESTIONS[missing[0]]
            return f"{self.name} — intake {len(QUESTIONS) - len(missing)}/{len(QUESTIONS)}.\n{QUESTIONS[missing[0]]}\nStill missing: {', '.join(missing)}.\nYou may supply all missing field: value lines at once."
        return "Intake values saved. Use draft to review documentation sufficiency; incomplete work remains exportable."

    @staticmethod
    def _invalidate(state):
        state["revision"] += 1
        state["check"] = None
        state.pop("approved_offer", None)
        state["outdated"] = state["draft"] is not None
        state["error"] = None

    def _structured_intake(self, text):
        if not text.lstrip().startswith("{"):
            return None
        try:
            duplicates = []
            def unique_object(pairs):
                value = {}
                for name, item in pairs:
                    if name in value:
                        duplicates.append(name)
                    value[name] = item
                return value
            value = json.loads(text, object_pairs_hook=unique_object)
        except ValueError:
            raise ValueError("Invalid JSON. Send one intake object or a valid card selection.") from None
        if not isinstance(value, dict) or "card_id" in value or "action" in value:
            return None
        if not (set(value) & FIELDS or value.get("schema") == "TOOL_OFFER_INTAKE_V1"):
            raise ValueError("This JSON is not an intake object. Documents and examples are not applied as intake; use public docs URLs.")
        if duplicates or set(value) - FIELDS - {"schema"}:
            raise ValueError("Intake keys must be unique and supported: " + ", ".join(sorted(FIELDS)) + ".")
        if "schema" in value and value["schema"] != "TOOL_OFFER_INTAKE_V1":
            raise ValueError("Intake schema must be TOOL_OFFER_INTAKE_V1.")
        updates = {name: item for name, item in value.items() if name != "schema"}
        if not updates:
            raise ValueError("Supply at least one intake field.")
        return self._validate_updates(updates)

    def _updates(self, state, text):
        structured = self._structured_intake(text)
        if structured is not None:
            return structured
        if text.lower().startswith("revise "):
            text = text[7:].strip()
        updates = {}
        current = None
        for line in text.splitlines():
            match = re.match(r"^([a-zA-Z_ ]+)\s*:\s*(.*)$", line)
            field = match.group(1).strip().lower().replace(" ", "_") if match else None
            field = ALIASES.get(field, field)
            if field in FIELDS:
                current = field
                updates[field] = match.group(2).strip()
            elif current:
                updates[current] += "\n" + line
            elif (
                match
                and re.fullmatch(r"[a-zA-Z_]+", match.group(1).strip())
                and not line.lower().startswith(("https://", "http://"))
            ):
                raise ValueError("Unknown field. Use help for the supported field names.")
        if not updates:
            missing = self.missing(state)
            if not missing:
                raise ValueError("No changes made. To revise the job, use job: <one specific outcome>. Use export json to view the record, or revise field: value to change another field.")
            target = state.get("awaiting") or missing[0]
            updates[target] = text
        return self._validate_updates(updates)

    @staticmethod
    def _validate_updates(updates):
        updates = dict(updates)
        for field, value in updates.items():
            if field == "docs" and isinstance(value, list):
                if not 1 <= len(value) <= 3 or any(not isinstance(url, str) or not url.strip() or len(url) > 2000 for url in value):
                    raise ValueError("docs must contain one to three nonempty public URL strings.")
                updates[field] = list(dict.fromkeys(validate_url(url.strip()) for url in value))
                continue
            if not isinstance(value, str):
                raise ValueError(field + " must be a string (docs also accepts a list of URL strings).")
            if not value.strip() or len(value) > 6000:
                raise ValueError("Each field needs 1–6000 characters.")
            if field == "tool_url":
                updates[field] = validate_url(value.strip())
            elif field == "docs":
                normalized = re.sub(r"\[[^\]]*\]\((https?://[^\s]+)\)", r"\1", value)
                normalized = re.sub(r",(?=\s*https?://)", " ", normalized)
                urls = [url.strip("<>") for url in normalized.split()]
                if not 1 <= len(urls) <= 3:
                    raise ValueError("Supply one to three public documentation URLs.")
                updates[field] = list(dict.fromkeys(validate_url(url) for url in urls))
        return updates

    def _handle(self, state, text, key, sender, *, limited=False):
        command = text.lower().lstrip("/")
        from .product_policy import publication_output, publication_request
        if not self._explicit(text) and publication_request(text):
            return publication_output("No validated generation available.", state, text)
        if command == "export incomplete":
            return json.dumps(state.get("incomplete_response", {"complete": False, "reason": "No incomplete response retained."}), ensure_ascii=False, indent=2)
        if planning_context(state) and (command in {"draft", "draft limited", "retry", "reextract", "offer approve", "check", "preflight"} or command.startswith(("transaction open", "publish"))):
            return "This is pre-launch planning, not commercial evidence. Use export plan for proposed requirements; switch explicitly with mode evidence and supply actual documentation and seller-authorized facts before an offer or approval. Existing drafts and purchase evidence remain unchanged."
        if command in {"buyer explanation", "export buyer readable"}:
            from .offer_representation import buyer_explanation, buyer_readable
            render = buyer_explanation if command == 'buyer explanation' else buyer_readable
            pending = {'pending_fields': state['fields'], 'intake_revision': state['revision']} if command == 'buyer explanation' else {}
            return render(state.get("draft"), state.get("restrictions"), outdated=state.get("outdated", False), documents=state.get('draft_documents', state.get('documents', [])), **pending)
        if command in {"offer approve", "check"} or command.startswith(("transaction open", "publish")):
            if restrictions_blocked(state.get("restrictions")):
                return "Commercial action blocked by saved restrictions. " + describe_restrictions(state["restrictions"]) + " Existing purchase evidence is preserved; use purchase status to retrieve it."
        if command in {"wallet", "purchase guide"}:
            return buyer_guide(state, self.checkout is not None)
        if command == "purchase status":
            if not state.get("fahce_checkout"):
                return "No wallet checkout is linked to this conversation. Nothing was prepared or purchased. Send wallet for guidance."
            if self.checkout is None:
                return "Checkout access is currently unavailable. The existing purchase is preserved; do not pay again."
            return self._wallet_check(state, key)
        starter = STARTER_PROMPTS.get(" ".join(text.casefold().split()))
        if starter and self.checkout is not None:
            starter = starter.replace("FAHCE is separate and is not executed through the machine adapter; native checkout availability must be checked separately", "A separate human-approved FAHCE checkout is available; this explanation initiates no evaluation or payment")
        if starter:
            return (INTRO + "\n\n" if not state["fields"] and command.startswith(("help me", "i have an mcp")) else "") + starter + ("\n\n" + self._question(state) if command.startswith(("help me", "i have an mcp")) else "")
        if command.startswith("transaction ") or command in {"offer approve", "payment options"}:
            try:
                return self._commerce_command(state, text, sender)
            except (TransitionError, ValueError, KeyError) as error:
                return "Commercial request refused: " + str(error) + " Existing offer and evidence preserved."
        if command == "reset":
            if state.get("fahce_checkout"):
                return "A FAHCE checkout is linked to this conversation. Use check to retrieve it; start a new conversation for an independent test. Existing checkout preserved."
            if state.get("pending_payment"):
                return "A payment attempt needs server-side reconciliation before this conversation can be reset. Export the preserved draft."
            if any((self.commerce.read(transaction_id) or {}).get("stage") not in (Stage.REJECTED.value, Stage.CANCELLED.value, Stage.UNSUPPORTED.value, Stage.EXPIRED.value, Stage.FAILED.value) for transaction_id in state.get("commercial_transactions", [])):
                return "An unresolved commercial transaction is linked to this session; use transaction status before reset. Draft preserved."
            state.clear()
            state.update({"fields": {}, "documents": [], "draft": None, "check": None, "revision": 0, "outdated": False, "awaiting": None, "error": None})
            return self._question(state)
        if ("?" in text or command.startswith(("help me ", "how do ", "how can ", "what can ", "i want to ", "can you ")) ) and not any(
                line.strip().lower().startswith(tuple(field + ":" for field in FIELDS)) for line in text.splitlines()) and not text.lower().startswith(("https://", "http://")):
            return "I prepare source-attributed commercial offers from public documentation and seller terms. Start with a public tool URL; you can revise and export your work. Optional FAHCE evaluation requires a configured authorized transport.\n\n" + self._question(state)
        if command in ("", "hi", "hello", "start", "help"):
            return INTRO + "\n\n" + (HELP + "\n\n" if command == "help" else "") + self._question(state)
        if command == "demo":
            return ("Stranger Builds text walkthrough (no purchase): supply your own seven fields, or use public Open-Meteo docs: "
                    "tool_url: https://api.open-meteo.com/v1/forecast; docs: https://open-meteo.com/en/docs; "
                    "customer: forecast API integrators; pricing: undecided; payment: undecided; access: public docs; "
                    "invocation: GET /v1/forecast?latitude=<latitude>&longitude=<longitude>&hourly=temperature_2m. "
                    "Then draft, inspect source/unknowns, offer approve, payment options, transaction open with explicit exact terms, "
                    "and transaction summary <id>. Only test_only TEST local is nonspending; all real rails return UNSUPPORTED. "
                    "Buyer approval requires a separate addressed agent; no seller message can approve for a buyer. "
                    "FAHCE is optional; send check to prepare wallet approval when configured. Your existing conversations and drafts are not reset.")
        if command == "status":
            progress = f"Intake {len(QUESTIONS) - len(self.missing(state))}/{len(QUESTIONS)}; draft: {'previous version — refresh needed' if state['outdated'] else 'saved for review' if state['draft'] else 'not created'}."
            supplied = state["fields"].get("docs", [])
            read_count = sum(document["requested_url"] in supplied for document in state["documents"])
            progress += f"\nDocumentation: {read_count}/{len(supplied)} supplied page(s) read."
            if state.get("draft"):
                progress += "\n" + evidence_text(state["draft"].get("documentation_evidence", {}))
            if self.conversation is not None and state["fields"]:
                labels = {"tool_url": "Tool URL", "docs": "Documentation", "customer": "Intended customer",
                          "seller_name": "Seller name", "job": "Desired outcome"}
                progress += "\n" + "\n".join(labels.get(field, field.capitalize()) + ": " + (", ".join(value) if isinstance(value, list) else str(value))[:500]
                                             for field, value in state["fields"].items())
            if state.get("commercial_transactions"):
                progress += "\nCommercial transaction IDs: " + ", ".join(state["commercial_transactions"])
            if state.get("approved_offer"):
                progress += "\nSeller-approved offer hash: " + state["approved_offer"]["hash"] + "; approval is sender-bound, not independent identity verification."
            coverage = (state.get("draft") or {}).get("model_extraction")
            if coverage:
                progress += f"\nLast draft model coverage: {'PARTIAL' if coverage['partial'] else 'full supplied text'}; {coverage['supplied_chars']} source characters. Not an exhaustive review."
            if state.get("extraction_cache"):
                progress += "\nOne successful extraction saved; reused only when documents, job, invocation, model and policy match. Reextract intentionally spends quota."
            progress += "\n" + describe_restrictions(state.get("restrictions"))
            return progress + ("\n" + state["error"] if state["error"] else "") + "\n" + self._check_status(state) + ("\n" + self._question(state) if self.missing(state) else "\nUse export json, revise field: value, or check.")
        if command.startswith("distribution select "):
            destinations = [item.strip() for item in text[len("distribution select "):].split(",")]
            if not 1 <= len(destinations) <= 5 or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", item) for item in destinations):
                return "Select one to five destination labels, separated by commas (80 characters each). No publication occurs."
            state["distribution"] = {"selected_destinations": list(dict.fromkeys(destinations)), "status": "not_published", "destination_references": []}
            return "Distribution destinations saved for preparation only. No external publication occurred. Use export listing."
        if command == "export listing":
            if not state["draft"]:
                return ("No draft yet. export listing requires a saved offer draft because it exports a listing-formatted offer. None was created. "
                        "In prelaunch, listing checklist, listing checklist json, plan status and export plan still work without a draft. "
                        "A checklist is preparation guidance, not a commercial listing. To export an offer, explicitly use mode evidence, supply actual intake and documentation, and build a draft.")
            draft = state["draft"]
            return json.dumps({
                "schema": "TOOL_OFFER_LISTING_PACKAGE_V1",
                "offer_revision": draft["revision"],
                "offer_sha256": fingerprint(draft),
                "outdated": state["outdated"],
                "draft_version": draft.get("draft_version"),
                "documentation_evidence": draft.get("documentation_evidence", {"status": "legacy_not_assessed"}),
                "seller_profile": draft["seller"], "restrictions": state.get("restrictions", empty_restrictions()),
                "short_description": draft["offer"].get("job"),
                "capability_statement": draft["offer"].get("capabilities", []),
                "commercial_terms": {field: draft["offer"].get(field) for field in
                    ("pricing", "payment_instructions", "access_instructions", "invocation_instructions")},
                "evidence_boundaries": draft.get("boundaries", []),
                "source_urls": draft["seller"].get("source_urls", []),
                "distribution": state.get("distribution", {"selected_destinations": [], "status": "not_published", "destination_references": []}),
                "lineage": state.get("offer_lineage", []),
                "independent_evaluation": self.export_record(state)["fahce"],
                "listing_checklist": build_checklist(state),
            }, ensure_ascii=False, indent=2)
        if command in ("export", "export json", "export readable", "export buyer", "export representation"):
            if not state["draft"]:
                if command in {"export", "export json"} and state["fields"]:
                    return json.dumps(self.export_record(state), ensure_ascii=False, indent=2)
                return "No draft yet. " + self._question(state)
            if command == "export readable":
                return self._readable(state)
            if command == "export buyer":
                from .offer_representation import buyer_offer
                return json.dumps(buyer_offer(state["draft"], outdated=state["outdated"], restrictions=state.get("restrictions"), documents=state.get('draft_documents', state.get('documents', []))), ensure_ascii=False, indent=2)
            if command == "export representation":
                from .offer_representation import representation
                return json.dumps(representation(state["draft"], state["documents"], restrictions=state.get("restrictions"), outdated=state["outdated"]), ensure_ascii=False, indent=2)
            return json.dumps(self.export_record(state), ensure_ascii=False, indent=2)
        if command == "preflight":
            if not state.get("draft") or state.get("outdated") or self.missing(state):
                return "A current complete draft is required for input preflight. Nothing was prepared or purchased."
            from .fahce_checkout import free_preflight
            try:
                checked = free_preflight(state["draft"], state["documents"])
            except Exception:
                return "FAHCE's free input check is unavailable. No checkout, signature, engine execution or payment was requested. Existing draft preserved."
            screen = checked["screen"]
            candidates, evidence = screen["candidate_limitations"], screen["limitations"]
            lines = ["Free input preflight — no checkout created.", "Request SHA-256: " + checked["request_sha256"],
                     f"Known candidate-format blockers: {len(candidates)}; evidence blockers: {len(evidence)}.",
                     "Engine execution, truth, semantic support and billability are not established. No payment authority granted."]
            raw = checked["candidate_output"].encode("utf-16-le")
            for item in candidates[:5]:
                if not isinstance(item, dict):
                    continue
                span = item.get("source_span", {})
                start, end = span.get("start"), span.get("end")
                if (span.get("unit") == "UTF16_CODE_UNIT" and type(start) is int and type(end) is int
                        and 0 <= start <= end <= len(raw) // 2):
                    fragment = raw[start * 2:end * 2].decode("utf-16-le", errors="replace")
                    lines.append("Rejected input fragment: " + fragment[:300])
            lines.append("Preserve these claims and their evidence; an input-format repair must retain their meaning. Zero blockers would still not prove engine interpretation.")
            return "\n".join(lines)
        if command == "check":
            if self.checkout is not None:
                return self._wallet_check(state, key)
            if not self.fahce.configured:
                return PENDING
            if not state["draft"] or state["outdated"]:
                return "A current draft is required before any FAHCE submission. Use draft or retry."
            if state.get("pending_payment"):
                return "FAHCE check requires server-side reconciliation of the previous attempt; no new payment attempted. Draft preserved and exportable."
            if state["check"] and state["check"].get("draft_hash") == fingerprint(state["draft"]):
                return self._check_status(state)
            attempt = {"idempotency_key": str(uuid4()), "draft_hash": fingerprint(state["draft"])}
            state["pending_payment"] = attempt
            # Persist before crossing the paid boundary; crashes cannot silently retry payment.
            self.store.save(key, state)
            try:
                state["check"] = self.fahce.check(state["draft"], state["documents"], idempotency_key=attempt["idempotency_key"])
                state["pending_payment"] = None
                state["error"] = None
                return self._check_status(state)
            except Exception:
                state["error"] = "FAHCE check did not complete safely. Draft preserved and exportable; server-side reconciliation is required before any new payment."
                return state["error"]
        if command in ("draft", "draft limited", "draft incomplete", "retry", "refresh docs", "reextract"):
            if self.missing(state):
                if state["fields"].get("docs") and (command == "refresh docs" or command == "retry" and state.get("documentation_error")):
                    return self._read_documents(state, refresh=True) + "\n\n" + self._question(state)
                return self._question(state)
            if command in ("retry", "draft") and (state.get("error") or "").startswith("Document extraction failed ("):
                return state["error"]
            if command == "reextract" and self.extractor is None:
                return "Model extraction is disabled. No model call made; use refresh docs for deterministic parsing."
            cache_key = self._extraction_key(state, state["documents"])
            cached = cache_key is not None and state.get("extraction_cache", {}).get("key") == cache_key
            if command in ("draft", "retry") and state["draft"] and not state["outdated"]:
                note = "\nSuccessful extraction is cached, including missing categories. Use reextract only to intentionally spend quota on a fresh extraction." if cached else ""
                if state["draft"].get("documentation_evidence", {}).get("status") == "insufficient":
                    return self._draft_delivery(state) + note + "\n\n" + discovery_text(state)
                return offer_checklist(state, self._draft_delivery(state) + note)
            self._invalidate(state)
            if command == "reextract":
                state.pop("extraction_cache", None)
            return self._build(state, refresh=command == "refresh docs", limited=command in {"draft limited", "draft incomplete"}, incomplete=command == "draft incomplete")
        try:
            updates = self._updates(state, text)
        except (ValueError, DocumentError) as error:
            return str(error) + " Existing draft preserved."
        if text.lower().startswith('revise ') and len(updates) == 1:
            from .guided_cards import correction
            field, value = next(iter(updates.items()))
            return correction(self, state, field, value)
        if any(state["fields"].get(key) != value for key, value in updates.items()):
            self._product_switch(state, updates)
            state["fields"].update(updates)
            self._invalidate(state)
        elif state["draft"] and not state["outdated"] and "docs" not in updates:
            return ', '.join(updates) + ' unchanged; already saved. Intake revision ' + str(state['revision']) + '; saved draft revision ' + str(state['draft']['revision']) + '. Use buyer explanation for the concise view or export buyer readable for full detail. No approval, checkout or publication.'
        notes = field_notes(state, updates, state.get("awaiting"))
        documentation_note = self._read_documents(state) if "docs" in updates else ""
        documentation_note = (notes + "\n\n" if notes else "") + documentation_note
        if "docs" in updates and state.get("draft") and not state["outdated"] and not state.get("documentation_error"):
            if state["documents"] == state.get("draft_documents", state["documents"]):
                return documentation_note + "\n\n" + self._draft_delivery(state)
            self._invalidate(state)
        if self.missing(state):
            return (documentation_note + "\n\n" if documentation_note else "") + self._question(state)
        state["awaiting"] = None
        if state.get("documentation_error"):
            return documentation_note + "\n\nIntake values saved; documentation is still unavailable. Use retry to fetch the same URLs, revise docs: <public URL> to replace them, or draft incomplete for a no-fetch, no-model record."
        return (notes + "\n\n" if notes else "") + self._build(state, limited=limited)

    def _commerce_command(self, state, text, sender):
        if text.lower().startswith(("offer approve", "transaction open")) and restrictions_blocked(state.get("restrictions")):
            raise TransitionError("Saved restrictions prohibit commercial approval or checkout.")
        parts = shlex.split(text)
        command = [word.lower() for word in parts[:2]]
        if command in (["transaction", "status"], ["transaction", "summary"]) and len(parts) == 2:
            visible = [identifier for identifier in state.get("commercial_transactions", [])
                       if sender in ((self.commerce.read(identifier) or {}).get("seller", {}).get("id"),
                                     (self.commerce.read(identifier) or {}).get("buyer", {}).get("id"))]
            if not visible:
                return "No seller-side transaction is linked to this conversation. For an existing buyer FAHCE checkout, use purchase status. No transaction, checkout or payment was created."
            if len(visible) != 1:
                return "Choose a linked transaction: " + ", ".join(visible) + ". Use transaction " + command[1] + " <id>. Nothing changed."
            parts.append(visible[0])
        if command == ["payment", "options"]:
            return json.dumps({"protocol": "AgentPaymentProtocol 0.1.0", "methods": RAILS,
                               "operational": ["test_only"] if self.local_test else [],
                               "x402": "FAHCE's USDC x402 REST contract is not interchangeable with Fetch payment messages; no rail or network substitution."})
        if command == ["offer", "approve"]:
            if not state.get("draft") or state.get("outdated"):
                raise TransitionError("Build a current draft before seller approval.")
            offer_hash = digest(state["draft"])
            if state.get("approved_offer", {}).get("hash") == offer_hash and state["approved_offer"].get("by") == sender:
                return "Seller offer approved already for this exact draft; no duplicate approval recorded."
            state["approved_offer"] = {"hash": offer_hash, "by": sender, "version": state["draft"]["revision"],
                                       "approved_at": datetime.now(timezone.utc).isoformat(),
                                       "idempotency_key": digest([sender, offer_hash, "seller-approval"]),
                                       "provenance": "Agent Chat Protocol sender; human ownership not independently authenticated"}
            return "Seller offer approved for this exact draft hash. This does not publish or verify seller claims."
        if command == ["transaction", "open"]:
            if not state.get("draft") or state.get("outdated") or not state.get("approved_offer") or state["approved_offer"]["hash"] != digest(state["draft"]) or state["approved_offer"]["by"] != sender:
                raise TransitionError("Current seller-approved draft required; use offer approve.")
            options = dict(word.split("=", 1) for word in parts[2:] if "=" in word)
            required = {"buyer", "method", "currency", "amount", "network", "recipient", "deadline"}
            if required - options.keys() or any("=" not in word for word in parts[2:]):
                raise TransitionError("Use transaction open buyer=<agent address> method=<rail> currency=<asset> amount=<exact decimal> network=<network> recipient=<recipient> deadline=<ISO timestamp>.")
            if not options["buyer"].startswith("agent1") or len(options["buyer"]) > 100:
                raise TransitionError("Buyer must be an explicit agent address, not a seller-supplied name.")
            if self.demo_buyer_address and options["buyer"] != self.demo_buyer_address:
                raise TransitionError("Hosted nonspending demo only accepts the configured buyer agent address.")
            if self.demo_recipient and options["method"] == "test_only" and options["recipient"] != self.demo_recipient:
                raise TransitionError("Hosted nonspending demo recipient must be the existing seller agent address.")
            terms = PaymentTerms(options["method"], options["currency"], options["amount"], options["network"], options["recipient"],
                                 RAILS.get(options["method"], (None, "not configured", "not configured"))[1],
                                 RAILS.get(options["method"], (None, None, "unknown"))[2],
                                 "Buyer approval of exact terms required; no wallet authority inferred", options["deadline"])
            decision = select_rail(terms, local_test=self.local_test)
            checked = state.get("check")
            if state.get("pending_payment"):
                fahce_status, fahce_reference = "PENDING_RECONCILIATION", None
            elif checked and checked.get("status") == "returned" and checked.get("draft_hash") == fingerprint(state["draft"]):
                fahce_status, fahce_reference = "RETURNED_WITH_EVIDENCE", checked.get("receipt_reference")
            elif self.fahce.configured:
                fahce_status, fahce_reference = "INCOMPLETE", None
            else:
                fahce_status, fahce_reference = "NOT_CONFIGURED", None
            record = self.commerce.create(state["draft"], state["documents"],
                                          {"id": sender, "provenance": "Agent Chat Protocol sender; seller label supplied, not authenticated", "label": state["draft"]["seller"]["name"]},
                                          {"id": options["buyer"], "provenance": "Seller-specified agent address; approval not yet received"},
                                          state["draft"]["offer"]["job"], terms,
                                          fahce_status=fahce_status, fahce_reference=fahce_reference)
            for stage in (Stage.EVIDENCE_REVIEWED, Stage.SELLER_OFFER_APPROVED, Stage.BUYER_APPROVAL_REQUIRED):
                evidence = ([record["offer_hash"], state["approved_offer"].get("approved_at"), state["approved_offer"].get("idempotency_key")]
                            if stage == Stage.SELLER_OFFER_APPROVED else [record["source_hash"]])
                self.commerce.transition(record["id"], stage, sender, stage.value + ":" + record["id"], evidence)
            if decision["status"] == Stage.UNSUPPORTED.value:
                self.commerce.transition(record["id"], Stage.UNSUPPORTED, sender, "unsupported:" + record["id"], [decision["required"]])
            state.setdefault("commercial_transactions", []).append(record["id"])
            return json.dumps({"transaction_id": record["id"], "rail_decision": decision,
                               "next": "UNSUPPORTED: no buyer approval or payment request permitted. See rail_decision.required."
                               if decision["status"] == Stage.UNSUPPORTED.value else "Buyer must inspect transaction status and approve exact terms; no funds requested."})
        if command == ["transaction", "status"] and len(parts) == 3:
            record = self.commerce.read(parts[2])
            if not record or sender not in (record["seller"]["id"], record["buyer"]["id"]):
                raise TransitionError("Unknown transaction or unauthorized participant.")
            return json.dumps({"record": record, "receipt": receipt(record), "local_verification": verify_receipt(record, receipt(record))}, ensure_ascii=False)
        if command == ["transaction", "summary"] and len(parts) == 3:
            record = self.commerce.read(parts[2])
            if not record or sender not in (record["seller"]["id"], record["buyer"]["id"]):
                raise TransitionError("Unknown transaction or unauthorized participant.")
            terms = record["payment_terms"]
            integrity = verify_receipt(record, receipt(record))
            permitted = record["events"][-1]["next_permitted"]
            return (f"Transaction {record['id']} — {record['stage']}; permitted next stages: {', '.join(permitted) if permitted else 'none'}.\n"
                    f"Exact rail: {terms['method']} {terms['currency']} {terms['amount']} on {terms['network']} to {terms['recipient']}; deadline {terms['deadline']}.\n"
                    f"Authorization: {record['authorization']}; payment: {record['payment']}; execution: {record['execution']}; "
                    f"delivery: {record['delivery']}; settlement: {record['settlement']}; FAHCE: {record['fahce']}.\n"
                    f"Local record hashes valid: {integrity['local_integrity']}; independently verified: {integrity['independent_verification']}. "
                    "Use transaction status <id> for the full evidence-bound, unsigned test receipt. No seller claim is independently proven.")
        if command == ["transaction", "approve"] and len(parts) == 9:
            record = self.commerce.read(parts[2])
            if not record or record["buyer"]["id"] != sender:
                raise TransitionError("Only the addressed buyer agent may approve.")
            terms = record["payment_terms"]
            if parts[3:] != [terms[name] for name in ("method", "currency", "amount", "network", "recipient", "deadline")]:
                raise TransitionError("Buyer approval must repeat the exact rail, asset, amount, network, recipient and deadline.")
            if terms["method"] != "test_only" or not self.local_test:
                raise TransitionError("Real payment authorization is not configured.")
            self.commerce.transition(record["id"], Stage.BUYER_APPROVED, sender, "buyer-approval:" + record["id"], [digest(terms)])
            return "Exact test-only terms approved; no wallet or payment authority granted. Seller may send the protocol request."
        if command == ["transaction", "send"] and len(parts) == 3:
            record = self.commerce.read(parts[2])
            if not self.local_test or not record or record["seller"]["id"] != sender or record["payment_terms"]["method"] != "test_only":
                raise TransitionError("Test-only seller authorization required; no request sent.")
            if record["stage"] != Stage.BUYER_APPROVED.value:
                raise TransitionError("Buyer must approve exact terms before a payment request.")
            self.commerce.bind_buyer(record["buyer"]["id"], record["id"])
            self.commerce.transition(record["id"], Stage.PAYMENT_REQUESTED, sender, "seller-request:" + record["id"],
                                     ["Payment protocol request intent sha256:" + request_intent_digest(record)])
            return "Test-only payment request queued for " + record["id"] + ". No money or settlement claimed."
        raise TransitionError("Unknown commercial command; use payment options, transaction status [id], or transaction summary [id].")

    def _extraction_key(self, state, documents):
        if not isinstance(self.extractor, OpenAIQuoteExtractor):
            return None
        return self.extractor.cache_key(documents, job=state["fields"].get("job"), invocation=state["fields"].get("invocation"))

    def _build(self, state, refresh=False, limited=False, incomplete=False):
        try:
            documents = state["documents"]
            if incomplete:
                documents = [doc for doc in documents if doc["requested_url"] in state["fields"]["docs"]]
            elif refresh or state.get("documentation_error") or [doc["requested_url"] for doc in documents] != state["fields"]["docs"]:
                documents = self._fetch_documents(state, state["fields"]["docs"])
            background_only = bool(documents) and all(background_article(doc) for doc in documents)
            cache_key = None if limited or background_only else self._extraction_key(state, documents)
            cache = state.get("extraction_cache", {})
            model_facts = model_coverage = None
            if cache_key is not None:
                if cache.get("key") == cache_key:
                    model_facts, model_coverage = cache["facts"], cache["coverage"]
                else:
                    model_facts = self.extractor.extract(documents, job=state["fields"].get("job"), invocation=state["fields"].get("invocation"))
                    model_coverage = self.extractor.coverage(documents, job=state["fields"].get("job"), invocation=state["fields"].get("invocation"))
                cache = {"key": cache_key, "facts": model_facts, "coverage": model_coverage}
            draft = build_draft(state["fields"], documents, state["revision"], None if limited or background_only else self.extractor,
                                model_facts=model_facts, model_coverage=model_coverage)
        except ExtractionError as error:
            state["error"] = (f"Document extraction failed ({error.code}). Exact source/excerpt quotation verification failed or the model was unavailable; "
                              "intake and any previous draft are preserved. No new extraction or FAHCE result is claimed. "
                              "Use draft limited for explicitly limited no-model extraction, or export readable to view the previous draft. "
                              "Only reextract deliberately retries the model and may consume quota. Report this code before repeating it.")
            return state["error"]
        except DocumentError as error:
            state["error"] = f"Documentation unavailable: {error} Intake and any previous draft are preserved. Use retry, revise docs: <public URL>, draft incomplete (no fetch or model), or export json."
            return state["error"]
        except Exception:
            state["error"] = "Documentation or model processing failed. Intake and any previous draft are preserved. Use retry, revise docs: <public URL>, or export json for the previous version."
            return state["error"]
        if cache_key is not None:
            # One successful entry only, inside this sender/session's existing state.
            state["extraction_cache"] = cache
        if "draft_count" not in state and state.get("draft"):
            state["draft_version_scope"] = "generated_since_version_tracking_began_after_legacy_draft"
        state["draft_count"] = state.get("draft_count", 0) + 1
        draft["draft_version"] = state["draft_count"]
        draft["draft_version_scope"] = state.get("draft_version_scope", "generated_in_this_conversation")
        draft["restrictions"] = json.loads(json.dumps(state.get("restrictions", empty_restrictions())))
        draft["commercial_terms_provenance"] = {
            "seller_terms": "seller_supplied_not_independently_authorized",
            "documented_third_party_terms": "source_claims_not_seller_permission",
            "authorization_status": draft["restrictions"]["commercial_authorization"],
        }
        previous = state.get("draft")
        if previous and fingerprint(previous) != fingerprint(draft):
            lineage = state.setdefault("offer_lineage", [])
            lineage.append({"revision": previous["revision"], "sha256": fingerprint(previous),
                            "successor_revision": draft["revision"], "successor_sha256": fingerprint(draft),
                            "draft": previous, "source_documents": state.get("draft_documents", []),
                            "source_custody": "retained" if state.get("draft_documents") else "not_available_for_legacy_draft"})
            del lineage[:-50]
        if not incomplete:
            state.pop("documentation_error", None)
        state.update(draft_documents=documents, draft=draft, outdated=False, error=None)
        if not incomplete:
            state["documents"] = documents
        if draft.get("documentation_evidence", {}).get("status") == "insufficient":
            return self._draft_delivery(state) + "\n\n" + discovery_text(state) + "\nUse review offer, review intake, revise field: value, export json, or draft limited to continue incomplete work."
        next_steps = "Use review offer, review intake, revise field: value (or job: one specific outcome), or export json."
        if state.get("restrictions", {}).get("demonstration_only"):
            next_steps += " This fictional exercise remains non-commercial; Finish review does not lift its restrictions."
        else:
            next_steps += " Optional: wallet or purchase guide explains setup; preflight screens input for free. Only explicit check requests eligible checkout preparation; payment needs separate buyer authorization."
        return offer_checklist(state, self._draft_delivery(state) + "\n\n" + next_steps)

    def _wallet_check(self, state, key):
        if not state.get("fahce_checkout") and restrictions_blocked(state.get("restrictions")):
            return "Checkout blocked by saved restrictions. " + describe_restrictions(state["restrictions"])
        if not state["draft"] or state["outdated"]:
            return "A current draft is required. Use draft or retry before preparing FAHCE payment."
        draft_hash = fingerprint(state["draft"])
        checkout = state.get("fahce_checkout")
        if checkout and checkout.get("draft_hash") != draft_hash:
            return "The draft changed after checkout preparation. The old checkout does not cover this revision. Complete or reconcile the earlier checkout before preparing another purchase."
        if state.get("pending_payment"):
            return "An earlier payment attempt requires reconciliation. No new checkout prepared."
        try:
            if checkout is None:
                checkout_key = fingerprint([key, draft_hash, "fahce-wallet-checkout-v1"])
                checkout = self.checkout.prepare(state["draft"], state["documents"], checkout_key)
                state["fahce_checkout"] = checkout
                self.store.save(key, state)
            status = self.checkout.status(checkout)
            if status["phase"] == "response_received":
                body = status.get("result")
                if not isinstance(body, dict) or body.get("schema") != "FAHCE_MACHINE_RESPONSE_V1" or body.get("operation") != "diagnose":
                    raise ValueError("Unexpected result")
                state["check"] = {
                    "status": "returned", "draft_hash": draft_hash,
                    "request_hash": status.get("requestSha256", checkout["requestSha256"]),
                    "source_request_hash": checkout["requestSha256"],
                    "reviewed_representation": status.get("representationRevision"),
                    "receipt_reference": "https://fahce.kinganlogic.com/api/v1/receipts/" + body["request_id"],
                    "result": body, "receipt_proof": status.get("receiptProof"),
                    "settlement_status": "gateway_reported_success" if status.get("gatewayReportsSuccess") else "not_confirmed",
                    "settlement_reference": status.get("transaction"),
                    "binding_scope": "Checkout retained exact submitted request and its HTTP response; caller-to-engine canonical input mapping is not independently verified.",
                    "scope": SCOPE,
                }
                return self._check_status(state)
            if status["phase"] == "input_review":
                return ("An input-format repair is ready for your review in the existing checkout. "
                        "Compare the original and revised offer, then choose Use revised input. "
                        "That does not sign or pay; any purchase requires a separate wallet approval. "
                        "Source evidence and previous attempts are preserved.\n"
                        "[Review input repair in existing checkout](" + checkout["url"] + ")")
            if status["phase"] == "input_blocked":
                preflight = status.get("preflight") or {}
                if preflight.get("status") == "UNAVAILABLE":
                    explanation = "The free input check is unavailable; this does not establish that your offer is invalid. "
                else:
                    counts = [preflight.get("candidateBlockers"), preflight.get("evidenceBlockers")]
                    explanation = (f"The submitted representation has {counts[0]} offer-format blocker(s) and {counts[1]} source-evidence blocker(s). "
                                   if all(type(count) is int and count >= 0 for count in counts) else "")
                    explanation += "Refreshing alone does not rewrite the input. Any input repair must be shown to you and explicitly accepted before a separate wallet approval. "
                return ("FAHCE's free input check cannot clear this draft for payment. No new wallet signature or payment was requested. "
                        + explanation +
                        "The complete draft and source documents are preserved; this is not a completed determination. "
                        "Use the existing checkout to refresh its status.\n[Open existing FAHCE checkout](" + checkout["url"] + ")")
            if status["phase"] in ("requesting_challenge", "unresolved", "submitting", "validating_authorization", "awaiting_wallet"):
                return "FAHCE checkout: " + status["phase"] + ". Do not approve another payment. Use the original checkout and send check again to retrieve status.\n[Open existing FAHCE checkout](" + checkout["url"] + ")"
            if status["phase"] not in ("ready", "challenge_ready"):
                return ("FAHCE checkout state is not recognized. Do not approve another payment. "
                        "The existing checkout and evidence are preserved.\n[Open existing FAHCE checkout](" + checkout["url"] + ")")
            preflight = status.get("preflight")
            if (not isinstance(preflight, dict) or preflight.get("status") != "NO_KNOWN_BLOCKER"
                    or preflight.get("requestSha256") != status.get("requestSha256")
                    or any(type(preflight.get(field)) is not int or preflight[field] != 0
                           for field in ("candidateBlockers", "evidenceBlockers"))):
                return ("FAHCE's free input check has not cleared this exact request. Do not approve another payment. "
                        "Open the existing checkout to refresh the free input check; no input is rewritten and no payment is made by refreshing.\n"
                        "[Open existing FAHCE checkout](" + checkout["url"] + ")")
            return (("FAHCE wallet checkout uses your explicitly reviewed input representation. " if status.get("representationRevision")
                     else "FAHCE wallet checkout prepared for this exact draft. ") + "Price: 0.15 USDC on Base. "
                    "Open the private link, review the offer and policies, choose Connect wallet — no payment, then separately approve with your own compatible wallet only if you want to buy. "
                    "Other buyers use their own wallets; the agent does not hold wallet keys.\n"
                    + "[Open FAHCE wallet checkout](" + checkout["url"] + ")" + "\nRequest SHA-256: " + status.get("requestSha256", checkout["requestSha256"])
                    + "\nAfter approval, send check again (or purchase status) in THIS conversation. Send wallet for setup guidance. A completed negative determination may be billable. "
                    "This link contains a private checkout capability; do not publish it.")
        except Exception:
            return "FAHCE checkout could not be prepared or refreshed. Existing payment state is preserved. Do not authorize another payment; retry check to read the same checkout."

    def _check_status(self, state):
        if restrictions_blocked(state.get("restrictions")) and not state.get("fahce_checkout"):
            return "Commercial actions and new checkout preparation are blocked by saved restrictions. No purchase was prepared."
        if state.get("pending_payment"):
            return "FAHCE payment attempt requires server-side reconciliation; no new payment will be attempted."
        check = state.get("check")
        if check and state["draft"] and not state["outdated"] and check.get("draft_hash") == fingerprint(state["draft"]):
            if check.get("binding_scope"):
                body = check["result"]
                counts = {}
                for claim in body["diagnosis"].get("claims", []):
                    label = claim.get("support", "UNKNOWN")
                    counts[label] = counts.get(label, 0) + 1
                proof = check.get("receipt_proof") or {}
                return ("FAHCE returned result — response received.\nHTTP: 200\n"
                        + "Receipt ID: " + body["request_id"]
                        + "\nEngine: " + body["receipt"]["engine_version"]
                        + "\nDetermination: " + body["billing"]["determination_status"]
                        + "\nDiagnosis: " + body["diagnosis"]["state"]
                        + "\nOffer verified: " + str(body["verification"]["verified"]).lower()
                        + "\nClaim findings: " + json.dumps(counts)
                        + "\nSubmitted request SHA-256: " + check["request_hash"]
                        + "\nAttested response hash: " + body["receipt"]["response_hash"]
                        + "\nReceipt signature/response proof: " + ("verified against published policy and Microsoft signing keys" if proof.get("verified") else "not established")
                        + "\nPayment evidence: " + check["settlement_status"]
                        + "\nTransaction hash: " + str(check.get("settlement_reference") or "not available")
                        + "\nWallet addresses: [hidden]"
                        + "\nNext step: " + body["next_safe_action"]["action"]
                        + "\nUse export json for the full returned determination and proof. " + SCOPE)
            return "FAHCE returned result (not a seller trust certificate):\n" + json.dumps(check, ensure_ascii=False, indent=2)
        if self.checkout is not None:
            if not state.get("draft") or state.get("outdated") or self.missing(state):
                return "FAHCE wallet bridge is configured; this intake has no current complete draft ready for checkout. Send wallet for guidance."
            return "FAHCE wallet bridge is configured, not a finding of checkout eligibility. A current draft alone is insufficient: saved restrictions, free input compatibility and existing-checkout/reconciliation safeguards still apply. Only explicit check requests preparation; any payment requires separate buyer review and wallet authorization."
        return "FAHCE evaluation not requested for this draft. This status does not assess transport configuration. " + SCOPE

    def _readable(self, state):
        prefix = "PREVIOUS DRAFT — requested revisions are not incorporated yet.\n\n" if state["outdated"] else ""
        return prefix + describe_restrictions(state.get("restrictions")) + "\n\n" + render_draft(state["draft"], state.get('draft_documents', state.get('documents', []))) + "\n\n" + self._check_status(state)

    def _draft_delivery(self, state):
        full = self._readable(state)
        if len(full.encode("utf-8")) < 5000:
            return full
        from .offer_representation import buyer_explanation
        brief = buyer_explanation(state["draft"], state.get("restrictions"), outdated=state.get("outdated", False), documents=state.get('draft_documents', state.get('documents', [])))
        if len(brief.encode("utf-8")) > 4500:
            from .guided_cards import review_summary
            return review_summary(state)
        return brief + "\n\nComplete concise buyer view, not the full audit document. All detailed capabilities, examples and source references remain in export readable and export json; large exports retain their integrity manifest and resumable parts.\n" + self._check_status(state)

    def export_record(self, state):
        check = state.get("check")
        if state["outdated"] or (check and check.get("draft_hash") != fingerprint(state["draft"])):
            check = None
        return {
            "schema": "TOOL_OFFER_EXPORT_V1", "agent_name": self.name,
            "draft_outdated": state["outdated"], "draft": state["draft"],
            "restrictions": state.get("restrictions", empty_restrictions()),
            "pending_intake": state["fields"] if state["outdated"] or not state.get("draft") else None,
            "source_documents": state["documents"],
            "document_attempts": state.get("document_attempts", []),
            "document_history": state.get("document_history", []),
            "fahce": check or {"status": "not_requested", "executed": False,
                               "machine_adapter_execution": "unavailable_by_design",
                               "human_checkout": "configured" if self.checkout is not None else "separate_native_flow_not_assessed_here",
                               "transport_configuration": "configured" if self.fahce.configured or self.checkout is not None else "not_assessed_by_this_export",
                               "message": self._check_status(state)},
            "approved_offer": state.get("approved_offer"), "commercial_transaction_ids": state.get("commercial_transactions", []),
            "recovery": state["error"],
            "product_history": state.get("product_history", []),
            "offer_lineage": state.get("offer_lineage", []),
        }
