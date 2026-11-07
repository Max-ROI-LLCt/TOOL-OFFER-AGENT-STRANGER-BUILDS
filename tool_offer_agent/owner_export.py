"""Owner-authenticated export bridge; no wallet signing or payment authority."""

import json
from uuid import UUID

from uagents import Model, Protocol


class OwnerExportRequest(Model):
    builder_sender: str
    conversation: str


class OwnerExportResponse(Model):
    record: dict | None = None
    error: str | None = None


def include_owner_export(agent, workflow, allowed_sender):
    if not allowed_sender:
        return
    protocol = Protocol(name="ToolOfferOwnerExport", version="0.1.0")

    @protocol.on_message(model=OwnerExportRequest, replies={OwnerExportResponse})
    async def export_saved(ctx, sender, msg):
        if sender != allowed_sender:
            await ctx.send(sender, OwnerExportResponse(error="Owner authorization required."))
            return
        try:
            UUID(msg.conversation)
            if not msg.builder_sender.startswith("agent1") or len(msg.builder_sender) > 100:
                raise ValueError()
            with workflow.lock:
                state = workflow.store.load(workflow.store.key(msg.builder_sender, msg.conversation))
                record = workflow.export_record(state) if state.get("draft") else None
            if record is None:
                await ctx.send(sender, OwnerExportResponse(error="No saved draft for this exact conversation."))
                return
            if len(json.dumps(record, ensure_ascii=False).encode("utf-8")) > 180000:
                await ctx.send(sender, OwnerExportResponse(error="Export exceeds the owner bridge size limit."))
                return
            await ctx.send(sender, OwnerExportResponse(record=record))
        except Exception:
            await ctx.send(sender, OwnerExportResponse(error="Saved export could not be read."))

    agent.include(protocol)
