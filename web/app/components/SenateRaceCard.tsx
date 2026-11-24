'use client';

import { useState } from 'react';
import type { ScorecardRace, SenateRaceSnapshot } from '@/app/lib/data';
import SenateRaceChart from '@/app/components/SenateRaceChart';
import { fmtMargin, fmtProb } from '@/app/lib/format';

const MARKET_LABELS: Record<string, string> = {
  polymarket: 'Polymarket',
  kalshi: 'Kalshi',
};

// "Our forecast has X winning over Y in N% of simulations, median margin Z."
function ForecastSummary({ race, past = false }: { race: SenateRaceSnapshot; past?: boolean }) {
  const fc = race.forecast;
  if (!fc || fc.dem_win_prob == null) return null;
  const demProb = fc.dem_win_prob;
  const demWins = demProb >= 0.5;
  const winner = demWins ? race.dem_candidate : race.rep_candidate;
  const loser = demWins ? race.rep_candidate : race.dem_candidate;
  const winnerSide = demWins ? 'D' : 'R';
  const med = fc.median_margin;
  const medTxt = fmtMargin(med, 1);
  const medClass =
    med == null || Math.abs(med) < 0.05 ? 'text-ink' : med > 0 ? 'text-dem' : 'text-rep';
  return (
    <p className="mt-2 text-sm text-cocoa-700">
      Our {past ? 'final forecast had' : 'forecast has'}{' '}
      <strong className={winnerSide === 'D' ? 'text-dem' : 'text-rep'}>{winner}</strong>{' '}
      winning over <strong>{loser}</strong> in{' '}
      <strong>{fmtProb(demWins ? demProb : 1 - demProb)}</strong> of simulations, with a
      median margin of <strong className={medClass}>{medTxt}</strong>
      {fc.margin_p10 != null && fc.margin_p90 != null && (
        <span className="text-cocoa-400">
          {' '}(80% range {fmtMargin(fc.margin_p10)} to {fmtMargin(fc.margin_p90)})
        </span>
      )}
      .
    </p>
  );
}

function partyClass(party: string | null | undefined): string {
  return party === 'D' ? 'text-dem' : party === 'R' ? 'text-rep' : 'text-stamp';
}

// "D +10.1": how far, and toward whom, the result landed from a forecast.
function missText(err: number): string {
  const r = Number(err.toFixed(1));
  if (r === 0) return 'on the nose';
  return `${Math.abs(r).toFixed(1)} pts too ${r > 0 ? 'Republican' : 'Democratic'}`;
}

// Post-election strip: the result, and how the forecast and the polling
// average each did against it.
function ResultStrip({ scored }: { scored: ScorecardRace }) {
  const res = scored.result;
  if (!res) return null;
  const ind = scored.race?.challenger_party === 'I';
  const m = (v: number | null | undefined) => {
    const t = fmtMargin(v);
    return ind ? t.replace(/^D/, 'I') : t;
  };
  const ok = scored.model.correct;
  const pollErr =
    res.margin != null && scored.model.poll_margin != null
      ? res.margin - scored.model.poll_margin
      : null;
  return (
    <div
      className={`mt-3 rounded-lg border px-3 py-2.5 text-sm ${
        ok === false ? 'border-rep-border bg-rep-wash' : 'border-[#cfe2c6] bg-stamp-wash'
      }`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="text-cocoa-700">
          <span className="text-[11px] font-bold uppercase tracking-wide text-cocoa-400">
            Result{' '}
          </span>
          <strong className={partyClass(res.winner_party)}>{res.winner ?? res.winner_party}</strong>{' '}
          won{res.margin != null && <> by <strong>{m(res.margin).replace(/^[DRI]\+/, '')}</strong></>}
          {res.flipped && <span className="ml-1.5 text-[11px] font-semibold text-peach">flip</span>}
        </div>
        {ok != null && (
          <div className={`text-xs font-bold ${ok ? 'text-stamp' : 'text-rep'}`}>
            {ok ? '✓ called it' : '✗ missed it'}
          </div>
        )}
      </div>
      <div className="mt-1 text-xs leading-relaxed text-cocoa-500">
        {scored.model.margin_error != null && (
          <>
            Forecast {m(scored.model.median_margin)}:{' '}
            <strong className="text-cocoa-700">{missText(scored.model.margin_error)}</strong>
            {scored.model.in_80_band != null && (
              <> ({scored.model.in_80_band ? 'inside' : 'outside'} the 80% range)</>
            )}
            .{' '}
          </>
        )}
        {pollErr != null && (
          <>
            Polling average {m(scored.model.poll_margin)}:{' '}
            <strong className="text-cocoa-700">{missText(pollErr)}</strong>.
          </>
        )}
      </div>
    </div>
  );
}

// One competitive race: candidate averages, a base-model vs vibes-adjusted
// margin toggle, and prediction-market odds chips for comparison. After the
// election, pass the scorecard row as `scored` to set it against the result.
export default function SenateRaceCard({
  race,
  scored,
}: {
  race: SenateRaceSnapshot;
  scored?: ScorecardRace;
}) {
  const [showVibes, setShowVibes] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const ranked = Object.entries(race.candidates).sort((a, b) => b[1] - a[1]);
  const vibes = race.vibes;
  const displayedMargin =
    showVibes && vibes?.available ? vibes.adjusted_dem_margin : race.dem_margin;
  const winProb = race.forecast?.dem_win_prob ?? null;
  const marketOdds = race.market_odds ?? {};
  const marketSources = Object.keys(marketOdds).filter(
    (s) => marketOdds[s].Democrat != null,
  );

  return (
    <div className="rounded-xl border border-cream-300 bg-white p-4">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-start justify-between gap-2 rounded-lg text-left transition-colors hover:bg-cream-50"
      >
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 font-display text-lg text-ink">
            {race.state}
            <svg
              className={`h-4 w-4 text-cocoa-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              aria-hidden="true"
            >
              <path d="M6 8l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </h3>
          <p className="mt-1 text-sm text-cocoa-700">
            {ranked.slice(0, 3).map(([name, pct]) => (
              <span key={name} className="mr-3 inline-block">
                {name}: <strong>{pct.toFixed(1)}%</strong>
              </span>
            ))}
          </p>
          <span className="mt-1 inline-block text-[11px] text-peach">
            {expanded ? 'Hide chart' : 'Click to chart this race'}
          </span>
        </div>
        <div className="shrink-0 text-right">
          {winProb != null ? (
            <>
              <div
                className={`font-display text-2xl leading-none ${
                  winProb >= 0.5 ? 'text-dem' : 'text-rep'
                }`}
              >
                {winProb >= 0.5 ? 'D' : 'R'} {fmtProb(winProb >= 0.5 ? winProb : 1 - winProb)}
              </div>
              <div className="mt-1 text-xs text-cocoa-400">win probability</div>
            </>
          ) : (
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
          )}
          <div className="mt-1 text-xs text-cocoa-400">
            polling avg {fmtMargin(displayedMargin)}
            {showVibes && vibes?.available ? ' · NYT vibes' : ''} · {race.num_polls} polls
          </div>
        </div>
      </button>

      {scored?.result && <ResultStrip scored={scored} />}

      <ForecastSummary race={race} past={Boolean(scored?.result)} />

      {expanded && (
        <div className="mt-3 border-t border-cream-100 pt-3">
          <SenateRaceChart race={race} />
        </div>
      )}

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
        {marketSources.map((source) => {
          const url = race.market_urls?.[source];
          const label = (
            <>
              {MARKET_LABELS[source] ?? source}: D{' '}
              {(marketOdds[source].Democrat * 100).toFixed(0)}%
            </>
          );
          const chipClass =
            'rounded-full border border-cream-300 bg-cream-50 px-2.5 py-1 font-semibold text-cocoa-500';
          return url ? (
            <a
              key={source}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className={`${chipClass} transition-colors hover:border-cocoa-400 hover:text-cocoa-700 hover:underline`}
              title={`${MARKET_LABELS[source] ?? source}: implied probability the Democrat wins — view the market`}
            >
              {label} ↗
            </a>
          ) : (
            <span
              key={source}
              className={chipClass}
              title={`${MARKET_LABELS[source] ?? source}: implied probability the Democrat wins`}
            >
              {label}
            </span>
          );
        })}
      </div>
    </div>
  );
}
