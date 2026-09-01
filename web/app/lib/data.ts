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
  estimated_dem_seats_lo: number | null;
  estimated_dem_seats_hi: number | null;
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
export interface MarginHistBin {
  mid: number;
  pct: number;
}

export interface RaceForecastSummary {
  dem_win_prob: number | null;
  median_margin: number | null;
  margin_p10: number | null;
  margin_p90: number | null;
  num_simulations: number | null;
  margin_hist?: MarginHistBin[];
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
  forecast?: RaceForecastSummary;
  vibes?: RaceVibes;
  market_odds?: MarketOddsBySource;
  market_urls?: Record<string, string>;
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
  dem_win_prob_sim?: number | null;
  median_margin?: number | null;
  margin_p10?: number | null;
  margin_p90?: number | null;
  market_urls?: Record<string, string>;
}

export interface PollsterEmpirical {
  mean_error: number;
  std_error: number;
  n_polls: number;
}

export interface NationalPollsterGrade {
  pollster: string;
  quality: number;
  grade: string | null;
  sb_error: number;
  empirical: PollsterEmpirical | null;
}

export interface StatePoll {
  pollster: string;
  rated: boolean;
  grade: string | null;
  quality: number | null;
  start_date: string;
  end_date: string;
  sample_size: number | null;
  population: string | null;
  dem_candidate: string;
  rep_candidate: string;
  dem_pct: number | null;
  rep_pct: number | null;
  margin: number | null;
  partisan: boolean;
}

export interface StatePollsterHistory {
  pollster: string;
  n_polls: number;
  mean_error: number;
  std_error: number;
}

export interface StatePolls {
  state: string;
  abbr: string | null;
  num_polls: number;
  polls: StatePoll[];
  pollster_history: StatePollsterHistory[];
}

export interface PollstersData {
  national: NationalPollsterGrade[];
  states: StatePolls[];
  unknown_default_quality: number;
  unknown_default_grade: string | null;
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
  bias?: number;
  dem_control_prob_with_vibes?: number;
  mean_dem_seats_with_vibes?: number;
  fundamentals_weight_recent?: number;
  fundamentals_blend_k?: number;
  national_environment?: NationalEnvironment;
  market_control_dem_prob: Record<string, number>;
  market_control_urls?: Record<string, string>;
  maturity: string;
  label: string;
}

export interface NationalEnvironment {
  national_swing: number;
  available: boolean;
  president_party?: string;
  approval_net?: number | null;
  generic_margin?: number | null;
  approval_implied_margin?: number | null;
  expected_national_margin?: number;
  house_baseline_2024?: number;
  senate_responsiveness?: number;
}

export interface Meta {
  last_updated: string;
  data_tier: string;
  label: string;
  model_versions: Record<string, string>;
  poll_counts: Record<string, number>;
  last_poll_dates?: Record<string, string | null>;
  // Feeds whose newest poll is >3 days old at export time (see export_json.py).
  stale_feeds?: string[];
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

export function getPollsters(): PollstersData {
  return read<PollstersData>('pollsters.json', {
    national: [],
    states: [],
    unknown_default_quality: 0,
    unknown_default_grade: null,
  });
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
