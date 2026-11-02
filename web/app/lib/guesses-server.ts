// Server-only glue for the public-guesses API: the Upstash client from env,
// the request IP, and the board's allowed picks from predictions.json.

import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import { Redis } from '@upstash/redis';
import { allowedPicksFor, type AllowedPicks } from '@/app/lib/guesses-shared';
import {
  MemoryRedis,
  createGuessStore,
  type GuessStore,
  type RedisLike,
} from '@/app/lib/guesses-store';
import { getPredictions } from '@/app/lib/predictions';

// Vercel's Upstash integration exposes the REST pair under either prefix,
// depending on how it was added to the project. Accept both.
function envPair(): { url: string; token: string } | null {
  const url = process.env.UPSTASH_REDIS_REST_URL ?? process.env.KV_REST_API_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN ?? process.env.KV_REST_API_TOKEN;
  return url && token ? { url, token } : null;
}

class UpstashAdapter implements RedisLike {
  constructor(private readonly r: Redis) {}

  async hget(key: string, field: string) {
    const v = await this.r.hget<string>(key, field);
    return v == null ? null : String(v);
  }
  async hset(key: string, field: string, value: string) {
    await this.r.hset(key, { [field]: value });
  }
  async hsetnx(key: string, field: string, value: string) {
    return (await this.r.hsetnx(key, field, value)) === 1;
  }
  async hdel(key: string, field: string) {
    await this.r.hdel(key, field);
  }
  async hgetall(key: string) {
    const all = await this.r.hgetall<Record<string, string>>(key);
    return all ?? {};
  }
  async hlen(key: string) {
    return this.r.hlen(key);
  }
  async incr(key: string) {
    return this.r.incr(key);
  }
  async expire(key: string, seconds: number) {
    await this.r.expire(key, seconds);
  }
}

let store: GuessStore | null | undefined;

export function getGuessStore(): GuessStore | null {
  if (store !== undefined) return store;
  const pair = envPair();
  if (!pair) {
    // Local development without Upstash: GUESSES_MEMORY_STORE=1 keeps entries
    // in process memory (lost on restart). Never set this on Vercel.
    store = process.env.GUESSES_MEMORY_STORE === '1' ? createGuessStore(new MemoryRedis()) : null;
    return store;
  }
  // Values are stored as JSON strings we parse ourselves.
  const redis = new Redis({ ...pair, automaticDeserialization: false });
  store = createGuessStore(new UpstashAdapter(redis));
  return store;
}

export function setGuessStoreForTests(s: GuessStore | null | undefined): void {
  store = s;
}

// Behind the hub's proxy and Vercel's edge the client address is the first
// hop in x-forwarded-for; fall back to x-real-ip, then a shared bucket.
export function clientIp(req: Request): string {
  const xff = req.headers.get('x-forwarded-for');
  if (xff) {
    const first = xff.split(',')[0]?.trim();
    if (first) return first;
  }
  return req.headers.get('x-real-ip')?.trim() || 'unknown';
}

export function bearerToken(req: Request): string | null {
  const h = req.headers.get('authorization') ?? '';
  const m = /^Bearer\s+(\S+)$/.exec(h);
  return m ? m[1] : null;
}

export type AdminCheck = 'ok' | 'unconfigured' | 'denied';

// Compare the presented bearer token with ADMIN_TOKEN in constant time.
export function checkAdmin(req: Request): AdminCheck {
  const expected = process.env.ADMIN_TOKEN;
  if (!expected) return 'unconfigured';
  const presented = bearerToken(req);
  if (!presented) return 'denied';
  const a = createHash('sha256').update(presented).digest();
  const b = createHash('sha256').update(expected).digest();
  return timingSafeEqual(a, b) ? 'ok' : 'denied';
}

// Which client address each candidate header carries, as short keyed hashes,
// so a probe from two networks can tell whether the hub proxy collapses them
// into one rate-limit bucket without exposing anyone's IP.
export function clientKeyDiagnostics(req: Request): string {
  const secret =
    process.env.ADMIN_TOKEN ?? process.env.UPSTASH_REDIS_REST_TOKEN ?? process.env.KV_REST_API_TOKEN ?? 'local';
  const h = (v: string | null | undefined) =>
    v ? createHmac('sha256', secret).update(v).digest('hex').slice(0, 10) : '-';
  const xff = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim();
  const xvff = req.headers.get('x-vercel-forwarded-for')?.split(',')[0]?.trim();
  const xri = req.headers.get('x-real-ip')?.trim();
  return `used=${h(clientIp(req))};xff=${h(xff)};xvff=${h(xvff)};xri=${h(xri)}`;
}

export function boardAllowedPicks(): AllowedPicks {
  return allowedPicksFor(getPredictions().races);
}

export function json(body: unknown, status = 200, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      ...extra,
    },
  });
}

export async function readJson(req: Request): Promise<unknown | undefined> {
  try {
    return await req.json();
  } catch {
    return undefined;
  }
}
