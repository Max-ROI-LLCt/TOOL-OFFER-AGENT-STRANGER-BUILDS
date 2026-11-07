// Offline owner tool. Never prints tokens or sends email. Never runs Wrangler.
import { randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { hash } from '../site/src/signing.mjs';

const [action, registryPath, principal, expiryOrHash, deliveryPath, approval] = process.argv.slice(2);
if (!['issue', 'revoke'].includes(action) || !registryPath || !/^[a-z0-9_-]{1,64}$/.test(principal || '')) throw new Error('Usage: issue <private-registry.json> <principal> <ISO-expiry> <private-delivery.json> --owner-approved | revoke <registry> <principal> <token-sha256>');
const path = resolve(registryPath);
// Begin with the complete current registry; do not replace existing clients.
const registry = JSON.parse(readFileSync(path, 'utf8'));
if (action === 'issue') {
  if (approval !== '--owner-approved' || !deliveryPath || existsSync(resolve(deliveryPath))) throw new Error('Owner approval and a new confidential delivery file are required.');
  const expiry = Date.parse(expiryOrHash);
  if (!Number.isFinite(expiry) || expiry <= Date.now() || expiry > Date.now() + 90 * 86400000) throw new Error('Expiry must be in the next 90 days.');
  const token = 'toa_' + randomBytes(32).toString('base64url');
  const tokenHash = hash(token);
  writeFileSync(resolve(deliveryPath), JSON.stringify({ principal, expires_at: new Date(expiry).toISOString(), token }, null, 2), { mode: 0o600, flag: 'wx' });
  registry[tokenHash] = { principal, expires_at: new Date(expiry).toISOString(), revoked: false };
} else {
  const record = registry[expiryOrHash];
  if (!/^[a-f0-9]{64}$/.test(expiryOrHash || '') || (typeof record === 'string' ? record : record?.principal) !== principal) throw new Error('Token hash must belong to this principal.');
  delete registry[expiryOrHash];
}
writeFileSync(path, JSON.stringify(registry, null, 2) + '\n', { mode: 0o600 });
console.log('Private registry prepared. Owner must review and install TOOL_OFFER_MACHINE_CLIENTS; no live credential changed and no email sent.');
