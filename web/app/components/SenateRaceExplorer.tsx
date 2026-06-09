'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import type { SenateRaceDetail } from '@/app/lib/data';

type ModelKey = 'base' | 'with_vibes' | 'market_blend';

const MODEL_META: Record<ModelKey, { label: string; color: string }> = {
  base: { label: 'Our base model', color: '#2563eb' },
  with_vibes: { label: 'Our model + NYT vibes', color: '#7c3aed' },
  market_blend: { label: 'Model × market blend', color: '#0f766e' },
};

const MARKET_COLORS: Record<string, string> = {
  polymarket: '#1d4ed8',
  kalshi: '#b45309',
};

// Per-race Senate forecast explorer: pick a race, toggle which model variants
// and market odds are shown as Dem-win-probability bars.
export default function SenateRaceExplorer({ races }: { races: SenateRaceDetail[] }) {
  const ordered = useMemo(
    () =>
      [...races].sort((a, b) => {
        if (a.battleground !== b.battleground) return a.battleground ? -1 : 1;
        return a.state.localeCompare(b.state);
      }),
    [races],
  );
  const [stateName, setStateName] = useState(ordered[0]?.state ?? '');
  const [shown, setShown] = useState<Set<ModelKey>>(
    () => new Set<ModelKey>(['base', 'with_vibes', 'market_blend']),
  );
  const [showMarkets, setShowMarkets] = useState(true);

  const race = ordered.find((r) => r.state === stateName) ?? ordered[0];
  if (!race) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
        No Senate race data yet.
      </div>
    );
  }

  const toggle = (key: ModelKey) =>
    setShown((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const bars: { label: string; prob: number | null; color: string; note?: string }[] = [];
  if (shown.has('base')) {
    bars.push({
      label: MODEL_META.base.label,
      prob: race.models.base.dem_win_prob,
      color: MODEL_META.base.color,
      note: race.models.base.sources.includes('polls') ? 'from polls' : 'rating prior only',
    });
  }
  if (shown.has('with_vibes')) {
    const v = race.models.with_vibes;
    bars.push({
      label: MODEL_META.with_vibes.label,
      prob: v.dem_win_prob,
      color: MODEL_META.with_vibes.color,
      note:
        v.vibes_adjustment !== 0
          ? `vibes shift ${v.vibes_adjustment > 0 ? '+' : ''}${v.vibes_adjustment} pts`
          : 'no vibes data for this race yet',
    });
  }
  if (shown.has('market_blend')) {
    const m = race.models.market_blend;
    bars.push({
      label: MODEL_META.market_blend.label,
      prob: m.dem_win_prob,
      color: MODEL_META.market_blend.color,
      note:
        m.market_prob != null
          ? `markets at ${(m.market_prob * 100).toFixed(0)}%, weight ${m.market_weight}`
          : 'no market quotes — equals base model',
    });
  }
  if (showMarkets) {
    for (const quote of race.markets) {
      const prob = quote.dem_win_prob ?? (quote.rep_win_prob != null ? 1 - quote.rep_win_prob : null);
      bars.push({
        label: quote.source === 'polymarket' ? 'Polymarket' : quote.source === 'kalshi' ? 'Kalshi' : quote.source,
        prob,
        color: MARKET_COLORS[quote.source] ?? '#64748b',
        note: 'market price',
      });
    }
    if (race.markets.length === 0) {
      bars.push({ label: 'Markets', prob: null, color: '#94a3b8', note: 'no open market for this race yet' });
    }
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <select
          value={race.state}
          onChange={(e) => setStateName(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1"
        >
          {ordered.map((r) => (
            <option key={r.state} value={r.state}>
              {r.state}
              {r.battleground ? ' ★' : ''}
              {r.special ? ' (special)' : ''}
            </option>
          ))}
        </select>
        {(Object.keys(MODEL_META) as ModelKey[]).map((key) => (
          <label key={key} className="flex cursor-pointer items-center gap-1.5">
            <input
              type="checkbox"
              checked={shown.has(key)}
              onChange={() => toggle(key)}
              style={{ accentColor: MODEL_META[key].color }}
            />
            <span style={{ color: MODEL_META[key].color }}>{MODEL_META[key].label}</span>
          </label>
        ))}
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            checked={showMarkets}
            onChange={() => setShowMarkets((s) => !s)}
          />
          <span className="text-slate-700">Polymarket / Kalshi odds</span>
        </label>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-3 flex flex-wrap items-baseline gap-x-3 text-sm text-slate-500">
          <span className="text-base font-semibold text-slate-800">{race.state}</span>
          {race.rating && <span>rating: {race.rating.replace('_', ' ')}</span>}
          {race.incumbent_party && <span>{race.incumbent_party}-held</span>}
          {race.open_seat && <span>open seat</span>}
          <span>{race.num_polls} polls</span>
          {race.dem_margin != null && (
            <span>
              polled margin {race.dem_margin > 0 ? 'D+' : 'R+'}
              {Math.abs(race.dem_margin).toFixed(1)}
            </span>
          )}
        </div>

        <div className="space-y-2">
          {bars.map((bar, i) => (
            <div key={`${bar.label}-${i}`}>
              <div className="flex justify-between text-xs text-slate-500">
                <span>
                  {bar.label}
                  {bar.note ? <span className="text-slate-400"> — {bar.note}</span> : null}
                </span>
                <span className="font-semibold text-slate-700">
                  {bar.prob != null ? `${(bar.prob * 100).toFixed(0)}% Dem` : '—'}
                </span>
              </div>
              <div className="mt-0.5 h-3 w-full overflow-hidden rounded bg-slate-100">
                {bar.prob != null && (
                  <div
                    className="h-full rounded"
                    style={{ width: `${Math.min(100, bar.prob * 100)}%`, backgroundColor: bar.color }}
                  />
                )}
              </div>
            </div>
          ))}
        </div>

        <p className="mt-3 text-xs text-slate-400">
          Probabilities are Democratic win chances. The vibes component blends NYT
          coverage tone into the polling margin —{' '}
          <Link href="/methodology#vibes" className="underline">
            how the vibes adjustment works
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
