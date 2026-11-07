import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

const source = readFileSync(new URL('./transaction_custody.mjs', import.meta.url), 'utf8');
const moduleSource = source.replace('import { DurableObject } from "cloudflare:workers";', 'class DurableObject {}');
assert.notEqual(moduleSource, source);
const { default: worker, CommercialCustody } = await import('data:text/javascript;base64,' + Buffer.from(moduleSource).toString('base64'));

function fixture(context) {
  const database = new DatabaseSync(':memory:');
  context.after(() => database.close());
  const storage = {
    sql: { exec(statement, ...parameters) {
      const prepared = database.prepare(statement);
      const rows = statement.startsWith('SELECT') ? prepared.all(...parameters) : (prepared.run(...parameters), []);
      return { toArray: () => rows };
    } },
    transactionSync(operation) {
      database.exec('BEGIN');
      try {
        const result = operation();
        database.exec('COMMIT');
        return result;
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },
  };
  const custody = new CommercialCustody({ storage }, {});
  const names = [];
  const env = { TOOL_OFFER_CUSTODY_TOKEN: 'synthetic-unfunded-custody-test', COMMERCIAL_CUSTODY: { getByName(name) { names.push(name); return custody; } } };
  const call = (body, authorization = 'Bearer synthetic-unfunded-custody-test') => worker.fetch(new Request('https://custody.example.invalid/v1/state', {
    method: 'POST', headers: { Authorization: authorization }, body: JSON.stringify(body),
  }), env);
  return { call, custody, names, storage };
}

test('synthetic custody rejects authentication and malformed state before dispatch', async context => {
  const { call, names } = fixture(context);
  assert.equal((await call({}, 'Bearer wrong-synthetic-token')).status, 401);
  assert.equal(names.length, 0);
  assert.equal((await call({ key: 'not-a-hash', operation: 'load' })).status, 400);
  assert.equal(names.length, 0);
  for (const after of [null, [], 'invalid']) {
    assert.equal((await call({ key: 'a'.repeat(64), operation: 'compare_and_swap', before: null, after })).status, 400);
  }
});

test('synthetic custody uses real in-memory SQLite canonical CAS and rejects duplicate creation', async context => {
  const { call } = fixture(context);
  const key = 'a'.repeat(64);
  const saved = { stage: 'SYNTHETIC_REVIEW', details: { zebra: 2, alpha: 1 } };
  const create = { key, operation: 'compare_and_swap', before: null, after: saved };
  assert.equal((await (await call(create)).json()).swapped, true);
  assert.equal((await (await call(create)).json()).swapped, false);
  const next = { stage: 'SYNTHETIC_PENDING' };
  assert.equal((await (await call({ key, operation: 'compare_and_swap', before: { details: { alpha: 1, zebra: 2 }, stage: 'SYNTHETIC_REVIEW' }, after: next })).json()).swapped, true);
  assert.deepEqual((await (await call({ key, operation: 'load' })).json()).state, next);
});

test('synthetic concurrent requests allow one transition without any payment network', async context => {
  const { call } = fixture(context);
  const key = 'b'.repeat(64);
  const before = { stage: 'SYNTHETIC_APPROVED' };
  await call({ key, operation: 'compare_and_swap', before: null, after: before });
  const attempts = await Promise.all(['first', 'second'].map(async name => (await (await call({ key, operation: 'compare_and_swap', before, after: { stage: 'SYNTHETIC_PENDING', name } })).json()).swapped));
  assert.equal(attempts.filter(Boolean).length, 1);
});

test('synthetic failed SQL update rolls back the old record', context => {
  const { custody, storage } = fixture(context);
  const key = 'c'.repeat(64);
  const before = { stage: 'SYNTHETIC_RETAINED' };
  assert.equal(custody.compareAndSwap(key, null, before), true);
  const original = storage.sql.exec;
  storage.sql.exec = (statement, ...parameters) => {
    const result = original(statement, ...parameters);
    if (statement.startsWith('UPDATE')) throw new Error('Synthetic post-write fault');
    return result;
  };
  assert.throws(() => custody.compareAndSwap(key, before, { stage: 'SYNTHETIC_NEW' }), /Synthetic/);
  storage.sql.exec = original;
  assert.deepEqual(custody.load(key), before);
});

test('synthetic oversized Unicode request is rejected', async context => {
  const { call, names } = fixture(context);
  assert.equal((await call({ key: 'd'.repeat(64), operation: 'load', padding: '漢'.repeat(90000) })).status, 413);
  assert.equal(names.length, 0);
});
