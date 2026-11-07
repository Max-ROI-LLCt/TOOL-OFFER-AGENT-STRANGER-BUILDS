"""Verify a JavaScript envelope with the official SDK and return a test-signed reply."""
import hashlib
import json
import sys
from uagents_core.envelope import Envelope
from uagents_core.identity import Identity
from uagents import Model
from tool_offer_agent.machine import MachineRequest, MachineResponse

request = json.load(sys.stdin)
envelope = Envelope.model_validate(request['envelope'])
assert envelope.verify()
assert envelope.schema_digest == Model.build_schema_digest(MachineRequest)
payload = MachineRequest.parse_raw(envelope.decode_payload())
assert Identity.verify_digest(request['gateway_address'], hashlib.sha256(payload.body.encode()).digest(), payload.authorization)
data = json.loads(payload.body)
agent = Identity.from_string('33' * 32)
body = json.dumps({**data, 'status': 'complete', 'text': 'SDK interoperability verified'})
response = MachineResponse(body=body, signature=agent.sign_digest(hashlib.sha256(body.encode()).digest()))
reply = Envelope(version=1, sender=agent.address, target=envelope.sender, session=envelope.session,
                 schema_digest=Model.build_schema_digest(MachineResponse))
reply.encode_payload(response.json())
print(reply.model_dump_json())
