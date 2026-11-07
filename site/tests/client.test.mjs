import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { assemble, MachineClient, readinessReport, verifyResult } from '../../machine/client.mjs';
import { address, digest, hash, sign } from '../src/signing.mjs';

function fixture(text) {
  const raw = Buffer.from(text);
  const sha = bytes => createHash('sha256').update(bytes).digest('hex');
  const manifest = { schema: 'TOOL_OFFER_EXPORT_MANIFEST_V1', kind: 'response', revision: 2,
    encoding: 'utf-8', part_encoding: 'base64', total_bytes: raw.length, part_bytes: 3000,
    total_parts: Math.ceil(raw.length / 3000), sha256: sha(raw) };
  manifest.export_id = hash(JSON.stringify([manifest.kind, manifest.revision, manifest.sha256]));
  const parts = Array.from({ length: manifest.total_parts }, (_, index) => {
    const bytes = raw.subarray(index * 3000, (index + 1) * 3000);
    return { schema: 'TOOL_OFFER_EXPORT_PART_V1', export_id: manifest.export_id, revision: 2,
      total_parts: manifest.total_parts, index: index + 1, offset_bytes: index * 3000,
      bytes: bytes.length, sha256: sha(bytes), data_base64: bytes.toString('base64') };
  });
  return { manifest, parts };
}

test('short and long offers preserve newlines and multibyte characters across resumed parts', () => {
  for (const text of ['Offer\n\nFully free.\nNo seller authorization.\n', 'A'.repeat(2999) + '🌱\nEvidence, not certification.\n'.repeat(400)]) {
    const { manifest, parts } = fixture(text);
    assert.equal(assemble(manifest, [...parts].reverse()), text);
    assert.throws(() => assemble(manifest, parts.slice(1)), /Missing export parts/);
    assert.equal(assemble(manifest, [parts[0], ...parts.slice(1)]), text);
    const corrupt = structuredClone(parts);
    corrupt[0].data_base64 = Buffer.from('corrupt').toString('base64');
    assert.throws(() => assemble(manifest, corrupt));
  }
});

test('caller verifies exact signature, identity, bindings and displayed text', () => {
  const key = '33'.repeat(32);
  const expected = { agent_address: address(key), request_id: crypto.randomUUID(), session_id: crypto.randomUUID(), release_id: 'test-only' };
  const signed = { request_id: expected.request_id, session_id: expected.session_id, release_id: expected.release_id, status: 'complete', text: 'A complete offer.\n', model_attempts: 1 };
  const body = JSON.stringify(signed);
  const result = { ...signed, proof: { agent_address: expected.agent_address, body, signature: sign(digest(body), key) } };
  assert.deepEqual(verifyResult(result, expected), signed);
  assert.throws(() => verifyResult({ ...result, text: 'Forged offer' }, expected));
  assert.throws(() => verifyResult(result, { ...expected, session_id: crypto.randomUUID() }));
  assert.throws(() => verifyResult(result, { ...expected, agent_address: address('44'.repeat(32)) }));
});

test('bounded timeout retains job and application request_id without resubmitting', async () => {
  const journal = { session_id: crypto.randomUUID() };
  let submissions = 0;
  const client = new MachineClient({ origin: 'https://test.invalid', authorization: 'test-only', journal, save() {}, fetcher: async () => {
    submissions++;
    return Response.json({ job_id: crypto.randomUUID(), status: 'pending' });
  } });
  await assert.rejects(client.job('fresh', 'send_message', { message: 'A safe question' }, { timeoutMs: 0 }), /Bounded poll expired/);
  const retained = structuredClone(journal.jobs.fresh);
  await assert.rejects(client.job('fresh', 'send_message', { message: 'A safe question' }, { timeoutMs: 0 }), /Bounded poll expired/);
  assert.equal(submissions, 1);
  assert.deepEqual(journal.jobs.fresh, retained);
  await assert.rejects(client.job('fresh', 'send_message', { message: 'Different' }), /changed work/);
});

test('typed readiness is bound to the signed body, snapshot and complete report hash', () => {
  const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)) : item);
  const report = { schema_version: 'TOOL_OFFER_READINESS_V1', scope: 'preparation_for_review_only',
    basis: { snapshot_sha256: hash('snapshot'), release_id: 'readiness-test' }, human_readable: 'Offer readiness\n\nUnverified permissions.\n' };
  const readiness = { schema_version: 'TOOL_OFFER_READINESS_DELIVERY_V1', delivery: 'inline', report,
    snapshot_sha256: report.basis.snapshot_sha256, report_sha256: hash(canonical(report)) };
  const key = '33'.repeat(32);
  const expected = { agent_address: address(key), request_id: crypto.randomUUID(), session_id: crypto.randomUUID(), release_id: 'readiness-test' };
  const signed = { ...expected, status: 'complete', text: report.human_readable, readiness, model_attempts: 0 };
  const body = JSON.stringify(signed);
  const result = { ...signed, proof: { agent_address: expected.agent_address, body, signature: sign(digest(body), key) } };
  verifyResult(result, expected);
  assert.deepEqual(readinessReport(result, undefined, expected.release_id), report);
  assert.throws(() => verifyResult({ ...result, readiness: { ...readiness, snapshot_sha256: hash('different') } }, expected));
  assert.throws(() => readinessReport(result, undefined, 'different-release'));
  assert.throws(() => readinessReport({ ...result, text: 'Partial' }, undefined, expected.release_id));
  assert.throws(() => readinessReport({ ...result, model_attempts: 1 }, undefined, expected.release_id));
  assert.throws(() => readinessReport({ ...result, readiness: { ...readiness, report: { ...report, human_readable: 'Tampered' } } }, undefined, expected.release_id));
  const raw = canonical(report);
  const exported = { ...result, text: '{}', readiness: { ...readiness, delivery: 'multipart', report: undefined } };
  const { manifest, parts } = fixture(raw);
  assert.deepEqual(readinessReport(exported, assemble(manifest, parts), expected.release_id), report);
  assert.throws(() => readinessReport(exported, raw.slice(0, -1), expected.release_id));
});
