import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { address, digest, hash, sign, verify } from '../src/signing.mjs';
import generated from '../src/generated.json' with { type: 'json' };

test('Cloudflare runtime: discovery, auth, durable jobs, signed replies, MCP and REST', { timeout: 45000 }, async () => {
  const config = { ...generated, gateway_address: address('11'.repeat(32)), contract: { ...generated.contract, agent_address: address('33'.repeat(32)) } };
  const compiled = await build({ entryPoints: ['src/worker.mjs'], bundle: true, write: false, format: 'esm', external: ['cloudflare:workers'],
    plugins: [{ name: 'offline-identities', setup(builder) {
      builder.onLoad({ filter: /generated\.json$/ }, () => ({ contents: JSON.stringify(config), loader: 'json' }));
    } }],
  });
  const token = 'toa_' + 'a'.repeat(43);
  const secondToken = 'toa_' + 'b'.repeat(43);
  const calls = [];
  const cached = new Map();
  let mode = 'normal';
  const runtime = new Miniflare(convertV4MiniflareOptions({ modules: true, script: compiled.outputFiles[0].text, compatibilityDate: '2026-10-30',
    telemetry: { enabled: false },
    durableObjects: { MACHINE_GATEWAY: { className: 'MachineGateway', useSQLite: true } },
    bindings: { TOOL_OFFER_GATEWAY_KEY: '11'.repeat(32), TOOL_OFFER_MACHINE_CLIENTS: JSON.stringify({ [hash(token)]: 'alice', [hash(secondToken)]: 'bob' }) },
    serviceBindings: { ASSETS: async (request) => {
      const pathname = new URL(request.url).pathname;
      const file = pathname === '/' ? 'index.html' : pathname === '/machine/' ? 'machine/index.html' : pathname.slice(1);
      if (file.includes('..')) return new Response('not found', { status: 404 });
      try { return new Response(readFileSync(resolve('public', file))); }
      catch { return new Response('not found', { status: 404 }); }
    } },
    outboundService: async (request) => {
      assert.equal(request.url, 'https://agentverse.ai/v1/hosting/submit');
      assert.equal(request.headers.get('x-uagents-connection'), 'sync');
      const envelope = await request.json();
      const payload = JSON.parse(Buffer.from(envelope.payload, 'base64').toString());
      assert.equal(verify(digest(payload.body), payload.authorization, config.gateway_address), true);
      const data = JSON.parse(payload.body);
      assert.equal(data.transport_sender, envelope.sender);
      calls.push(data.operation);
      assert.ok(['capabilities', 'get_status', 'export_offer', 'get_export_part', 'assess_offer_readiness', 'result'].includes(data.operation), 'No inference or payment allowed in runtime test');
      const cacheKey = data.principal + ':' + data.session_id + ':' + data.request_id;
      const outcome = data.operation === 'result' ? cached.get(cacheKey) || { status: 'uncertain' }
        : { status: 'complete', text: mode === 'large' ? 'x'.repeat(140000) : 'Offline existing-agent status; no inference', model_attempts: 0 };
      if (data.operation === 'assess_offer_readiness') outcome.readiness = { schema_version: 'TOOL_OFFER_READINESS_DELIVERY_V1', delivery: 'inline', report: { human_readable: outcome.text }, snapshot_sha256: hash('controlled snapshot') };
      if (!['capabilities', 'result'].includes(data.operation)) {
        cached.set(cacheKey, outcome);
        if (mode === 'lost-reply') { mode = 'normal'; return new Response('temporary transport failure', { status: 502 }); }
      }
      const body = JSON.stringify({ ...data, ...outcome, release_id: mode === 'mismatch' ? 'older-release' : data.release_id });
      return Response.json({ version: 1, sender: config.contract.agent_address, target: envelope.sender, session: envelope.session,
        schema_digest: config.response_digest, payload: Buffer.from(JSON.stringify({ body, signature: sign(digest(body), '33'.repeat(32)) })).toString('base64') });
    },
  }));
  try {
    const origin = config.contract.origin;
    const dispatch = (path, body, credential = token, additional = {}) => runtime.dispatchFetch(origin + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...(credential ? { Authorization: 'Bearer ' + credential } : {}), ...additional }, body: JSON.stringify(body),
    });
    const discovery = await runtime.dispatchFetch(origin + '/capabilities/machines');
    assert.match(discovery.headers.get('Content-Type'), /application\/json/);
    assert.match(discovery.headers.get('Cache-Control'), /must-revalidate/);
    assert.equal((await discovery.json()).release_id, generated.release_id);
    assert.match(await (await runtime.dispatchFetch(origin + '/')).text(), /Machine/);
    const initialized = await dispatch('/mcp', { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'test', version: '1' } } }, null);
    assert.equal((await initialized.json()).result.protocolVersion, '2025-11-25');
    const listed = await dispatch('/mcp', { jsonrpc: '2.0', id: 2, method: 'tools/list' }, null);
    assert.equal((await listed.json()).result.tools.length, config.contract.tools.length);
    const denied = await dispatch('/api/machine/start_session', { request_id: crypto.randomUUID() }, null);
    assert.equal(denied.status, 401);
    assert.match(denied.headers.get('WWW-Authenticate'), /Bearer/);
    assert.match((await denied.json()).recovery, /OAuth client credentials or Fetch identity proof/);
    const privateInvalid = await dispatch('/api/machine/get_status', { session_id: {}, request_id: 'invalid' }, null);
    assert.equal(privateInvalid.status, 401);
    assert.equal((await privateInvalid.json()).error, 'credential_required');
    assert.equal(calls.length, 0);
    assert.equal((await dispatch('/mcp', {}, token, { Origin: 'https://untrusted.example' })).status, 403);
    assert.equal((await dispatch('/mcp', {}, token, { 'MCP-Protocol-Version': 'invalid' })).status, 400);
    assert.equal((await dispatch('/api/machine/get_status', { session_id: {}, request_id: crypto.randomUUID() })).status, 400);
    const startArgs = { request_id: crypto.randomUUID() };
    const session = await (await dispatch('/api/machine/start_session', startArgs)).json();
    assert.ok(session.session_id);
    assert.deepEqual(await (await dispatch('/api/machine/start_session', startArgs)).json(), session);
    const args = { session_id: session.session_id, request_id: crypto.randomUUID() };
    const mcp = await (await dispatch('/mcp', { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'get_status', arguments: args } })).json();
    const job = JSON.parse(mcp.result.content[0].text);
    assert.deepEqual(mcp.result.structuredContent, job);
    assert.ok(job.job_id, JSON.stringify(mcp));
    assert.equal((await dispatch('/api/machine/get_result', { job_id: job.job_id }, secondToken)).status, 404);
    let result;
    for (let attempt = 0; attempt < 30; attempt++) {
      result = await (await dispatch('/api/machine/get_result', { job_id: job.job_id })).json();
      if (['complete', 'error', 'uncertain'].includes(result.status)) break;
      await new Promise((resolveWait) => setTimeout(resolveWait, 250));
    }
    assert.equal(result.status, 'complete', JSON.stringify({ result, calls }));
    assert.equal(result.model_attempts, 0);
    assert.deepEqual(calls, ['capabilities', 'get_status']);
    const replay = await (await dispatch('/api/machine/get_status', args)).json();
    assert.equal(replay.job_id, job.job_id);
    assert.deepEqual(calls, ['capabilities', 'get_status']);
    const awaitJob = async (jobId, finalStatuses = ['complete', 'error']) => {
      for (let attempt = 0; attempt < 25; attempt++) {
        const response = await (await dispatch('/api/machine/get_result', { job_id: jobId })).json();
        if (finalStatuses.includes(response.status)) return response;
        await new Promise((resolveWait) => setTimeout(resolveWait, 500));
      }
      assert.fail('Bounded fake job did not settle');
    };
    const waitedArgs = { ...args, request_id: crypto.randomUUID() };
    const beforeWait = calls.length;
    const waited = await (await dispatch('/api/machine/get_status', waitedArgs, token, { Prefer: 'wait=5' })).json();
    assert.equal(waited.status, 'complete', JSON.stringify(waited));
    assert.ok(waited.proof.signature);
    assert.deepEqual(calls.slice(beforeWait), ['capabilities', 'get_status']);
    const waitedReplay = await (await dispatch('/api/machine/get_status', waitedArgs, token, { Prefer: 'wait=5' })).json();
    assert.equal(waitedReplay.job_id, waited.job_id);
    assert.deepEqual(waitedReplay.proof, waited.proof);
    assert.deepEqual(calls.slice(beforeWait), ['capabilities', 'get_status']);
    const readinessArgs = { ...args, request_id: crypto.randomUUID() };
    assert.equal((await dispatch('/api/machine/assess_offer_readiness', readinessArgs, null)).status, 401);
    assert.equal((await dispatch('/api/machine/assess_offer_readiness', readinessArgs, secondToken)).status, 404);
    const readinessJob = await (await dispatch('/api/machine/assess_offer_readiness', readinessArgs)).json();
    const readinessResult = await awaitJob(readinessJob.job_id);
    assert.equal(readinessResult.readiness.schema_version, 'TOOL_OFFER_READINESS_DELIVERY_V1');
    assert.equal(readinessResult.model_attempts, 0);
    assert.deepEqual(readinessResult.readiness, JSON.parse(readinessResult.proof.body).readiness);
    assert.equal((await (await dispatch('/api/machine/assess_offer_readiness', readinessArgs)).json()).job_id, readinessJob.job_id);
    assert.equal((await dispatch('/api/machine/get_status', readinessArgs)).status, 409);
    const readinessMcp = await (await dispatch('/mcp', { jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'get_result', arguments: { job_id: readinessJob.job_id } } })).json();
    assert.deepEqual(readinessMcp.result.structuredContent.readiness, readinessResult.readiness);
    mode = 'large';
    const exported = await (await dispatch('/api/machine/export_offer', { ...args, request_id: crypto.randomUUID(), format: 'json' })).json();
    assert.equal((await awaitJob(exported.job_id)).text.length, 140000);
    mode = 'lost-reply';
    const beforeRecovery = calls.length;
    const interruptedArgs = { ...args, request_id: crypto.randomUUID() };
    const interrupted = await (await dispatch('/api/machine/get_status', interruptedArgs)).json();
    assert.equal((await awaitJob(interrupted.job_id)).status, 'complete');
    assert.deepEqual(calls.slice(beforeRecovery), ['capabilities', 'get_status', 'result']);
    assert.equal((await (await dispatch('/api/machine/get_status', interruptedArgs)).json()).job_id, interrupted.job_id);
    mode = 'mismatch';
    const beforeMismatch = calls.length;
    const mismatched = await (await dispatch('/api/machine/get_status', { ...args, request_id: crypto.randomUUID() })).json();
    const mismatchResult = await awaitJob(mismatched.job_id, ['uncertain', 'error']);
    assert.equal(mismatchResult.error, 'release_mismatch');
    assert.deepEqual(calls.slice(beforeMismatch), ['capabilities']);
    let limited;
    for (let attempt = 0; attempt < 121; attempt++) {
      limited = await dispatch('/api/machine/get_result', { job_id: job.job_id });
      if (limited.status === 429) break;
    }
    assert.equal(limited.status, 429);
    assert.ok(Number(limited.headers.get('Retry-After')) >= 1);
    const quota = await limited.json();
    assert.equal(quota.window, 'minute');
    assert.match(quota.recovery, /original request_id/);
  } finally { await runtime.dispose(); }
});
