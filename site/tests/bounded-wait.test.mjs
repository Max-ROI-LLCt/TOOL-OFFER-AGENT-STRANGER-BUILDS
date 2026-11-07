import assert from 'node:assert/strict';
import test from 'node:test';
import { waitForCompletion } from '../src/gateway.mjs';

test('bounded wait observes one stable job and returns the unchanged signed result', async () => {
  let now = 0;
  let reads = 0;
  const initial = { job_id: 'same-job', session_id: 'same-session', status: 'pending' };
  const final = { status: 'complete', text: '📦', proof: { body: 'signed-body', signature: 'unchanged' } };
  const result = await waitForCompletion(initial, identifier => {
    assert.equal(identifier, initial.job_id);
    reads++;
    return now >= 300 ? final : { status: 'processing' };
  }, 5000, async delay => { now += delay; }, () => now);
  assert.deepEqual(result, { ...initial, ...final });
  assert.equal(reads, 3);
  assert.equal(now, 300);
});

test('timeout and uncertain results preserve IDs without dispatch or retry', async () => {
  const initial = { job_id: 'stable', status: 'pending' };
  let now = 0;
  const result = await waitForCompletion(initial, () => ({ status: 'processing' }), 1000, async delay => { now += delay; }, () => now);
  assert.deepEqual(result, { ...initial, status: 'processing' });
  assert.equal(now, 1000);
  const uncertain = await waitForCompletion(initial, () => ({ status: 'uncertain', error: 'do_not_resubmit' }), 1000, async delay => { now += delay; }, () => now);
  assert.equal(uncertain.job_id, 'stable');
  assert.equal(uncertain.status, 'uncertain');
  for (const invalid of [0, -1, 5001, NaN, '5000']) assert.equal(await waitForCompletion(initial, () => assert.fail('must not load'), invalid), initial);
});
