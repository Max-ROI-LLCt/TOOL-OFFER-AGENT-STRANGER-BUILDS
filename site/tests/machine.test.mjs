import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { applyCall, authenticate, validate } from '../src/gateway.mjs';
import { address, digest, hash, makeRequest, readResponse, sign, verify } from '../src/signing.mjs';
import generated from '../src/generated.json' with { type: 'json' };

const config = { ...generated, gateway_address: address('11'.repeat(32)), contract: { ...generated.contract, agent_address: address('33'.repeat(32)) } };
const token = 'toa_' + 'a'.repeat(43);
const env = { TOOL_OFFER_MACHINE_CLIENTS: JSON.stringify({ [hash(token)]: 'alice' }) };

test('every tool parameter has a description and a schema-valid example with conservative annotations', () => {
  for (const tool of generated.contract.tools) {
    for (const parameter of Object.values(tool.inputSchema.properties)) assert.ok(parameter.description?.trim());
    assert.equal(tool.inputSchema.examples.length, 1);
    assert.doesNotThrow(() => validate(tool.inputSchema, tool.inputSchema.examples[0]));
    assert.equal(tool.annotations.readOnlyHint, false);
    assert.equal(tool.annotations.idempotentHint, false);
    assert.equal(tool.annotations.destructiveHint, tool.name === 'send_message');
    assert.equal(tool.annotations.openWorldHint, ['send_message', 'get_result'].includes(tool.name));
  }
});
function fixture() {
  let state = {};
  const now = Date.UTC(2026, 10, 2);
  function call(name, args, principal = 'alice', when = now, configuration = config) {
    const transaction = structuredClone(state);
    const result = applyCall(transaction, principal, name, args, when, configuration);
    state = transaction;
    return result;
  }
  const session = call('start_session', { request_id: crypto.randomUUID() }).session_id;
  return { call, session, now, state: () => state };
}

test('Tool Offer signatures work with the actual uagents Python SDK in both directions', () => {
  const request = makeRequest(config, '11'.repeat(32), { principal: 'alice', session_id: crypto.randomUUID(), request_id: crypto.randomUUID(), operation: 'get_status', arguments: {} }, '22'.repeat(32));
  const output = execFileSync(process.env.TOOL_OFFER_TEST_PYTHON || 'python3', ['-m', 'tests.machine_crypto_vector'], {
    cwd: resolve('..'), input: JSON.stringify({ ...request, gateway_address: config.gateway_address }), encoding: 'utf8', timeout: 20000,
  });
  const response = JSON.parse(output);
  assert.equal(readResponse(config, request, response).text, 'SDK interoperability verified');
  const tampered = structuredClone(response);
  const inner = JSON.parse(Buffer.from(tampered.payload, 'base64').toString());
  inner.body = inner.body.replace('verified', 'tampered');
  tampered.payload = Buffer.from(JSON.stringify(inner)).toString('base64');
  assert.throws(() => readResponse(config, request, tampered), /invalid_agent_signature/);
  assert.throws(() => readResponse(config, request, { ...response, session: crypto.randomUUID() }), /invalid_response_envelope/);
  assert.throws(() => makeRequest(config, '44'.repeat(32), request.body), /gateway_identity_mismatch/);
});

test('a signature from another product identity is never accepted', () => {
  const message = digest('Tool Offer message');
  const signature = sign(message, '44'.repeat(32));
  assert.equal(verify(message, signature, address('11'.repeat(32))), false);
});

test('unique transport senders avoid Agentverse synchronous reply collisions', () => {
  const data = { principal: 'alice', session_id: crypto.randomUUID(), request_id: crypto.randomUUID(), operation: 'get_status', arguments: {} };
  const first = makeRequest(config, '11'.repeat(32), data);
  const second = makeRequest(config, '11'.repeat(32), data);
  assert.notEqual(first.envelope.sender, second.envelope.sender);
});

test('caller credentials are required, hashed, and cannot select their own principal', () => {
  assert.equal(authenticate(new Request('https://example.com', { headers: { Authorization: `Bearer ${token}` } }), env), 'alice');
  assert.throws(() => authenticate(new Request(`https://example.com?token=${token}`), env), /credential_required/);
  assert.throws(() => authenticate(new Request('https://example.com', { headers: { Authorization: `Bearer toa_${'b'.repeat(43)}` } }), env), /invalid_credential/);
  assert.throws(() => validate(config.contract.tools[0].inputSchema, { request_id: crypto.randomUUID(), principal: 'owner' }), /unknown_argument/);
});

test('session creation and operations are idempotent without recounting quota', () => {
  const setup = fixture();
  const request = { request_id: crypto.randomUUID() };
  assert.deepEqual(setup.call('start_session', request), setup.call('start_session', request));
  const args = { session_id: setup.session, request_id: crypto.randomUUID(), message: 'What do you do for free?' };
  const first = setup.call('send_message', args);
  const second = setup.call('send_message', args);
  assert.equal(first.job_id, second.job_id);
  assert.equal(setup.state().sessions[setup.session].count, 1);
  assert.throws(() => setup.call('send_message', { ...args, message: 'Different text' }), /idempotency_conflict/);
});

test('clients cannot read another client session, job or export', () => {
  const setup = fixture();
  const queued = setup.call('get_status', { session_id: setup.session, request_id: crypto.randomUUID() });
  assert.throws(() => setup.call('get_result', { job_id: queued.job_id }, 'bob'), /job_not_found/);
  assert.throws(() => setup.call('export_offer', { session_id: setup.session, request_id: crypto.randomUUID(), format: 'json' }, 'bob'), /session_not_found/);
});

test('uncertain work blocks further mutation and expired sessions cannot be revived', () => {
  const setup = fixture();
  const args = { session_id: setup.session, request_id: crypto.randomUUID(), message: 'Question' };
  const job = setup.call('send_message', args);
  setup.state().jobs[job.job_id].status = 'uncertain';
  assert.throws(() => setup.call('send_message', { ...args, request_id: crypto.randomUUID() }), /session_busy_or_uncertain/);
  assert.throws(() => setup.call('get_status', { session_id: setup.session, request_id: crypto.randomUUID() }, 'alice', setup.now + 8 * 86400000), /session_not_found/);
});

test('UTC daily quota is atomic and replaying a job consumes no message allowance', () => {
  const setup = fixture();
  const limited = { ...config, contract: { ...config.contract, limits: { ...config.contract.limits, daily_messages_per_client: 1 } } };
  const args = { session_id: setup.session, request_id: crypto.randomUUID(), message: 'Question' };
  const job = setup.call('send_message', args, 'alice', setup.now, limited);
  setup.state().jobs[job.job_id].status = 'complete';
  assert.equal(setup.call('send_message', args, 'alice', setup.now, limited).job_id, job.job_id);
  const count = setup.state().sessions[setup.session].count;
  assert.throws(() => setup.call('send_message', { ...args, request_id: crypto.randomUUID() }, 'alice', setup.now, limited), /quota_exceeded/);
  assert.equal(setup.state().sessions[setup.session].count, count);
  assert.equal(setup.call('send_message', { ...args, request_id: crypto.randomUUID() }, 'alice', setup.now + 86400000, limited).status, 'pending');
});

test('unknown operations, oversized inputs, malformed IDs and arbitrary URLs are rejected', () => {
  const setup = fixture();
  assert.throws(() => setup.call('payment', {}), /unknown_tool/);
  assert.throws(() => setup.call('send_message', { session_id: setup.session, request_id: crypto.randomUUID(), message: 'a'.repeat(4001) }), /invalid_string/);
  assert.throws(() => setup.call('get_status', { session_id: '../another', request_id: crypto.randomUUID() }), /invalid_uuid/);
  assert.throws(() => setup.call('get_status', { session_id: setup.session, request_id: crypto.randomUUID(), url: 'https://other-product.example/' }), /unknown_argument/);
});

test('approved beta quota permits twenty messages per client and five hundred globally, never unlimited', () => {
  const setup = fixture();
  for (const principal of Array.from({ length: 25 }, (_, index) => 'beta-' + index)) {
    const session = setup.call('start_session', { request_id: crypto.randomUUID() }, principal).session_id;
    const args = { session_id: session, message: 'Offline quota test' };
    for (let count = 0; count < 20; count++) {
      const job = setup.call('send_message', { ...args, request_id: crypto.randomUUID() }, principal);
      setup.state().jobs[job.job_id].status = 'complete';
    }
    assert.throws(() => setup.call('send_message', { ...args, request_id: crypto.randomUUID() }, principal), /quota_exceeded/);
    const status = setup.call('get_status', { session_id: session, request_id: crypto.randomUUID() }, principal);
    setup.state().jobs[status.job_id].status = 'complete';
  }
  assert.throws(() => setup.call('send_message', { session_id: setup.session, request_id: crypto.randomUUID(), message: 'Global limit test' }), /quota_exceeded/);
});

test('all published instructions and tool schemas come from the same release', () => {
  const discovery = JSON.parse(readFileSync('public/capabilities/machines'));
  const openapi = JSON.parse(readFileSync('public/openapi.json'));
  const profile = readFileSync('../AGENT-PROFILE.txt', 'utf8');
  const instructions = readFileSync('public/instructions.txt', 'utf8');
  assert.equal(discovery.release_id, generated.release_id);
  assert.equal(openapi['x-release-id'], generated.release_id);
  assert.deepEqual(discovery.tools, generated.contract.tools);
  assert.deepEqual(discovery.limits, generated.contract.limits);
  assert.equal(discovery.limits.daily_messages_per_client, 20);
  assert.equal(discovery.limits.daily_messages_global, 500);
  assert.ok(instructions.includes('"daily_messages_per_client": 20'));
  assert.ok(instructions.includes('"daily_messages_global": 500'));
  assert.ok(instructions.startsWith(profile));
  assert.ok(instructions.includes(generated.release_id));
  assert.ok(profile.includes(generated.contract.origin + '/instructions.md'));
  assert.ok(profile.length < 14000);
  for (const path of ['public/llms.txt', 'public/machine/index.html']) assert.ok(readFileSync(path, 'utf8').includes(generated.release_id));
  for (const tool of generated.contract.tools) assert.deepEqual(openapi.paths[`/api/machine/${tool.name}`].post.requestBody.content['application/json'].schema, tool.inputSchema);
  assert.match(readFileSync('public/index.html', 'utf8'), /href="\/machine\/">Machine/);
  for (const path of ['/capabilities/machines', '/openapi.json', '/instructions.md', '/llms.txt']) {
    assert.ok(readFileSync('public/machine/index.html', 'utf8').includes(`href="${path}"`));
  }
});
