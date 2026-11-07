// Existing gateway signer authorizes only domain-separated, short-lived owner requests.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { address, digest, sign } from '../site/src/signing.mjs';
const [action, request_id, days] = process.argv.slice(2);
if (!['list', 'revoke', 'audit'].includes(action)) throw new Error('Usage: list [cursor] | revoke <client-id> | audit <client-id>. Enrollment is automatic; no approvals.');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const config = JSON.parse(readFileSync(resolve(root, 'site/src/generated.json')));
const key = JSON.parse(readFileSync(resolve(root, 'data/machine-credentials/worker-secrets.json'))).TOOL_OFFER_GATEWAY_KEY;
if (address(key) !== config.gateway_address) throw new Error('Owner signer does not match the gateway identity');
const body = JSON.stringify({ schema: 'TOOL_OFFER_ACCESS_OWNER_V1', action, ...(action === 'list' ? { cursor: request_id || '' } : { request_id }),
  ...(days ? { credential_days: Number(days) } : {}), issued_at: Date.now(), nonce: crypto.randomUUID() });
const response = await fetch(config.contract.origin + '/api/access/owner', { method: 'POST', redirect: 'error', signal: AbortSignal.timeout(30000),
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body, signature: sign(digest('TOOL_OFFER_ACCESS_OWNER_V1\n' + body), key) }) });
const result = await response.json();
if (!response.ok) throw new Error(`Owner action rejected (${response.status}): ${result.error || 'request_rejected'}`);
console.log(JSON.stringify(result, null, 2));
