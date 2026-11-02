// Phase 5 — storage for public guesses, on Upstash Redis.
//
// Keys:
//   guesses:entries            hash  id → JSON (GuessEntry + token_hash)
//   guesses:names              hash  nameKey → id   (one person per name)
//   guesses:rl:<ip>:<bucket>   int   writes from an IP in the current window
//
// The store talks to a tiny RedisLike interface so tests run on an in-memory
// fake and the route handlers stay thin. All values are plain strings.

import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import {
  LOCK_AT_ISO,
  isLocked,
  isReservedName,
  nameKey,
  normalizeName,
  validateGuesses,
  validateSubmission,
  type AllowedPicks,
  type GuessEntry,
  type GuessesPayload,
} from '@/app/lib/guesses-shared';

export interface RedisLike {
  hget(key: string, field: string): Promise<string | null>;
  hset(key: string, field: string, value: string): Promise<void>;
  hsetnx(key: string, field: string, value: string): Promise<boolean>;
  hdel(key: string, field: string): Promise<void>;
  hgetall(key: string): Promise<Record<string, string>>;
  hlen(key: string): Promise<number>;
  incr(key: string): Promise<number>;
  expire(key: string, seconds: number): Promise<void>;
}

export const KEYS = {
  entries: 'guesses:entries',
  names: 'guesses:names',
  rate: (ip: string, bucket: number) => `guesses:rl:${ip}:${bucket}`,
};

export interface StoreOptions {
  now?: () => number;
  // Writes (submit + edit) allowed per IP per window.
  rateLimit?: { max: number; windowSec: number };
  maxEntries?: number;
}

export interface StoreResult<T = unknown> {
  status: number;
  body: T;
}

interface Stored extends GuessEntry {
  token_hash: string;
}

export interface GuessStore {
  list(): Promise<GuessesPayload>;
  submit(body: unknown, ip: string, allowed: AllowedPicks): Promise<StoreResult>;
  update(id: string, token: string | null, body: unknown, ip: string, allowed: AllowedPicks): Promise<StoreResult>;
  // Admin hide: deletes the entry and frees its display name. The caller
  // (the DELETE route) is responsible for checking the admin token.
  remove(id: string): Promise<StoreResult>;
}

function reservedError(name: string): StoreResult {
  return { status: 409, body: { error: `“${name}” is reserved — pick another display name` } };
}

function sha256(s: string): string {
  return createHash('sha256').update(s).digest('hex');
}

function tokenMatches(token: string | null, hash: string): boolean {
  if (!token) return false;
  const a = Buffer.from(sha256(token), 'hex');
  const b = Buffer.from(hash, 'hex');
  return a.length === b.length && timingSafeEqual(a, b);
}

function publicView(s: Stored): GuessEntry {
  const { token_hash: _hash, ...entry } = s;
  return entry;
}

export function createGuessStore(redis: RedisLike, opts: StoreOptions = {}): GuessStore {
  const now = opts.now ?? (() => Date.now());
  const rate = opts.rateLimit ?? { max: 10, windowSec: 600 };
  const maxEntries = opts.maxEntries ?? 1000;

  async function overLimit(ip: string): Promise<boolean> {
    const bucket = Math.floor(now() / 1000 / rate.windowSec);
    const key = KEYS.rate(ip, bucket);
    const n = await redis.incr(key);
    if (n === 1) await redis.expire(key, rate.windowSec * 2);
    return n > rate.max;
  }

  async function readEntry(id: string): Promise<Stored | null> {
    const raw = await redis.hget(KEYS.entries, id);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as Stored;
    } catch {
      return null;
    }
  }

  async function list(): Promise<GuessesPayload> {
    const all = await redis.hgetall(KEYS.entries);
    const entries: GuessEntry[] = [];
    for (const raw of Object.values(all)) {
      try {
        entries.push(publicView(JSON.parse(raw) as Stored));
      } catch {
        /* skip a corrupt row rather than fail the page */
      }
    }
    entries.sort((a, b) => a.created_at.localeCompare(b.created_at));
    return { configured: true, lock_at: LOCK_AT_ISO, locked: isLocked(now()), entries };
  }

  async function submit(body: unknown, ip: string, allowed: AllowedPicks): Promise<StoreResult> {
    if (isLocked(now())) {
      return { status: 423, body: { error: 'Guesses locked at 6:00 PM ET on Nov 3, 2026' } };
    }
    if (await overLimit(ip)) {
      return { status: 429, body: { error: 'Too many changes from this connection; try again in a few minutes' } };
    }
    const v = validateSubmission(body, allowed);
    if (!v.ok) return { status: 400, body: { error: v.error } };
    if (isReservedName(v.name)) return reservedError(v.name);
    if ((await redis.hlen(KEYS.entries)) >= maxEntries) {
      return { status: 507, body: { error: 'The board is full' } };
    }

    const id = randomBytes(8).toString('hex');
    const claimed = await redis.hsetnx(KEYS.names, nameKey(v.name), id);
    if (!claimed) {
      return { status: 409, body: { error: `“${v.name}” is taken — pick another display name` } };
    }
    const token = randomBytes(24).toString('hex');
    const ts = new Date(now()).toISOString();
    const stored: Stored = {
      id,
      name: v.name,
      guesses: v.guesses,
      created_at: ts,
      updated_at: ts,
      token_hash: sha256(token),
    };
    await redis.hset(KEYS.entries, id, JSON.stringify(stored));
    return { status: 201, body: { id, token, entry: publicView(stored) } };
  }

  async function update(
    id: string,
    token: string | null,
    body: unknown,
    ip: string,
    allowed: AllowedPicks,
  ): Promise<StoreResult> {
    if (isLocked(now())) {
      return { status: 423, body: { error: 'Guesses locked at 6:00 PM ET on Nov 3, 2026' } };
    }
    if (await overLimit(ip)) {
      return { status: 429, body: { error: 'Too many changes from this connection; try again in a few minutes' } };
    }
    const existing = await readEntry(id);
    if (!existing) return { status: 404, body: { error: 'No such entry' } };
    if (!tokenMatches(token, existing.token_hash)) {
      return { status: 403, body: { error: 'This browser does not hold the edit token for that entry' } };
    }
    if (body == null || typeof body !== 'object') return { status: 400, body: { error: 'body must be JSON' } };
    const { name, guesses } = body as { name?: unknown; guesses?: unknown };

    const v = validateGuesses(guesses, allowed);
    if (!v.ok) return { status: 400, body: { error: v.error } };

    let newName = existing.name;
    if (name != null) {
      const cleaned = normalizeName(name);
      if (!cleaned) return { status: 400, body: { error: 'display name must be 1–30 characters' } };
      if (nameKey(cleaned) !== nameKey(existing.name)) {
        if (isReservedName(cleaned)) return reservedError(cleaned);
        const claimed = await redis.hsetnx(KEYS.names, nameKey(cleaned), id);
        if (!claimed) {
          return { status: 409, body: { error: `“${cleaned}” is taken — pick another display name` } };
        }
        await redis.hdel(KEYS.names, nameKey(existing.name));
      }
      newName = cleaned;
    }

    const stored: Stored = {
      ...existing,
      name: newName,
      guesses: v.guesses,
      updated_at: new Date(now()).toISOString(),
    };
    await redis.hset(KEYS.entries, id, JSON.stringify(stored));
    return { status: 200, body: { id, entry: publicView(stored) } };
  }

  async function remove(id: string): Promise<StoreResult> {
    const existing = await readEntry(id);
    if (!existing) return { status: 404, body: { error: 'No such entry' } };
    await redis.hdel(KEYS.entries, id);
    // Free the name only if it still points at this entry.
    const key = nameKey(existing.name);
    if ((await redis.hget(KEYS.names, key)) === id) await redis.hdel(KEYS.names, key);
    return { status: 200, body: { id, removed: true } };
  }

  return { list, submit, update, remove };
}

// In-memory RedisLike for tests and local development without Upstash.
export class MemoryRedis implements RedisLike {
  private hashes = new Map<string, Map<string, string>>();
  private counters = new Map<string, number>();

  private hash(key: string): Map<string, string> {
    let h = this.hashes.get(key);
    if (!h) {
      h = new Map();
      this.hashes.set(key, h);
    }
    return h;
  }

  async hget(key: string, field: string) {
    return this.hash(key).get(field) ?? null;
  }
  async hset(key: string, field: string, value: string) {
    this.hash(key).set(field, value);
  }
  async hsetnx(key: string, field: string, value: string) {
    const h = this.hash(key);
    if (h.has(field)) return false;
    h.set(field, value);
    return true;
  }
  async hdel(key: string, field: string) {
    this.hash(key).delete(field);
  }
  async hgetall(key: string) {
    return Object.fromEntries(this.hash(key));
  }
  async hlen(key: string) {
    return this.hash(key).size;
  }
  async incr(key: string) {
    const n = (this.counters.get(key) ?? 0) + 1;
    this.counters.set(key, n);
    return n;
  }
  async expire() {
    /* TTLs are not modelled in memory */
  }
}
