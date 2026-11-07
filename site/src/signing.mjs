import { secp256k1 } from '@noble/curves/secp256k1.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { bech32, base64, hex } from '@scure/base';

const encoder = new TextEncoder();
export const digest = (text) => sha256(encoder.encode(text));
export const hash = (text) => hex.encode(digest(text));
export const newKey = () => hex.encode(secp256k1.utils.randomSecretKey());
export const address = (key) => bech32.encode('agent', bech32.toWords(secp256k1.getPublicKey(hex.decode(key))), 200);
export const sign = (bytes, key) => bech32.encode('sig', bech32.toWords(secp256k1.sign(bytes, hex.decode(key), { prehash: false })), 200);
export function verify(bytes, signature, sender) {
  try {
    const publicKey = bech32.decode(sender, 200);
    const signed = bech32.decode(signature, 200);
    return publicKey.prefix === 'agent' && signed.prefix === 'sig' && secp256k1.verify(
      bech32.fromWords(signed.words), bytes, bech32.fromWords(publicKey.words), { prehash: false, lowS: false },
    );
  } catch { return false; }
}

export function envelopeDigest(envelope) {
  const pieces = [envelope.sender, envelope.target, envelope.session, envelope.schema_digest, envelope.payload || ''].map((part) => encoder.encode(part));
  for (const field of ['expires', 'nonce']) {
    if (envelope[field] !== undefined && envelope[field] !== null) {
      const bytes = new Uint8Array(8);
      new DataView(bytes.buffer).setBigUint64(0, BigInt(envelope[field]));
      pieces.push(bytes);
    }
  }
  const joined = new Uint8Array(pieces.reduce((total, piece) => total + piece.length, 0));
  let offset = 0;
  for (const piece of pieces) { joined.set(piece, offset); offset += piece.length; }
  return sha256(joined);
}

export function makeRequest(config, gatewayKey, data, transportKey = newKey()) {
  if (address(gatewayKey) !== config.gateway_address) throw new Error('gateway_identity_mismatch');
  const sender = address(transportKey);
  const body = JSON.stringify({ ...data, release_id: config.release_id, issued_at: Math.floor(Date.now() / 1000), transport_sender: sender });
  const envelope = {
    version: 1, sender, target: config.contract.agent_address, session: crypto.randomUUID(),
    schema_digest: config.request_digest,
    payload: base64.encode(encoder.encode(JSON.stringify({ body, authorization: sign(digest(body), gatewayKey) }))),
    expires: Math.floor(Date.now() / 1000) + 110,
  };
  envelope.signature = sign(envelopeDigest(envelope), transportKey);
  return { envelope, body: JSON.parse(body) };
}

export function readResponse(config, request, envelope) {
  if (envelope.version !== 1 || envelope.sender !== config.contract.agent_address || envelope.target !== request.envelope.sender ||
      envelope.session !== request.envelope.session || envelope.schema_digest !== config.response_digest) throw new Error('invalid_response_envelope');
  const response = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(base64.decode(envelope.payload)));
  if (!verify(digest(response.body), response.signature, config.contract.agent_address)) throw new Error('invalid_agent_signature');
  const result = JSON.parse(response.body);
  for (const field of ['request_id', 'session_id', 'transport_sender']) {
    if (result[field] !== request.body[field]) throw new Error('response_binding_mismatch');
  }
  if (result.release_id !== config.release_id) throw new Error('release_mismatch');
  return { ...result, proof: { agent_address: config.contract.agent_address, body: response.body, signature: response.signature } };
}

export async function exchange(config, gatewayKey, data, fetcher = fetch) {
  const request = makeRequest(config, gatewayKey, data);
  const response = await fetcher('https://agentverse.ai/v1/hosting/submit', {
    method: 'POST', redirect: 'manual', signal: AbortSignal.timeout(100000),
    headers: { 'Content-Type': 'application/json', 'x-uagents-connection': 'sync' },
    body: JSON.stringify(request.envelope),
  });
  if (!response.ok) throw new Error('agent_transport_unavailable');
  const text = await response.text();
  if (text.length > 250000) throw new Error('agent_response_too_large');
  return readResponse(config, request, JSON.parse(text));
}
