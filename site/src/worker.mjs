import { DurableObject } from 'cloudflare:workers';
import config from './generated.json' with { type: 'json' };
import discoveryRoutes from './discovery-routes.json' with { type: 'json' };
import { applyCall, authenticate, MachineError, validate, waitForCompletion } from './gateway.mjs';
import { exchange, digest, hash, verify } from './signing.mjs';
import { AccessRegistry } from './access.mjs';

const headers = { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'X-Content-Type-Options': 'nosniff', 'X-Tool-Offer-Release': config.release_id, 'X-Tool-Offer-Version': config.contract.version,
  'Link': `<${config.contract.machine_readable_profile}>; rel="describedby"; type="application/json"` };
const recovery = (value, status) => status === 401 ? 'Authenticate automatically using OAuth client credentials or Fetch identity proof at /machine/#access; send Authorization: Bearer <token>. No human approval. Never send credentials in URLs.'
  : status === 409 ? 'Keep the original request_id and arguments. Poll the existing job. Changed arguments need a fresh request_id only after prior work is resolved; uncertain work must not be resubmitted.'
  : status === 429 ? (value.window === 'lifetime' ? 'This session has reached its lifetime limit. Preserve existing export manifests; a new session does not inherit this offer.' : 'Wait for Retry-After/reset_at, then replay the original request_id and arguments. Do not rotate credentials to bypass quotas.') : undefined;
const json = (value, status = 200) => new Response(JSON.stringify({ ...value, ...(recovery(value, status) ? { recovery: recovery(value, status) } : {}) }), { status, headers });

async function boundedJson(request, form = false) {
  if (!(request.headers.get('Content-Type') || '').startsWith(form ? 'application/x-www-form-urlencoded' : 'application/json')) throw new MachineError(form ? 'form_required' : 'json_required', 415);
  const reader = request.body?.getReader();
  if (!reader) throw new MachineError('body_required');
  const chunks = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.length;
    if (length > 24000) { await reader.cancel(); throw new MachineError('request_too_large', 413); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    if (form) {
      const params = new URLSearchParams(text);
      if ([...params.keys()].some(key => params.getAll(key).length !== 1)) throw new Error();
      return Object.fromEntries(params);
    }
    return JSON.parse(text);
  }
  catch { throw new MachineError('invalid_json'); }
}

export class MachineGateway extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec('CREATE TABLE IF NOT EXISTS records (collection TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, expires INTEGER NOT NULL, PRIMARY KEY(collection, key))');
    this.sql.exec('CREATE INDEX IF NOT EXISTS record_expiry ON records(expires)');
    this.sql.exec("CREATE INDEX IF NOT EXISTS job_session ON records(collection, json_extract(value, '$.session_id'))");
    this.sql.exec("CREATE INDEX IF NOT EXISTS job_request ON records(collection, json_extract(value, '$.principal'), json_extract(value, '$.request_id'))");
    this.sql.exec("CREATE INDEX IF NOT EXISTS job_status ON records(collection, json_extract(value, '$.status'))");
    this.access = new AccessRegistry({
      get: (collection, key) => this.get(collection, key),
      put: (collection, key, value) => this.put(collection, key, value),
      transact: fn => this.ctx.storage.transactionSync(fn),
      scan: (collection, cursor, limit) => this.sql.exec('SELECT key,value FROM records WHERE collection=? AND key>? AND expires>? ORDER BY key LIMIT ?', collection, cursor, Date.now(), limit).toArray().map(row => ({ key: row.key, value: JSON.parse(row.value) })),
    }, config);
  }

  get(collection, key) {
    const rows = this.sql.exec('SELECT value FROM records WHERE collection=? AND key=?', collection, key).toArray();
    return rows.length ? JSON.parse(rows[0].value) : undefined;
  }

  put(collection, key, value, expires = value.expires) {
    this.sql.exec('INSERT INTO records(collection,key,value,expires) VALUES(?,?,?,?) ON CONFLICT(collection,key) DO UPDATE SET value=excluded.value,expires=excluded.expires', collection, key, JSON.stringify(value), expires);
  }

  nextJob() {
    const rows = this.sql.exec("SELECT value FROM records WHERE collection='jobs' AND expires>? AND (json_extract(value,'$.status')='pending' OR (json_extract(value,'$.status') IN ('processing','uncertain') AND json_extract(value,'$.recoveries')<3)) ORDER BY json_extract(value,'$.created_at') LIMIT 1", Date.now()).toArray();
    return rows.length ? JSON.parse(rows[0].value) : null;
  }

  async fetch(request) {
    if (new URL(request.url).pathname === '/access') {
      try {
        this.sql.exec('DELETE FROM records WHERE expires<=?', Date.now());
        return json(await this.access.handle(await request.json()));
      }
      catch (error) {
        const response = json({ error: error instanceof MachineError ? error.message : 'access_unavailable' }, error.status || 503);
        if (error.details?.retry_after_seconds) response.headers.set('Retry-After', String(error.details.retry_after_seconds));
        return response;
      }
    }
      const { principal, name, args, wait_ms = 0 } = await request.json();
      const tool = config.contract.tools.find((entry) => entry.name === name);
      if (!tool) throw new MachineError('unknown_tool');
      validate(tool.inputSchema, args);
    try {
      const result = this.ctx.storage.transactionSync(() => {
        const now = Date.now();
        const minute = Math.floor(now / 60000);
        const day = Math.floor(now / 86400000);
        this.sql.exec('DELETE FROM records WHERE expires<=?', now);
        const state = { sessions: {}, starts: {}, quotas: {}, jobs: {} };
        const keys = {
          sessions: [args?.session_id], starts: [`${principal}:${args?.request_id}`],
          quotas: [`${principal}:minute:${minute}`, `${principal}:sessions:${day}`, `${principal}:messages:${day}`, `global:messages:${day}`, `global:operations:${day}`],
        };
        for (const [collection, identifiers] of Object.entries(keys)) {
          for (const key of identifiers) {
            if (typeof key !== 'string') continue;
            const value = this.get(collection, key);
            if (value) state[collection][key] = value;
          }
        }
        const jobs = this.sql.exec("SELECT key,value FROM records WHERE collection='jobs' AND (key=? OR (json_extract(value,'$.principal')=? AND (json_extract(value,'$.session_id')=? OR json_extract(value,'$.request_id')=?)))", args?.job_id || '', principal, args?.session_id || '', args?.request_id || '').toArray();
        for (const row of jobs) state.jobs[row.key] = JSON.parse(row.value);
        const result = applyCall(state, principal, name, args, now, config);
        for (const [collection, records] of Object.entries(state)) for (const [key, value] of Object.entries(records)) this.put(collection, key, value);
        if (result.job_id) Object.assign(result, this.get('results', result.job_id) || {});
        return result;
      });
      if (this.nextJob() && !await this.ctx.storage.getAlarm()) await this.ctx.storage.setAlarm(Date.now() + 100);
      const completed = await waitForCompletion(result, identifier => {
        const job = this.get('jobs', identifier);
        if (!job || job.principal !== principal) return { status: 'uncertain' };
        return { status: job.status, ...(this.get('results', identifier) || {}) };
      }, wait_ms);
      return json(completed);
    } catch (error) {
      const response = json({ error: error instanceof MachineError ? error.message : 'gateway_unavailable', ...(error.details || {}) }, error.status || 503);
      if (error.details?.retry_after_seconds) response.headers.set('Retry-After', String(error.details.retry_after_seconds));
      return response;
    }
  }

  async alarm() {
    const selected = this.ctx.storage.transactionSync(() => {
      const job = this.nextJob();
      if (!job) return null;
      const recovery = job.status !== 'pending';
      job.status = 'processing';
      if (recovery) job.recoveries++;
      this.put('jobs', job.id, job);
      return { ...job, recovery };
    });
    if (!selected) return;
    await this.ctx.storage.setAlarm(Date.now() + 120000);
    let result;
    try {
      if (selected.release_id !== config.release_id) throw new Error('release_changed_do_not_resubmit');
      const data = { principal: selected.principal, session_id: selected.session_id, request_id: selected.request_id,
        operation: selected.recovery ? 'result' : selected.operation, arguments: selected.recovery ? {} : selected.arguments };
      if (!selected.recovery) {
        const capability = await exchange(config, this.env.TOOL_OFFER_GATEWAY_KEY, { ...data, operation: 'capabilities', arguments: {} });
        if (capability.status !== 'complete') throw new Error('release_check_failed');
      }
      result = await exchange(config, this.env.TOOL_OFFER_GATEWAY_KEY, data);
      if (!['complete', 'processing', 'uncertain', 'error'].includes(result.status)) throw new Error('invalid_result');
    } catch (error) {
      const safeReasons = ['gateway_identity_mismatch', 'agent_transport_unavailable', 'invalid_response_envelope', 'invalid_agent_signature', 'response_binding_mismatch', 'release_mismatch'];
      console.warn(JSON.stringify({ component: 'tool_offer_machine_transport', reason: safeReasons.includes(error.message) ? error.message : error.name }));
      result = { status: 'uncertain', error: error.message === 'release_mismatch' ? 'release_mismatch' : 'dispatch_uncertain_do_not_resubmit' };
    }
    this.ctx.storage.transactionSync(() => {
      const job = this.get('jobs', selected.id);
      if (!job) return;
      job.status = result.status;
      const storedResult = { status: result.status, ...(result.text !== undefined ? { text: result.text } : {}),
        ...(result.readiness !== undefined ? { readiness: result.readiness } : {}),
        ...(result.proof ? { proof: result.proof } : {}),
        ...(result.error ? { error: result.error } : {}), ...(result.model_attempts !== undefined ? { model_attempts: result.model_attempts } : {}) };
      this.put('jobs', job.id, job);
      this.put('results', job.id, storedResult, job.expires);
    });
    if (this.nextJob()) await this.ctx.storage.setAlarm(Date.now() + 5000);
    else await this.ctx.storage.deleteAlarm();
  }
}

const application = {
  async fetch(request, env) {
    const url = new URL(request.url);
    const access = url.pathname === '/api/access/applications' || /^\/api\/access\/applications\/[a-f0-9-]{36}$/.test(url.pathname) || url.pathname === '/api/access/owner' || ['/oauth/register', '/oauth/token', '/oauth/status'].includes(url.pathname);
    if (access) {
      try {
        const stub = env.MACHINE_GATEWAY.get(env.MACHINE_GATEWAY.idFromName('tool-offer-machine-v1'));
        const ip = request.headers.get('CF-Connecting-IP');
        if (!ip || !env.TOOL_OFFER_GATEWAY_KEY) throw new MachineError('access_temporarily_unavailable', 503);
        const ipHash = hash('ToolOfferAccessIP/v1:' + env.TOOL_OFFER_GATEWAY_KEY + ':' + Math.floor(Date.now() / 86400000) + ':' + ip);
        const metered = await stub.fetch('https://internal/access', { method: 'POST', body: JSON.stringify({ action: 'attempt', ip: ipHash,
          enrollment: request.method === 'POST' && ['/oauth/register', '/api/access/applications'].includes(url.pathname) }) });
        if (!metered.ok) return metered;
        if (request.headers.has('Origin') && request.headers.get('Origin') !== config.contract.origin) throw new MachineError('origin_not_allowed', 403);
        let input;
        if (url.pathname === '/api/access/owner' && request.method === 'POST') {
          const signed = await boundedJson(request);
          if (typeof signed?.body !== 'string' || signed.body.length > 4000 || typeof signed.signature !== 'string' ||
              !verify(digest('TOOL_OFFER_ACCESS_OWNER_V1\n' + signed.body), signed.signature, config.gateway_address)) throw new MachineError('owner_authorization_required', 401);
          let body;
          try { body = JSON.parse(signed.body); } catch { throw new MachineError('invalid_owner_request'); }
          if (body?.schema !== 'TOOL_OFFER_ACCESS_OWNER_V1' || !Number.isSafeInteger(body.issued_at) ||
              Math.abs(Date.now() - body.issued_at) > 60000 || !/^[a-f0-9-]{36}$/.test(body.nonce || '') ||
              !['list', 'revoke', 'audit'].includes(body.action)) throw new MachineError('invalid_or_expired_owner_request', 401);
          input = { action: body.action, request_id: body.request_id, cursor: body.cursor, nonce: body.nonce, owner_verified: true };
        } else {
          if (request.method === 'POST' && url.pathname === '/oauth/register') input = { action: 'register', registration: await boundedJson(request), ip: ipHash };
          else if (request.method === 'POST' && ['/oauth/token', '/oauth/status'].includes(url.pathname)) input = { action: url.pathname === '/oauth/token' ? 'token' : 'oauth_status', form: await boundedJson(request, true), ip: ipHash };
          else if (request.method === 'POST' && url.pathname === '/api/access/applications') {
            const signed = await boundedJson(request);
            if (typeof signed?.body !== 'string' || signed.body.length > 12000 || typeof signed.signature !== 'string') throw new MachineError('identity_proof_required', 401);
            let body;
            try { body = JSON.parse(signed.body); } catch { throw new MachineError('invalid_access_application'); }
            if (body?.schema !== 'TOOL_OFFER_ACCESS_ENROLL_V1' || body.identity?.type !== 'uagents' ||
                typeof body.identity.address !== 'string' || !Number.isSafeInteger(body.issued_at) || Math.abs(Date.now() - body.issued_at) > 60000 ||
                !/^[a-f0-9-]{36}$/.test(body.nonce || '') || !verify(digest('TOOL_OFFER_ACCESS_ENROLL_V1\n' + signed.body), signed.signature, body.identity.address)) throw new MachineError('identity_proof_required', 401);
            input = { action: 'submit', application: body, ip: ipHash, identity_verified: true };
          }
          else if (request.method === 'GET' && url.pathname.startsWith('/api/access/applications/')) {
            const auth = request.headers.get('Authorization') || '';
            input = { action: 'status', request_id: url.pathname.split('/').at(-1), ip: ipHash,
              status_hash: /^AccessRequest tar_[A-Za-z0-9_-]{43}$/.test(auth) ? hash(auth.slice(14)) : '' };
          } else return json({ error: 'method_not_allowed' }, 405);
        }
        const result = await stub.fetch('https://internal/access', { method: 'POST', body: JSON.stringify({ ...input, rate_checked: true }) });
        const response = json(await result.json(), result.status);
        if (result.headers.has('Retry-After')) response.headers.set('Retry-After', result.headers.get('Retry-After'));
        if (response.status === 401 && request.method === 'GET') response.headers.set('WWW-Authenticate', 'AccessRequest realm="tool-offer-access"');
        return response;
      } catch (error) { return json({ error: error instanceof MachineError ? error.message : 'access_unavailable' }, error.status || 503); }
    }
    const mcp = ['/mcp', '/mcp/'].includes(url.pathname);
    const rest = url.pathname.startsWith('/api/machine/');
    if (!mcp && !rest) {
      const mappedPath = discoveryRoutes[url.pathname];
      const assetRequest = mappedPath ? new Request(new URL(mappedPath, url), request) : request;
      const asset = await env.ASSETS.fetch(assetRequest);
      const response = new Response(asset.body, asset);
      response.headers.set('Link', headers.Link);
      const jsonPaths = ['/capabilities/machines', '/openapi.json', '/readiness.schema.json', '/.well-known/api-catalog', '/.well-known/mcp.json', '/examples/fictional-seller.json', '/examples/quickstart.json', '/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-authorization-server'];
      jsonPaths.push('/manifest.json');
      if (jsonPaths.includes(url.pathname) || ['/instructions.md', '/llms.txt'].includes(url.pathname)) {
        response.headers.set('Content-Type', jsonPaths.includes(url.pathname) ? 'application/json; charset=utf-8' : url.pathname === '/instructions.md' ? 'text/markdown; charset=utf-8' : 'text/plain; charset=utf-8');
        response.headers.set('Cache-Control', 'no-cache, max-age=0, must-revalidate');
      }
      if (['/', '/machine', '/machine/', '/examples', '/examples/'].includes(url.pathname)) {
        response.headers.set('Cache-Control', 'no-cache, max-age=0, must-revalidate');
        response.headers.set('Content-Type', 'text/html; charset=utf-8');
      }
      if (url.pathname === '/sitemap.xml') {
        response.headers.set('Cache-Control', 'no-cache, max-age=0, must-revalidate');
        response.headers.set('Content-Type', 'application/xml; charset=utf-8');
      }
      response.headers.set('X-Tool-Offer-Release', config.release_id);
      response.headers.set('X-Tool-Offer-Version', config.contract.version);
      response.headers.set('Cache-Control', 'no-cache, max-age=0, must-revalidate');
      return response;
    }
    let id = null;
    try {
      if (request.headers.has('Origin') && request.headers.get('Origin') !== config.contract.origin) throw new MachineError('origin_not_allowed', 403);
      if (request.method !== 'POST') {
        const response = json({ error: 'post_json_required',
          message: 'This is a JSON POST protocol endpoint, not a webpage. Standalone SSE is not supported.',
          documentation: config.contract.origin + '/machine/', discovery: config.contract.machine_readable_profile }, 405);
        response.headers.set('Allow', 'POST');
        response.headers.set('Link', headers.Link + ', <' + config.contract.origin + '/machine/>; rel="help"; type="text/html"');
        return response;
      }
      if (mcp && request.headers.has('MCP-Protocol-Version') && request.headers.get('MCP-Protocol-Version') !== '2025-11-25') throw new MachineError('unsupported_protocol_version');
      const body = await boundedJson(request);
      let name;
      let args;
      if (mcp) {
        if (!body || body.jsonrpc !== '2.0' || typeof body.method !== 'string' || (body.id !== undefined && typeof body.id !== 'string' && typeof body.id !== 'number')) throw new MachineError('invalid_jsonrpc');
        id = body.id ?? null;
        if (body.method === 'notifications/initialized' && body.id === undefined) return new Response(null, { status: 202, headers });
        if (body.id === undefined) throw new MachineError('request_id_required');
        if (body.method === 'initialize') return json({ jsonrpc: '2.0', id, result: {
          protocolVersion: '2025-11-25', capabilities: { tools: {} }, serverInfo: { name: 'tool-offer-agent', version: config.contract.version },
          instructions: `Read the canonical machine-readable profile ${config.contract.machine_readable_profile} before calling. Capabilities: ${config.contract.capabilities.join(' ')} ${config.contract.payments.drafting.terms} ${config.contract.payments.evaluation.terms} ${config.contract.scope} Release ${config.release_id}.`,
        } });
        if (body.method === 'ping') return json({ jsonrpc: '2.0', id, result: {} });
        if (body.method === 'tools/list') return json({ jsonrpc: '2.0', id, result: { tools: config.contract.tools } });
        if (body.method !== 'tools/call') return json({ jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not supported' } });
        name = body.params?.name;
        args = body.params?.arguments;
      } else {
        name = url.pathname.slice('/api/machine/'.length);
        args = body;
      }
      let principal;
      try { principal = authenticate(request, env); }
      catch (error) {
        const credential = request.headers.get('Authorization') || '';
        if (!/^Bearer toa_[A-Za-z0-9_-]{43}$/.test(credential)) throw error;
        const stub = env.MACHINE_GATEWAY.get(env.MACHINE_GATEWAY.idFromName('tool-offer-machine-v1'));
        const response = await stub.fetch('https://internal/access', { method: 'POST', body: JSON.stringify({ action: 'authenticate', token_hash: hash(credential.slice(7)) }) });
        const result = await response.json();
        if (!response.ok) throw new MachineError('invalid_credential', 401);
        principal = result.principal;
      }
      if (!env.TOOL_OFFER_GATEWAY_KEY) throw new MachineError('adapter_not_configured', 503);
      const stub = env.MACHINE_GATEWAY.get(env.MACHINE_GATEWAY.idFromName('tool-offer-machine-v1'));
      const preference = /^wait=([1-5])$/.exec(request.headers.get('Prefer') || '');
      const wait_ms = preference ? Number(preference[1]) * 1000 : 0;
      const response = await stub.fetch('https://internal/call', { method: 'POST', body: JSON.stringify({ principal, name, args, wait_ms }) });
      const result = await response.json();
      const outgoing = !mcp ? json(result, response.status) : json({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: JSON.stringify(result) }], structuredContent: result, isError: !response.ok } });
      if (response.headers.has('Retry-After')) outgoing.headers.set('Retry-After', response.headers.get('Retry-After'));
      return outgoing;
    } catch (error) {
      const message = error instanceof MachineError ? error.message : 'adapter_unavailable';
      const status = error.status || 503;
      const payload = mcp ? { jsonrpc: '2.0', id, error: { code: -32000, message } } : { error: message };
      const response = json(payload, status);
      if (status === 401) response.headers.set('WWW-Authenticate', 'Bearer realm="tool-offer-machine", resource_metadata="' + config.contract.origin + '/.well-known/oauth-protected-resource/mcp"');
      return response;
    }
  },
};

export default {
  async fetch(request, env) {
    const result = await application.fetch(request, env);
    const url = new URL(request.url);
    if (url.protocol !== 'https:' || url.hostname !== 'tooloffer.kinganlogic.com') return result;
    const response = new Response(result.body, result);
    response.headers.set('Strict-Transport-Security', 'max-age=86400');
    return response;
  },
};
