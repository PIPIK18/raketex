import { handleUpload } from '@vercel/blob/client';
import { verifyUploadTicket } from './upload-ticket.mjs';

export default async function handler(request, response) {
  response.setHeader('Cache-Control', 'no-store');
  if (request.method !== 'POST') return response.status(405).json({ error: 'Use POST.' });
  try {
    const body = typeof request.body === 'string' ? JSON.parse(request.body) : request.body;
    const result = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname, ticket) => {
        // Flask issues this short-lived, file-scoped ticket only to a signed-in administrator.
        const claim = verifyUploadTicket(ticket, pathname, process.env.RAKETEX_SECRET_KEY);
        return {
          allowedContentTypes: [claim.content_type],
          maximumSizeInBytes: claim.size,
          validUntil: claim.exp * 1000,
          addRandomSuffix: false,
          allowOverwrite: false,
        };
      },
    });
    return response.status(200).json(result);
  } catch {
    return response.status(400).json({ error: 'Could not authorize this upload. Sign in again and retry.' });
  }
}
