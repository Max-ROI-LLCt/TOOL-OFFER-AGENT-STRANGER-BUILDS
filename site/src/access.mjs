// Automatic identity-proven enrollment. Application possession alone never grants tool access.
import { hash } from './signing.mjs';
import { MachineError } from './gateway.mjs';
import { oauth } from './oauth.mjs';

export const ACCESS_POLICY = {
  application_days: 7, credential_days: 30, maximum_credential_days: 90,
  applications_per_ip_day: 5, applications_global_day: 100,
  requests_per_ip_minute: 30, requests_global_minute: 600, audit_days: 90,
  requests_global_day: 10000, credentials_global_day: 1000,
};
const day = 86400000;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const sha = /^[a-f0-9]{64}$/;
const b64 = bytes => btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
const random = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const error = (code, status = 400) => { throw new MachineError(code, status); };
const only = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).every(k => keys.includes(k));
const iso = value => new Date(value).toISOString();

export async function applicationKey(jwk) {
  if (!only(jwk, ['kty', 'n', 'e', 'alg', 'ext', 'key_ops']) || jwk.kty !== 'RSA' || jwk.e !== 'AQAB' ||
      typeof jwk.n !== 'string' || !/^[A-Za-z0-9_-]{342,683}$/.test(jwk.n) ||
      (jwk.alg !== undefined && jwk.alg !== 'RSA-OAEP-256')) error('rsa_oaep_public_key_required');
  try {
    const key = await crypto.subtle.importKey('jwk', { kty: 'RSA', n: jwk.n, e: jwk.e }, { name: 'RSA-OAEP', hash: 'SHA-256' }, true, ['encrypt']);
    if (![2048, 3072, 4096].includes(key.algorithm.modulusLength)) error('rsa_key_size_not_supported');
    return key;
  } catch { error('rsa_oaep_public_key_required'); }
}

export class AccessRegistry {
  constructor(storage, config, policy = ACCESS_POLICY) { this.store = storage; this.config = config; this.policy = policy; }
  count(key, limit, expires) {
    const value = this.store.get('access_limits', key) || { count: 0, expires };
    if (value.count >= limit) throw new MachineError('access_rate_limit', 429, { retry_after_seconds: Math.max(1, Math.ceil((expires - Date.now()) / 1000)) });
    this.store.put('access_limits', key, { count: value.count + 1, expires });
  }
  rate(ip, now, submit = false) {
    if (!sha.test(ip || '')) error('access_temporarily_unavailable', 503);
    this.store.transact(() => {
      const minute = Math.floor(now / 60000), utc = Math.floor(now / day);
      this.count(`ip:${ip}:minute:${minute}`, this.policy.requests_per_ip_minute, (minute + 1) * 60000);
      this.count(`global:minute:${minute}`, this.policy.requests_global_minute, (minute + 1) * 60000);
      this.count(`global:requests:${utc}`, this.policy.requests_global_day, (utc + 1) * day);
      if (submit) {
        this.count(`ip:${ip}:day:${utc}`, this.policy.applications_per_ip_day, (utc + 1) * day);
        this.count(`global:day:${utc}`, this.policy.applications_global_day, (utc + 1) * day);
      }
    });
  }
  issuance(now) {
    const utc = Math.floor(now / day);
    this.count(`global:credentials:${utc}`, this.policy.credentials_global_day, (utc + 1) * day);
  }
  rememberToken(identity, tokenHash, expires, now) {
    identity.tokens = [...(identity.tokens || []), tokenHash];
    while (identity.tokens.length > 4) {
      this.store.put('access_clients', identity.tokens.shift(), { revoked: true, expires: now + day });
    }
    this.store.put('access_identities', identity.id, identity);
    this.store.put('access_clients', tokenHash, { principal: identity.principal, identity_id: identity.id, revoked: false, expires });
  }
  audit(record, event, now) {
    const identityId = record.identity_id || record.id;
    const value = { application_id: record.id, identity_id: identityId, event, at: iso(now), principal: record.principal || null,
      actor: ['submitted', 'registered'].includes(event) ? 'applicant' : event === 'credential_issued' ? 'identity_proof_policy' : 'signed_operator', expires: now + this.policy.audit_days * day };
    this.store.put('access_audit', `${identityId}:${now}:${crypto.randomUUID()}`, value);
  }
  view(record, now) {
    const identity = this.store.get('access_identities', record.identity_id);
    const token = this.store.get('access_clients', record.token_hash);
    const status = identity?.revoked ? 'revoked' : !identity || identity.expires <= now || record.expires <= now ||
      record.credential_expires <= now || !token || token.revoked || token.expires <= now ? 'expired' : record.status;
    return { request_id: record.id, client_id: record.identity_id, status, status_url: `/api/access/applications/${record.id}`, submitted_at: record.submitted_at, status_expires_at: iso(record.expires),
      ...(record.decided_at ? { decided_at: record.decided_at } : {}),
      ...(status === 'active' ? { principal: record.principal, credential_expires_at: iso(record.credential_expires),
        credential: record.encrypted_credential } : {}),
      human_approval_required: false, release_id: this.config.release_id };
  }
  async handle(input, now = Date.now()) {
    const { action, ip } = input;
    if (action === 'attempt') { this.rate(ip, now, input.enrollment === true); return { allowed: true }; }
    if (['register', 'token', 'oauth_status'].includes(action)) return oauth(this, input, now);
    if (action === 'authenticate') {
      const value = sha.test(input.token_hash || '') && this.store.get('access_clients', input.token_hash);
      const identity = value?.identity_id && this.store.get('access_identities', value.identity_id);
      if (!value || value.revoked || value.expires <= now || !identity || identity.revoked || identity.expires <= now) error('invalid_credential', 401);
      return { principal: value.principal };
    }
    if (action === 'submit') {
      if (input.rate_checked !== true) this.rate(ip, now, true);
      const body = input.application;
      if (input.identity_verified !== true || !only(body, ['schema', 'name', 'use_case', 'public_key', 'status_secret_sha256', 'identity', 'issued_at', 'nonce']) ||
          typeof body.name !== 'string' || body.name.length < 2 || body.name.length > 100 ||
          typeof body.use_case !== 'string' || body.use_case.length < 10 || body.use_case.length > 1000 ||
          /toa_|sk-proj-|PRIVATE KEY|[\x00-\x1f]/.test(body.name + body.use_case) || !sha.test(body.status_secret_sha256 || '')) error('invalid_access_application');
      const encryptionKey = await applicationKey(body.public_key);
      const identityId = 'fetch_' + hash(body.identity.address).slice(0, 48);
      if (this.store.get('access_identities', identityId)?.revoked) error('identity_revoked', 403);
      const key = { kty: 'RSA', n: body.public_key.n, e: body.public_key.e };
      const fingerprint = hash(JSON.stringify([body.name, body.use_case, key, identityId]));
      const requestId = crypto.randomUUID(), token = 'toa_' + random();
      const label = `ToolOfferAccess/v1:${requestId}`;
      const plaintext = new TextEncoder().encode(JSON.stringify({ token, request_id: requestId }));
      const cipher = await crypto.subtle.encrypt({ name: 'RSA-OAEP', label: new TextEncoder().encode(label) }, encryptionKey, plaintext);
      return this.store.transact(() => {
        const identity = this.store.get('access_identities', identityId);
        if (identity?.revoked) error('identity_revoked', 403);
        const prior = this.store.get('access_requests', body.status_secret_sha256);
        if (prior && prior.expires > now) {
          if (prior.fingerprint !== fingerprint) error('application_replay_conflict', 409);
          if (this.view(prior, now).status === 'active') return this.view(prior, now);
        }
        this.issuance(now);
        const credentialExpires = now + this.policy.credential_days * day;
        const record = { id: requestId, status: 'active', name: body.name, use_case: body.use_case,
          public_key: key, status_hash: body.status_secret_sha256, fingerprint, identity_id: identityId,
          principal: identityId, credential_expires: credentialExpires, token_hash: hash(token),
          encrypted_credential: { algorithm: 'RSA-OAEP-256', label, ciphertext: b64(new Uint8Array(cipher)) },
          submitted_at: iso(now), decided_at: iso(now), expires: credentialExpires + day };
        this.rememberToken({ ...identity, id: identityId, name: body.name, principal: identityId, type: 'uagents', revoked: false,
          expires: credentialExpires + 90 * day }, record.token_hash, credentialExpires, now);
        this.store.put('access_requests', body.status_secret_sha256, record);
        this.store.put('access_ids', record.id, { status_hash: record.status_hash, expires: record.expires });
        this.audit(record, 'submitted', now);
        this.audit(record, 'credential_issued', now);
        return this.view(record, now);
      });
    }
    if (action === 'status') {
      if (input.rate_checked !== true) this.rate(ip, now);
      const record = sha.test(input.status_hash || '') && this.store.get('access_requests', input.status_hash);
      if (!record || record.id !== input.request_id || record.expires <= now) error('application_not_authorized_or_expired', 401);
      return this.view(record, now);
    }
    if (input.owner_verified !== true) error('owner_authorization_required', 401);
    if (!['list', 'revoke', 'audit'].includes(action)) error('invalid_owner_action');
    if (input.nonce) this.store.transact(() => {
      const replay = 'operator:' + input.nonce;
      if (this.store.get('access_assertions', replay)?.expires > now) error('operator_request_replayed', 409);
      this.store.put('access_assertions', replay, { expires: now + 120000 });
    });
    if (action === 'list') {
      const rows = this.store.scan('access_identities', input.cursor || '', 51);
      return { identities: rows.slice(0, 50).map(row => ({ client_id: row.value.id, name: row.value.name, revoked: row.value.revoked, type: row.value.type })),
        next_cursor: rows.length > 50 ? rows[49].key : null };
    }
    if (typeof input.request_id === 'string' && this.store.get('access_identities', input.request_id)) {
      const identity = this.store.get('access_identities', input.request_id);
      if (action === 'audit') return { events: this.store.scan('access_audit', identity.id + ':', 30).filter(row => row.key.startsWith(identity.id + ':')).map(row => row.value) };
      if (action !== 'revoke') error('invalid_owner_action');
      this.store.transact(() => {
        this.store.put('access_identities', identity.id, { ...identity, revoked: true, expires: now + 3650 * day });
        this.audit(identity, 'revoked', now);
      });
      return { client_id: identity.id, status: 'revoked' };
    }
    if (!uuid.test(input.request_id || '')) error('invalid_owner_action');
    const ref = this.store.get('access_ids', input.request_id);
    const record = ref && this.store.get('access_requests', ref.status_hash);
    if (!record) error('application_not_found', 404);
    if (action === 'audit') return { events: this.store.scan('access_audit', record.identity_id + ':', 20).filter(row => row.value.application_id === record.id).map(row => row.value) };
    return this.store.transact(() => {
      const current = this.store.get('access_requests', ref.status_hash);
      if (action === 'revoke' && current.status === 'active') {
        current.status = 'revoked';
        const identity = this.store.get('access_identities', current.identity_id);
        this.store.put('access_identities', current.identity_id, { ...identity, revoked: true, expires: now + 3650 * day });
        this.store.put('access_clients', current.token_hash, { principal: current.principal, revoked: true, expires: current.credential_expires });
        delete current.encrypted_credential;
      } else if (action === 'revoke' && current.status === 'revoked') {
        return { request_id: current.id, status: current.status, idempotent: true };
      } else error('application_state_conflict', 409);
      current.decided_at = iso(now);
      current.expires = Math.max(current.expires, (current.credential_expires || now) + day);
      this.store.put('access_requests', ref.status_hash, current);
      this.audit(current, current.status, now);
      return { request_id: current.id, status: current.status };
    });
  }
}
