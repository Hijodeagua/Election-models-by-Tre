// Tre's hand-made Senate picks. Unlike everything in public/data/, this is NOT
// written by the Python pipeline — it is edited by hand (or via Edit mode on
// /predictions, which exports the JSON to paste back here) and committed.

import fs from 'node:fs';
import path from 'node:path';
import { getSenate } from '@/app/lib/data';
import type { PredictionsFile, PredictionRaceView } from '@/app/lib/predictions-shared';

export * from '@/app/lib/predictions-shared';

const FILE = path.join(process.cwd(), 'content', 'predictions.json');

export function getPredictions(): PredictionsFile {
  try {
    const raw = JSON.parse(fs.readFileSync(FILE, 'utf-8')) as PredictionsFile;
    return { as_of: raw.as_of, races: raw.races };
  } catch {
    return { as_of: '', races: [] };
  }
}

export function getPredictionViews(): PredictionRaceView[] {
  const { races } = getPredictions();
  const model = new Map(getSenate().races.map((r) => [r.state, r]));
  return races.map((race) => {
    const m = model.get(race.state);
    if (!m || m.dem_candidate == null) return { ...race, model: null };
    return {
      ...race,
      model: {
        dem_candidate: m.dem_candidate ?? null,
        rep_candidate: m.rep_candidate ?? null,
        poll_margin: m.dem_margin ?? null,
        median_margin: m.forecast?.median_margin ?? null,
        dem_win_prob: m.forecast?.dem_win_prob ?? null,
      },
    };
  });
}
