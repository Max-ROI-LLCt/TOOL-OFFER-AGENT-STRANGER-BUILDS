// OAuth client_credentials/private_key_jwt for agents from any framework (ES256, RFC 7523).
import { hash } from './signing.mjs';
import { MachineError } from './gateway.mjs';
const fail = (code, status = 400) => { throw new MachineError(code, status); };
const b64 = bytes => btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
const decode = text => Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/')), c => c.charCodeAt(0));
const DAY = 86400000;
const own = (o, keys) => o && typeof o === 'object' && !Array.isArray(o) && Object.keys(o).every(k => keys.includes(k));
export async function publicSigningKey(jwk) {
  if (!own(jwk, ['kty', 'crv', 'x', 'y', 'alg', 'kid', 'use', 'key_ops', 'ext']) || jwk.kty !== 'EC' || jwk.crv !== 'P-256' ||
      !/^[A-Za-z0-9_-]{43}$/.test(jwk.x || '') || !/^[A-Za-z0-9_-]{43}$/.test(jwk.y || '') || (jwk.alg !== undefined && jwk.alg !== 'ES256')) fail('invalid_client_metadata');
  try { return await crypto.subtle.importKey('jwk', { kty: 'EC', crv: 'P-256', x: jwk.x, y: jwk.y }, { name: 'ECDSA', namedCurve: 'P-256' }, true, ['verify']); }
  catch { fail('invalid_client_metadata'); }
}
export async function oauth(registry, input, now) {
  const { store, config } = registry;
  if (input.rate_checked !== true) registry.rate(input.ip, now, input.action === 'register');
  if (input.action === 'register') {
    const value = input.registration;
    if (!own(value, ['client_name', 'grant_types', 'token_endpoint_auth_method', 'token_endpoint_auth_signing_alg', 'jwks', 'scope']) ||
        typeof value.client_name !== 'string' || value.client_name.length < 2 || value.client_name.length > 100 || /toa_|sk-proj-|PRIVATE KEY|[\x00-\x1f]/.test(value.client_name) ||
        value.token_endpoint_auth_method !== 'private_key_jwt' || value.token_endpoint_auth_signing_alg !== 'ES256' ||
        JSON.stringify(value.grant_types) !== '["client_credentials"]' || !own(value.jwks, ['keys']) || !Array.isArray(value.jwks?.keys) || value.jwks.keys.length !== 1 ||
        (value.scope !== undefined && value.scope !== 'tool_offer:machine')) fail('invalid_client_metadata');
    const key = value.jwks.keys[0]; await publicSigningKey(key);
    const publicKey = { crv: 'P-256', kty: 'EC', x: b64(decode(key.x)), y: b64(decode(key.y)) };
    const id = 'jwk_' + b64(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(publicKey)))));
    return store.transact(() => {
      const previous = store.get('access_identities', id);
      if (previous?.revoked) fail('identity_revoked', 403);
      if (!previous || previous.expires <= now) {
        store.put('access_identities', id, { id, name: value.client_name, principal: 'oauth_' + hash(id).slice(0, 48),
          type: 'oauth_es256', public_key: publicKey, tokens: [], revoked: false, expires: now + 90 * DAY });
        registry.audit({ id }, 'registered', now);
      }
      return { client_id: id, client_name: value.client_name, grant_types: ['client_credentials'], scope: 'tool_offer:machine',
        token_endpoint_auth_method: 'private_key_jwt', token_endpoint_auth_signing_alg: 'ES256',
        status: 'registered_proof_required', human_approval_required: false, token_endpoint: config.contract.origin + '/oauth/token' };
    });
  }
  const form = input.form;
  if (!own(form, ['grant_type', 'client_id', 'client_assertion_type', 'client_assertion', 'scope', 'resource'])) fail('invalid_request');
  if (input.action === 'token' && form.grant_type !== 'client_credentials') fail('unsupported_grant_type');
  if (input.action === 'token' && (form.scope !== 'tool_offer:machine' || form.resource !== config.contract.origin + '/mcp')) fail('invalid_target_or_scope');
  const client = typeof form.client_id === 'string' && store.get('access_identities', form.client_id);
  if (!client || client.type !== 'oauth_es256' || client.revoked || client.expires <= now ||
      form.client_assertion_type !== 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer' ||
      typeof form.client_assertion !== 'string' || form.client_assertion.length > 6000) fail('invalid_client', 401);
  let claim;
  try {
    const parts = form.client_assertion.split('.');
    if (parts.length !== 3 || parts.some(p => !/^[A-Za-z0-9_-]+$/.test(p))) throw new Error();
    const head = JSON.parse(new TextDecoder().decode(decode(parts[0])));
    claim = JSON.parse(new TextDecoder().decode(decode(parts[1])));
    if (!own(head, ['alg', 'typ', 'kid']) || head.alg !== 'ES256' || (head.typ !== undefined && head.typ !== 'JWT') ||
        !claim || typeof claim !== 'object' || claim.iss !== client.id || claim.sub !== client.id ||
        claim.aud !== config.contract.origin + (input.action === 'token' ? '/oauth/token' : '/oauth/status') ||
        !Number.isSafeInteger(claim.iat) || !Number.isSafeInteger(claim.exp) ||
        claim.iat * 1000 > now + 30000 || claim.iat * 1000 < now - 120000 || claim.exp * 1000 <= now ||
        claim.exp <= claim.iat || claim.exp > claim.iat + 120 ||
        (claim.nbf !== undefined && (!Number.isSafeInteger(claim.nbf) || claim.nbf * 1000 > now + 30000)) ||
        !/^[A-Za-z0-9_-]{16,128}$/.test(claim.jti || '')) throw new Error();
    const key = await publicSigningKey(client.public_key);
    if (!await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, decode(parts[2]), new TextEncoder().encode(parts[0] + '.' + parts[1]))) throw new Error();
  } catch { fail('invalid_client', 401); }
  const token = 'toa_' + b64(crypto.getRandomValues(new Uint8Array(32)));
  return store.transact(() => {
    const current = store.get('access_identities', client.id);
    if (!current || current.revoked || current.expires <= now) fail('invalid_client', 401);
    const replay = client.id + ':' + hash(claim.jti);
    if (store.get('access_assertions', replay)?.expires > now) fail('invalid_client', 401);
    store.put('access_assertions', replay, { expires: claim.exp * 1000 + 30000 });
    if (input.action === 'oauth_status') return { client_id: client.id, status: 'active', scope: 'tool_offer:machine', human_approval_required: false };
    registry.issuance(now);
    current.expires = now + 90 * DAY;
    registry.rememberToken(current, hash(token), now + 3600000, now);
    registry.audit({ id: current.id }, 'credential_issued', now);
    return { access_token: token, token_type: 'Bearer', expires_in: 3600, scope: 'tool_offer:machine' };
  });
}
