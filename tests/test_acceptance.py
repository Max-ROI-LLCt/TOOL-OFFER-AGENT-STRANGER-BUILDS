from unittest import IsolatedAsyncioTestCase
from uuid import uuid4
from uagents_core.contrib.protocols.chat import ChatAcknowledgement
from tool_offer_agent.acceptance import ChatAcceptanceReceiver
from tool_offer_agent.chat import create_text_chat

class AcceptanceTests(IsolatedAsyncioTestCase):
    async def test_ack_is_not_completion_and_chunks_are_correlated(self):
        request = uuid4()
        receiver = ChatAcceptanceReceiver(sender='seller', session='session', request_id=request)
        receiver.receive('seller', 'session', ChatAcknowledgement(acknowledged_msg_id=request))
        self.assertTrue(receiver.acknowledged)
        self.assertFalse(receiver.completed.is_set())
        self.assertFalse(receiver.receive('other', 'session', create_text_chat('wrong sender')))
        receiver.receive('seller', 'session', create_text_chat('Part 2/2 — concatenate part bodies in order:\nworld'))
        receiver.receive('seller', 'session', create_text_chat('Part 1/2 — concatenate part bodies in order:\nhello '))
        self.assertEqual(await receiver.wait(timeout=1), 'hello world')

    async def test_timeout_and_budget_are_bounded(self):
        receiver = ChatAcceptanceReceiver(sender='seller', session='session', request_id=uuid4(), max_bytes=2)
        with self.assertRaises(TimeoutError):
            await receiver.wait(timeout=.01)
        with self.assertRaises(ValueError):
            receiver.receive('seller', 'session', create_text_chat('too long'))
