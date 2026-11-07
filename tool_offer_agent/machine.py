"""Signed, nonspending adapter boundary on the existing hosted workflow."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
import time
from uuid import UUID

from uagents import Model, Protocol
from uagents_core.identity import Identity
from pydantic.v1 import Field

from .workflow import Workflow
from .model_runtime import traced


class MachineRequest(Model):
    """Restricted Tool Offer website adapter; public agents should use Fetch Chat Protocol."""
    body: str = Field(description="JSON offer-preparation request bound to caller, session, release and ephemeral transport sender.")
    authorization: str = Field(description="Dedicated Tool Offer gateway signature; not a wallet or FAHCE/OCI signature.")


class MachineResponse(Model):
    """Source-attributed offer conversation/export result, not certification or payment authorization."""
    body: str = Field(description="JSON status and result bound to the original request and deployed release.")
    signature: str = Field(description="Existing Tool Offer Agent identity signs this message digest only.")


class MachineWorkflow(Workflow):
    def _handle(self, state, text, key, sender):
        command = " ".join(text.casefold().lstrip("/").split())
        if command in {"help", "start", "demo"}:
            return "Free machine offer preparation. " + self.machine_scope + " Commands: " + ", ".join(self.machine_commands)
        if command in {"check", "preflight", "wallet", "purchase guide", "purchase status", "offer approve", "reset"} or command.startswith(("transaction ", "payment ", "publish")):
            return "Unavailable through the free machine adapter. No checkout, evaluation, payment, approval, publication or reset was performed. Existing offer preserved."
        return super()._handle(state, text, key, sender)


class MachineService:
    def __init__(self, workflow, contract, release_id, gateway_address, clock=time.time):
        self.contract = contract
        self.release_id = release_id
        self.gateway_address = gateway_address
        self.clock = clock
        self.lock = threading.Lock()
        self.workflow = MachineWorkflow(store=workflow.store, fetcher=workflow.fetcher, extractor=workflow.extractor,
                                        conversation=workflow.conversation, name=workflow.name)
        self.workflow.machine_scope = contract["scope"]
        self.workflow.machine_commands = contract["safe_commands"]

    def execute(self, request, sender):
        if len(request.body.encode()) > 24000:
            raise ValueError("request_too_large")
        if not Identity.verify_digest(self.gateway_address, hashlib.sha256(request.body.encode()).digest(), request.authorization):
            raise ValueError("unauthorized_gateway")
        data = json.loads(request.body)
        required = {"operation", "principal", "session_id", "request_id", "release_id", "issued_at", "transport_sender", "arguments"}
        if not isinstance(data, dict) or set(data) != required or data["transport_sender"] != sender:
            raise ValueError("invalid_request")
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", data["principal"]):
            raise ValueError("invalid_principal")
        for field in ("session_id", "request_id"):
            if str(UUID(data[field], version=4)) != data[field]:
                raise ValueError("invalid_identifier")
        if type(data["issued_at"]) is not int or not -30 <= self.clock() - data["issued_at"] <= 180:
            raise ValueError("expired_request")
        result = {"request_id": data["request_id"], "session_id": data["session_id"], "transport_sender": sender,
                  "release_id": self.release_id, "status": "complete"}
        if data["operation"] == "capabilities":
            return {**result, "contract": self.contract}
        if data["release_id"] != self.release_id:
            return {**result, "status": "error", "error": "release_mismatch"}
        operation = data["operation"]
        arguments = data["arguments"]
        actor = "machine:" + data["principal"]
        cache_key = self.workflow.store.key("machine-jobs:" + actor, data["session_id"])
        fingerprint = hashlib.sha256(json.dumps([operation, arguments], sort_keys=True).encode()).hexdigest()
        with self.lock:
            cache = self.workflow.store.load(cache_key)
            records = cache.setdefault("machine_jobs", {})
            if operation == "result":
                stored = records.get(data["request_id"])
                return {**result, **(stored["result"] if stored else {"status": "uncertain", "error": "result_not_recorded"})}
            if data["request_id"] in records:
                stored = records[data["request_id"]]
                if stored["fingerprint"] != fingerprint:
                    return {**result, "status": "error", "error": "idempotency_conflict"}
                return {**result, **stored["result"]}
            if len(records) >= self.contract["limits"]["requests_per_session"]:
                return {**result, "status": "error", "error": "session_request_limit"}
            if any(record["result"]["status"] == "processing" for record in records.values()):
                return {**result, "status": "error", "error": "session_busy"}
            command = self.command(operation, arguments)
            records[data["request_id"]] = {"fingerprint": fingerprint, "result": {"status": "processing"}}
            self.workflow.store.save(cache_key, cache)
        try:
            timestamp = datetime.fromtimestamp(data["issued_at"], timezone.utc).isoformat()
            if operation == "assess_offer_readiness":
                from .readiness import machine_result
                try:
                    outcome = machine_result(self.workflow.store, actor, data["session_id"], self.release_id)
                except (ValueError, TypeError, KeyError):
                    outcome = {"status": "error", "error": "readiness_snapshot_invalid_or_over_budget", "model_attempts": 0}
            else:
                reply, events = traced(self.workflow.handle, actor, data["session_id"], command,
                                       message_id=data["request_id"], message_timestamp=timestamp,
                                       spending_actor=actor)
                reply = self.workflow.render_response(actor, data["session_id"], reply, command)
                outcome = {"status": "complete", "text": reply, "model_attempts": sum(e.get("request_sent", True) for e in events)}
                failure = re.search(r"\((CHAT_(?:INCOMPLETE|TRUNCATED|SOURCE_UNSUPPORTED|BUDGET|AUTH|QUOTA|TIMEOUT|PROVIDER|INVALID_RESPONSE))\)", reply)
                if failure:
                    outcome.update(status="error", error=failure.group(1))
        except Exception:
            outcome = {"status": "uncertain", "error": "operation_interrupted_do_not_resubmit"}
        with self.lock:
            cache = self.workflow.store.load(cache_key)
            cache["machine_jobs"][data["request_id"]]["result"] = outcome
            self.workflow.store.save(cache_key, cache)
        return {**result, **outcome}

    def command(self, operation, arguments):
        if not isinstance(arguments, dict):
            raise ValueError("invalid_arguments")
        if operation == "send_message" and set(arguments) == {"message"}:
            message = arguments["message"]
            if isinstance(message, str) and 1 <= len(message) <= self.contract["limits"]["message_characters"]:
                return message
        if operation == "get_status" and not arguments:
            return "status"
        if operation == "assess_offer_readiness" and not arguments:
            return "readiness"
        if operation == "export_offer" and set(arguments) == {"format"} and arguments["format"] in self.contract["exports"]:
            return "export " + arguments["format"]
        if operation == "get_export_part" and set(arguments) == {"export_id", "index"}:
            if re.fullmatch(r"[a-f0-9]{64}", str(arguments["export_id"])) and type(arguments["index"]) is int and 1 <= arguments["index"] <= 999999:
                return f"export part {arguments['export_id']} {arguments['index']}"
        raise ValueError("unsupported_operation")


def include_machine(agent, workflow):
    from .machine_contract import CONTRACT, RELEASE_ID, GATEWAY_ADDRESS

    service = MachineService(workflow, CONTRACT, RELEASE_ID, GATEWAY_ADDRESS)
    protocol = Protocol(name="ToolOfferMachine", version=CONTRACT["version"])

    @protocol.on_message(model=MachineRequest, replies={MachineResponse})
    async def receive(ctx, sender, request):
        signer = getattr(ctx.agent, "sign_digest", None)
        if not callable(signer):
            signer = ctx.agent.identity.sign_digest
        try:
            result = await asyncio.to_thread(service.execute, request, sender)
        except Exception:
            result = {"status": "error", "error": "unauthorized_or_invalid_request", "release_id": RELEASE_ID}
        body = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        signature = signer(hashlib.sha256(body.encode()).digest())
        await ctx.send(sender, MachineResponse(body=body, signature=signature))

    agent.include(protocol, publish_manifest=True)
