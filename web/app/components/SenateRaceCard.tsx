'use client';

import { useState } from 'react';
import type { SenateRaceSnapshot } from '@/app/lib/data';

const MARKET_LABELS: Record<string, string> = {
  polymarket: 'Polymarket',
  kalshi: 'Kalshi',
};

function fmtMargin(margin: number | null | undefined): string {
  if (margin == null) return '—';
  const side = margin > 0 ? 'D' : margin < 0 ? 'R' : 'Even';
  return margin === 0 ? 'Even' : `${side} +${Math.abs(margin).toFixed(1)}`;
}

// One competitive race: candidate averages, a base-model vs vibes-adjusted
// margin toggle, and prediction-market odds chips for comparison.
export default function SenateRaceCard({ race }: { race: SenateRaceSnapshot }) {
  const [showVibes, setShowVibes] = useState(false);
  const ranked = Object.entries(race.candidates).sort((a, b) => b[1] - a[1]);
  const vibes = race.vibes;
  const displayedMargin =
    showVibes && vibes?.available ? vibes.adjusted_dem_margin : race.dem_margin;
  const marketOdds = race.market_odds ?? {};
  const marketSources = Object.keys(marketOdds).filter(
    (s) => marketOdds[s].Democrat != null,
  );

  return (
    <div className="rounded-xl border border-cream-300 bg-white p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-display text-lg text-ink">{race.state}</h3>
          <p className="mt-1 text-sm text-cocoa-700">
            {ranked.slice(0, 3).map(([name, pct]) => (
              <span key={name} className="mr-3 whitespace-nowrap">
                {name}: <strong>{pct.toFixed(1)}%</strong>
              </span>
            ))}
          </p>
        </div>
        <div className="text-right">
          <div
            className={`font-display text-2xl leading-none ${
              displayedMargin == null
                ? 'text-cocoa-300'
                : displayedMargin > 0
                  ? 'text-dem'
                  : displayedMargin < 0
                    ? 'text-rep'
                    : 'text-cocoa-700'
            }`}
          >
            {fmtMargin(displayedMargin)}
          </div>
          <div className="mt-1 text-xs text-cocoa-400">
            {showVibes && vibes?.available ? 'with NYT vibes' : 'base model'} ·{' '}
            {race.num_polls} polls
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-cream-100 pt-3 text-xs">
        {vibes && (
          <button
            onClick={() => setShowVibes((v) => !v)}
            disabled={!vibes.available}
            className={`rounded-full border px-2.5 py-1 font-semibold transition-colors ${
              !vibes.available
                ? 'cursor-not-allowed border-cream-300 text-cocoa-300'
                : showVibes
                  ? 'border-peach-border bg-peach-wash text-peach'
                  : 'border-cream-300 text-cocoa-500 hover:bg-cream-100'
            }`}
            title={
              vibes.available
                ? `Vibes adjustment: ${vibes.adjustment >= 0 ? '+' : ''}${vibes.adjustment} toward ${
                    vibes.adjustment >= 0 ? 'D' : 'R'
                  }`
                : 'NYT coverage data not fetched yet'
            }
          >
            NYT vibes {showVibes && vibes.available ? 'on' : 'off'}
            {vibes.available && vibes.adjustment !== 0 && (
              <span className="ml-1 font-semibold">
                ({vibes.adjustment > 0 ? '+' : ''}
                {vibes.adjustment})
              </span>
            )}
          </button>
        )}
        {marketSources.map((source) => (
          <span
            key={source}
            className="rounded-full border border-cream-300 bg-cream-50 px-2.5 py-1 font-semibold text-cocoa-500"
            title={`${MARKET_LABELS[source] ?? source}: implied probability the Democrat wins`}
          >
            {MARKET_LABELS[source] ?? source}: D{' '}
            {(marketOdds[source].Democrat * 100).toFixed(0)}%
          </span>
        ))}
      </div>
    </div>
  );
}
