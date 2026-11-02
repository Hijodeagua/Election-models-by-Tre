// Phase 5 — public guesses: submit, edit, lock, rate limit, and the HTTP
// handlers on top of an in-memory Redis.

import { beforeEach, describe, expect, it } from 'vitest';
import {
  LOCK_AT_MS,
  allowedPicksFor,
  isLocked,
  isReservedName,
  modelGuess,
  normalizeName,
  validateSubmission,
  type AllowedPicks,
} from '@/app/lib/guesses-shared';
import { MemoryRedis, createGuessStore, type GuessStore } from '@/app/lib/guesses-store';
import { findUpstashEnv, setGuessStoreForTests, storageEnvNames } from '@/app/lib/guesses-server';
import { GET, POST } from '@/app/api/guesses/route';
import { DELETE, PUT } from '@/app/api/guesses/[id]/route';

const ALLOWED: AllowedPicks = {
  ME: ['D', 'R'],
  TX: ['D', 'R'],
  NE: ['D', 'R', 'I'],
};

// A clock the tests can move. Default: an hour before the lock.
let nowMs = LOCK_AT_MS - 3_600_000;
const clock = () => nowMs;

function makeStore(opts: { max?: number } = {}): GuessStore {
  return createGuessStore(new MemoryRedis(), {
    now: clock,
    rateLimit: { max: opts.max ?? 10, windowSec: 600 },
  });
}

const GOOD = { name: 'Pat', guesses: { ME: { pick: 'D', margin: 3 }, TX: { pick: 'R', margin: null } } };

beforeEach(() => {
  nowMs = LOCK_AT_MS - 3_600_000;
});

describe('validation', () => {
  it('normalises names and rejects empty or long ones', () => {
    expect(normalizeName('  Tre   Watterson ')).toBe('Tre Watterson');
    expect(normalizeName('a\u0000b')).toBe('ab');
    expect(normalizeName('')).toBeNull();
    expect(normalizeName('x'.repeat(31))).toBeNull();
    expect(normalizeName('x'.repeat(30))).toHaveLength(30);
    expect(normalizeName(42)).toBeNull();
  });

  it('accepts a good submission and rounds margins to one decimal', () => {
    const v = validateSubmission({ name: 'Pat', guesses: { ME: { pick: 'D', margin: 3.26 } } }, ALLOWED);
    expect(v.ok).toBe(true);
    if (v.ok) expect(v.guesses.ME).toEqual({ pick: 'D', margin: 3.3 });
  });

  it('rejects unknown races, disallowed independents, bad picks and margins', () => {
    const bad = (guesses: unknown) => {
      const v = validateSubmission({ name: 'Pat', guesses }, ALLOWED);
      expect(v.ok).toBe(false);
      return v.ok ? '' : v.error;
    };
    expect(bad({ ZZ: { pick: 'D' } })).toMatch(/not a race/);
    expect(bad({ ME: { pick: 'I' } })).toMatch(/no independent/);
    expect(bad({ ME: { pick: 'X' } })).toMatch(/D, R or I/);
    expect(bad({ ME: { pick: 'D', margin: 101 } })).toMatch(/between 0 and 100/);
    expect(bad({ ME: { pick: 'D', margin: -1 } })).toMatch(/between 0 and 100/);
    expect(bad({ ME: { pick: 'D', margin: 'lots' } })).toMatch(/must be a number/);
    expect(bad({})).toMatch(/at least one race/);
    expect(bad({ ME: null, TX: { pick: null } })).toMatch(/at least one race/);
  });

  it('allows an independent only where one is on the ballot', () => {
    const allowed = allowedPicksFor([
      { abbr: 'ME', ind_candidate: null },
      { abbr: 'NE', ind_candidate: 'Dan Osborn' },
    ]);
    expect(allowed).toEqual({ ME: ['D', 'R'], NE: ['D', 'R', 'I'] });
    const v = validateSubmission({ name: 'x', guesses: { NE: { pick: 'I', margin: 2 } } }, allowed);
    expect(v.ok).toBe(true);
  });

  it('derives the model call, treating the independent as the positive side where configured', () => {
    expect(modelGuess({ ind_candidate: null, model: null })).toBeNull();
    expect(
      modelGuess({
        ind_candidate: null,
        model: { dem_candidate: 'A', rep_candidate: 'B', poll_margin: null, median_margin: -4.26, dem_win_prob: 0.3 },
      }),
    ).toEqual({ pick: 'R', margin: 4.3 });
    expect(
      modelGuess({
        ind_candidate: 'Dan Osborn',
        model: { dem_candidate: 'Dan Osborn', rep_candidate: 'B', poll_margin: null, median_margin: 1.2, dem_win_prob: 0.55 },
      }),
    ).toEqual({ pick: 'I', margin: 1.2 });
    expect(
      modelGuess({
        ind_candidate: null,
        model: { dem_candidate: 'A', rep_candidate: 'B', poll_margin: null, median_margin: 0.04, dem_win_prob: 0.5 },
      }),
    ).toBeNull();
  });
});

describe('submit', () => {
  it('stores the entry, returns a token once, and lists it without the token', async () => {
    const store = makeStore();
    const res = await store.submit(GOOD, '1.1.1.1', ALLOWED);
    expect(res.status).toBe(201);
    const body = res.body as { id: string; token: string; entry: { name: string } };
    expect(body.id).toMatch(/^[a-f0-9]{16}$/);
    expect(body.token).toMatch(/^[a-f0-9]{48}$/);
    expect(body.entry.name).toBe('Pat');

    const list = await store.list();
    expect(list.locked).toBe(false);
    expect(list.entries).toHaveLength(1);
    expect(list.entries[0]).not.toHaveProperty('token_hash');
    expect(list.entries[0].guesses).toEqual({ ME: { pick: 'D', margin: 3 }, TX: { pick: 'R', margin: null } });
  });

  it('rejects a second claim on the same name, case-insensitively', async () => {
    const store = makeStore();
    expect((await store.submit(GOOD, '1.1.1.1', ALLOWED)).status).toBe(201);
    const dup = await store.submit({ ...GOOD, name: 'pat' }, '2.2.2.2', ALLOWED);
    expect(dup.status).toBe(409);
    expect((await store.list()).entries).toHaveLength(1);
  });

  it('returns 400 for invalid input and stores nothing', async () => {
    const store = makeStore();
    expect((await store.submit({ name: '', guesses: GOOD.guesses }, 'ip', ALLOWED)).status).toBe(400);
    expect((await store.submit({ name: 'x'.repeat(31), guesses: GOOD.guesses }, 'ip', ALLOWED)).status).toBe(400);
    expect((await store.submit({ name: 'ok', guesses: { ME: { pick: 'I' } } }, 'ip', ALLOWED)).status).toBe(400);
    expect((await store.list()).entries).toHaveLength(0);
  });

  it('rate-limits writes per IP', async () => {
    const store = makeStore({ max: 3 });
    for (let i = 0; i < 3; i++) {
      expect((await store.submit({ ...GOOD, name: `p${i}` }, '9.9.9.9', ALLOWED)).status).toBe(201);
    }
    expect((await store.submit({ ...GOOD, name: 'p3' }, '9.9.9.9', ALLOWED)).status).toBe(429);
    // A different connection is unaffected.
    expect((await store.submit({ ...GOOD, name: 'p4' }, '8.8.8.8', ALLOWED)).status).toBe(201);
    // The window rolls over.
    nowMs += 600_000;
    expect((await store.submit({ ...GOOD, name: 'p5' }, '9.9.9.9', ALLOWED)).status).toBe(201);
  });
});

describe('edit', () => {
  async function seeded() {
    const store = makeStore();
    const res = await store.submit(GOOD, '1.1.1.1', ALLOWED);
    const { id, token } = res.body as { id: string; token: string };
    return { store, id, token };
  }

  it('replaces guesses with the right token and bumps updated_at', async () => {
    const { store, id, token } = await seeded();
    nowMs += 60_000;
    const res = await store.update(id, token, { guesses: { ME: { pick: 'R', margin: 1 } } }, '1.1.1.1', ALLOWED);
    expect(res.status).toBe(200);
    const [entry] = (await store.list()).entries;
    expect(entry.guesses).toEqual({ ME: { pick: 'R', margin: 1 } });
    expect(entry.name).toBe('Pat');
    expect(entry.updated_at > entry.created_at).toBe(true);
  });

  it('refuses a wrong or missing token and an unknown id', async () => {
    const { store, id } = await seeded();
    expect((await store.update(id, 'nope', { guesses: GOOD.guesses }, 'ip', ALLOWED)).status).toBe(403);
    expect((await store.update(id, null, { guesses: GOOD.guesses }, 'ip', ALLOWED)).status).toBe(403);
    expect((await store.update('0'.repeat(16), 'x', { guesses: GOOD.guesses }, 'ip', ALLOWED)).status).toBe(404);
  });

  it('renames, freeing the old name and refusing a taken one', async () => {
    const { store, id, token } = await seeded();
    expect((await store.submit({ ...GOOD, name: 'Sam' }, '2.2.2.2', ALLOWED)).status).toBe(201);
    expect(
      (await store.update(id, token, { name: 'sam', guesses: GOOD.guesses }, '1.1.1.1', ALLOWED)).status,
    ).toBe(409);
    expect(
      (await store.update(id, token, { name: 'Pat W', guesses: GOOD.guesses }, '1.1.1.1', ALLOWED)).status,
    ).toBe(200);
    // The old name is free again.
    expect((await store.submit({ ...GOOD, name: 'Pat' }, '3.3.3.3', ALLOWED)).status).toBe(201);
    expect((await store.list()).entries.map((e) => e.name).sort()).toEqual(['Pat', 'Pat W', 'Sam']);
  });

  it('validates the edited guesses', async () => {
    const { store, id, token } = await seeded();
    expect((await store.update(id, token, { guesses: {} }, 'ip', ALLOWED)).status).toBe(400);
    expect((await store.update(id, token, { guesses: { ME: { pick: 'I' } } }, 'ip', ALLOWED)).status).toBe(400);
  });
});

describe('reserved names', () => {
  it('reserves hijodeagua, tre and model, case-insensitively', () => {
    for (const n of ['hijodeagua', 'Hijodeagua', 'HIJODEAGUA', 'tre', 'Tre', 'TRE', 'model', 'Model']) {
      expect(isReservedName(n)).toBe(true);
    }
    for (const n of ['Tre W', 'Treasure', 'models', 'hijo']) expect(isReservedName(n)).toBe(false);
  });

  it('returns 409 for a reserved name on submit and stores nothing', async () => {
    const store = makeStore();
    for (const name of ['Hijodeagua', 'tre', '  MODEL  ']) {
      const res = await store.submit({ ...GOOD, name }, 'ip', ALLOWED);
      expect(res.status).toBe(409);
      expect((res.body as { error: string }).error).toMatch(/reserved/);
    }
    expect((await store.list()).entries).toHaveLength(0);
  });

  it('returns 409 when renaming to a reserved name', async () => {
    const store = makeStore();
    const res = await store.submit({ ...GOOD, name: 'Sam' }, 'ip', ALLOWED);
    const { id, token } = res.body as { id: string; token: string };
    const rename = await store.update(id, token, { name: 'Model', guesses: GOOD.guesses }, 'ip', ALLOWED);
    expect(rename.status).toBe(409);
    expect((await store.list()).entries[0].name).toBe('Sam');
  });
});

describe('admin hide', () => {
  it('removes the entry and frees its name', async () => {
    const store = makeStore();
    const res = await store.submit({ ...GOOD, name: 'Spammer' }, 'ip', ALLOWED);
    const { id } = res.body as { id: string };
    expect((await store.remove(id)).status).toBe(200);
    expect((await store.list()).entries).toHaveLength(0);
    expect((await store.remove(id)).status).toBe(404);
    // The name can be claimed again.
    expect((await store.submit({ ...GOOD, name: 'spammer' }, 'ip2', ALLOWED)).status).toBe(201);
  });

  it('does not free a name that now belongs to someone else', async () => {
    const store = makeStore();
    const a = (await store.submit({ ...GOOD, name: 'Alex' }, 'ip', ALLOWED)).body as { id: string; token: string };
    // Alex renames, then someone else takes "Alex"; hiding the renamed entry
    // must not release the other person's name.
    expect((await store.update(a.id, a.token, { name: 'Alexis', guesses: GOOD.guesses }, 'ip', ALLOWED)).status).toBe(200);
    expect((await store.submit({ ...GOOD, name: 'Alex' }, 'ip2', ALLOWED)).status).toBe(201);
    expect((await store.remove(a.id)).status).toBe(200);
    expect((await store.submit({ ...GOOD, name: 'alex' }, 'ip3', ALLOWED)).status).toBe(409);
    expect((await store.submit({ ...GOOD, name: 'Alexis' }, 'ip3', ALLOWED)).status).toBe(201);
  });
});

describe('lock', () => {
  it('flips at exactly 2026-11-03T23:00:00Z (6:00 PM ET)', () => {
    expect(LOCK_AT_MS).toBe(Date.UTC(2026, 10, 3, 23, 0, 0));
    expect(isLocked(LOCK_AT_MS - 1)).toBe(false);
    expect(isLocked(LOCK_AT_MS)).toBe(true);
  });

  it('refuses submits and edits after the lock but still lists', async () => {
    const store = makeStore();
    const res = await store.submit(GOOD, 'ip', ALLOWED);
    const { id, token } = res.body as { id: string; token: string };

    nowMs = LOCK_AT_MS - 1;
    expect((await store.update(id, token, { guesses: GOOD.guesses }, 'ip', ALLOWED)).status).toBe(200);

    nowMs = LOCK_AT_MS;
    expect((await store.submit({ ...GOOD, name: 'late' }, 'ip', ALLOWED)).status).toBe(423);
    expect((await store.update(id, token, { guesses: { ME: { pick: 'R' } } }, 'ip', ALLOWED)).status).toBe(423);

    const list = await store.list();
    expect(list.locked).toBe(true);
    expect(list.entries).toHaveLength(1);
    expect(list.entries[0].guesses).toEqual(GOOD.guesses); // unchanged
  });
});

describe('HTTP handlers', () => {
  const url = 'http://localhost/election/api/guesses';
  const jsonReq = (method: string, body: unknown, headers: Record<string, string> = {}) =>
    new Request(url, {
      method,
      headers: { 'content-type': 'application/json', 'x-forwarded-for': '5.5.5.5, 10.0.0.1', ...headers },
      body: JSON.stringify(body),
    });

  beforeEach(() => {
    setGuessStoreForTests(makeStore());
  });

  it('GET returns the payload with no-store caching', async () => {
    const res = await GET(new Request(url));
    expect(res.status).toBe(200);
    expect(res.headers.get('cache-control')).toBe('no-store');
    const body = await res.json();
    expect(body).toMatchObject({ configured: true, locked: false, entries: [] });
    expect(body.lock_at).toBe('2026-11-03T23:00:00.000Z');
  });

  it('POST creates, PUT edits with the bearer token, GET shows the result', async () => {
    // The real board has 17 races; use two that exist on it.
    const submission = { name: 'Route Tester', guesses: { ME: { pick: 'D', margin: 2 }, TX: { pick: 'R', margin: 5 } } };
    const created = await POST(jsonReq('POST', submission));
    expect(created.status).toBe(201);
    const { id, token } = (await created.json()) as { id: string; token: string };

    const denied = await PUT(jsonReq('PUT', { guesses: { ME: { pick: 'R' } } }), { params: { id } });
    expect(denied.status).toBe(403);

    const edited = await PUT(
      jsonReq('PUT', { guesses: { ME: { pick: 'R', margin: 1 } } }, { authorization: `Bearer ${token}` }),
      { params: { id } },
    );
    expect(edited.status).toBe(200);

    const list = (await (await GET(new Request(url))).json()) as { entries: { name: string; guesses: unknown }[] };
    expect(list.entries).toHaveLength(1);
    expect(list.entries[0].name).toBe('Route Tester');
    expect(list.entries[0].guesses).toEqual({ ME: { pick: 'R', margin: 1 } });
  });

  it('rejects malformed JSON, bad ids and a missing store', async () => {
    const bad = await POST(new Request(url, { method: 'POST', body: '{not json' }));
    expect(bad.status).toBe(400);
    const badId = await PUT(jsonReq('PUT', { guesses: {} }), { params: { id: '../x' } });
    expect(badId.status).toBe(404);

    setGuessStoreForTests(null);
    const get = await GET(new Request(url));
    expect(((await get.json()) as { configured: boolean }).configured).toBe(false);
    expect((await POST(jsonReq('POST', GOOD))).status).toBe(503);
  });

  it('DELETE requires ADMIN_TOKEN, then hides the entry and frees its name', async () => {
    const created = await POST(jsonReq('POST', { name: 'Hide Me', guesses: { ME: { pick: 'D', margin: 1 } } }));
    const { id, token } = (await created.json()) as { id: string; token: string };
    const del = (auth?: string) =>
      DELETE(
        new Request(`${url}/${id}`, { method: 'DELETE', headers: auth ? { authorization: `Bearer ${auth}` } : {} }),
        { params: { id } },
      );

    const prev = process.env.ADMIN_TOKEN;
    try {
      delete process.env.ADMIN_TOKEN;
      expect((await del('anything')).status).toBe(503);

      process.env.ADMIN_TOKEN = 'admin-secret_123';
      expect((await del()).status).toBe(403);
      expect((await del(token)).status).toBe(403); // an edit token is not an admin token
      expect((await del('wrong')).status).toBe(403);

      const ok = await del('admin-secret_123');
      expect(ok.status).toBe(200);
      expect(await ok.json()).toEqual({ id, removed: true });

      const list = (await (await GET(new Request(url))).json()) as { entries: unknown[] };
      expect(list.entries).toHaveLength(0);
      expect((await del('admin-secret_123')).status).toBe(404);
      // Name is free again.
      expect((await POST(jsonReq('POST', { name: 'hide me', guesses: { ME: { pick: 'R' } } }))).status).toBe(201);
    } finally {
      if (prev === undefined) delete process.env.ADMIN_TOKEN;
      else process.env.ADMIN_TOKEN = prev;
    }
  });

  it('GET reports hashed client keys, never the raw address', async () => {
    const res = await GET(new Request(url, { headers: { 'x-forwarded-for': '203.0.113.7, 10.0.0.1' } }));
    const keys = res.headers.get('x-guesses-client-keys') ?? '';
    expect(keys).toMatch(/^used=[a-f0-9]{10};xff=[a-f0-9]{10};xvff=-;xri=-$/);
    expect(keys).not.toContain('203.0.113.7');
    const other = await GET(new Request(url, { headers: { 'x-forwarded-for': '198.51.100.9' } }));
    expect(other.headers.get('x-guesses-client-keys')).not.toBe(keys);
  });

  it('enforces the lock through the handlers', async () => {
    nowMs = LOCK_AT_MS + 1;
    const res = await POST(jsonReq('POST', GOOD));
    expect(res.status).toBe(423);
  });
});

describe('storage env lookup', () => {
  it('prefers the exact names', () => {
    const env = {
      UPSTASH_REDIS_REST_URL: 'https://a', UPSTASH_REDIS_REST_TOKEN: 'ta',
      KV_REST_API_URL: 'https://b', KV_REST_API_TOKEN: 'tb',
    };
    expect(findUpstashEnv(env)).toEqual({ url: 'https://a', token: 'ta', source: 'UPSTASH_REDIS_REST_URL' });
    expect(findUpstashEnv({ KV_REST_API_URL: 'https://b', KV_REST_API_TOKEN: 'tb' })?.url).toBe('https://b');
  });

  it('accepts a custom prefix and never a read-only token', () => {
    const env = {
      STORAGE_KV_REST_API_URL: 'https://p',
      STORAGE_KV_REST_API_READ_ONLY_TOKEN: 'ro',
      STORAGE_KV_REST_API_TOKEN: 'rw',
      STORAGE_REDIS_URL: 'rediss://x',
    };
    expect(findUpstashEnv(env)).toEqual({ url: 'https://p', token: 'rw', source: 'STORAGE_KV_REST_API_URL' });
    expect(findUpstashEnv({ STORAGE_KV_REST_API_URL: 'https://p', STORAGE_KV_REST_API_READ_ONLY_TOKEN: 'ro' })).toBeNull();
    expect(findUpstashEnv({ REDIS_URL: 'rediss://x' })).toBeNull();
  });

  it('lists storage-looking names without values', () => {
    const names = storageEnvNames({ STORAGE_KV_URL: 's3cret', REDIS_URL: 'x', PATH: '/bin', KVETCH: 'no', NEXT_PUBLIC_X: 'y' });
    expect(names).toEqual(['REDIS_URL', 'STORAGE_KV_URL']);
  });

  it('GET reports the names it sees when storage is unconfigured', async () => {
    setGuessStoreForTests(null);
    const body = (await (await GET(new Request('http://localhost/election/api/guesses'))).json()) as {
      configured: boolean;
      storage_env_seen: string[];
    };
    expect(body.configured).toBe(false);
    expect(Array.isArray(body.storage_env_seen)).toBe(true);
  });
});
