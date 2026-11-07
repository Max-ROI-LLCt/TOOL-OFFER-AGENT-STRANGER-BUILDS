// Unattended OAuth client credentials (default), or existing Fetch identity proof.
// Private keys/capabilities/tokens stay in the applicant's 0600 file; stdout never prints them.
import { existsSync, readFileSync, writeFileSync, mkdirSync, lstatSync, renameSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { address, digest, hash, sign } from '../site/src/signing.mjs';
export async function runClient(argv, options = {}) {
const [action, filename, ...args] = argv;
if (!['register', 'token', 'status', 'fetch-enroll', 'call'].includes(action) || !filename) throw new Error('Usage: register <private-file> <name> | token <file> | status <file> | fetch-enroll <file> <existing-Fetch-private-key-file> | call <file> <tool> <JSON-arguments>');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const origin = options.origin || JSON.parse(readFileSync(resolve(root, 'machine/contract.json'))).origin;
const fetcher = options.fetcher || fetch;
const path = resolve(filename), encoder = new TextEncoder();
const encode = value => Buffer.from(typeof value === 'string' ? value : JSON.stringify(value)).toString('base64url');
const random = () => Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64url');
const privateFile = target => {
  if (!existsSync(target)) return;
  const stat = lstatSync(target);
  if (!stat.isFile() || stat.isSymbolicLink() || (stat.mode & 0o077)) throw new Error('Private identity files must be regular files with mode 0600; refuse unsafe permissions or symlinks.');
};
const save = () => {
  privateFile(path);
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = path + '.' + crypto.randomUUID() + '.tmp';
  writeFileSync(temporary, JSON.stringify(state, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
  renameSync(temporary, path);
};
const request = async (route, options = {}) => {
  const response = await fetcher(origin + route, { ...options, redirect: 'error', signal: AbortSignal.timeout(30000), headers: { 'Content-Type': 'application/json', ...options.headers } });
  let body;
  try { body = await response.json(); } catch { throw new Error('Invalid server response; no credentials printed.'); }
  if (!response.ok) throw new Error(`Machine authentication failed (${response.status}): ${/^[a-z_]{1,64}$/.test(body?.error || '') ? body.error : 'request_rejected'}`);
  return body;
};
privateFile(path);
let state;
try { state = existsSync(path) ? JSON.parse(readFileSync(path)) : null; }
catch { throw new Error('Invalid private state file; preserve it for recovery.'); }
if (state && state.origin !== origin) throw new Error('Existing identity file belongs to another origin; preserve it.');
async function assertion(endpoint) {
  const key = await crypto.subtle.importKey('jwk', state.private_key, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  const iat = Math.floor(Date.now() / 1000);
  const body = encode({ alg: 'ES256', typ: 'JWT' }) + '.' + encode({ iss: state.client_id, sub: state.client_id, aud: origin + endpoint,
    iat, exp: iat + 60, jti: crypto.randomUUID() });
  const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, key, encoder.encode(body));
  return body + '.' + Buffer.from(signature).toString('base64url');
}
async function token() {
  const result = await request('/oauth/token', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'client_credentials', client_id: state.client_id,
      client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer', client_assertion: await assertion('/oauth/token'),
      scope: 'tool_offer:machine', resource: origin + '/mcp' }).toString() });
  if (!/^toa_[A-Za-z0-9_-]{43}$/.test(result.access_token || '') || result.token_type !== 'Bearer' || !Number.isInteger(result.expires_in) || result.expires_in <= 0) throw new Error('Invalid credential response.');
  state.token = result.access_token; state.token_expires_at = Date.now() + result.expires_in * 1000; save();
  return { client_id: state.client_id, credential_saved_privately: true, expires_in: result.expires_in, human_approval_required: false };
}
if (action === 'register') {
  if (!state) {
    const keys = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
    state = { origin, type: 'oauth_es256', name: args[0] || 'Machine client', public_key: await crypto.subtle.exportKey('jwk', keys.publicKey), private_key: await crypto.subtle.exportKey('jwk', keys.privateKey) };
    save();
  }
  if (state.type !== 'oauth_es256') throw new Error('Use a separate private file for another identity type.');
  const result = await request('/oauth/register', { method: 'POST', body: JSON.stringify({ client_name: state.name,
    grant_types: ['client_credentials'], token_endpoint_auth_method: 'private_key_jwt', token_endpoint_auth_signing_alg: 'ES256', jwks: { keys: [state.public_key] } }) });
  state.client_id = result.client_id; save(); return result;
} else if (action === 'fetch-enroll') {
  if (state && state.type !== 'uagents') throw new Error('Use a separate private file for another identity type.');
  if (!args[0]) throw new Error('The existing Fetch private-key file is required.');
  privateFile(resolve(args[0]));
  const privateKey = readFileSync(resolve(args[0]), 'utf8').trim();
  if (!/^[a-f0-9]{64}$/i.test(privateKey)) throw new Error('Expected the caller’s existing hex Fetch private key file; its value is never sent.');
  if (!state) {
    const keys = await crypto.subtle.generateKey({ name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['encrypt', 'decrypt']);
    state = { origin, type: 'uagents', name: 'Fetch machine', public_key: await crypto.subtle.exportKey('jwk', keys.publicKey), private_key: await crypto.subtle.exportKey('jwk', keys.privateKey), request_secret: 'tar_' + random() }; save();
  }
  const fetchAddress = address(privateKey);
  if (state.fetch_address && state.fetch_address !== fetchAddress) throw new Error('The signing key belongs to a different Fetch identity. Preserve this identity file.');
  state.fetch_address = fetchAddress; save();
  const body = JSON.stringify({ schema: 'TOOL_OFFER_ACCESS_ENROLL_V1', name: state.name, use_case: 'Use bounded source-attributed offer preparation and read-only exports.',
    identity: { type: 'uagents', address: address(privateKey) }, public_key: state.public_key, status_secret_sha256: hash(state.request_secret), issued_at: Date.now(), nonce: crypto.randomUUID() });
  const result = await request('/api/access/applications', { method: 'POST', body: JSON.stringify({ body, signature: sign(digest('TOOL_OFFER_ACCESS_ENROLL_V1\n' + body), privateKey) }) });
  if (result.status !== 'active' || result.credential.label !== 'ToolOfferAccess/v1:' + result.request_id) throw new Error('Identity enrollment did not complete');
  const key = await crypto.subtle.importKey('jwk', state.private_key, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['decrypt']);
  const plaintext = await crypto.subtle.decrypt({ name: 'RSA-OAEP', label: encoder.encode(result.credential.label) }, key, Buffer.from(result.credential.ciphertext, 'base64url'));
  const delivery = JSON.parse(new TextDecoder().decode(plaintext));
  if (delivery.request_id !== result.request_id || !/^toa_[A-Za-z0-9_-]{43}$/.test(delivery.token)) throw new Error('Credential binding mismatch');
  state.token = delivery.token; state.request_id = result.request_id; state.client_id = result.client_id; state.token_expires_at = Date.parse(result.credential_expires_at); save();
  delete result.credential; return { ...result, credential_saved_privately: true };
} else {
  if (!state?.client_id) throw new Error('Register or enroll the machine identity first.');
  if (action === 'token') {
    if (state.type !== 'oauth_es256') throw new Error('Fetch identities use fetch-enroll to obtain an encrypted credential.');
    return token();
  } else if (action === 'status') {
    const result = state.type === 'oauth_es256' ? await request('/oauth/status', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ client_id: state.client_id,
      client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer', client_assertion: await assertion('/oauth/status') }).toString() }) :
      await request('/api/access/applications/' + state.request_id, { headers: { Authorization: 'AccessRequest ' + state.request_secret } });
    delete result.credential; return result;
  } else {
    if (state.type === 'oauth_es256' && (!state.token || state.token_expires_at < Date.now() + 10000)) await token();
    if (!state.token || !/^[a-z_]+$/.test(args[0] || '')) throw new Error('A credential and known tool name are required.');
    if (state.token_expires_at <= Date.now()) throw new Error('Credential expired; run fetch-enroll again using the same Fetch identity.');
    return request('/api/machine/' + args[0], { method: 'POST', headers: { Authorization: 'Bearer ' + state.token }, body: JSON.stringify(JSON.parse(args[1] || '{}')) });
  }
}
}
if (resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(await runClient(process.argv.slice(2)))); }
  catch (error) { console.error(error instanceof SyntaxError ? 'Invalid JSON arguments or private state.' : error.message); process.exitCode = 1; }
}
