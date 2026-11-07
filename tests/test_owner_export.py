from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from tool_offer_agent.owner_export import OwnerExportRequest, include_owner_export


class OwnerExportTests(IsolatedAsyncioTestCase):
    def handler(self):
        handlers = []
        protocol = Mock()
        protocol.on_message.side_effect = lambda **kwargs: lambda fn: handlers.append(fn) or fn
        workflow = Mock()
        from threading import RLock
        workflow.lock = RLock()
        workflow.store.load.return_value = {'draft': {'revision': 17}}
        workflow.export_record.return_value = {'schema': 'TOOL_OFFER_EXPORT_V1'}
        with patch('tool_offer_agent.owner_export.Protocol', return_value=protocol):
            include_owner_export(Mock(), workflow, 'agent1authorized')
        return handlers[0], workflow

    async def test_unauthorized_sender_cannot_read_state(self):
        handler, workflow = self.handler()
        ctx = SimpleNamespace(send=AsyncMock())
        await handler(ctx, 'agent1other', OwnerExportRequest(builder_sender='agent1builder', conversation=str(uuid4())))
        workflow.store.load.assert_not_called()
        self.assertEqual(ctx.send.call_args.args[1].error, 'Owner authorization required.')

    async def test_owner_can_export_exact_saved_conversation_without_mutation(self):
        handler, workflow = self.handler()
        ctx = SimpleNamespace(send=AsyncMock())
        session = str(uuid4())
        await handler(ctx, 'agent1authorized', OwnerExportRequest(builder_sender='agent1builder', conversation=session))
        workflow.store.key.assert_called_once_with('agent1builder', session)
        workflow.store.save.assert_not_called()
        self.assertEqual(ctx.send.call_args.args[1].record['schema'], 'TOOL_OFFER_EXPORT_V1')

    async def test_missing_draft_reports_error_not_fake_record(self):
        handler, workflow = self.handler()
        workflow.store.load.return_value = {}
        ctx = SimpleNamespace(send=AsyncMock())
        await handler(ctx, 'agent1authorized', OwnerExportRequest(builder_sender='agent1builder', conversation=str(uuid4())))
        self.assertIsNone(ctx.send.call_args.args[1].record)
