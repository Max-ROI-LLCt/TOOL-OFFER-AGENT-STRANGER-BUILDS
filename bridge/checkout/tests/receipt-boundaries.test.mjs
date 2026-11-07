import test from 'node:test';
import assert from 'node:assert/strict';
import { verifyReceiptEvidence } from '../attestation-verifier.mjs';

test('synthetic missing attestation is never promoted from gateway success', async () => {
  await assert.rejects(verifyReceiptEvidence({ gatewaySuccess: true }, { policies: [] }, []), /HASH_ONLY_OR_MISSING_PROOF/);
});

test('synthetic unpinned proof cannot become a verified receipt', async () => {
  await assert.rejects(verifyReceiptEvidence({ attestation: { policy_sha256: '0'.repeat(64) } }, { policies: [] }, []), /PINNED_PUBLISHED_POLICY_REQUIRED/);
});
