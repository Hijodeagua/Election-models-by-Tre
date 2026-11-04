import Link from 'next/link';
import LastUpdated from '@/app/components/LastUpdated';
import LiveForecastPanel from '@/app/components/LiveForecastPanel';
import { EmptyState, PageHead, Panel, StatCard } from '@/app/components/ui';
import { getLiveForecast, getScorecard, type ScoreMargin, type ScoreProb, type ScorecardRace } from '@/app/lib/data';
import { fmtMargin, fmtProb } from '@/app/lib/format';

export const metadata = {
  title: 'Scorecard | Election Oracle',
  description:
    'How the model and the picks did against the actual 2026 Senate results, scored on the pre-election snapshot.',
};

const PARTY_TEXT: Record<string, string> = { D: 'text-dem', R: 'text-rep', I: 'text-stamp' };

export default function ScorecardPage() {
  const card = getScorecard();
  const live = getLiveForecast();

  if (!card || card.status === 'awaiting_results') {
    return (
      <div>
        <Head />
        {live && <LiveForecastPanel live={live} />}
        <EmptyState>
          No results called yet. Polls begin closing at 6pm ET on November 3; results are pulled
          every six hours after that and scored against the forecast as it stood before the first
          close.
          {card?.snapshot?.mode === 'git' && card.snapshot.committed_at && (
            <> Snapshot currently pinned to the {fmtStamp(card.snapshot.committed_at)} refresh.</>
          )}
        </EmptyState>
        <WhatIsScored picksMade={card?.picks_made ?? 0} numRaces={card?.num_races ?? 35} />
        <LastUpdated />
      </div>
    );
  }

  const m = card.model;
  const p = card.picks;
  const ch = card.chamber;

  return (
    <div>
      <Head />
      {live && <LiveForecastPanel live={live} />}

      <div className="mb-4 rounded-lg bg-cream-200 px-3.5 py-2 text-[11.5px] text-cocoa-500">
        {card.status === 'final' ? 'Final.' : `${card.num_called} of ${card.num_races} races called.`}{' '}
        Scored against the forecast and picks as committed on{' '}
        <strong className="text-cocoa-700">{fmtStamp(card.snapshot.committed_at)}</strong>
        {card.snapshot.ref && <> (commit {card.snapshot.ref.slice(0, 7)})</>}, before the first polls
        closed. Updated {fmtStamp(card.generated)}.
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Model calls right"
          value={m.n ? `${Math.round((m.accuracy ?? 0) * m.n)}/${m.n}` : '—'}
          tone="ink"
          sub={m.brier != null ? `Brier ${m.brier.toFixed(3)}` : undefined}
        />
        <StatCard
          label="Model margin error"
          value={m.margins.mae != null ? `${m.margins.mae.toFixed(1)} pts` : '—'}
          tone="ink"
          sub={m.margins.bias != null ? `bias ${signed(m.margins.bias)} toward ${m.margins.bias > 0 ? 'D' : 'R'}` : undefined}
        />
        <StatCard
          label="Picks right"
          value={p.n ? `${Math.round((p.accuracy ?? 0) * p.n)}/${p.n}` : '—'}
          tone="peach"
          sub={p.margins.mae != null ? `margin error ${p.margins.mae.toFixed(1)} pts` : `${card.picks_made} picks made`}
        />
        <StatCard
          label="Senate seats (D)"
          value={String(ch.dem_seats_so_far)}
          tone={ch.dem_seats_so_far >= 51 ? 'dem' : 'rep'}
          sub={
            ch.final
              ? `model had D control at ${fmtProb(ch.predicted_dem_control_prob ?? 0)}`
              : `${ch.races_outstanding} races outstanding`
          }
        />
      </div>

      <Panel title="Head to head" className="mt-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
                <th className="py-2 pr-4">Forecaster</th>
                <th className="py-2 pr-4 text-right">Races</th>
                <th className="py-2 pr-4 text-right">Calls right</th>
                <th className="py-2 pr-4 text-right">Brier</th>
                <th className="py-2 pr-4 text-right">Log-loss</th>
                <th className="py-2 text-right">Margin MAE</th>
              </tr>
            </thead>
            <tbody>
              <ScoreRow label="Our simulation" prob={m} margin={m.margins} />
              <ScoreRow label="Polls only (no fundamentals, no markets)" prob={m.polls_only} margin={m.poll_average_margins} />
              <ScoreRow label="Polymarket" prob={card.market} />
              <ScoreRow label="Tre's picks" prob={p} margin={p.margins} highlight />
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-cocoa-400">
          Brier is the mean squared error of the win probability: 0 is perfect, 0.25 is a coin flip.
          Picks are scored as 100% confidence in the chosen side. Each row covers only the called
          races where that forecaster had a number, so the race counts differ.
        </p>
      </Panel>

      {m.calibration.length > 0 && (
        <Panel title="Calibration — did 70% mean 70%?" className="mt-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {m.calibration.map((b) => (
              <div key={b.bin} className="rounded-lg border border-cream-300 bg-cream-50 px-3 py-2">
                <div className="text-[11px] text-cocoa-400">{b.bin} · {b.n} races</div>
                <div className="mt-0.5 text-sm text-cocoa-700">
                  said <strong>{Math.round(b.predicted * 100)}%</strong> · won{' '}
                  <strong>{Math.round(b.actual * 100)}%</strong>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <div className="mt-4 overflow-x-auto rounded-xl border border-cream-300 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
              <th className="px-4 py-3">State</th>
              <th className="px-4 py-3">Result</th>
              <th className="px-4 py-3 text-right">Model</th>
              <th className="px-4 py-3 text-right">Miss</th>
              <th className="px-4 py-3 text-right">Pick</th>
              <th className="px-4 py-3 text-right">Polymarket</th>
            </tr>
          </thead>
          <tbody>
            {[...card.races]
              .sort((a, b) => Number(b.called) - Number(a.called) || a.state.localeCompare(b.state))
              .map((r) => (
                <RaceRow key={r.state} r={r} />
              ))}
          </tbody>
        </table>
      </div>

      <WhatIsScored picksMade={card.picks_made} numRaces={card.num_races} />
      <LastUpdated />
    </div>
  );
}

function Head() {
  return (
    <PageHead
      kicker="Scorecard"
      title="How did we do?"
      sub={
        <>
          The forecast and{' '}
          <Link href="/predictions" className="text-peach underline">
            the picks
          </Link>{' '}
          were frozen before the first polls closed and are scored here against the certified
          results as they come in. No retroactive edits count.
        </>
      }
    />
  );
}

function ScoreRow({
  label,
  prob,
  margin,
  highlight = false,
}: {
  label: string;
  prob: ScoreProb;
  margin?: ScoreMargin;
  highlight?: boolean;
}) {
  const right = prob.n ? Math.round((prob.accuracy ?? 0) * prob.n) : null;
  return (
    <tr className={`border-b border-cream-100 last:border-0 ${highlight ? 'bg-peach-wash' : ''}`}>
      <td className="py-2 pr-4 font-medium text-cocoa-700">{label}</td>
      <td className="py-2 pr-4 text-right text-cocoa-500">{prob.n || '—'}</td>
      <td className="py-2 pr-4 text-right text-cocoa-700">
        {right != null ? `${right}/${prob.n}` : '—'}
      </td>
      <td className="py-2 pr-4 text-right text-cocoa-700">{prob.brier?.toFixed(3) ?? '—'}</td>
      <td className="py-2 pr-4 text-right text-cocoa-700">{prob.log_loss?.toFixed(3) ?? '—'}</td>
      <td className="py-2 text-right text-cocoa-700">{margin?.mae != null ? margin.mae.toFixed(1) : '—'}</td>
    </tr>
  );
}

function RaceRow({ r }: { r: ScorecardRace }) {
  const res = r.result;
  const modelP = r.model.dem_win_prob;
  return (
    <tr className={`border-b border-cream-100 last:border-0 ${r.called ? '' : 'text-cocoa-400'}`}>
      <td className="px-4 py-3 font-medium text-cocoa-700">{r.state}</td>
      <td className="px-4 py-3">
        {res ? (
          <>
            <strong className={PARTY_TEXT[res.winner_party ?? ''] ?? ''}>{res.winner ?? res.winner_party}</strong>
            {res.margin != null && <span className="ml-2 text-cocoa-500">{fmtMargin(res.margin)}</span>}
          </>
        ) : (
          <span>not called</span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        {modelP != null ? (
          <>
            <span className={modelP >= 0.5 ? 'text-dem' : 'text-rep'}>{fmtProb(modelP)} D</span>
            <span className="ml-1 text-xs text-cocoa-400">{fmtMargin(r.model.median_margin)}</span>
            <Mark ok={r.model.correct} />
          </>
        ) : (
          '—'
        )}
      </td>
      <td className="px-4 py-3 text-right text-cocoa-700">
        {r.model.margin_error != null ? signed(r.model.margin_error) : '—'}
      </td>
      <td className="px-4 py-3 text-right">
        {r.pick.party ? (
          <>
            <span className={PARTY_TEXT[r.pick.party] ?? ''}>
              {r.pick.party}
              {r.pick.margin != null && `+${r.pick.margin.toFixed(1)}`}
            </span>
            <Mark ok={r.pick.correct} />
          </>
        ) : r.pick.on_board ? (
          <span className="text-cocoa-400">no call</span>
        ) : (
          <span className="text-cocoa-300">—</span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        {r.market.polymarket_dem_prob != null ? (
          <>
            {fmtProb(r.market.polymarket_dem_prob)} D<Mark ok={r.market.correct} />
          </>
        ) : (
          <span className="text-cocoa-300">—</span>
        )}
      </td>
    </tr>
  );
}

function Mark({ ok }: { ok?: boolean }) {
  if (ok == null) return null;
  return (
    <span className={`ml-1.5 font-bold ${ok ? 'text-stamp' : 'text-rep'}`} aria-label={ok ? 'correct' : 'wrong'}>
      {ok ? '✓' : '✗'}
    </span>
  );
}

function WhatIsScored({ picksMade, numRaces }: { picksMade: number; numRaces: number }) {
  return (
    <div className="mt-8 rounded-xl border border-peach-border bg-peach-wash p-5 text-sm text-cocoa-700">
      <h3 className="font-display text-lg text-ink">What gets scored, and how</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        <li>
          <strong>The snapshot.</strong> The last data refresh committed before 6pm ET on November 3
          is the record. Later refreshes and later edits to the picks file are ignored, so{' '}
          {picksMade === 0 ? 'picks have to be committed before then to count' : `the ${picksMade} picks on file at that moment are the ones scored`}.
        </li>
        <li>
          <strong>The results.</strong> Pulled from each race&rsquo;s Wikipedia article once a
          results table with real vote counts appears, with a hand-correction file for anything the
          scraper gets wrong. Only called races are scored, so early numbers move.
        </li>
        <li>
          <strong>The yardsticks.</strong> Calls right, Brier score and log-loss for probabilities;
          mean absolute error and bias for margins; the chamber call once all {numRaces} races are
          in. Polymarket is scored on the races where it had a market.
        </li>
      </ul>
    </div>
  );
}

function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return 'unknown time';
  return new Date(iso).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York' }) + ' ET';
}

function signed(n: number): string {
  const r = Number(n.toFixed(1));
  return `${r > 0 ? '+' : ''}${r.toFixed(1)}`;
}
