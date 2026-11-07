import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { applyCall, authenticate } from '../src/gateway.mjs';
import { hash } from '../src/signing.mjs';
import { assemble, verifyResult } from '../../machine/client.mjs';
import generated from '../src/generated.json' with { type: 'json' };

const python = process.env.TOOL_OFFER_TEST_PYTHON || 'python3';
const now = Date.UTC(2026, 10, 3);

test('expiring and revoked client records retain principal accounting and legacy credentials', () => {
  const token = 'toa_' + 'a'.repeat(43);
  const request = new Request('https://test.invalid', { headers: { Authorization: 'Bearer ' + token } });
  const registry = { [hash(token)]: { principal: 'customer', expires_at: new Date(now + 1000).toISOString() } };
  const env = () => ({ TOOL_OFFER_MACHINE_CLIENTS: JSON.stringify(registry) });
  assert.equal(authenticate(request, env(), now), 'customer');
  assert.throws(() => authenticate(request, env(), now + 1000), /invalid_credential/);
  registry[hash(token)].revoked = true;
  assert.throws(() => authenticate(request, env(), now), /invalid_credential/);
  registry[hash(token)] = 'customer';
  assert.equal(authenticate(request, env(), now), 'customer');
});

test('offline issuance preserves registry, delivers once privately and supports revocation', () => {
  const directory = mkdtempSync(join(tmpdir(), 'tooloffer-client-test-'));
  try {
    const registry = join(directory, 'registry.json');
    const delivery = join(directory, 'delivery.json');
    writeFileSync(registry, JSON.stringify({ existing: 'retained' }));
    const expiry = new Date(Date.now() + 86400000).toISOString();
    const command = ['../machine/clients.mjs', 'issue', registry, 'test-customer', expiry, delivery, '--owner-approved'];
    const output = execFileSync(process.execPath, command, { encoding: 'utf8' });
    const secret = JSON.parse(readFileSync(delivery));
    assert.ok(!output.includes(secret.token));
    const records = JSON.parse(readFileSync(registry));
    assert.equal(records.existing, 'retained');
    assert.equal(records[hash(secret.token)].principal, 'test-customer');
    assert.throws(() => execFileSync(process.execPath, command, { stdio: 'pipe' }));
    execFileSync(process.execPath, ['../machine/clients.mjs', 'revoke', registry, 'test-customer', hash(secret.token)]);
    assert.deepEqual(JSON.parse(readFileSync(registry)), { existing: 'retained' });
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('500 messages with four deterministic followups need more than 1000 operations', () => {
  const state = {};
  const call = (principal, name, args, when = now) => applyCall(state, principal, name, args, when, generated);
  for (let client = 0; client < 50; client++) {
    const principal = 'customer-' + client;
    const session_id = call(principal, 'start_session', { request_id: crypto.randomUUID() }).session_id;
    for (let message = 0; message < 10; message++) {
      const when = now + message * 60000;
      for (const [tool, extra] of [['send_message', { message: 'Controlled fixture' }], ['get_status', {}],
        ['assess_offer_readiness', {}], ['export_offer', { format: 'json' }], ['get_export_part', { export_id: 'a'.repeat(64), index: 1 }]]) {
        const job = call(principal, tool, { session_id, request_id: crypto.randomUUID(), ...extra }, when);
        state.jobs[job.job_id].status = 'complete';
        call(principal, 'get_result', { job_id: job.job_id }, when);
      }
    }
  }
  const day = Math.floor(now / 86400000);
  assert.equal(state.quotas[`global:messages:${day}`].count, 500);
  assert.equal(state.quotas[`global:operations:${day}`].count, 2500);
  assert.equal(generated.contract.limits.daily_operations_global, 5000);
  const session_id = call('extra', 'start_session', { request_id: crypto.randomUUID() }, now + 600000).session_id;
  assert.throws(() => call('extra', 'send_message', { session_id, request_id: crypto.randomUUID(), message: 'Over global limit' }, now + 600000), e => e.status === 429 && e.details.scope === 'global' && e.details.resource === 'messages');
  state.quotas[`global:operations:${day}`].count = 5000;
  assert.throws(() => call('extra', 'get_status', { session_id, request_id: crypto.randomUUID() }, now + 600000), e => e.status === 429 && e.details.resource === 'operations');
});

test('authorized fictional seller: real gateway, signed agent results, polling, readiness and full export', () => {
  const state = {};
  const principal = 'fictional-client';
  const token = 'toa_' + 'f'.repeat(43);
  const request = new Request('https://test.invalid', { headers: { Authorization: 'Bearer ' + token } });
  const env = { TOOL_OFFER_MACHINE_CLIENTS: JSON.stringify({ [hash(token)]: principal }) };
  assert.equal(authenticate(request, env), principal);
  const call = (tool, args) => applyCall(state, principal, tool, args, now, generated);
  const session = call('start_session', { request_id: crypto.randomUUID() });
  const cases = [{ tool: 'start_session', status: 200, body: session }];
  const fixture = JSON.parse(execFileSync(python, ['-m', 'machine.examples', session.session_id], {
    cwd: resolve('..'), encoding: 'utf8', timeout: 20000, maxBuffer: 4 * 1024 * 1024,
    env: { ...process.env, TOOL_OFFER_FIXTURE_SIGNED: '1' },
  }));
  let manifest;
  const parts = [];
  const openapi = JSON.parse(readFileSync('public/openapi.json'));
  // jsonschema checks run against these actual results in the Python regression.
  for (const operation of fixture.operations) {
    const job = call(operation.tool, operation.arguments);
    cases.push({ tool: operation.tool, status: 200, body: job });
    assert.equal(job.status, 'pending');
    assert.ok(openapi.paths['/api/machine/' + operation.tool]);
    const result = operation.result;
    verifyResult(result, { agent_address: result.proof.agent_address, release_id: generated.release_id,
      session_id: session.session_id, request_id: operation.arguments.request_id });
    state.jobs[job.job_id].status = result.status;
    state.jobs[job.job_id].result = result;
    const polled = call('get_result', { job_id: job.job_id });
    cases.push({ tool: 'get_result', status: 200, body: polled });
    assert.equal(polled.status, 'complete');
    assert.equal(polled.model_attempts || 0, 0);
    if (operation.tool === 'export_offer') manifest = JSON.parse(polled.text);
    if (operation.tool === 'get_export_part' && JSON.parse(polled.text).export_id === manifest?.export_id) parts.push(JSON.parse(polled.text));
  }
  const reconstructed = JSON.parse(assemble(manifest, parts));
  assert.equal(reconstructed.draft.seller.name, 'Fictional Parcel Workshop');
  assert.equal(reconstructed.draft.offer.pricing, fixture.seller_assertions.pricing);
  assert.equal(fixture.operational_proof.startsWith('NOT_ESTABLISHED'), true);
  assert.ok(fixture.buyer_copy.includes('Normalize parcel dimensions'));
  const corrupt = structuredClone(parts); corrupt[0].sha256 = '0'.repeat(64);
  assert.throws(() => assemble(manifest, corrupt));
  assert.throws(() => assemble(manifest, parts.slice(1)));
  const validated = execFileSync(python, ['-m', 'tests.validate_machine_schemas'], {
    cwd: resolve('..'), input: JSON.stringify(cases), encoding: 'utf8', timeout: 20000,
  });
  assert.match(validated, /Validated/);
});
