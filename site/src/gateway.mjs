import { hash } from './signing.mjs';

export class MachineError extends Error {
  constructor(code, status = 400, details = {}) { super(code); this.status = status; this.details = details; }
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export function validate(schema, value) {
  if (schema.type === 'object') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new MachineError('invalid_arguments');
    if (Object.keys(value).some((key) => !Object.hasOwn(schema.properties, key))) throw new MachineError('unknown_argument');
    if (schema.required.some((key) => !Object.hasOwn(value, key))) throw new MachineError('missing_argument');
    for (const [key, entry] of Object.entries(value)) validate(schema.properties[key], entry);
    return;
  }
  if (schema.type === 'string' && (typeof value !== 'string' || [...value].length < (schema.minLength ?? 0) || [...value].length > (schema.maxLength ?? 1000))) throw new MachineError('invalid_string');
  if (schema.type === 'integer' && (!Number.isSafeInteger(value) || value < schema.minimum || value > schema.maximum)) throw new MachineError('invalid_integer');
  if (schema.format === 'uuid' && !uuid.test(value)) throw new MachineError('invalid_uuid_v4');
  if (schema.enum && !schema.enum.includes(value)) throw new MachineError('invalid_choice');
  if (schema.pattern && !new RegExp(schema.pattern).test(value)) throw new MachineError('invalid_pattern');
}

export function authenticate(request, env, now = Date.now()) {
  const header = request.headers.get('Authorization') || '';
  if (!/^Bearer toa_[A-Za-z0-9_-]{43}$/.test(header)) throw new MachineError('credential_required', 401);
  const clients = JSON.parse(env.TOOL_OFFER_MACHINE_CLIENTS || '{}');
  const record = clients[hash(header.slice(7))];
  const principal = typeof record === 'string' ? record : record?.principal;
  if (typeof principal !== 'string' || !/^[a-z0-9_-]{1,64}$/.test(principal)) throw new MachineError('invalid_credential', 401);
  if (typeof record !== 'string' && (record.revoked === true || !Number.isFinite(Date.parse(record.expires_at)) || Date.parse(record.expires_at) <= now)) throw new MachineError('invalid_credential', 401);
  return principal;
}

function consume(state, key, limit, expires, now) {
  const counter = state.quotas[key] || { count: 0, expires };
  if (counter.count >= limit) throw new MachineError('quota_exceeded', 429, {
    scope: key.startsWith('global:') ? 'global' : 'client', window: key.includes(':minute:') ? 'minute' : 'utc_day',
    resource: key.split(':').at(-2), limit, reset_at: new Date(expires).toISOString(), retry_after_seconds: Math.max(1, Math.ceil((expires - now) / 1000)),
  });
  state.quotas[key] = { ...counter, count: counter.count + 1 };
}

export function applyCall(state, principal, name, args, now, config) {
  state.sessions ??= {};
  state.jobs ??= {};
  state.starts ??= {};
  state.quotas ??= {};
  for (const collection of [state.sessions, state.jobs, state.starts, state.quotas]) {
    for (const [key, value] of Object.entries(collection)) if (value.expires <= now) delete collection[key];
  }
  const tool = config.contract.tools.find((entry) => entry.name === name);
  if (!tool) throw new MachineError('unknown_tool');
  validate(tool.inputSchema, args);
  const limits = config.contract.limits;
  const minute = Math.floor(now / 60000);
  const day = Math.floor(now / 86400000);
  consume(state, `${principal}:minute:${minute}`, limits.requests_per_minute, (minute + 1) * 60000, now);
  if (name === 'get_result') {
    const job = state.jobs[args.job_id];
    if (!job || job.principal !== principal) throw new MachineError('job_not_found', 404);
    return { job_id: job.id, session_id: job.session_id, status: job.status, release_id: job.release_id, ...(job.result || {}) };
  }
  if (name === 'start_session') {
    const startKey = `${principal}:${args.request_id}`;
    if (state.starts[startKey]) return state.starts[startKey].result;
    consume(state, `${principal}:sessions:${day}`, limits.daily_sessions_per_client, (day + 1) * 86400000, now);
    const sessionId = crypto.randomUUID();
    const expires = now + limits.session_days * 86400000;
    state.sessions[sessionId] = { principal, expires, count: 0 };
    const result = { session_id: sessionId, expires_at: new Date(expires).toISOString(), release_id: config.release_id };
    state.starts[startKey] = { expires, result };
    return result;
  }
  const session = state.sessions[args.session_id];
  if (!session || session.principal !== principal) throw new MachineError('session_not_found_or_expired', 404);
  const fingerprint = hash(JSON.stringify([name, Object.entries(args).sort(([first], [second]) => first.localeCompare(second))]));
  const prior = Object.values(state.jobs).find((job) => job.principal === principal && job.request_id === args.request_id);
  if (prior) {
    if (prior.fingerprint !== fingerprint) throw new MachineError('idempotency_conflict', 409);
    return { job_id: prior.id, session_id: prior.session_id, status: prior.status, release_id: prior.release_id };
  }
  if (Object.values(state.jobs).some((job) => job.session_id === args.session_id && ['pending', 'processing', 'uncertain'].includes(job.status))) throw new MachineError('session_busy_or_uncertain', 409);
  if (session.count >= limits.requests_per_session) throw new MachineError('session_request_limit', 429, { scope: 'session', window: 'lifetime', limit: limits.requests_per_session, retry_same_session: false });
  if (name === 'send_message') {
    consume(state, `${principal}:messages:${day}`, limits.daily_messages_per_client, (day + 1) * 86400000, now);
    consume(state, `global:messages:${day}`, limits.daily_messages_global, (day + 1) * 86400000, now);
  }
  consume(state, `global:operations:${day}`, limits.daily_operations_global, (day + 1) * 86400000, now);
  session.count++;
  const { session_id: sessionId, request_id: requestId, ...argumentsOnly } = args;
  const job = { id: crypto.randomUUID(), principal, session_id: sessionId, request_id: requestId,
    operation: name, arguments: argumentsOnly, fingerprint, status: 'pending', expires: session.expires,
    release_id: config.release_id, recoveries: 0, created_at: now };
  state.jobs[job.id] = job;
  return { job_id: job.id, session_id: sessionId, status: job.status, release_id: job.release_id };
}
export async function waitForCompletion(initial, load, milliseconds, pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)), clock = Date.now) {
  if (!initial.job_id || !Number.isInteger(milliseconds) || milliseconds < 1 || milliseconds > 5000) return initial;
  const deadline = clock() + milliseconds;
  let result = initial;
  while (['pending', 'processing'].includes(result.status) && clock() < deadline) {
    await pause(Math.min(100, deadline - clock()));
    result = { ...initial, ...load(initial.job_id) };
  }
  return result;
}
