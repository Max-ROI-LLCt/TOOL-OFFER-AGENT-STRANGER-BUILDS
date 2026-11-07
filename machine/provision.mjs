import { mkdirSync, writeFileSync, existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { randomBytes } from 'node:crypto';
import { newKey, address, hash } from '../site/src/signing.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const directory = resolve(root, 'data/machine-credentials');
if ([resolve(directory, 'worker-secrets.json'), resolve(directory, 'owner-client.json'), resolve(root, 'machine/gateway.json')].some(existsSync)) throw new Error('Existing dedicated credentials preserved; rotate deliberately instead.');
const contract = JSON.parse(readFileSync(resolve(root, 'machine/contract.json'), 'utf8'));
const key = newKey();
const token = 'toa_' + randomBytes(32).toString('base64url');
mkdirSync(directory, { recursive: true, mode: 0o700 });
writeFileSync(resolve(directory, 'worker-secrets.json'), JSON.stringify({
  TOOL_OFFER_GATEWAY_KEY: key,
  TOOL_OFFER_MACHINE_CLIENTS: JSON.stringify({ [hash(token)]: 'owner-machine' }),
}, null, 2), { mode: 0o600, flag: 'wx' });
writeFileSync(resolve(directory, 'owner-client.json'), JSON.stringify({
  mcpServers: { tool_offer: { url: contract.origin + '/mcp', headers: { Authorization: 'Bearer ' + token } } },
}, null, 2), { mode: 0o600, flag: 'wx' });
writeFileSync(resolve(root, 'machine/gateway.json'), JSON.stringify({ gateway_address: address(key), purpose: 'Tool Offer machine message authorization only; not an OCI, FAHCE, wallet or attestation key.' }, null, 2) + '\n', { flag: 'wx' });
console.log('Dedicated Tool Offer credentials created in data/machine-credentials (private). No existing product keys accessed.');
