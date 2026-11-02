// Types and pure helpers for Tre's Senate picks. Safe to import from client
// components — the file reader lives in predictions.ts (server only).

import type { StateFeatures } from '@/app/lib/data';

export type Party = 'D' | 'R' | 'I';

export interface PredictionRace {
  state: string;
  abbr: string;
  held_by: Party;
  incumbent: string | null;
  open: boolean;
  dem_candidate: string | null;
  rep_candidate: string | null;
  ind_candidate: string | null;
  pick: Party | null;
  // Winner's margin in points, always >= 0.
  margin: number | null;
  note: string;
}

export interface PredictionsFile {
  as_of: string;
  races: PredictionRace[];
}

// What the model currently says about the same race, pulled from senate.json
// so the page can show "your pick vs. the model" without a second pipeline.
export interface ModelView {
  dem_candidate: string | null;
  rep_candidate: string | null;
  // Dem − Rep polling average, positive = D ahead.
  poll_margin: number | null;
  // Simulation median Dem − Rep margin and P(D wins).
  median_margin: number | null;
  dem_win_prob: number | null;
}

export interface PredictionRaceView extends PredictionRace {
  model: ModelView | null;
  features: StateFeatures | null;
}

// Convert a pick + winner's margin into the signed Dem − Rep convention the
// rest of the site uses (so fmtMargin renders it as "D+3.0" / "R+3.0").
// Independents have no place on that axis, so they return null.
export function toDemMargin(pick: Party | null, margin: number | null): number | null {
  if (pick == null || margin == null) return null;
  if (pick === 'D') return margin;
  if (pick === 'R') return -margin;
  return null;
}

export type MarginBucket = 'lean' | 'likely' | 'safe';

// Standard ratings-style bands: under 3 lean, 3–8 likely, 8+ safe.
export function marginBucket(margin: number | null): MarginBucket {
  if (margin == null) return 'likely';
  if (margin < 3) return 'lean';
  if (margin < 8) return 'likely';
  return 'safe';
}

export const PREDICTIONS_README =
  "Tre's hand-made 2026 Senate picks. This file is the published source of truth for /predictions. `pick` is \"D\", \"R\", \"I\" or null; `margin` is the winner's margin in points (always positive), or null. Edit on the page in Edit mode, then paste the exported JSON back here and commit.";

const RACE_KEYS: (keyof PredictionRace)[] = [
  'state', 'abbr', 'held_by', 'incumbent', 'open',
  'dem_candidate', 'rep_candidate', 'ind_candidate', 'pick', 'margin', 'note',
];

// The JSON Edit mode exports for web/content/predictions.json: only the
// hand-edited fields, in file order. Model numbers and state features are
// page-time joins and must not leak into the committed file.
export function toPredictionsFile(
  races: PredictionRace[],
  asOf: string,
): { _readme: string; as_of: string; races: PredictionRace[] } {
  return {
    _readme: PREDICTIONS_README,
    as_of: asOf,
    races: races.map((r) => Object.fromEntries(RACE_KEYS.map((k) => [k, r[k]])) as unknown as PredictionRace),
  };
}
