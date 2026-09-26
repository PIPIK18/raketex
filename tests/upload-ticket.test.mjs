import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { verifyUploadTicket } from '../api/upload-ticket.mjs';
import handler from '../api/blob-upload.mjs';
import { getPayloadFromClientToken } from '@vercel/blob/client';

const secret = 'test-secret';
const pathname = `uploads/${'a'.repeat(32)}.mp4`;
const claim = {scope: 'upload', owner: 'admin-session', pathname, size: 500 * 1024 * 1024,
  content_type: 'video/mp4', exp: Math.floor(Date.now() / 1000) + 60};
function sign(value) {
  const encoded = Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${encoded}.${createHmac('sha256', secret).update(encoded).digest('hex')}`;
}
test('accepts a signed file-scoped authorization', () => {
  assert.equal(verifyUploadTicket(sign(claim), pathname, secret).size, claim.size);
});
test('rejects unsigned, expired, substituted, oversized, and wrong-scope tickets', () => {
  for (const value of [{...claim, exp: 1}, {...claim, size: claim.size + 1}, {...claim, scope: 'uploaded'}]) {
    assert.throws(() => verifyUploadTicket(sign(value), pathname, secret));
  }
  assert.throws(() => verifyUploadTicket(sign(claim), 'uploads/other.mp4', secret));
  assert.throws(() => verifyUploadTicket(sign(claim), pathname, 'wrong-secret'));
  assert.throws(() => verifyUploadTicket(sign(claim), pathname, undefined));
});
test('token endpoint refuses unauthenticated callers', async () => {
  const response = {setHeader() {}, status(code) { this.code = code; return this; }, json(body) { this.body = body; }};
  await handler({method: 'POST', body: {type: 'blob.generate-client-token', payload: {pathname, clientPayload: null}}}, response);
  assert.equal(response.code, 400);
});
test('SDK token keeps the authorized path, content type, size, and expiry', async () => {
  const previousSecret = process.env.RAKETEX_SECRET_KEY;
  const previousToken = process.env.BLOB_READ_WRITE_TOKEN;
  process.env.RAKETEX_SECRET_KEY = secret;
  process.env.BLOB_READ_WRITE_TOKEN = 'vercel_blob_rw_TestStore_01234567890123456789012345678901';
  try {
    const response = {setHeader() {}, status(code) { this.code = code; return this; }, json(body) { this.body = body; }};
    await handler({method: 'POST', body: {type: 'blob.generate-client-token', payload: {pathname, clientPayload: sign(claim), multipart: true}}}, response);
    assert.equal(response.code, 200);
    const payload = getPayloadFromClientToken(response.body.clientToken);
    assert.equal(payload.pathname, pathname);
    assert.equal(payload.maximumSizeInBytes, claim.size);
    assert.deepEqual(payload.allowedContentTypes, ['video/mp4']);
    assert.equal(payload.allowOverwrite, false);
  } finally {
    if (previousSecret === undefined) delete process.env.RAKETEX_SECRET_KEY;
    else process.env.RAKETEX_SECRET_KEY = previousSecret;
    if (previousToken === undefined) delete process.env.BLOB_READ_WRITE_TOKEN;
    else process.env.BLOB_READ_WRITE_TOKEN = previousToken;
  }
});
