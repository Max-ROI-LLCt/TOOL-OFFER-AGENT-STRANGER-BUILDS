import assert from 'node:assert/strict';
import test from 'node:test';
import { registerHooks } from 'node:module';
import { mkdtempSync, readFileSync, writeFileSync, statSync, chmodSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { AccessRegistry, ACCESS_POLICY } from '../src/access.mjs';
import { applyCall } from '../src/gateway.mjs';
import { address, digest, hash, newKey, sign } from '../src/signing.mjs';
import { runClient } from '../../machine/access-client.mjs';
import config from '../src/generated.json' with { type: 'json' };

registerHooks({ resolve(specifier, context, next) {
  if (specifier === 'cloudflare:workers') return { url: 'data:text/javascript,export class DurableObject {}', shortCircuit: true };
  return next(specifier, context);
} });
const { default: worker } = await import('../src/worker.mjs');
const origin = config.contract.origin;

test('HSTS covers successful and error HTTPS responses only on the product host', async () => {
  const server = runtime();
  for (const [path, options, status] of [
    ['/manifest.json', {}, 200], ['/missing-hsts-test', {}, 404], ['/mcp/', {}, 405],
    ['/mcp', { headers: { Origin: 'https://untrusted.invalid' } }, 403],
    ['/api/machine/get_status', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }, 401],
  ]) {
    const response = await server.fetcher(origin + path, options);
    assert.equal(response.status, status, path);
    assert.equal(response.headers.get('Strict-Transport-Security'), 'max-age=86400');
  }
  for (const location of ['http://tooloffer.kinganlogic.com/mcp', 'https://kinganlogic.com/mcp', 'https://preview.workers.dev/mcp']) {
    const response = await worker.fetch(new Request(location), {});
    assert.equal(response.headers.get('Strict-Transport-Security'), null, location);
  }
});

function runtime(policy = ACCESS_POLICY) {
  const records = new Map(), machine = {};
  const storage = {
    get: (collection, key) => structuredClone(records.get(collection + ':' + key)),
    put: (collection, key, value) => records.set(collection + ':' + key, structuredClone(value)),
    transact: operation => {
      const before = structuredClone(records);
      try { return operation(); }
      catch (error) { records.clear(); for (const [key, value] of before) records.set(key, value); throw error; }
    },
    scan: (collection, cursor, limit) => [...records].filter(([key]) => key.startsWith(collection + ':') && key.slice(collection.length + 1) > cursor)
      .sort().slice(0, limit).map(([key, value]) => ({ key: key.slice(collection.length + 1), value })),
  };
  const registry = new AccessRegistry(storage, config, policy);
  const stub = { async fetch(url, options) {
    const body = JSON.parse(options.body);
    try {
      const result = url.endsWith('/access') ? await registry.handle(body) : applyCall(machine, body.principal, body.name, body.args, Date.now(), config);
      return Response.json(result);
    } catch (error) {
      return Response.json({ error: error.message }, { status: error.status || 503,
        headers: { 'Retry-After': String(error.details?.retry_after_seconds || 60), 'Cache-Control': 'no-store' } });
    }
  } };
  const env = { TOOL_OFFER_GATEWAY_KEY: 'controlled-test-only-key', TOOL_OFFER_MACHINE_CLIENTS: '{}',
    MACHINE_GATEWAY: { idFromName: name => name, get: () => stub },
    ASSETS: { fetch: async request => {
      const pathname = new URL(request.url).pathname;
      try { return new Response(readFileSync(new URL('../public' + (pathname.endsWith('/') ? pathname + 'index.html' : pathname), import.meta.url))); }
      catch { return new Response('Not found', { status: 404 }); }
    } },
  };
  const fetcher = (url, options = {}) => worker.fetch(new Request(url, { ...options,
    headers: { 'CF-Connecting-IP': '192.0.2.15', ...options.headers } }), env);
  return { registry, records, machine, env, fetcher };
}

test('MCP browser guidance and slash alias preserve protocol, Origin validation and authentication', async () => {
  const server = runtime();
  for (const path of ['/mcp', '/mcp/']) {
    const response = await server.fetcher(origin + path);
    assert.equal(response.status, 405);
    assert.equal(response.headers.get('Allow'), 'POST');
    assert.equal(response.headers.get('X-Tool-Offer-Version'), config.contract.version);
    assert.match(response.headers.get('Link'), /\/machine\/>; rel="help"/);
    assert.equal((await response.json()).documentation, origin + '/machine/');
    assert.equal((await server.fetcher(origin + path, { headers: { Origin: 'https://untrusted.example' } })).status, 403);
    const post = body => server.fetcher(origin + path, { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'MCP-Protocol-Version': '2025-11-25' }, body: JSON.stringify(body) });
    const initialized = await post({ jsonrpc: '2.0', id: 17, method: 'initialize', params: { protocolVersion: '2025-11-25' } });
    assert.equal(initialized.status, 200);
    const result = await initialized.json();
    assert.equal(result.id, 17);
    assert.equal(result.result.protocolVersion, '2025-11-25');
    assert.equal(result.result.serverInfo.version, config.contract.version);
    assert.equal(initialized.headers.get('Location'), null);
    const tools = await (await post({ jsonrpc: '2.0', id: 18, method: 'tools/list' })).json();
    assert.deepEqual(tools.result.tools, config.contract.tools);
    assert.equal((await post({ jsonrpc: '2.0', method: 'notifications/initialized' })).status, 202);
    const protectedCall = await post({ jsonrpc: '2.0', id: 19, method: 'tools/call', params: {
      name: 'start_session', arguments: { request_id: crypto.randomUUID() } } });
    assert.equal(protectedCall.status, 401);
    assert.match(protectedCall.headers.get('WWW-Authenticate'), /oauth-protected-resource\/mcp/);
  }
});

test('public manifest and invocation discovery match the canonical contract without credentials', async () => {
  const server = runtime();
  const manifest = await server.fetcher(origin + '/manifest.json');
  assert.equal(manifest.status, 200);
  assert.match(manifest.headers.get('Content-Type'), /^application\/json/);
  assert.match(manifest.headers.get('Cache-Control'), /must-revalidate/);
  assert.ok(manifest.headers.get('Link').includes(config.contract.machine_readable_profile));
  const published = await manifest.json();
  assert.equal(published.release_id, config.release_id);
  assert.equal(published.version, config.contract.version);
  assert.deepEqual(published.tools, config.contract.tools);
  assert.deepEqual(published.limits, config.contract.limits);
  assert.equal(published.access.oauth.details, origin + '/machine/#access');
  assert.equal(published.access.oauth.openapi, origin + '/openapi.json');
  const initialize = await server.fetcher(origin + '/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: config.contract.invocation.mcp.protocol_version } }) });
  const initialized = await initialize.json();
  assert.equal(initialized.result.protocolVersion, config.contract.invocation.mcp.protocol_version);
  assert.ok(initialized.result.instructions.includes(config.contract.machine_readable_profile));
  for (const capability of config.contract.capabilities) assert.ok(initialized.result.instructions.includes(capability));
  const listed = await server.fetcher(origin + '/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list' }) });
  assert.deepEqual((await listed.json()).result.tools, config.contract.tools);
  const denied = await server.fetcher(origin + '/api/machine/start_session', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: crypto.randomUUID() }) });
  assert.equal(denied.status, 401);
  assert.deepEqual(server.machine, {});
});

test('all static responses and mapped aliases revalidate with the same release identity', async () => {
  const server = runtime();
  const inventory = JSON.parse(readFileSync(new URL('../public/discovery-surfaces.json', import.meta.url)));
  for (const surface of inventory.surfaces.filter(item => item.file)) {
    const response = await server.fetcher(origin + surface.path);
    assert.equal(response.headers.get('X-Tool-Offer-Release'), config.release_id, surface.path);
    assert.equal(response.headers.get('X-Tool-Offer-Version'), config.contract.version, surface.path);
    assert.match(response.headers.get('Cache-Control'), /must-revalidate/, surface.path);
    if (surface.file !== '404.html') assert.equal(response.status, 200, surface.path);
  }
  assert.deepEqual(server.machine, {});
});

test('actual Worker routes and CLI: both identities enroll, poll, call unattended and remain isolated', async () => {
  const server = runtime(), directory = mkdtempSync(join(tmpdir(), 'toa-autonomous-'));
  const oauthFile = join(directory, 'oauth.json'), fetchFile = join(directory, 'fetch.json'), keyFile = join(directory, 'fetch-key');
  const call = args => runClient(args, { origin, fetcher: server.fetcher });
  try {
    const registration = await call(['register', oauthFile, 'Autonomous fixture']);
    assert.equal(registration.human_approval_required, false);
    assert.equal(JSON.parse(readFileSync(oauthFile)).token, undefined);
    assert.equal((await call(['status', oauthFile])).status, 'active');
    const session = await call(['call', oauthFile, 'start_session', JSON.stringify({ request_id: crypto.randomUUID() })]);
    assert.ok(session.session_id);
    const oauthState = JSON.parse(readFileSync(oauthFile));
    assert.equal(statSync(oauthFile).mode & 0o777, 0o600);
    assert.ok(!JSON.stringify([registration, session]).includes(oauthState.token));
    const initialPrincipal = (await server.registry.handle({ action: 'authenticate', token_hash: hash(oauthState.token) })).principal;
    await call(['register', oauthFile]);
    await call(['token', oauthFile]);
    const renewed = JSON.parse(readFileSync(oauthFile));
    assert.equal((await server.registry.handle({ action: 'authenticate', token_hash: hash(renewed.token) })).principal, initialPrincipal);
    writeFileSync(keyFile, newKey(), { mode: 0o600 });
    const enrolled = await call(['fetch-enroll', fetchFile, keyFile]);
    assert.equal(enrolled.status, 'active');
    assert.equal(enrolled.human_approval_required, false);
    assert.equal(enrolled.credential, undefined);
    assert.equal((await call(['status', fetchFile])).request_id, enrolled.request_id);
    assert.equal((await call(['fetch-enroll', fetchFile, keyFile])).request_id, enrolled.request_id);
    assert.ok((await call(['call', fetchFile, 'start_session', JSON.stringify({ request_id: crypto.randomUUID() })])).session_id);
    const fetchState = JSON.parse(readFileSync(fetchFile));
    const other = await server.fetcher(origin + '/api/access/applications/' + enrolled.request_id,
      { headers: { Authorization: 'AccessRequest tar_' + 'z'.repeat(43) } });
    assert.equal(other.status, 401);
    const leaked = JSON.stringify([...server.records]);
    assert.ok(!leaked.includes(fetchState.token) && !leaked.includes(renewed.token));
    const cross = await server.fetcher(origin + '/api/machine/get_status', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + fetchState.token },
      body: JSON.stringify({ session_id: session.session_id, request_id: crypto.randomUUID() }) });
    assert.ok([403, 404].includes(cross.status));
    await server.registry.handle({ action: 'revoke', owner_verified: true, request_id: enrolled.request_id });
    await assert.rejects(call(['call', fetchFile, 'start_session', JSON.stringify({ request_id: crypto.randomUUID() })]), /401/);
    assert.equal((await call(['status', fetchFile])).status, 'revoked');
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('failed signatures, invalid JSON and wrong content type are counted before cryptography or parsing', async () => {
  const server = runtime({ ...ACCESS_POLICY, applications_per_ip_day: 3 });
  for (const [body, type] of [['null', 'application/json'], ['{broken', 'application/json'], ['{}', 'text/plain']]) {
    const result = await server.fetcher(origin + '/api/access/applications', { method: 'POST', headers: { 'Content-Type': type }, body });
    assert.ok([400, 401, 415].includes(result.status));
  }
  const blocked = await server.fetcher(origin + '/api/access/applications', { method: 'POST', body: '{}' });
  assert.equal(blocked.status, 429);
  assert.ok(Number(blocked.headers.get('Retry-After')) > 0);
});

test('enrollment rejects substituted Fetch identity, expired proof, unsigned operator and disallowed origin', async () => {
  const server = runtime({ ...ACCESS_POLICY, applications_per_ip_day: 20 });
  const signingKey = newKey(), otherKey = newKey();
  const payload = { schema: 'TOOL_OFFER_ACCESS_ENROLL_V1', identity: { type: 'uagents', address: address(signingKey) }, issued_at: Date.now(), nonce: crypto.randomUUID() };
  for (const [identityKey, issued] of [[otherKey, Date.now()], [signingKey, Date.now() - 120000]]) {
    const body = JSON.stringify({ ...payload, issued_at: issued });
    const result = await server.fetcher(origin + '/api/access/applications', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body, signature: sign(digest('TOOL_OFFER_ACCESS_ENROLL_V1\n' + body), identityKey) }) });
    assert.equal(result.status, 401);
  }
  assert.equal((await server.fetcher(origin + '/oauth/register', { method: 'POST', headers: { Origin: 'https://attacker.invalid' }, body: '{}' })).status, 403);
  assert.equal((await server.fetcher(origin + '/api/access/owner', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).status, 401);
});

test('browser cookies do not authorize MCP; public discovery and precise resource challenge remain available', async () => {
  const server = runtime();
  const invoke = (method, params = {}) => server.fetcher(origin + '/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: 'session=untrusted', Origin: origin },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) });
  assert.equal((await invoke('initialize')).status, 200);
  assert.equal((await invoke('tools/list')).status, 200);
  const protectedCall = await invoke('tools/call', { name: 'start_session', arguments: { request_id: crypto.randomUUID() } });
  assert.equal(protectedCall.status, 401);
  assert.ok(protectedCall.headers.get('WWW-Authenticate').includes('/.well-known/oauth-protected-resource/mcp'));
});

test('CLI rejects insecure private files and symlinks without exposing stored values', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'toa-permissions-')), filename = join(directory, 'client.json');
  try {
    writeFileSync(filename, '{"token":"never-print-this"}', { mode: 0o644 });
    await assert.rejects(runClient(['status', filename]), /0600/);
    chmodSync(filename, 0o600);
    symlinkSync(filename, join(directory, 'link.json'));
    await assert.rejects(runClient(['status', join(directory, 'link.json')]), /symlinks/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('signed operator can inspect and revoke without enabling approval, and signatures cannot replay', async () => {
  const server = runtime(), operator = newKey(), previousAddress = config.gateway_address;
  const directory = mkdtempSync(join(tmpdir(), 'toa-operator-'));
  config.gateway_address = address(operator);
  const invoke = (body, key = operator) => server.fetcher(origin + '/api/access/owner', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body,
      signature: sign(digest('TOOL_OFFER_ACCESS_OWNER_V1\n' + body), key) }) });
  const command = (action, requestId) => JSON.stringify({ schema: 'TOOL_OFFER_ACCESS_OWNER_V1', action,
    request_id: requestId, issued_at: Date.now(), nonce: crypto.randomUUID() });
  try {
    const registration = await runClient(['register', join(directory, 'client.json'), 'Controlled client'], { origin, fetcher: server.fetcher });
    const list = command('list');
    assert.equal((await invoke(list, newKey())).status, 401);
    const result = await invoke(list);
    assert.equal(result.status, 200);
    assert.equal((await result.json()).identities[0].client_id, registration.client_id);
    assert.equal((await invoke(list)).status, 409);
    assert.equal((await invoke(command('approve', registration.client_id))).status, 401);
    assert.equal((await invoke(command('revoke', registration.client_id))).status, 200);
    const audit = await invoke(command('audit', registration.client_id));
    assert.ok((await audit.json()).events.some(event => event.event === 'revoked' && event.actor === 'signed_operator'));
    await assert.rejects(runClient(['token', join(directory, 'client.json')], { origin, fetcher: server.fetcher }), /401/);
  } finally { config.gateway_address = previousAddress; rmSync(directory, { recursive: true, force: true }); }
});

test('public discovery routes map to real JSON assets with revalidation and a consistent release', async () => {
  const server = runtime();
  for (const path of ['/.well-known/oauth-authorization-server', '/.well-known/oauth-protected-resource',
    '/.well-known/oauth-protected-resource/mcp', '/examples/quickstart.json', '/openapi.json']) {
    const response = await server.fetcher(origin + path);
    assert.equal(response.status, 200, path);
    assert.match(response.headers.get('Content-Type'), /^application\/json/);
    assert.match(response.headers.get('Cache-Control'), /must-revalidate/);
    assert.equal(response.headers.get('X-Tool-Offer-Release'), config.release_id);
    const body = await response.json();
    assert.equal(body['x-release-id'] || body.release_id, config.release_id);
  }
});
