"""Agent Chat Protocol boundary; workflow imports do not need SDK credentials."""

import hashlib
import time
import asyncio
from datetime import datetime, timezone
import os
import re
import json
from uuid import uuid4

from uagents import Agent, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

from .storage import AgentStateStore, DEFAULT_STATE_PATH, StateStore
from .workflow import Workflow


def create_text_chat(text):
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=[TextContent(type="text", text=text)])


def create_readiness_chat(text):
    message = create_text_chat(str(text))
    try:
        from uagents_core.contrib.protocols.chat import MetadataContent
        from .readiness_cards import valid_metadata
        from .guided_cards import valid_metadata as valid_guided_metadata
        metadata = getattr(text, "metadata", None)
        if valid_metadata(metadata) or valid_guided_metadata(metadata):
            message.content.append(MetadataContent(type="metadata", metadata=metadata))
    except Exception:
        pass
    return message


def incoming_text(message):
    from uagents_core.contrib.protocols.chat import MetadataContent
    from uagents_core.contrib.protocols.chat.cards import extract_card_response
    responses = []
    for content in message.content:
        if not isinstance(content, MetadataContent):
            continue
        metadata = content.metadata
        if 'card_protocol_version' not in metadata or 'card_kind' in metadata:
            continue
        def unique(pairs):
            selection = {}
            for name, value in pairs:
                if name in selection:
                    raise ValueError('Duplicate card selection key')
                selection[name] = value
            return selection
        if 'selection' in metadata:
            json.loads(metadata['selection'], object_pairs_hook=unique)
        response = extract_card_response(content)
        if response is None:
            raise ValueError('Invalid card response metadata')
        responses.append(response)
    if not responses:
        return message.text()
    if len(responses) != 1:
        raise ValueError("Ambiguous card response")
    response = responses[0]
    selection = dict(response.selection or {})
    if response.card_id:
        card_id = response.card_id.hex
        if selection.get("card_id", card_id) != card_id:
            raise ValueError("Conflicting card identity")
        selection["card_id"] = card_id
    if response.cancelled:
        if not selection.get("card_id"):
            raise ValueError("Unbound cancellation")
        selection = {"action": "cancel", "card_id": selection["card_id"]}
    if selection:
        return json.dumps(selection, ensure_ascii=False)
    return response.text or message.text()


def strip_routing_mentions(text):
    targets = (
        os.getenv("TOOL_OFFER_AGENT_HANDLE", "tool-offer-builder").lstrip("@"),
        os.getenv("TOOL_OFFER_AGENT_ADDRESS", "agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a").lstrip("@"),
    )
    pattern = r"^\s*@(?:" + "|".join(re.escape(target) for target in targets if target) + r")(?=\s|$)\s*"
    while True:
        cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)
        if cleaned == text:
            return text
        text = cleaned


async def bounded_send(ctx, sender, message, trace, phase):
    try:
        result = await asyncio.wait_for(ctx.send(sender, message), timeout=8)
        status = getattr(getattr(result, "status", None), "value", None)
        outcome = "transport_delivered" if status == "delivered" else "transport_failed" if status == "failed" else "transport_unconfirmed"
    except asyncio.TimeoutError:
        outcome = "delivery_timeout"
    except Exception:
        outcome = "delivery_exception"
    if hasattr(ctx, "logger"):
        ctx.logger.info("Tool Offer delivery: " + json.dumps({"trace": trace, "phase": phase, "outcome": outcome, "scope": "agent_transport_only; ASI history/rendering not confirmed"}))
    return outcome


async def respond(ctx, sender, msg, workflow):
    trace = str(msg.msg_id)
    started = time.monotonic()
    if hasattr(ctx, "logger"):
        ctx.logger.info("Tool Offer incoming: " + json.dumps({"trace": trace, "session_hash": hashlib.sha256(str(getattr(ctx, "session", "")).encode()).hexdigest()[:16]}))
    await bounded_send(ctx, sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id), trace, "ack")
    try:
        text = incoming_text(msg)
    except (ValueError, TypeError):
        await bounded_send(ctx, sender, create_text_chat("Invalid card response; nothing changed. Request review intake or use cancel review in plain chat."), trace, "reply")
        return
    if not text:
        return
    text = strip_routing_mentions(text)
    session = getattr(ctx, "session", None)
    try:
        timestamp = msg.timestamp.replace(tzinfo=timezone.utc) if msg.timestamp.tzinfo is None else msg.timestamp.astimezone(timezone.utc)
        arguments = {"message_id": str(msg.msg_id), "message_timestamp": timestamp.isoformat()} if isinstance(workflow, Workflow) else {}
        from .model_runtime import traced
        reply, events = await asyncio.to_thread(traced, workflow.handle, sender, str(session) if session else None, text,
                                               spending_actor="native:" + sender, **arguments)
        if hasattr(ctx, "logger"):
            diagnostic = getattr(getattr(workflow, "conversation", None), "last_provider_error", None)
            configuration = getattr(workflow, "model_configuration", None)
            ctx.logger.info("Tool Offer processed: " + json.dumps({"trace": trace, "elapsed_ms": int((time.monotonic() - started) * 1000), "model_attempts": sum(e.get("request_sent", True) for e in events)}))
            for item in events:
                ctx.logger.info("Tool Offer inference: " + json.dumps({"trace": trace, **item}, sort_keys=True))
            if events and isinstance(configuration, dict):
                ctx.logger.info("Tool Offer ASI provider configuration: " + json.dumps(configuration, sort_keys=True))
            if "CHAT_" in reply and isinstance(diagnostic, dict):
                ctx.logger.info("Tool Offer ASI provider diagnostic: " + json.dumps(diagnostic, sort_keys=True))
                if isinstance(configuration, dict):
                    ctx.logger.info("Tool Offer ASI provider configuration: " + json.dumps(configuration, sort_keys=True))
            failure = re.match(r"Document extraction failed \((MODEL_[A-Z_]+)\)", reply)
            if failure:
                ctx.logger.info("Tool Offer extraction outcome: " + failure.group(1))
            elif reply.startswith("FAHCE wallet checkout prepared"):
                checkout_id = re.search(r"/checkout/([a-f0-9]{64})/", reply)
                if checkout_id:
                    ctx.logger.info("FAHCE checkout prepared; checkout_id=" + checkout_id.group(1))
            elif reply.startswith("FAHCE returned result"):
                ctx.logger.info("FAHCE checkout result returned to conversation")
            elif reply.startswith("Draft v"):
                ctx.logger.info("Tool Offer draft returned; unextracted categories=" + str(reply.count("Not extracted from supplied documentation")))
    except Exception:
        if hasattr(ctx, "logger"):
            ctx.logger.info("Tool Offer processing failure: " + json.dumps({"trace": trace, "outcome": "application_failure", "elapsed_ms": int((time.monotonic() - started) * 1000)}))
        # SDK/model exceptions can contain secrets; never echo or log their contents.
        reply = "Local processing is unavailable. No successful change or check is claimed. Retry status or export when storage is available."
    # Prepare immutable exports before sending a single bounded response.
    from .readiness import ReadinessText
    if isinstance(workflow, Workflow):
        try:
            reply = await asyncio.to_thread(workflow.render_response, sender, str(session) if session else None, reply, text.lower().lstrip("/"))
        except Exception:
            reply = "Export delivery could not be prepared safely. Existing offer preserved; no complete export claimed. Request export json again."
    # Workflow snapshots large replies durably. Never push an unsolicited sequence
    # of fragments that clients may treat as competing final answers.
    from .export_delivery import REPLY_BYTES
    if len(reply.encode("utf-8")) > REPLY_BYTES:
        reply = "Response exceeds the bounded delivery budget. Use export json to obtain a resumable export manifest; no complete export was delivered."
    if hasattr(ctx, "logger"):
        encoded_reply = reply.encode("utf-8")
        ctx.logger.info("Tool Offer response payload: " + json.dumps({
            "trace": trace, "bytes": len(encoded_reply),
            "sha256": hashlib.sha256(encoded_reply).hexdigest(),
            "incomplete_marker": "INCOMPLETE" in reply or "CHAT_TRUNCATED" in reply,
            "multipart_manifest": '"TOOL_OFFER_EXPORT_MANIFEST_V1"' in reply,
        }))
    await bounded_send(ctx, sender, create_readiness_chat(reply) if isinstance(reply, ReadinessText) else create_text_chat(reply), trace, "reply")
    if reply.startswith("Test-only payment request queued for ") and text.lower().startswith("transaction send "):
        from .protocol_payment import payment_request
        from .commerce import Stage, TransitionError
        from uagents_core.types import DeliveryStatus
        transaction_id = text.split()[2]
        record = workflow.commerce.read(transaction_id)
        try:
            status = await ctx.send(record["buyer"]["id"], payment_request(record))
            if status.status == DeliveryStatus.DELIVERED:
                return
            evidence = "Payment request delivery not confirmed by agent transport"
        except TransitionError:
            workflow.commerce.transition(transaction_id, Stage.EXPIRED, sender, "request-expired:" + transaction_id, ["Expired before dispatch; no request sent"])
            await ctx.send(sender, create_text_chat("Test-only payment authorization expired before dispatch. No payment request was sent."))
            return
        except Exception:
            evidence = "Payment request send raised an unspecified transport error"
        try:
            workflow.commerce.transition(transaction_id, Stage.PENDING_RECONCILIATION, sender, "request-uncertain:" + transaction_id, [evidence])
        except TransitionError:
            pass
        await ctx.send(sender, create_text_chat("Test-only request delivery is uncertain. It will not be sent again automatically. Inspect transaction status for reconciliation."))


def create_agent(hosted=False, *, agent_kwargs=None):
    name = os.getenv("TOOL_OFFER_AGENT_NAME", "Tool Offer Agent")
    extractor = None
    conversation = None
    configuration = None
    use_extraction = os.getenv("TOOL_OFFER_USE_MODEL", "1" if hosted else "0") == "1"
    use_conversation = os.getenv("TOOL_OFFER_USE_CONVERSATION", "1" if hosted and use_extraction else "0") == "1"
    if use_extraction or use_conversation:
        from openai import OpenAI
        from .model_runtime import client_configuration
        api_key = os.getenv("TOOL_OFFER_ASI_ONE_API_KEY")
        if not api_key or not api_key.strip():
            raise RuntimeError("ASI inference requires the server-side TOOL_OFFER_ASI_ONE_API_KEY secret.")
        base_url = "https://api.asi1.ai/v1"
        configuration = client_configuration(base_url, api_key)
        configuration.update(provider="personal_asi_one", model="asi1", endpoint=base_url + "/chat/completions")
        client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        if use_extraction:
            from .drafting import OpenAIQuoteExtractor
            extractor = OpenAIQuoteExtractor(client)
        if use_conversation:
            from .conversation import ConversationInterpreter
            conversation = ConversationInterpreter(client, model="asi1")
    agent = Agent(name=name, **(agent_kwargs or {}))
    store = AgentStateStore(agent.storage) if hosted else StateStore(os.getenv("TOOL_OFFER_STATE_PATH", DEFAULT_STATE_PATH))
    if use_extraction or use_conversation:
        from .model_runtime import configure_spending
        configure_spending(client, store)
    transaction_store = None
    if hosted and os.getenv("TOOL_OFFER_CUSTODY_URL") and os.getenv("TOOL_OFFER_CUSTODY_TOKEN"):
        from .cloudflare_custody import CloudflareTransactionStore
        transaction_store = CloudflareTransactionStore(os.environ["TOOL_OFFER_CUSTODY_URL"], os.environ["TOOL_OFFER_CUSTODY_TOKEN"])
    hosted_demo = hosted and os.getenv("TOOL_OFFER_ENABLE_HOSTED_TEST_PAYMENTS") == "1"
    demo_buyer = os.getenv("TOOL_OFFER_DEMO_BUYER_ADDRESS") if hosted_demo else None
    if hosted_demo and (transaction_store is None or not demo_buyer or not re.fullmatch(r"agent1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{59}", demo_buyer)):
        raise RuntimeError("Hosted nonspending demo requires custody URL, token and a valid allowed buyer address.")
    local_test = (not hosted and os.getenv("TOOL_OFFER_ENABLE_TEST_PAYMENTS") == "1") or hosted_demo
    checkout = None
    if os.getenv("TOOL_OFFER_FAHCE_CHECKOUT_URL") and os.getenv("TOOL_OFFER_FAHCE_CHECKOUT_TOKEN"):
        from .fahce_checkout import FahceCheckoutClient
        checkout = FahceCheckoutClient(os.environ["TOOL_OFFER_FAHCE_CHECKOUT_URL"], os.environ["TOOL_OFFER_FAHCE_CHECKOUT_TOKEN"])
    workflow = Workflow(checkout=checkout, store=store, extractor=extractor, conversation=conversation, name=name, local_test=local_test, transaction_store=transaction_store,
                        demo_buyer_address=demo_buyer, demo_recipient=os.getenv("TOOL_OFFER_AGENT_ADDRESS", "agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a") if hosted_demo else None)
    workflow.model_configuration = configuration
    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(ChatMessage)
    async def handle_message(ctx, sender, msg):
        await respond(ctx, sender, msg, workflow)

    @protocol.on_message(ChatAcknowledgement)
    async def handle_ack(ctx, sender, msg):
        pass

    agent.include(protocol, publish_manifest=hosted)
    if local_test:
        from .protocol_payment import include_payment_seller
        include_payment_seller(agent, workflow.commerce, local_test=True, publish_manifest=hosted)
    owner_export = os.getenv("TOOL_OFFER_OWNER_EXPORT_ADDRESS")
    if owner_export:
        from .owner_export import include_owner_export
        include_owner_export(agent, workflow, owner_export)
    if hosted:
        from .machine import include_machine
        include_machine(agent, workflow)
    return agent
