"""Bounded ACP response collector for independently running acceptance clients."""
import asyncio
import re
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage


class ChatAcceptanceReceiver:
    def __init__(self, *, sender, session, request_id, max_bytes=524288):
        self.sender, self.session, self.request_id = sender, str(session), request_id
        self.max_bytes = max_bytes
        self.acknowledged = False
        self.parts = {}
        self.total = None
        self.message_ids = set()
        self.bytes_received = 0
        self.completed = asyncio.Event()

    def receive(self, sender, session, message):
        if sender != self.sender or str(session) != self.session:
            return False
        if isinstance(message, ChatAcknowledgement):
            if message.acknowledged_msg_id == self.request_id:
                self.acknowledged = True
            return False
        if not isinstance(message, ChatMessage) or message.msg_id in self.message_ids:
            return False
        text = message.text()
        match = re.match(r'^Part (\d+)/(\d+) — concatenate part bodies in order:\n', text)
        part, total = (int(match[1]), int(match[2])) if match else (1, 1)
        body = text[match.end():] if match else text
        if not body or not 1 <= part <= total <= 100 or self.total not in (None, total):
            raise ValueError('Invalid or inconsistent response chunks')
        if part in self.parts and self.parts[part] != body:
            raise ValueError('Conflicting duplicate chunk')
        if part not in self.parts:
            self.bytes_received += len(body.encode('utf-8'))
            if self.bytes_received > self.max_bytes:
                raise ValueError('Response budget exceeded')
            self.parts[part] = body
        self.total = total
        self.message_ids.add(message.msg_id)
        if len(self.parts) == total:
            self.completed.set()
        return self.completed.is_set()

    async def wait(self, timeout=120):
        await asyncio.wait_for(self.completed.wait(), timeout=timeout)
        return ''.join(self.parts[i] for i in range(1, self.total + 1))
