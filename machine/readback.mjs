import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const args = process.argv.slice(2);
assert.equal(args.length, 2, 'Usage: node machine/readback.mjs --work <existing-audit-directory>');
assert.equal(args[0], '--work');
const work = resolve(args[1]);
const generated = JSON.parse(readFileSync(resolve(root, 'site/src/generated.json'), 'utf8'));
const inventory = JSON.parse(readFileSync(resolve(root, 'site/public/discovery-surfaces.json'), 'utf8'));
assert.equal(inventory.release_id, generated.release_id);
assert.equal(inventory.version, generated.contract.version);
const receipt = { checked_at: new Date().toISOString(), version: generated.contract.version, release_id: generated.release_id, paths: [], payment_calls: 0, inference_calls: 0 };
const filename = resolve(work, 'public-readback.json');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function save() {
  writeFileSync(filename + '.tmp', JSON.stringify(receipt, null, 2) + '\n', { mode: 0o600 });
  renameSync(filename + '.tmp', filename);
}
try {
  for (const surface of inventory.surfaces) {
    const { path, file: local } = surface;
    for (const mode of ['ordinary', 'revalidated', 'cache-busted']) {
    const requested = generated.contract.origin + path + (mode === 'cache-busted' ? '?release=' + generated.release_id : '');
    const response = await fetch(requested, { redirect: 'manual', signal: AbortSignal.timeout(25000),
      headers: { 'User-Agent': 'ToolOfferRelease/1.0', ...(mode === 'revalidated' ? { 'Cache-Control': 'no-cache', Pragma: 'no-cache' } : {}) } });
    assert.equal(response.headers.get('X-Tool-Offer-Release'), generated.release_id, path + ' runtime release');
    assert.equal(response.headers.get('X-Tool-Offer-Version'), generated.contract.version, path + ' runtime version');
    assert.match(response.headers.get('Cache-Control') || '', /must-revalidate/, path + ' cache policy');
    if (surface.redirect) {
      assert.ok([301, 302, 307, 308].includes(response.status), path + ' redirect status');
      const destination = new URL(response.headers.get('Location'), generated.contract.origin);
      assert.equal(destination.origin, generated.contract.origin);
      assert.equal(destination.pathname, surface.redirect);
      receipt.paths.push({ path, mode, status: response.status, redirect: surface.redirect, release_content_matches: true, matches_release_asset: true });
      save();
      continue;
    }
    assert.equal(response.status, 200, path);
    const type = response.headers.get('Content-Type') || '';
    const expectedType = surface.content_type;
    assert.ok(type.startsWith(expectedType), path + ' Content-Type');
    assert.equal(response.headers.get('X-Tool-Offer-Release'), generated.release_id, path + ' runtime release');
    assert.ok(response.headers.get('Link')?.includes(`<${generated.contract.machine_readable_profile}>; rel="describedby"`), path + ' canonical discovery link');
    assert.match(response.headers.get('Cache-Control') || '', /must-revalidate/, path + ' cache policy');
    const bytes = Buffer.from(await response.arrayBuffer());
    const expected = readFileSync(resolve(root, 'site/public', local));
    if (surface.sha256) assert.equal(hash(expected), surface.sha256, path + ' local inventory digest');
    const artifact = 'public-' + mode + '-' + path.replaceAll('/', '_') + (path.endsWith('.md') ? '.http-body.txt' : '');
    writeFileSync(resolve(work, artifact), bytes, { mode: 0o600 });
    const exact = hash(bytes) === hash(expected);
    const injected = '<script type="module" async fetchpriority="low" src="' + generated.contract.origin + '/.webmcp/bridge.js" data-packs="c2pa,mcp-server-client"></script>';
    const text = bytes.toString('utf8');
    const bridgeOnly = local.endsWith('.html') && text.split(injected).length === 2
      && text.replace(injected, '') === expected.toString('utf8');
    receipt.paths.push({ path, mode, status: response.status, content_type: type, release_id: generated.release_id, bytes: bytes.length, sha256: hash(bytes), local_sha256: hash(expected),
      cache_control: response.headers.get('Cache-Control'), etag: response.headers.get('ETag'), cf_cache_status: response.headers.get('CF-Cache-Status'),
      matches_release_asset: exact, release_content_matches: exact || bridgeOnly,
      ...(bridgeOnly ? { observed_addition: injected, addition_provenance: 'Expected Cloudflare WebMCP edge injection; configuration provenance preserved in evidence/structured-source-binding.json.',
        content_security_policy: response.headers.get('Content-Security-Policy'), execution_verified: false } : {}) });
    save();
    }
  }
  receipt.not_found = [];
  for (const path of ['/__tool_offer_release_check_missing__', '/.well-known/agent.json', '/.well-known/agent-card.json']) {
    const response = await fetch(generated.contract.origin + path, { redirect: 'error', signal: AbortSignal.timeout(25000) });
    assert.equal(response.status, 404, path + ' must not advertise an unimplemented protocol');
    assert.equal(response.headers.get('X-Tool-Offer-Release'), generated.release_id);
    assert.equal(response.headers.get('X-Tool-Offer-Version'), generated.contract.version);
    assert.ok((await response.text()).includes(generated.release_id), path + ' current error page');
    receipt.not_found.push({ path, status: response.status });
  }
  receipt.protocol_routes = [];
  for (const path of ['/mcp', '/mcp/']) {
    const response = await fetch(generated.contract.origin + path, { redirect: 'error', signal: AbortSignal.timeout(25000) });
    assert.equal(response.status, 405);
    assert.equal(response.headers.get('Allow'), 'POST');
    assert.match(response.headers.get('Link'), /\/machine\/>; rel="help"/);
    assert.equal(response.headers.get('X-Tool-Offer-Release'), generated.release_id);
    assert.equal((await response.json()).documentation, generated.contract.origin + '/machine/');
    const initialized = await fetch(generated.contract.origin + path, { method: 'POST', redirect: 'error',
      headers: { 'Content-Type': 'application/json', 'MCP-Protocol-Version': '2025-11-25' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 'slash-check', method: 'initialize', params: { protocolVersion: '2025-11-25' } }) });
    assert.equal(initialized.status, 200);
    const body = await initialized.json();
    assert.equal(body.result.protocolVersion, '2025-11-25');
    assert.equal(body.result.serverInfo.version, generated.contract.version);
    receipt.protocol_routes.push({ path, get_status: response.status, post_status: initialized.status, protocol: body.result.protocolVersion });
  }
  const publicMcp = async (method, params = {}) => {
    const response = await fetch(generated.contract.origin + '/mcp', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(25000),
      headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 'discovery-verification', method, params }),
    });
    assert.equal(response.status, 200, method);
    return response.json();
  };
  const initialized = await publicMcp('initialize', { protocolVersion: generated.contract.invocation.mcp.protocol_version, capabilities: {}, clientInfo: { name: 'discovery-verifier', version: '1.0' } });
  assert.equal(initialized.result.protocolVersion, generated.contract.invocation.mcp.protocol_version);
  assert.equal(initialized.result.serverInfo.version, generated.contract.version);
  assert.ok(initialized.result.instructions.includes(generated.release_id));
  assert.ok(initialized.result.instructions.includes(generated.contract.machine_readable_profile));
  for (const capability of generated.contract.capabilities) assert.ok(initialized.result.instructions.includes(capability));
  const listed = await publicMcp('tools/list');
  assert.deepEqual(listed.result.tools, generated.contract.tools);
  const denied = await fetch(generated.contract.origin + '/api/machine/start_session', {
    method: 'POST', redirect: 'error', signal: AbortSignal.timeout(25000),
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: crypto.randomUUID() }),
  });
  assert.equal(denied.status, 401, 'REST does not execute unauthenticated calls');
  assert.equal(denied.headers.get('Strict-Transport-Security'), 'max-age=86400');
  receipt.hsts = [];
  for (const [path, expected, extraHeaders] of [
    ['/', 200, {}], ['/manifest.json', 200, {}], ['/missing-hsts-readback', 404, {}],
    ['/mcp', 405, {}], ['/mcp/', 405, {}], ['/mcp', 403, { Origin: 'https://untrusted.invalid' }],
  ]) {
    const response = await fetch(generated.contract.origin + path, { headers: extraHeaders, redirect: 'error', signal: AbortSignal.timeout(25000) });
    assert.equal(response.status, expected);
    assert.equal(response.headers.get('Strict-Transport-Security'), 'max-age=86400');
    receipt.hsts.push({ path, status: response.status, policy: response.headers.get('Strict-Transport-Security') });
    await response.arrayBuffer();
  }
  receipt.invocation_discovery = { initialize: true, tools_list: true, rest_authentication_required: true };
  const response = await fetch(generated.contract.origin + '/mcp', {
    method: 'POST', redirect: 'error', signal: AbortSignal.timeout(25000),
    headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 'version-discovery-only', method: 'server/discover' }),
  });
  const body = await response.json();
  assert.equal(body.error?.code, -32601, 'Reassess version compatibility: server/discover changed');
  receipt.mcp_2026_discovery = { status: response.status, error_code: body.error.code, implemented: false, existing_version: '2025-11-25' };
  receipt.passed = receipt.paths.every(path => path.release_content_matches);
  receipt.all_byte_exact = receipt.paths.every(path => path.matches_release_asset);
  save();
  console.log(JSON.stringify({ passed: receipt.passed, paths: receipt.paths.length, release_id: receipt.release_id, receipt: filename }));
  assert.equal(receipt.passed, true, 'Inspect retained live assets for byte differences');
} catch (error) {
  receipt.blocker = { at: new Date().toISOString(), message: error.message };
  save();
  throw error;
}
