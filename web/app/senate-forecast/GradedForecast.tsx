import Link from 'next/link';
import {
  ForecasterGradesPanel,
  GradingRubric,
  PollsterGradesPanel,
  ReportCardPanel,
} from '@/app/components/Grades';
import LastUpdated from '@/app/components/LastUpdated';
import SeatDistributionChart from '@/app/components/SeatDistributionChart';
import SeatRankChart from '@/app/components/SeatRankChart';
import { PageHead, Panel, StatCard } from '@/app/components/ui';
import type { Scorecard, ScorecardRace, SenateForecastData } from '@/app/lib/data';
import { fmtMargin, fmtProb } from '@/app/lib/format';

const PARTY_TEXT: Record<string, string> = { D: 'text-dem', R: 'text-rep', I: 'text-stamp' };

function signed(n: number): string {
  const r = Number(n.toFixed(1));
  return `${r > 0 ? '+' : ''}${r.toFixed(1)}`;
}

function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return 'an unknown time';
  return (
    new Date(iso).toLocaleString('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'America/New_York',
    }) + ' ET'
  );
}

// "D 93%" / "R 87%" / "I 23%" — the side the forecast favoured and how hard.
function callText(r: ScorecardRace): { side: string; text: string } | null {
  const p = r.model.dem_win_prob;
  if (p == null) return null;
  const side = p >= 0.5 ? (r.race?.challenger_party ?? 'D') : 'R';
  return { side, text: `${side} ${fmtProb(p >= 0.5 ? p : 1 - p)}` };
}

// A margin in the challenger's terms: "I" replaces "D" where an independent
// sat in the challenger column.
function sideMargin(margin: number | null | undefined, r: ScorecardRace): string {
  const text = fmtMargin(margin);
  return r.race?.challenger_party === 'I' ? text.replace(/^D/, 'I') : text;
}

// The forecast pages after the election: the frozen pre-election forecast,
// race by race, next to what happened.
export default function GradedForecast({
  card,
  forecast,
}: {
  card: Scorecard;
  forecast: SenateForecastData;
}) {
  const m = card.model;
  const ch = card.chamber;
  const final = card.status === 'final';
  const demPct = Math.round(forecast.dem_control_prob * 100);
  const called = card.races.filter((r) => r.result);
  const wrong = called.filter((r) => r.model.correct === false);
  const flips = called.filter((r) => r.result?.flipped);
  const byMiss = called
    .filter((r) => r.model.margin_error != null)
    .sort((a, b) => Math.abs(b.model.margin_error!) - Math.abs(a.model.margin_error!));
  // Most competitive first, as the forecast saw it.
  const ordered = [...card.races].sort(
    (a, b) =>
      Math.abs((a.model.dem_win_prob ?? 0.5) - 0.5) - Math.abs((b.model.dem_win_prob ?? 0.5) - 0.5),
  );
  const outcomes = Object.fromEntries(
    called.map((r) => [
      r.state,
      { winnerParty: r.result!.winner_party, correct: r.model.correct ?? null },
    ]),
  );
  const pct = ch.seat_percentile;
  const controlRight =
    ch.dem_control_actual == null ? null : forecast.dem_control_prob >= 0.5 === ch.dem_control_actual;
  const band = m.band_coverage;

  return (
    <div>
      <PageHead
        kicker="Senate Forecast · Graded"
        title="How the Senate forecast held up"
        sub={
          <>
            The forecast below is the one on the site at{' '}
            <strong className="text-cocoa-700">{fmtStamp(card.snapshot.committed_at)}</strong>, before
            the first polls closed. Nothing in it has been touched since. Each race is set against
            the result{final ? '' : ` (${card.num_called} of ${card.num_races} called so far)`}, and
            the whole thing gets a letter.
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Overall grade"
          value={card.report_card?.overall ?? '—'}
          tone="peach"
          sub={final ? 'all four subjects in' : 'provisional'}
        />
        <StatCard
          label="Winners called"
          value={m.n ? `${Math.round((m.accuracy ?? 0) * m.n)}/${m.n}` : '—'}
          tone="ink"
          sub={wrong.length ? `missed ${wrong.map((r) => r.state).join(', ')}` : 'no misses'}
        />
        <StatCard
          label="Average margin miss"
          value={m.margins.mae != null ? `${m.margins.mae.toFixed(1)} pts` : '—'}
          tone="ink"
          sub={
            m.margins.bias != null
              ? `${Math.abs(m.margins.bias).toFixed(1)} too ${m.margins.bias > 0 ? 'Republican' : 'Democratic'} on average`
              : undefined
          }
        />
        <StatCard
          label="Democratic seats"
          value={String(ch.dem_seats_so_far)}
          tone={ch.dem_seats_so_far >= forecast.dem_majority_threshold ? 'dem' : 'rep'}
          sub={`we forecast ${forecast.mean_dem_seats.toFixed(1)}`}
        />
      </div>

      {card.report_card && <ReportCardPanel card={card.report_card} className="mt-4" />}

      <Panel title="The chamber — what we said, what happened" className="mt-4">
        <div className="mb-1.5 flex justify-between text-[11px] font-bold">
          <span className="text-dem">We said: Democrats {demPct}%</span>
          <span className="text-rep">Republicans {100 - demPct}%</span>
        </div>
        <div className="flex h-3.5 overflow-hidden rounded-full">
          <div className="bg-dem" style={{ width: `${demPct}%` }} />
          <div className="bg-rep" style={{ width: `${100 - demPct}%` }} />
        </div>
        <p className="mt-3 text-sm leading-relaxed text-cocoa-700">
          {ch.dem_control_actual == null ? (
            <>
              Democrats have {ch.dem_seats_so_far} seats with {ch.races_outstanding} races still
              out.
            </>
          ) : (
            <>
              <strong className={ch.dem_control_actual ? 'text-dem' : 'text-rep'}>
                {ch.dem_control_actual ? 'Democrats' : 'Republicans'} won the chamber
              </strong>
              , {ch.dem_seats_so_far} seats to {100 - ch.dem_seats_so_far}. The forecast had the{' '}
              {controlRight ? 'right' : 'wrong'} party favoured
              {pct && (
                <>
                  , but the average simulation gave Democrats {forecast.mean_dem_seats.toFixed(1)}{' '}
                  seats, and only <strong>{(pct.share_at_or_above * 100).toFixed(1)}%</strong> of
                  simulations had them at {ch.dem_seats_so_far} or more
                </>
              )}
              . {flips.length > 0 && (
                <>
                  {flips.length} seats changed hands: {flips.map((r) => r.state).join(', ')}.
                </>
              )}
            </>
          )}
        </p>
        <div className="mt-3">
          <SeatDistributionChart forecast={forecast} actualSeats={final ? ch.dem_seats_so_far : null} />
        </div>
        <p className="mt-1 text-xs text-cocoa-400">
          Bars are the {forecast.num_simulations.toLocaleString()} simulated outcomes from the frozen
          forecast; the peach line is where the count ended up.
        </p>
      </Panel>

      <Panel title="Every seat as we shaded it, with the misses marked" className="mt-4">
        <SeatRankChart
          races={forecast.races}
          demHoldovers={forecast.dem_safe_seats}
          threshold={forecast.dem_majority_threshold}
          outcomes={outcomes}
        />
      </Panel>

      {byMiss.length > 0 && (
        <Panel title="Where it went wrong" className="mt-4">
          <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-cocoa-700">
            {wrong.length > 0 && (
              <li>
                <strong>Wrong winner in {wrong.length} of {m.n}.</strong>{' '}
                {wrong
                  .map((r) => {
                    const c = callText(r);
                    return `${r.state} (we had ${c?.text ?? '—'}; ${r.result?.winner ?? r.result?.winner_party} won by ${sideMargin(r.result?.margin, r).replace(/^[DRI]\+/, '')})`;
                  })
                  .join('; ')}
                .
              </li>
            )}
            {m.margins.bias != null && Math.abs(m.margins.bias) >= 1 && (
              <li>
                <strong>
                  The margins ran {Math.abs(m.margins.bias).toFixed(1)} points too{' '}
                  {m.margins.bias > 0 ? 'Republican' : 'Democratic'}.
                </strong>{' '}
                {called.filter((r) => (r.model.margin_error ?? 0) > 0).length} of {m.margins.n} races
                finished more Democratic than the median forecast. A miss that goes the same way
                almost everywhere is the national error the simulation allows for, but this one was
                bigger than it budgeted.
              </li>
            )}
            {band && band.share != null && (
              <li>
                <strong>
                  The 80% ranges were too narrow: {band.inside} of {band.n} results landed inside.
                </strong>{' '}
                A well-sized 80% range holds about {Math.round(band.n * 0.8)} of {band.n}.
              </li>
            )}
            <li>
              <strong>Biggest margin misses.</strong>{' '}
              {byMiss
                .slice(0, 5)
                .map(
                  (r) =>
                    `${r.state} (${sideMargin(r.model.median_margin, r)} forecast, ${sideMargin(r.result?.margin, r)} actual)`,
                )
                .join('; ')}
              .
            </li>
          </ul>
        </Panel>
      )}

      {/* Race by race — cards on phones, a table from sm up. */}
      <h3 className="mt-6 font-display text-xl text-ink">Race by race</h3>
      <p className="mt-1 text-sm text-cocoa-500">
        Closest forecasts first. &ldquo;Miss&rdquo; is the result minus the median forecast margin:
        a D means the Democrat did better than we said.
      </p>

      <div className="mt-3 grid gap-3 sm:hidden">
        {ordered.map((r) => (
          <RaceCard key={r.state} r={r} />
        ))}
      </div>

      <div className="mt-3 hidden overflow-x-auto rounded-xl border border-cream-300 bg-white sm:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
              <th className="px-4 py-3">Race</th>
              <th className="px-4 py-3 text-right">We said</th>
              <th className="px-4 py-3 text-right">Forecast margin</th>
              <th className="px-4 py-3">Result</th>
              <th className="px-4 py-3 text-right">Miss</th>
              <th className="px-4 py-3 text-right">In 80% range</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((r) => (
              <RaceRow key={r.state} r={r} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-cocoa-400">
        (I) races have no Democrat in the challenger column, so the forecast and the result are both
        the independent against the Republican. † flipped seat.
      </p>

      {card.forecasters && card.forecasters.length > 0 && (
        <ForecasterGradesPanel
          forecasters={card.forecasters}
          numRaces={card.num_races}
          className="mt-6"
        />
      )}

      {card.pollster_grades && (
        <PollsterGradesPanel
          grades={card.pollster_grades}
          limit={8}
          className="mt-4"
          moreHref={
            <Link href="/pollsters" className="text-peach underline">
              See every pollster&rsquo;s grade
            </Link>
          }
        />
      )}

      {card.report_card && <GradingRubric card={card.report_card} />}

      <div className="mt-4 rounded-xl border border-peach-border bg-peach-wash p-5 text-sm text-cocoa-700">
        <h3 className="font-display text-lg text-ink">What was being graded</h3>
        <p className="mt-2 leading-relaxed">
          The forecast ran {forecast.num_simulations.toLocaleString()} simulated elections from each
          race&rsquo;s polling average and a fundamentals prior, with a shared national error (σ ={' '}
          {forecast.national_sigma}), a per-race error (σ = {forecast.race_sigma}) and prediction
          markets blended in at {(forecast.market_weight * 100).toFixed(0)}%. The{' '}
          <Link href="/methodology" className="text-peach underline">
            methodology
          </Link>{' '}
          has the detail, the{' '}
          <Link href="/scorecard" className="text-peach underline">
            scorecard
          </Link>{' '}
          has calibration and the picks, and the{' '}
          <Link href="/senate" className="text-peach underline">
            Senate page
          </Link>{' '}
          has each race&rsquo;s polling average against its result.
        </p>
      </div>

      <LastUpdated />
    </div>
  );
}

function Verdict({ ok }: { ok: boolean | null | undefined }) {
  if (ok == null) return null;
  return (
    <span
      className={`ml-1.5 font-bold ${ok ? 'text-stamp' : 'text-rep'}`}
      aria-label={ok ? 'correct' : 'wrong'}
    >
      {ok ? '✓' : '✗'}
    </span>
  );
}

function raceLabel(r: ScorecardRace) {
  const ch = r.race?.challenger_party === 'I' ? 'I' : 'D';
  return (
    <>
      {r.race?.dem_candidate ?? '—'} ({ch}) v. {r.race?.rep_candidate ?? '—'} (R)
    </>
  );
}

function ResultText({ r }: { r: ScorecardRace }) {
  const res = r.result;
  if (!res) return <span className="text-cocoa-400">not called</span>;
  return (
    <>
      <strong className={PARTY_TEXT[res.winner_party ?? ''] ?? ''}>
        {res.winner ?? res.winner_party}
      </strong>
      {res.margin != null && <span className="ml-1.5 text-cocoa-500">{sideMargin(res.margin, r)}</span>}
      {res.flipped && (
        <span className="ml-1 text-peach" title="Seat changed hands">
          †
        </span>
      )}
    </>
  );
}

function MissText({ r }: { r: ScorecardRace }) {
  const e = r.model.margin_error;
  if (e == null) return <span className="text-cocoa-300">—</span>;
  const big = Math.abs(e) >= 8;
  return (
    <span className={big ? 'font-semibold text-peach' : 'text-cocoa-700'}>
      {Number(e.toFixed(1)) === 0 ? '0.0' : `${e > 0 ? 'D' : 'R'} ${signed(Math.abs(e))}`}
    </span>
  );
}

function RaceRow({ r }: { r: ScorecardRace }) {
  const call = callText(r);
  return (
    <tr
      className={`border-b border-cream-100 last:border-0 ${r.model.correct === false ? 'bg-rep-wash/60' : ''}`}
    >
      <td className="px-4 py-3">
        <div className="font-medium text-cocoa-700">{r.state}</div>
        <div className="text-xs text-cocoa-400">{raceLabel(r)}</div>
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right">
        {call ? (
          <>
            <span className={`font-semibold ${PARTY_TEXT[call.side] ?? ''}`}>{call.text}</span>
            <Verdict ok={r.model.correct} />
          </>
        ) : (
          '—'
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right text-cocoa-700">
        {sideMargin(r.model.median_margin, r)}
        {r.model.margin_p10 != null && r.model.margin_p90 != null && (
          <div className="text-[11px] text-cocoa-400">
            {sideMargin(r.model.margin_p10, r)} to {sideMargin(r.model.margin_p90, r)}
          </div>
        )}
      </td>
      <td className="px-4 py-3">
        <ResultText r={r} />
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right">
        <MissText r={r} />
      </td>
      <td className="px-4 py-3 text-right">
        {r.model.in_80_band == null ? (
          <span className="text-cocoa-300">—</span>
        ) : r.model.in_80_band ? (
          <span className="text-stamp">inside</span>
        ) : (
          <span className="text-peach">outside</span>
        )}
      </td>
    </tr>
  );
}

function RaceCard({ r }: { r: ScorecardRace }) {
  const call = callText(r);
  return (
    <div
      className={`rounded-xl border p-4 ${r.model.correct === false ? 'border-rep-border bg-rep-wash' : 'border-cream-300 bg-white'}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium text-cocoa-700">{r.state}</div>
          <div className="mt-0.5 text-xs text-cocoa-400">{raceLabel(r)}</div>
        </div>
        {call && (
          <div className="whitespace-nowrap text-right text-sm">
            <span className={`font-semibold ${PARTY_TEXT[call.side] ?? ''}`}>{call.text}</span>
            <Verdict ok={r.model.correct} />
          </div>
        )}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div>
          <dt className="text-cocoa-400">Forecast margin</dt>
          <dd className="mt-0.5 text-sm text-cocoa-700">{sideMargin(r.model.median_margin, r)}</dd>
        </div>
        <div>
          <dt className="text-cocoa-400">Result</dt>
          <dd className="mt-0.5 text-sm">
            <ResultText r={r} />
          </dd>
        </div>
        <div>
          <dt className="text-cocoa-400">Miss</dt>
          <dd className="mt-0.5 text-sm">
            <MissText r={r} />
          </dd>
        </div>
        <div>
          <dt className="text-cocoa-400">80% range</dt>
          <dd className="mt-0.5 text-sm text-cocoa-700">
            {r.model.in_80_band == null ? '—' : r.model.in_80_band ? 'inside' : 'outside'}
          </dd>
        </div>
      </dl>
    </div>
  );
}
