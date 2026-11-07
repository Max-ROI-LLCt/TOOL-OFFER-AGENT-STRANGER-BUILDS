import assert from 'node:assert/strict';
import test from 'node:test';
import { AccessRegistry, ACCESS_POLICY } from '../src/access.mjs';
import { hash } from '../src/signing.mjs';

const origin = 'https://test.invalid', ip = hash('controlled-ip'), now = Date.now();
function setup(policy = ACCESS_POLICY) {
  const records = new Map();
  const storage = {
    get: (c, k) => records.has(c + ':' + k) ? structuredClone(records.get(c + ':' + k)) : undefined,
    put: (c, k, v) => records.set(c + ':' + k, structuredClone(v)),
    transact: fn => { const before = structuredClone(records); try { return fn(); } catch (e) { records.clear(); for (const [k, v] of before) records.set(k, v); throw e; } },
    scan: (c, cursor, limit) => [...records].filter(([k]) => k.startsWith(c + ':') && k.slice(c.length + 1) > cursor).sort().slice(0, limit).map(([k, value]) => ({ key: k.slice(c.length + 1), value })),
  };
  return { registry: new AccessRegistry(storage, { contract: { origin }, release_id: 'test-release' }, policy), records };
}
async function keys() {
  const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  return { pair, public_key: await crypto.subtle.exportKey('jwk', pair.publicKey) };
}
async function register(registry, identity) {
  return registry.handle({ action: 'register', ip, registration: { client_name: 'Controlled autonomous agent', grant_types: ['client_credentials'],
    token_endpoint_auth_method: 'private_key_jwt', token_endpoint_auth_signing_alg: 'ES256', jwks: { keys: [identity.public_key] } } }, now);
}
async function form(identity, id, overrides = {}, endpoint = '/oauth/token') {
  const enc = v => Buffer.from(JSON.stringify(v)).toString('base64url');
  const payload = { iss: id, sub: id, aud: origin + endpoint, iat: Math.floor(now / 1000), exp: Math.floor(now / 1000) + 60, jti: crypto.randomUUID(), ...overrides };
  const text = enc({ alg: 'ES256', typ: 'JWT' }) + '.' + enc(payload);
  const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, identity.pair.privateKey, new TextEncoder().encode(text));
  return { grant_type: 'client_credentials', client_id: id, client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
    client_assertion: text + '.' + Buffer.from(signature).toString('base64url'), scope: 'tool_offer:machine', resource: origin + '/mcp' };
}

test('generic autonomous OAuth: registration is not authorization; proof issues scoped credential without approval', async () => {
  const { registry, records } = setup(), identity = await keys(), client = await register(registry, identity);
  assert.equal(client.human_approval_required, false);
  assert.equal(client.status, 'registered_proof_required');
  const tokenForm = await form(identity, client.client_id);
  const token = await registry.handle({ action: 'token', ip, form: tokenForm }, now);
  assert.equal(token.expires_in, 3600); assert.equal(token.scope, 'tool_offer:machine');
  const authenticated = await registry.handle({ action: 'authenticate', token_hash: hash(token.access_token) }, now);
  assert.match(authenticated.principal, /^oauth_/);
  assert.ok(!JSON.stringify([...records]).includes(token.access_token));
  const sameClient = await register(registry, identity);
  assert.equal(sameClient.client_id, client.client_id);
  const renewed = await registry.handle({ action: 'token', ip, form: await form(identity, client.client_id) }, now);
  assert.deepEqual(await registry.handle({ action: 'authenticate', token_hash: hash(renewed.access_token) }, now), authenticated);
  await assert.rejects(registry.handle({ action: 'token', ip, form: tokenForm }, now), /invalid_client/);
  await assert.rejects(registry.handle({ action: 'authenticate', token_hash: hash(token.access_token) }, now + 3600001), /invalid_credential/);
});

test('OAuth rejects other keys, altered subject/audience/expiry/scope, private registration keys and repeated JWT IDs', async () => {
  const { registry } = setup({ ...ACCESS_POLICY, requests_per_ip_minute: 100 }), a = await keys(), b = await keys(), client = await register(registry, a);
  await assert.rejects(registry.handle({ action: 'token', ip, form: await form(b, client.client_id) }, now), /invalid_client/);
  for (const claims of [{ sub: 'another-agent' }, { aud: 'https://elsewhere.invalid/oauth/token' }, { exp: 1 }, { exp: Math.floor(now / 1000) + 3600 }, { iat: Math.floor(now / 1000) + 300 }]) {
    await assert.rejects(registry.handle({ action: 'token', ip, form: await form(a, client.client_id, claims) }, now), /invalid_client/);
  }
  const invalid = await form(a, client.client_id); invalid.scope = 'admin';
  await assert.rejects(registry.handle({ action: 'token', ip, form: invalid }, now), /invalid_target_or_scope/);
  const privateKey = { ...a.public_key, d: 'never-accept-private-key-material' };
  await assert.rejects(register(registry, { public_key: privateKey }), /invalid_client_metadata/);
});

test('signed operator revocation blocks every issued token and cannot be evaded by re-registering the same identity', async () => {
  const { registry } = setup(), identity = await keys(), client = await register(registry, identity);
  const token = await registry.handle({ action: 'token', ip, form: await form(identity, client.client_id) }, now);
  await assert.rejects(registry.handle({ action: 'revoke', request_id: client.client_id }, now), /owner_authorization_required/);
  await registry.handle({ action: 'revoke', request_id: client.client_id, owner_verified: true }, now);
  await assert.rejects(registry.handle({ action: 'authenticate', token_hash: hash(token.access_token) }, now), /invalid_credential/);
  await assert.rejects(register(registry, identity), /identity_revoked/);
  const audit = await registry.handle({ action: 'audit', request_id: client.client_id, owner_verified: true }, now);
  assert.ok(audit.events.some(e => e.event === 'revoked'));
});

test('Fetch enrollment automatically encrypts the credential to its applicant; status cannot cross clients', async () => {
  const { registry, records } = setup();
  const pair = await crypto.subtle.generateKey({ name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['encrypt', 'decrypt']);
  const application = { name: 'Controlled Fetch agent', use_case: 'Prepare documentation-backed offers.', public_key: await crypto.subtle.exportKey('jwk', pair.publicKey),
    status_secret_sha256: hash('capability-kept-by-applicant'), identity: { type: 'uagents', address: 'controlled-signature-verified-at-worker' } };
  await assert.rejects(registry.handle({ action: 'submit', ip, application }, now), /invalid_access_application/);
  const result = await registry.handle({ action: 'submit', ip, application, identity_verified: true }, now);
  assert.equal(result.status, 'active'); assert.equal(result.human_approval_required, false);
  const decrypted = JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({ name: 'RSA-OAEP', label: new TextEncoder().encode(result.credential.label) }, pair.privateKey, Buffer.from(result.credential.ciphertext, 'base64url'))));
  assert.equal(decrypted.request_id, result.request_id);
  assert.ok(!JSON.stringify([...records]).includes(decrypted.token));
  const authenticated = await registry.handle({ action: 'authenticate', token_hash: hash(decrypted.token) }, now);
  assert.equal(authenticated.principal, result.client_id);
  await assert.rejects(registry.handle({ action: 'status', ip, request_id: result.request_id, status_hash: hash('another-applicant') }, now), /application_not_authorized/);
  await assert.rejects(registry.handle({ action: 'status', ip, request_id: crypto.randomUUID(), status_hash: application.status_secret_sha256 }, now), /application_not_authorized/);
  const replay = await registry.handle({ action: 'submit', ip, application, identity_verified: true }, now);
  assert.equal(replay.request_id, result.request_id); assert.deepEqual(replay.credential, result.credential);
});

test('anonymous enrollment and failed status attempts are bounded separately from existing machine quotas', async () => {
  const { registry } = setup({ ...ACCESS_POLICY, applications_per_ip_day: 1, requests_per_ip_minute: 3 });
  const a = await keys(); await register(registry, a);
  await assert.rejects(register(registry, a), /access_rate_limit/);
  for (let i = 0; i < 2; i++) await assert.rejects(registry.handle({ action: 'status', ip, request_id: crypto.randomUUID(), status_hash: hash('unknown') }, now), /application_not_authorized/);
  await assert.rejects(registry.handle({ action: 'status', ip, request_id: crypto.randomUUID() }, now), /access_rate_limit/);
});

test('concurrent OAuth issuance is replay-safe, token history bounded, and authorization never expands', async () => {
  const { registry } = setup(), identity = await keys(), client = await register(registry, identity);
  const request = { action: 'token', ip, form: await form(identity, client.client_id) };
  const results = await Promise.allSettled([registry.handle(request, now), registry.handle(request, now)]);
  assert.equal(results.filter(result => result.status === 'fulfilled').length, 1);
  const initial = results.find(result => result.status === 'fulfilled').value.access_token;
  for (let index = 0; index < 4; index++) await registry.handle({ action: 'token', ip, form: await form(identity, client.client_id) }, now);
  await assert.rejects(registry.handle({ action: 'authenticate', token_hash: hash(initial) }, now), /invalid_credential/);
  await assert.rejects(registry.handle({ action: 'approve', owner_verified: true, automatic: true, request_id: client.client_id }, now), /invalid_owner_action/);
  await assert.rejects(registry.handle({ action: 'token', ip, form: await form(identity, client.client_id, { nbf: Math.floor(now / 1000) + 300 }) }, now), /invalid_client/);
});

test('public registration rejects remote-key inputs, private keys, forged metadata and bounds credential issuance', async () => {
  const { registry } = setup({ ...ACCESS_POLICY, applications_per_ip_day: 20, credentials_global_day: 1 });
  const identity = await keys(), client = await register(registry, identity);
  for (const extra of [{ jwks_uri: 'http://127.0.0.1/secrets' }, { client_id: 'someone-else' }, { token_endpoint_auth_method: 'none' }]) {
    await assert.rejects(registry.handle({ action: 'register', ip, registration: { client_name: 'Test only', grant_types: ['client_credentials'],
      token_endpoint_auth_method: 'private_key_jwt', token_endpoint_auth_signing_alg: 'ES256', jwks: { keys: [identity.public_key] }, ...extra } }, now), /invalid_client_metadata/);
  }
  await registry.handle({ action: 'token', ip, form: await form(identity, client.client_id) }, now);
  await assert.rejects(registry.handle({ action: 'token', ip, form: await form(identity, client.client_id) }, now), /access_rate_limit/);
});

test('Fetch token eviction and expiry permit safe renewal without resetting the stable identity', async () => {
  const { registry } = setup({ ...ACCESS_POLICY, applications_per_ip_day: 20 });
  const pair = await crypto.subtle.generateKey({ name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['encrypt', 'decrypt']);
  const application = { name: 'Renewable Fetch fixture', use_case: 'Prepare bounded offers safely.', public_key: await crypto.subtle.exportKey('jwk', pair.publicKey),
    status_secret_sha256: hash('first-private-capability'), identity: { type: 'uagents', address: 'worker-verified-fixture-identity' } };
  const first = await registry.handle({ action: 'submit', ip, application, identity_verified: true }, now);
  for (let index = 0; index < 4; index++) await registry.handle({ action: 'submit', ip, identity_verified: true,
    application: { ...application, status_secret_sha256: hash('distinct-capability-' + index) } }, now);
  const status = await registry.handle({ action: 'status', ip, request_id: first.request_id, status_hash: application.status_secret_sha256 }, now);
  assert.equal(status.status, 'expired');
  assert.equal(status.credential, undefined);
  const renewed = await registry.handle({ action: 'submit', ip, application, identity_verified: true }, now);
  assert.equal(renewed.status, 'active');
  assert.notEqual(renewed.request_id, first.request_id);
  assert.equal(renewed.client_id, first.client_id);
  const later = now + 31 * 86400000;
  const expired = await registry.handle({ action: 'submit', ip, application, identity_verified: true }, later);
  assert.equal(expired.status, 'active');
  assert.equal(expired.client_id, first.client_id);
});
