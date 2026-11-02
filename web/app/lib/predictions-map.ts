// Shared look and summary math for the predictions board, used by the live
// map (PredictionsBoard) and the shareable PNGs (share-image) so both always
// agree. Pure: safe in client components and tests.

import type { Party, PredictionRace } from '@/app/lib/predictions-shared';
import type { MarginBucket } from '@/app/lib/predictions-shared';

// A diverging ramp off the site's D/R tokens. Lean steps are light tints, so
// every coloured state also carries a direct label (abbr + margin).
export const FILL: Record<Party, Record<MarginBucket, string>> = {
  D: { lean: '#93c5fd', likely: '#2563eb', safe: '#1e3a8a' },
  R: { lean: '#fca5a5', likely: '#dc2626', safe: '#7f1d1d' },
  I: { lean: '#a7cf9a', likely: '#4e8c3f', safe: '#2f5d25' },
};
export const FILL_NO_PICK = '#d9cfc7';
export const FILL_NOT_RACE = '#f0ebe5';

// Where the centroid is a poor label anchor (water, panhandle, tiny state),
// nudge the label or pull it out on a leader line.
export const LABEL_ADJUST: Record<string, { dx: number; dy: number; leader?: boolean }> = {
  MI: { dx: 22, dy: 42 },
  NH: { dx: 62, dy: 24, leader: true },
  FL: { dx: 18, dy: 6 },
  LA: { dx: -10, dy: -4 },
  AK: { dx: 0, dy: 8 },
};

export function fmtWinnerMargin(pick: Party | null, margin: number | null): string {
  if (pick == null) return '—';
  if (margin == null) return `${pick} (no margin)`;
  return `${pick}+${margin.toFixed(1)}`;
}

export interface BoardSummary {
  picks: Record<Party, number>;
  flipsToD: number;
  flipsToR: number;
  indFlips: number;
  uncalled: number;
  net: number; // flipsToD − flipsToR
  total: number;
}

export function boardSummary(races: Pick<PredictionRace, 'pick' | 'held_by'>[]): BoardSummary {
  const picks: Record<Party, number> = { D: 0, R: 0, I: 0 };
  let flipsToD = 0;
  let flipsToR = 0;
  let indFlips = 0;
  let uncalled = 0;
  for (const r of races) {
    if (r.pick == null) {
      uncalled += 1;
      continue;
    }
    picks[r.pick] += 1;
    if (r.pick !== r.held_by) {
      if (r.pick === 'D') flipsToD += 1;
      else if (r.pick === 'R') flipsToR += 1;
      else indFlips += 1;
    }
  }
  return { picks, flipsToD, flipsToR, indFlips, uncalled, net: flipsToD - flipsToR, total: races.length };
}

export function fmtNet(net: number): string {
  return net === 0 ? '±0' : net > 0 ? `D+${net}` : `R+${-net}`;
}

// ---------------------------------------------------------------------------
// The other 18 races of 2026 (not on the board) are safe holds, and 65 seats
// are not up this cycle. Together with the 17 board races that makes 100.
// Kept in step with config/senate_2026.json by tests/share-image.test.ts.
// ---------------------------------------------------------------------------
export const SAFE_HOLDS: Readonly<Record<string, 'D' | 'R'>> = {
  CO: 'D', DE: 'D', IL: 'D', MA: 'D', NJ: 'D', NM: 'D', OR: 'D', RI: 'D', VA: 'D',
  AL: 'R', AR: 'R', ID: 'R', KY: 'R', OK: 'R', SD: 'R', TN: 'R', WV: 'R', WY: 'R',
};

// Seats not up in 2026. King and Sanders caucus with Democrats and count as D.
export const NOT_UP: Readonly<Record<'D' | 'R', number>> = { D: 34, R: 31 };

export type StateFillKind = 'race' | 'safe' | 'none';

// Fill for any state: a board race by its guess (hatched when uncalled),
// a safe hold by its party's safe shade, anything else as "no 2026 race".
export function stateFill(
  abbr: string,
  race: Pick<PredictionRace, 'pick' | 'margin'> | undefined,
  marginBucketOf: (m: number | null) => MarginBucket,
  hatch: string,
): { kind: StateFillKind; fill: string } {
  if (race) {
    return { kind: 'race', fill: race.pick == null ? hatch : FILL[race.pick][marginBucketOf(race.margin)] };
  }
  const safe = SAFE_HOLDS[abbr];
  if (safe) return { kind: 'safe', fill: FILL[safe].safe };
  return { kind: 'none', fill: FILL_NOT_RACE };
}

export interface SenateTotal {
  D: number;
  R: number;
  I: number;
  uncalled: number;
}

export function senateTotal(races: Pick<PredictionRace, 'pick' | 'held_by'>[]): SenateTotal {
  const { picks, uncalled } = boardSummary(races);
  const safeD = Object.values(SAFE_HOLDS).filter((p) => p === 'D').length;
  const safeR = Object.values(SAFE_HOLDS).filter((p) => p === 'R').length;
  return {
    D: NOT_UP.D + safeD + picks.D,
    R: NOT_UP.R + safeR + picks.R,
    I: picks.I,
    uncalled,
  };
}

// "53 D, 47 R" (+ ", 1 I" when an independent is guessed, + ", 2 still to call").
export function fmtSenateCounts(t: SenateTotal): string {
  const parts = [`${t.D} D`, `${t.R} R`];
  if (t.I) parts.push(`${t.I} I`);
  if (t.uncalled) parts.push(`${t.uncalled} still to call`);
  return parts.join(', ');
}

export function fmtSenateTotal(t: SenateTotal): string {
  return `Senate after these guesses: ${fmtSenateCounts(t)}`;
}
