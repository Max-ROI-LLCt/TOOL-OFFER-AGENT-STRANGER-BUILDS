"""Fetch Agent Payment Protocol seller role; only non-spending local test offers."""

from datetime import datetime, timezone

from uagents import Protocol
from uagents_core.contrib.protocols.payment import (
    CancelPayment, CommitPayment, Funds, RejectPayment, RequestPayment, payment_protocol_spec,
)

from .commerce import Stage, TransactionJournal, TransitionError, digest, request_intent_digest


def payment_request(record):
    terms = record["payment_terms"]
    if record["stage"] != Stage.PAYMENT_REQUESTED.value or terms["method"] != "test_only":
        raise TransitionError("Only an approved, persisted local test request may be sent.")
    remaining = (datetime.fromisoformat(terms["deadline"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise TransitionError("Payment authorization expired before external dispatch.")
    return RequestPayment(
        accepted_funds=[Funds(amount=terms["amount"], currency=terms["currency"], payment_method=terms["method"])],
        recipient=terms["recipient"], deadline_seconds=max(1, int(remaining)),
        reference=record["id"], description="TEST ONLY: no money, wallet, execution or settlement",
        metadata={"transaction_id": record["id"], "offer_hash": record["offer_hash"], "mode": "test_only",
                  "request_intent_hash": request_intent_digest(record)},
    )


def include_payment_seller(agent, journal, *, local_test=False, publish_manifest=False):
    protocol = Protocol(spec=payment_protocol_spec, role="seller")

    @protocol.on_message(CommitPayment)
    async def committed(ctx, sender, msg):
        record = journal.read(msg.reference) if msg.reference else None
        if not local_test or not record or sender != record["buyer"]["id"]:
            return
        terms = record["payment_terms"]
        if record["stage"] != Stage.PAYMENT_REQUESTED.value or terms["method"] != "test_only":
            return
        if msg.reference != record["id"] or msg.funds != Funds(amount=terms["amount"], currency=terms["currency"], payment_method=terms["method"]) or msg.recipient != terms["recipient"] or msg.transaction_id != "TEST_ONLY:" + record["id"]:
            return
        cancellation = CancelPayment(transaction_id=msg.transaction_id, reason="Controlled test finished; no actual payment or settlement.")
        try:
            journal.transition(record["id"], Stage.PAYMENT_COMMITTED, sender, "buyer-commit:" + msg.transaction_id,
                               ["Protocol commitment sha256:" + digest(msg.model_dump())])
            journal.transition(record["id"], Stage.CANCELLED, record["seller"]["id"], "seller-cancel:" + msg.transaction_id,
                               ["Protocol cancellation sha256:" + digest(cancellation.model_dump())])
        except TransitionError:
            return
        await ctx.send(sender, cancellation)

    @protocol.on_message(RejectPayment)
    async def rejected(ctx, sender, msg):
        transaction_id = journal.pending_for_buyer(sender)
        record = journal.read(transaction_id) if transaction_id else None
        if record and record["stage"] == Stage.PAYMENT_REQUESTED.value:
            try:
                journal.transition(transaction_id, Stage.REJECTED, sender, "buyer-reject:" + transaction_id,
                                   ["Protocol rejection sha256:" + digest(msg.model_dump())])
            except TransitionError:
                return

    agent.include(protocol, publish_manifest=publish_manifest)
    return protocol
