import { Readable } from 'node:stream';
import { get } from '@vercel/blob';

export default async function handler(request, response) {
  const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname)
    .replace(/^\/blob\//, '');

  if (!pathname || pathname.includes('..')) {
    return response.status(400).send('Invalid blob pathname.');
  }

  try {
    // The Vercel Blob SDK automatically uses the deployment's short-lived OIDC
    // credentials. No read-write token is exposed or manually forwarded here.
    const result = await get(pathname, { access: 'private' });
    if (!result || result.statusCode !== 200) {
      return response.status(404).send('File not found.');
    }

    response.setHeader('Content-Type', result.blob.contentType || 'application/octet-stream');
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Cache-Control', 'private, no-cache');

    if (request.method === 'HEAD') {
      return response.status(200).end();
    }

    Readable.fromWeb(result.stream).pipe(response);
  } catch (error) {
    console.error('Private media read failed:', error);
    return response.status(502).send('Could not load this file.');
  }
}
