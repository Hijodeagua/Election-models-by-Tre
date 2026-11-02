// GET  /election/api/guesses  → everyone's guesses + lock state (plus an
//      x-guesses-client-keys header of hashed client addresses, for proxy checks)
// POST /election/api/guesses  → create an entry; returns its edit token once

import { LOCK_AT_ISO, isLocked, type GuessesPayload } from '@/app/lib/guesses-shared';
import {
  boardAllowedPicks,
  clientIp,
  clientKeyDiagnostics,
  getGuessStore,
  json,
  readJson,
} from '@/app/lib/guesses-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(req: Request): Promise<Response> {
  const diag = { 'x-guesses-client-keys': clientKeyDiagnostics(req) };
  const store = getGuessStore();
  if (!store) {
    const empty: GuessesPayload = {
      configured: false,
      lock_at: LOCK_AT_ISO,
      locked: isLocked(),
      entries: [],
    };
    return json(empty, 200, diag);
  }
  return json(await store.list(), 200, diag);
}

export async function POST(req: Request): Promise<Response> {
  const store = getGuessStore();
  if (!store) return json({ error: 'Guess storage is not configured' }, 503);
  const body = await readJson(req);
  if (body === undefined) return json({ error: 'body must be JSON' }, 400);
  const result = await store.submit(body, clientIp(req), boardAllowedPicks());
  return json(result.body, result.status);
}
