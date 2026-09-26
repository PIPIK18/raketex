import { createHmac, timingSafeEqual } from 'node:crypto';

export function verifyUploadTicket(ticket, pathname, secret, now = Date.now()) {
  if (!secret || typeof ticket !== 'string') throw new Error('Upload authorization required.');
  const [encoded, signature, extra] = ticket.split('.');
  if (extra || !/^[a-f0-9]{64}$/.test(signature || '')) throw new Error('Invalid upload authorization.');
  const expected = createHmac('sha256', secret).update(encoded).digest();
  if (!timingSafeEqual(Buffer.from(signature, 'hex'), expected)) throw new Error('Invalid upload authorization.');
  const claim = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8'));
  if (claim.scope !== 'upload' || claim.pathname !== pathname || claim.exp * 1000 <= now ||
      !Number.isSafeInteger(claim.size) || claim.size <= 0 || claim.size > 500 * 1024 * 1024 ||
      !/^uploads\/[a-f0-9]{32}\.(png|jpe?g|gif|webp|mp4|webm|ogv)$/.test(pathname)) {
    throw new Error('Upload authorization expired or does not match this file.');
  }
  return claim;
}
