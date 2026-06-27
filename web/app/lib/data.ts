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

export interface RaceVibes {
  available: boolean;
  adjustment: number;
  dem_effect: number;
  rep_effect: number;
  adjusted_dem_margin: number | null;
}

// source ("polymarket" | "kalshi") -> outcome ("Democrat" | ...) -> probability 0-1
export type MarketOddsBySource = Record<string, Record<string, number>>;

// One point in a race's history: our Dem−Rep margin and the model's implied
// probability the Democrat wins, as of that date.
export interface SenateRaceTrendPoint {
  as_of: string;
  dem_margin: number;
  dem_win_prob: number;
  num_polls: number;
}

export interface SenateRaceSnapshot {
  state: string;
  as_of: string;
  candidates: Record<string, number>;
  margin: number | null;
  num_polls: number;
  rating: string | null;
  dem_candidate?: string;
  rep_candidate?: string;
  dem_margin?: number | null;
  dem_win_prob?: number | null;
  vibes?: RaceVibes;
  market_odds?: MarketOddsBySource;
  trend?: SenateRaceTrendPoint[];
}

export interface SenateData {
  races: SenateRaceSnapshot[];
  num_races: number;
}

export interface ComparisonPoint {
  as_of: string;
  approve: number;
  disapprove: number;
  net: number;
  lo?: number | null;
  hi?: number | null;
}

export interface ComparisonSource {
  label: string;
  description: string;
  available: boolean;
  series: ComparisonPoint[];
}

export interface ApprovalComparisonData {
  sources: Record<string, ComparisonSource>;
}

export interface RaceForecast {
  state: string;
  race: string;
  dem_candidate: string;
  rep_candidate: string;
  margin: number | null;
  num_polls: number;
  dem_win_prob_polls: number | null;
  dem_win_prob_blended: number | null;
  market_dem_prob: Record<string, number>;
}

export interface SenateForecastData {
  as_of: string;
  num_simulations: number;
  dem_control_prob: number;
  mean_dem_seats: number;
  median_dem_seats: number;
  seat_distribution: Record<string, number>;
  races: RaceForecast[];
  dem_safe_seats: number;
  rep_safe_seats: number;
  dem_majority_threshold: number;
  market_weight: number;
  national_sigma: number;
  race_sigma: number;
  market_control_dem_prob: Record<string, number>;
  maturity: string;
  label: string;
}

export interface Meta {
  last_updated: string;
  data_tier: string;
  label: string;
  model_versions: Record<string, string>;
  poll_counts: Record<string, number>;
  last_poll_dates?: Record<string, string | null>;
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

export function getApprovalComparison(): ApprovalComparisonData {
  return read<ApprovalComparisonData>('approval_comparison.json', { sources: {} });
}

export function getSenateForecast(): SenateForecastData | null {
  return read<SenateForecastData | null>('senate_forecast.json', null);
}

export function getMeta(): Meta {
  return read<Meta>('meta.json', {
    last_updated: '',
    data_tier: 'tracker',
    label: 'A work in progress from the team at Policy y Peaches',
    model_versions: {},
    poll_counts: {},
    last_poll_dates: {},
  });
}
