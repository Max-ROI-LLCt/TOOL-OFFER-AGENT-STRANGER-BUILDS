import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from uagents import Agent, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, chat_protocol_spec
from uagents_core.contrib.protocols.payment import (
    CancelPayment, CommitPayment, CompletePayment, Funds, RejectPayment, RequestPayment, payment_protocol_spec,
)

from tests.support import FakeFetcher, INTAKE, StoreTestMixin
from tool_offer_agent.chat import create_agent, create_text_chat
from tool_offer_agent.commerce import Stage, receipt, request_intent_digest, verify_receipt
from tool_offer_agent.workflow import Workflow


async def execute_in_process(function, *args, **kwargs):
    return function(*args, **kwargs)


class PaymentProtocolExchangeTests(StoreTestMixin, IsolatedAsyncioTestCase):
    async def test_lost_request_response_is_persisted_and_never_replayed(self):
        from types import SimpleNamespace
        from tool_offer_agent.chat import respond

        threading_override = patch("tool_offer_agent.chat.asyncio.to_thread", new=execute_in_process)
        threading_override.start()
        self.addCleanup(threading_override.stop)
        workflow = Workflow(store=self.store, fetcher=FakeFetcher(), local_test=True)
        seller, buyer = "agent1seller", "agent1buyer"
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
        workflow.handle(seller, "conversation", INTAKE)
        workflow.handle(seller, "conversation", "offer approve")
        opened = json.loads(workflow.handle(seller, "conversation", (
            f"transaction open buyer={buyer} method=test_only currency=TEST amount=2.50 "
            f"network=local recipient={seller} deadline={deadline}"
        )))
        transaction_id = opened["transaction_id"]
        workflow.handle(buyer, "buyer-conversation", (
            f"transaction approve {transaction_id} test_only TEST 2.50 local {seller} {deadline}"
        ))
        outgoing = []

        async def send(_recipient, message):
            outgoing.append(message)
            if isinstance(message, RequestPayment):
                self.assertEqual(workflow.commerce.read(transaction_id)["stage"], Stage.PAYMENT_REQUESTED.value)
                raise TimeoutError("Transport outcome unknown")

        ctx = SimpleNamespace(session="conversation", send=send)
        await respond(ctx, seller, create_text_chat(f"transaction send {transaction_id}"), workflow)
        before = workflow.commerce.read(transaction_id)
        self.assertEqual(before["stage"], Stage.PENDING_RECONCILIATION.value)
        self.assertEqual(before["payment"], "not_committed")
        self.assertEqual(before["settlement"], "not_verified")
        restored = Workflow(store=self.store, fetcher=FakeFetcher(), local_test=True)
        await respond(ctx, seller, create_text_chat(f"transaction send {transaction_id}"), restored)
        self.assertEqual(len([message for message in outgoing if isinstance(message, RequestPayment)]), 1)
        self.assertEqual(restored.commerce.read(transaction_id), before)

    async def test_real_sdk_exchange_and_chat_trigger_without_payment(self):
        threading_override = patch("tool_offer_agent.chat.asyncio.to_thread", new=execute_in_process)
        threading_override.start()
        self.addCleanup(threading_override.stop)
        self.assertEqual(payment_protocol_spec.version, "0.1.0")
        local_options = {"endpoint": [], "enable_agent_inspector": False,
                         "publish_agent_details": False, "mark_inactive_on_shutdown": False,
                         "report_events": False}
        with patch("uagents.agent.get_almanac_contract", return_value=None):
            with patch.dict(os.environ, {
                "TOOL_OFFER_USE_MODEL": "0", "TOOL_OFFER_ENABLE_TEST_PAYMENTS": "1",
                "TOOL_OFFER_STATE_PATH": self.store.path,
            }):
                seller_agent = create_agent(agent_kwargs={**local_options, "seed": "tool-offer-local-seller-2026"})
            buyer_agent = Agent(name="Controlled buyer", seed="tool-offer-local-buyer-2026", **local_options)
            owner_agent = Agent(name="Controlled owner", seed="tool-offer-local-owner-2026", **local_options)
        payment_messages = []
        buyer_replies = []
        owner_replies = []
        reject_transaction_id = None
        cancelled = asyncio.Event()
        buyer_payments = Protocol(spec=payment_protocol_spec, role="buyer")

        @buyer_payments.on_message(RequestPayment)
        async def on_payment_request(ctx, sender, message):
            payment_messages.append((sender, message))
            self.assertEqual(sender, seller_agent.address)
            self.assertIn(message.reference, (transaction_id, reject_transaction_id))
            self.assertEqual(message.accepted_funds, [Funds(amount="2.50", currency="TEST", payment_method="test_only")])
            if message.reference == reject_transaction_id:
                await ctx.send(sender, RejectPayment(reason="Controlled buyer declined"))
                return
            await ctx.send(sender, CommitPayment(
                funds=message.accepted_funds[0], recipient=message.recipient,
                transaction_id="TEST_ONLY:" + transaction_id, reference=transaction_id,
            ))

        @buyer_payments.on_message(CancelPayment)
        async def on_cancel(ctx, sender, message):
            payment_messages.append((sender, message))
            cancelled.set()

        @buyer_payments.on_message(CompletePayment)
        async def on_complete(ctx, sender, message):
            payment_messages.append((sender, message))
            cancelled.set()

        buyer_agent.include(buyer_payments, publish_manifest=False)

        def include_chat_receiver(agent, replies):
            chat_protocol = Protocol(spec=chat_protocol_spec)

            @chat_protocol.on_message(ChatMessage)
            async def on_reply(ctx, sender, message):
                replies.append(message.text())

            @chat_protocol.on_message(ChatAcknowledgement)
            async def on_ack(ctx, sender, message):
                pass

            agent.include(chat_protocol, publish_manifest=False)

        include_chat_receiver(buyer_agent, buyer_replies)
        include_chat_receiver(owner_agent, owner_replies)
        workflow = Workflow(store=self.store, fetcher=FakeFetcher(), local_test=True)
        owner = owner_agent.address
        buyer = buyer_agent.address
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
        workflow.handle(owner, "conversation", INTAKE)
        workflow.handle(owner, "conversation", "offer approve")
        opened = json.loads(workflow.handle(owner, "conversation", (
            f"transaction open buyer={buyer} method=test_only currency=TEST amount=2.50 "
            f"network=local recipient={seller_agent.address} deadline={deadline}"
        )))
        transaction_id = opened["transaction_id"]
        self.assertEqual(opened["rail_decision"]["status"], "TEST_ONLY")

        buyer_approval = (
            f"transaction approve {transaction_id} test_only TEST 2.50 local "
            f"{seller_agent.address} {deadline}"
        )
        await buyer_agent._build_context().send(seller_agent.address, create_text_chat(buyer_approval))
        await self._process_pending(seller_agent, buyer_agent, owner_agent)
        self.assertTrue(any("approved" in text for text in buyer_replies))
        await owner_agent._build_context().send(seller_agent.address, create_text_chat(f"transaction send {transaction_id}"))
        await self._process_pending(seller_agent, buyer_agent, owner_agent)
        self.assertTrue(cancelled.is_set())
        self.assertTrue(any("queued" in text for text in owner_replies))
        self.assertEqual([type(message).__name__ for _, message in payment_messages], ["RequestPayment", "CancelPayment"])
        record = workflow.commerce.read(transaction_id)
        self.assertEqual(payment_messages[0][1].metadata["request_intent_hash"], request_intent_digest(record))
        self.assertIn("Payment protocol request intent sha256:" + request_intent_digest(record),
                      next(event for event in record["events"] if event["stage"] == Stage.PAYMENT_REQUESTED.value)["evidence"])
        self.assertTrue(any(event["evidence"][0].startswith("Protocol commitment sha256:") for event in record["events"] if event["stage"] == Stage.PAYMENT_COMMITTED.value))
        self.assertEqual(record["stage"], Stage.CANCELLED.value)
        self.assertEqual(record["payment"], "test_commit_not_settled")
        self.assertEqual(record["settlement"], "not_verified")
        self.assertTrue(verify_receipt(record, receipt(record))["local_integrity"])

        opened_again = json.loads(workflow.handle(owner, "conversation", (
            f"transaction open buyer={buyer} method=test_only currency=TEST amount=2.50 "
            f"network=local recipient={seller_agent.address} deadline={deadline}"
        )))
        reject_transaction_id = opened_again["transaction_id"]
        await buyer_agent._build_context().send(seller_agent.address, create_text_chat(
            f"transaction approve {reject_transaction_id} test_only TEST 2.50 local "
            f"{seller_agent.address} {deadline}"
        ))
        await self._process_pending(seller_agent, buyer_agent, owner_agent)
        await owner_agent._build_context().send(seller_agent.address, create_text_chat(f"transaction send {reject_transaction_id}"))
        await self._process_pending(seller_agent, buyer_agent, owner_agent)
        rejected = workflow.commerce.read(reject_transaction_id)
        self.assertEqual(rejected["stage"], Stage.REJECTED.value)
        self.assertEqual(rejected["payment"], "not_committed")
        self.assertEqual(rejected["settlement"], "not_verified")

    @staticmethod
    async def _process_pending(*agents):
        for _ in range(15):
            pending = False
            for agent in agents:
                if not agent._message_queue.empty():
                    pending = True
                    task = asyncio.create_task(agent._process_single_message(*agent._message_queue.get_nowait()))
                    await asyncio.sleep(0.15)
                    await asyncio.wait_for(task, timeout=5)
            if not pending:
                return
        raise AssertionError("Agent SDK queues failed to settle")
