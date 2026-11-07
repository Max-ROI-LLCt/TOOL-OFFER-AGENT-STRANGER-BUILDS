import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { digest, hash, verify } from '../site/src/signing.mjs';
const rawHash = bytes => createHash('sha256').update(bytes).digest('hex');
const canonical = value => JSON.stringify(value, function (_key, item) {
  return item && typeof item === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item;
});

export function readinessReport(result, payload, releaseId) {
  const delivery = result.readiness;
  assert.equal(result.model_attempts, 0, 'Readiness unexpectedly used inference');
  assert.equal(delivery?.schema_version, 'TOOL_OFFER_READINESS_DELIVERY_V1');
  const report = delivery.delivery === 'inline' ? delivery.report : JSON.parse(payload);
  const bytes = delivery.delivery === 'inline' ? canonical(report) : payload;
  assert.equal(hash(bytes), delivery.report_sha256, 'Readiness report hash mismatch');
  assert.equal(report.schema_version, 'TOOL_OFFER_READINESS_V1');
  assert.equal(report.scope, 'preparation_for_review_only');
  assert.equal(report.basis.snapshot_sha256, delivery.snapshot_sha256, 'Readiness snapshot mismatch');
  assert.equal(report.basis.release_id, releaseId, 'Readiness release mismatch');
  if (delivery.summary) assert.deepEqual(delivery.summary, { status: report.status, scope: report.scope, basis: report.basis,
    authorization: report.authorization, finding_count: report.findings.length, next_step: report.next_step }, 'Readiness summary mismatch');
  assert.equal(typeof report.human_readable, 'string');
  if (delivery.delivery === 'inline') assert.equal(result.text, report.human_readable, 'Readiness text differs');
  return report;
}

export function verifyResult(result, expected) {
  assert.equal(result.status, 'complete', 'Result is not complete');
  const proof = result.proof;
  assert.equal(proof?.agent_address, expected.agent_address, 'Unexpected signing identity');
  assert.equal(verify(digest(proof.body), proof.signature, expected.agent_address), true, 'Invalid agent signature');
  const signed = JSON.parse(proof.body);
  for (const field of ['session_id', 'request_id', 'release_id']) assert.equal(signed[field], expected[field], 'Signed binding mismatch: ' + field);
  for (const field of ['status', 'text', 'model_attempts']) assert.equal(signed[field], result[field], 'Unsigned result differs: ' + field);
  assert.deepEqual(signed.readiness, result.readiness, 'Unsigned readiness differs');
  return signed;
}

export function assemble(manifest, parts) {
  assert.equal(manifest.schema, 'TOOL_OFFER_EXPORT_MANIFEST_V1');
  assert.equal(manifest.encoding, 'utf-8');
  assert.equal(manifest.part_encoding, 'base64');
  assert.ok(Number.isSafeInteger(manifest.total_bytes) && manifest.total_bytes > 0 && manifest.total_bytes <= 8 * 1024 * 1024);
  assert.ok(Number.isSafeInteger(manifest.part_bytes) && manifest.part_bytes > 0);
  assert.equal(manifest.total_parts, Math.ceil(manifest.total_bytes / manifest.part_bytes));
  assert.equal(parts.length, manifest.total_parts, 'Missing export parts');
  const ordered = new Map();
  for (const part of parts) {
    assert.equal(part.schema, 'TOOL_OFFER_EXPORT_PART_V1');
    assert.ok(Number.isSafeInteger(part.index) && part.index >= 1 && part.index <= manifest.total_parts && !ordered.has(part.index));
    for (const field of ['export_id', 'revision', 'total_parts']) assert.equal(part[field], manifest[field]);
    assert.equal(part.offset_bytes, (part.index - 1) * manifest.part_bytes);
    const bytes = Buffer.from(part.data_base64, 'base64');
    assert.equal(bytes.toString('base64'), part.data_base64, 'Noncanonical base64');
    assert.equal(bytes.length, Math.min(manifest.part_bytes, manifest.total_bytes - part.offset_bytes));
    assert.equal(bytes.length, part.bytes);
    assert.equal(rawHash(bytes), part.sha256);
    ordered.set(part.index, bytes);
  }
  const bytes = Buffer.concat(Array.from({ length: manifest.total_parts }, (_, index) => ordered.get(index + 1)));
  assert.equal(bytes.length, manifest.total_bytes);
  assert.equal(rawHash(bytes), manifest.sha256);
  assert.equal(hash(JSON.stringify([manifest.kind, manifest.revision, manifest.sha256])), manifest.export_id);
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
}

export class MachineClient {
  constructor({ origin, authorization, agent_address, release_id, journal, save, fetcher = fetch, waitSeconds = 5 }) {
    Object.assign(this, { origin, authorization, agent_address, release_id, journal, save, fetcher, waitSeconds });
    this.journal.jobs ??= {};
  }

  async call(name, args, { mcp = false } = {}) {
    assert.ok(['start_session', 'send_message', 'get_status', 'get_result', 'export_offer', 'get_export_part', 'assess_offer_readiness'].includes(name));
    const response = await this.fetcher(this.origin + (mcp ? '/mcp' : '/api/machine/' + name), {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(30000),
      headers: { Authorization: this.authorization, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', ...(this.waitSeconds ? { Prefer: 'wait=' + this.waitSeconds } : {}), ...(mcp ? { 'MCP-Protocol-Version': '2025-11-25' } : {}) },
      body: JSON.stringify(mcp ? { jsonrpc: '2.0', id: crypto.randomUUID(), method: 'tools/call', params: { name, arguments: args } } : args),
    });
    let body = await response.json();
    if (mcp && body.result) body = JSON.parse(body.result.content[0].text);
    if (!response.ok || body.error && !body.job_id) {
      const error = new Error(`Machine request failed: ${response.status} ${typeof body.error === 'string' ? body.error : 'rpc_error'}`);
      error.status = response.status;
      error.details = body;
      throw error;
    }
    return body;
  }

  async session() {
    this.journal.start_request_id ||= crypto.randomUUID();
    this.save();
    const session = await this.call('start_session', { request_id: this.journal.start_request_id });
    if (this.journal.session_id) assert.equal(session.session_id, this.journal.session_id);
    this.journal.session_id = session.session_id;
    this.save();
    return session;
  }

  async job(label, name, args = {}, { timeoutMs = 180000, mcp = false } = {}) {
    const existing = this.journal.jobs[label];
    if (existing) assert.deepEqual([existing.name, existing.args], [name, args], 'Never reuse a journal label for changed work');
    const item = this.journal.jobs[label] ||= { name, args, request_id: crypto.randomUUID(), states: [] };
    this.save();
    if (!item.job_id) {
      const queued = await this.call(name, { session_id: this.journal.session_id, request_id: item.request_id, ...args }, { mcp });
      item.job_id = queued.job_id;
      item.states.push(queued.status);
      this.save();
      if (queued.status === 'complete') {
        verifyResult(queued, { agent_address: this.agent_address, release_id: this.release_id,
          session_id: this.journal.session_id, request_id: item.request_id });
        item.result = queued;
        this.save();
        return queued;
      }
    }
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const result = await this.call('get_result', { job_id: item.job_id }, { mcp });
      item.states.push(result.status);
      item.states = [...new Set(item.states)];
      this.save();
      if (result.status === 'complete') {
        verifyResult(result, { agent_address: this.agent_address, release_id: this.release_id,
          session_id: this.journal.session_id, request_id: item.request_id });
        item.result = result;
        this.save();
        return result;
      }
      if (result.status === 'error') throw new Error('Terminal job error; inspect retained job, do not duplicate: ' + item.job_id);
      await new Promise(resolveWait => setTimeout(resolveWait, 3000));
    }
    throw new Error('Bounded poll expired; retain the same job and request_id: ' + item.job_id);
  }

  async download(label, format = 'json') {
    const result = await this.job(label, 'export_offer', { format });
    return this.materialize(label, result);
  }

  async readiness(label = 'readiness', options = {}) {
    const result = await this.job(label, 'assess_offer_readiness', {}, options);
    const delivery = result.readiness;
    assert.ok(['inline', 'text_json', 'multipart'].includes(delivery?.delivery), 'Invalid readiness delivery');
    if (delivery.delivery === 'multipart') assert.deepEqual(delivery.manifest, JSON.parse(result.text), 'Readiness manifest differs');
    const payload = delivery.delivery === 'inline' ? null : await this.materialize(label, result);
    return readinessReport(result, payload, this.release_id);
  }

  async materialize(label, result) {
    let manifest;
    try { manifest = JSON.parse(result.text); } catch { return result.text; }
    if (manifest.schema !== 'TOOL_OFFER_EXPORT_MANIFEST_V1') return result.text;
    const parts = [];
    for (let index = 1; index <= manifest.total_parts; index++) {
      const part = await this.job(`${label}:part:${index}`, 'get_export_part', { export_id: manifest.export_id, index });
      parts.push(JSON.parse(part.text));
    }
    return assemble(manifest, parts);
  }
}
