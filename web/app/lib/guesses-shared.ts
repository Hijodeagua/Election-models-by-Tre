// Phase 5 — public guesses vs the model. Types, validation and the lock rule.
// Pure: safe to import from client components, route handlers and tests.

import type { Party, PredictionRaceView } from '@/app/lib/predictions-shared';

// Route handlers live under the app's basePath (next.config.mjs), and the hub
// proxies whosyurgoat.app/election/* through to them unchanged.
export const GUESSES_API = '/election/api/guesses';

export const MAX_NAME_LEN = 30;
export const MAX_MARGIN = 100;

// Server-side lock: Tuesday Nov 3, 2026, 6:00 PM Eastern. US DST ends on
// Nov 1, 2026, so Eastern is EST (UTC−5) by then → 23:00 UTC.
export const LOCK_AT_ISO = '2026-11-03T23:00:00.000Z';
export const LOCK_AT_MS = Date.parse(LOCK_AT_ISO);

export function isLocked(nowMs: number = Date.now()): boolean {
  return nowMs >= LOCK_AT_MS;
}

export interface RaceGuess {
  pick: Party;
  // Winner's margin in points (>= 0), or null when the guesser skipped it.
  margin: number | null;
}

// abbr → guess. Partial maps are allowed: a guesser can leave races blank.
export type GuessMap = Record<string, RaceGuess>;

export interface GuessEntry {
  id: string;
  name: string;
  guesses: GuessMap;
  created_at: string;
  updated_at: string;
}

export interface GuessesPayload {
  configured: boolean;
  lock_at: string;
  locked: boolean;
  entries: GuessEntry[];
}

// Which parties a guesser may pick in each board race. Independents are only
// offered where one is actually on the ballot (Nebraska, Montana).
export type AllowedPicks = Record<string, Party[]>;

export function allowedPicksFor(
  races: Pick<PredictionRaceView, 'abbr' | 'ind_candidate'>[],
): AllowedPicks {
  const out: AllowedPicks = {};
  for (const r of races) out[r.abbr] = r.ind_candidate ? ['D', 'R', 'I'] : ['D', 'R'];
  return out;
}

// Display names: trim, collapse inner whitespace, strip control characters.
// Returns null when nothing usable is left or the result is too long.
export function normalizeName(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  // eslint-disable-next-line no-control-regex
  const cleaned = raw.replace(/[\u0000-\u001f\u007f]/g, '').replace(/\s+/g, ' ').trim();
  if (cleaned.length === 0 || cleaned.length > MAX_NAME_LEN) return null;
  return cleaned;
}

// Case-insensitive key so "Tre" and "tre" cannot both be claimed.
export function nameKey(name: string): string {
  return name.toLocaleLowerCase('en-US');
}

export type Validation =
  | { ok: true; name: string; guesses: GuessMap }
  | { ok: false; error: string };

const PARTIES: Party[] = ['D', 'R', 'I'];

export function validateGuesses(raw: unknown, allowed: AllowedPicks): Validation {
  if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, error: 'guesses must be an object keyed by state abbreviation' };
  }
  const guesses: GuessMap = {};
  for (const [abbr, value] of Object.entries(raw as Record<string, unknown>)) {
    const options = allowed[abbr];
    if (!options) return { ok: false, error: `${abbr} is not a race on the board` };
    if (value == null) continue; // blank race
    if (typeof value !== 'object') return { ok: false, error: `${abbr}: guess must be an object` };
    const { pick, margin } = value as { pick?: unknown; margin?: unknown };
    if (pick == null) continue; // blank race
    if (typeof pick !== 'string' || !PARTIES.includes(pick as Party)) {
      return { ok: false, error: `${abbr}: pick must be D, R or I` };
    }
    if (!options.includes(pick as Party)) {
      return { ok: false, error: `${abbr}: no ${pick === 'I' ? 'independent' : pick} on the ballot` };
    }
    let m: number | null = null;
    if (margin != null && margin !== '') {
      const n = typeof margin === 'string' ? Number(margin) : margin;
      if (typeof n !== 'number' || !Number.isFinite(n)) {
        return { ok: false, error: `${abbr}: margin must be a number` };
      }
      if (n < 0 || n > MAX_MARGIN) {
        return { ok: false, error: `${abbr}: margin must be between 0 and ${MAX_MARGIN}` };
      }
      m = Math.round(n * 10) / 10;
    }
    guesses[abbr] = { pick: pick as Party, margin: m };
  }
  if (Object.keys(guesses).length === 0) {
    return { ok: false, error: 'pick a winner in at least one race' };
  }
  return { ok: true, name: '', guesses };
}

export function validateSubmission(body: unknown, allowed: AllowedPicks): Validation {
  if (body == null || typeof body !== 'object') return { ok: false, error: 'body must be JSON' };
  const { name, guesses } = body as { name?: unknown; guesses?: unknown };
  const cleanName = normalizeName(name);
  if (!cleanName) {
    return { ok: false, error: `display name is required (1–${MAX_NAME_LEN} characters)` };
  }
  const v = validateGuesses(guesses, allowed);
  if (!v.ok) return v;
  return { ok: true, name: cleanName, guesses: v.guesses };
}

// What the model calls the race, in the same pick/margin shape as a guess.
// The simulation's positive side is whoever the config lists as the
// "Democratic" candidate, which for Nebraska and Montana is the independent.
export function modelGuess(
  race: Pick<PredictionRaceView, 'model' | 'ind_candidate'>,
): RaceGuess | null {
  const med = race.model?.median_margin;
  if (med == null) return null;
  const rounded = Math.round(med * 10) / 10;
  if (rounded === 0) return null;
  const positiveSide: Party =
    race.ind_candidate && race.model?.dem_candidate === race.ind_candidate ? 'I' : 'D';
  return { pick: rounded > 0 ? positiveSide : 'R', margin: Math.abs(rounded) };
}

export function guessesDisagree(a: RaceGuess | null, b: RaceGuess | null): boolean {
  if (!a || !b) return false;
  return a.pick !== b.pick;
}
