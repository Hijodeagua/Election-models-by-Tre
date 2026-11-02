// PUT /election/api/guesses/:id  (Authorization: Bearer <edit token>)
// Replaces the entry's guesses and, optionally, its display name.

import {
  bearerToken,
  boardAllowedPicks,
  clientIp,
  getGuessStore,
  json,
  readJson,
} from '@/app/lib/guesses-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function PUT(
  req: Request,
  { params }: { params: { id: string } },
): Promise<Response> {
  const store = getGuessStore();
  if (!store) return json({ error: 'Guess storage is not configured' }, 503);
  const id = params.id;
  if (!/^[a-f0-9]{16}$/.test(id)) return json({ error: 'No such entry' }, 404);
  const body = await readJson(req);
  if (body === undefined) return json({ error: 'body must be JSON' }, 400);
  const result = await store.update(id, bearerToken(req), body, clientIp(req), boardAllowedPicks());
  return json(result.body, result.status);
}
