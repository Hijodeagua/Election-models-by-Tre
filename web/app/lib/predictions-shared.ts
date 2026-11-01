// Types and pure helpers for Tre's Senate picks. Safe to import from client
// components — the file reader lives in predictions.ts (server only).

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
