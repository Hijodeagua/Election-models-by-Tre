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

export function getMeta(): Meta {
  return read<Meta>('meta.json', {
    last_updated: '',
    data_tier: 'tracker',
    label: 'TRACKER — weighted polling averages only, not a forecast',
    model_versions: {},
    poll_counts: {},
  });
}
