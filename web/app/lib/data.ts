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

export interface RaceFundamentals {
  available: boolean;
  pres_2024?: number | null;
  pres_2020?: number | null;
  pres_weight_recent?: number;
  statewide_2022?: { office: string; margin: number } | null;
  statewide_2022_weight?: number;
  lean?: number;
  national_swing?: number;
  incumbent_party?: string | null;
  incumbent_terms?: number | null;
  incumbent_appointed?: boolean;
  incumbency_advantage?: number;
  incumbency_effect?: number;
  dem_statewide_wins?: number;
  dem_statewide_losses?: number;
  rep_statewide_wins?: number;
  rep_statewide_losses?: number;
  experience_raw?: number;
  experience_effect?: number;
  midterm_penalty_effect?: number;
  prior?: number;
  poll_margin?: number | null;
  num_polls?: number;
  fundamentals_weight?: number;
  blend_k?: number;
  final_margin?: number | null;
}

export interface FundamentalsCoefficients {
  pres_weight_recent: number;
  statewide_2022_weight: number;
  blend_k: number;
  incumbency_advantage: number;
  appointed_incumbent_factor: number;
  experience_per_statewide_win: number;
  experience_per_statewide_loss: number;
  experience_cap: number;
  midterm_penalty: number;
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
  fundamentals?: RaceFundamentals;
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
  bias_calibration?: BiasCalibration;
  fundamentals_coefficients?: FundamentalsCoefficients;
  election_date?: string | null;
  days_to_election?: number;
  campaign_drift_sigma?: number;
  polling_national_sigma?: number;
}

export interface BiasCalibration {
  cycle_type: string;
  weight: number;
  raw_bias: number | null;
  n_races: number;
  years: number[];
  applied: number;
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

export interface HouseDistrictForecast {
  label: string;
  state: string;
  district: string;
  margin_2024: number;
  winner_2024: string;
  expected_margin: number;
  dem_win_prob: number;
  margin_p10: number;
  margin_p90: number;
  redrawn?: boolean;
  margin_2022?: number | null;
  lean?: number;
  open_seat?: boolean;
  open_seat_reason?: string;
  incumbent_party?: string;
  incumbency_adjust?: number;
}

export interface RedistrictingEntry {
  state: string;
  dem_seat_shift: number;
  sd: number;
  include?: boolean;
  note?: string;
}

export interface SeatsVotesPoint {
  margin: number;
  dem_seats: number;
}

export interface HouseForecastData {
  available: boolean;
  reason?: string;
  as_of: string;
  num_simulations: number;
  dem_majority_prob: number;
  mean_dem_seats: number;
  median_dem_seats: number;
  seats_p10: number;
  seats_p90: number;
  seat_distribution: Record<string, number>;
  dem_majority_threshold: number;
  total_seats: number;
  expected_national_margin: number;
  raw_national_margin: number | null;
  generic_ballot_two_party: number | null;
  generic_ballot_raw_margin: number | null;
  approval_implied_margin: number | null;
  approval_net: number | null;
  generic_ballot_bias: number;
  baseline_margin: number;
  national_swing: number;
  national_sigma: number;
  polling_sigma: number;
  campaign_drift_sigma: number;
  days_to_election: number;
  election_date?: string;
  district_sigma: number;
  tail_dof: number | null;
  redistricting_shift_mean: number;
  redistricting_states: RedistrictingEntry[];
  redrawn_states?: string[];
  districts: HouseDistrictForecast[];
  competitive: string[];
  num_competitive: number;
  num_districts: number;
  seats_by_margin: SeatsVotesPoint[];
  tipping_point_margin: number | null;
  seats_2024: { D: number; R: number };
  expected_flips: { r_to_d: number; d_to_r: number };
  lean_weight_2024?: number;
  lean_weight_2022?: number;
  incumbency_advantage?: number;
  num_open_seats?: number;
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

export function getHouseForecast(): HouseForecastData | null {
  const data = read<HouseForecastData | null>('house_forecast.json', null);
  return data && data.available ? data : null;
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
