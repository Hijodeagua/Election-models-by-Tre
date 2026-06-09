// Static-data access layer. The Python pipeline (scripts/export_json.py) writes
// these files into public/data/ during the GitHub Actions cron. We read them at
// build/request time on the server so the client never needs to know the
// basePath-prefixed URL.

import fs from 'node:fs';
import path from 'node:path';

const DATA_DIR = path.join(process.cwd(), 'public', 'data');

export type CI = [number, number] | null;

export interface ApprovalSnapshot {
  as_of: string;
  approve: number;
  disapprove: number;
  net_approval: number;
  num_polls: number;
  ci_approve: CI;
  ci_disapprove: CI;
}

export interface ApprovalData {
  current: ApprovalSnapshot | null;
  trend: ApprovalSnapshot[];
  num_polls: number;
}

export interface GenericBallotSnapshot {
  as_of: string;
  dem_pct: number;
  rep_pct: number;
  margin: number;
  num_polls: number;
  estimated_dem_seats: number | null;
  estimated_rep_seats: number | null;
  ci_dem: CI;
  ci_rep: CI;
}

export interface GenericBallotData {
  current: GenericBallotSnapshot | null;
  trend: GenericBallotSnapshot[];
  num_polls: number;
}

export interface SenateRaceSnapshot {
  state: string;
  as_of: string;
  candidates: Record<string, number>;
  margin: number | null;
  num_polls: number;
  rating: string | null;
}

export interface SenateData {
  races: SenateRaceSnapshot[];
  num_races: number;
}

// ── Dashboard payloads ──────────────────────────────────────────────

export interface ComparisonPoint {
  as_of: string;
  approve: number;
  disapprove: number;
  net: number;
  num_polls?: number;
}

export type ComparisonSourceKey =
  | 'our_model'
  | 'silver_bulletin'
  | 'votehub_raw'
  | 'fifty_plus_one';

export interface ApprovalComparison {
  series: Record<ComparisonSourceKey, ComparisonPoint[]>;
  available: ComparisonSourceKey[];
  labels: Record<ComparisonSourceKey, string>;
}

export interface MarketQuote {
  source: string;
  market_id: string;
  title: string;
  kind: string;
  state: string;
  dem_win_prob: number | null;
  rep_win_prob: number | null;
  volume: number | null;
  as_of: string;
  url: string;
}

export interface RaceModels {
  base: { dem_win_prob: number; sources: string[] };
  with_vibes: {
    dem_win_prob: number;
    vibes_adjustment: number;
    detail: Record<string, unknown> | null;
  };
  market_blend: {
    dem_win_prob: number;
    market_prob: number | null;
    market_weight: number;
  };
}

export interface SenateRaceDetail {
  state: string;
  abbr: string | null;
  incumbent_party: string | null;
  rating: string | null;
  battleground: boolean;
  open_seat: boolean;
  special: boolean;
  candidates: Record<string, number>;
  num_polls: number;
  dem_margin: number | null;
  models: RaceModels;
  markets: MarketQuote[];
}

export interface SenateRacesData {
  cycle: number;
  races: SenateRaceDetail[];
  num_races: number;
  market_blend_weight: number;
}

export interface SimulationResult {
  n_sims: number;
  dem_control_prob: number;
  rep_control_prob: number;
  mean_dem_seats: number;
  median_dem_seats: number;
  seat_histogram: Record<string, number>;
  race_win_freq: Record<string, number>;
  tipping_point_freq: Record<string, number>;
  baseline_dem: number;
  baseline_rep: number;
  dem_seats_needed: number;
  seed: number;
  national_swing_sd: number;
  idiosyncratic_sd: number;
}

export interface SenateControlData {
  simulation: SimulationResult | null;
  market_control_odds: MarketQuote[];
  market_blend_weight: number;
  notes: string[];
}

export interface Meta {
  last_updated: string;
  data_tier: string;
  label: string;
  model_versions: Record<string, string>;
  poll_counts: Record<string, number>;
}

function read<T>(file: string, fallback: T): T {
  try {
    const raw = fs.readFileSync(path.join(DATA_DIR, file), 'utf-8');
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function getApproval(): ApprovalData {
  return read<ApprovalData>('approval.json', { current: null, trend: [], num_polls: 0 });
}

export function getGenericBallot(): GenericBallotData {
  return read<GenericBallotData>('generic_ballot.json', { current: null, trend: [], num_polls: 0 });
}

export function getSenate(): SenateData {
  return read<SenateData>('senate.json', { races: [], num_races: 0 });
}

const EMPTY_LABELS: Record<ComparisonSourceKey, string> = {
  our_model: 'Our model (weighted average)',
  silver_bulletin: 'Silver Bulletin',
  votehub_raw: 'VoteHub raw average',
  fifty_plus_one: '50+1 (Strength In Numbers)',
};

export function getApprovalComparison(): ApprovalComparison {
  return read<ApprovalComparison>('approval_comparison.json', {
    series: { our_model: [], silver_bulletin: [], votehub_raw: [], fifty_plus_one: [] },
    available: [],
    labels: EMPTY_LABELS,
  });
}

export function getSenateRaces(): SenateRacesData {
  return read<SenateRacesData>('senate_races.json', {
    cycle: 2026,
    races: [],
    num_races: 0,
    market_blend_weight: 0.25,
  });
}

export function getSenateControl(): SenateControlData {
  return read<SenateControlData>('senate_control.json', {
    simulation: null,
    market_control_odds: [],
    market_blend_weight: 0.25,
    notes: [],
  });
}

export function getMeta(): Meta {
  return read<Meta>('meta.json', {
    last_updated: '',
    data_tier: 'tracker',
    label: 'TRACKER — weighted polling averages only, not a forecast',
    model_versions: {},
    poll_counts: {},
  });
}
