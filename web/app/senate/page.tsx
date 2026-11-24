import Link from 'next/link';
import LastUpdated from '@/app/components/LastUpdated';
import DataFreshnessBanner from '@/app/components/DataFreshnessBanner';
import SenateRaceCard from '@/app/components/SenateRaceCard';
import RaceDumbbellChart from '@/app/components/RaceDumbbellChart';
import { GradeBadge } from '@/app/components/Grades';
import { EmptyState, PageHead, Panel } from '@/app/components/ui';
import {
  getFinalSenate,
  getGradedScorecard,
  getSenate,
  type Scorecard,
  type ScorecardRace,
} from '@/app/lib/data';
import { fmtMargin } from '@/app/lib/format';

export default function SenatePage() {
  // After the election the cards show the frozen pre-election numbers, each
  // set against its result.
  const card = getGradedScorecard();
  const { races } = card ? getFinalSenate() : getSenate();
  const scored: Record<string, ScorecardRace> = Object.fromEntries(
    (card?.races ?? []).map((r) => [r.state, r]),
  );
  const keyRaces = races.filter((r) => r.dem_candidate != null);
  const otherRaces = races.filter((r) => r.dem_candidate == null);

  return (
    <div>
      {card ? (
        <PageHead
          kicker="Senate Battlegrounds · Graded"
          title="The races that decided the chamber"
          sub={
            <>
              Each card shows where a race stood on the morning of the election — the final
              polling average and our forecast — and then what the voters did. Green cards we
              called, red ones we missed. For the chamber total and the letter grades, see the{' '}
              <Link href="/senate-forecast" className="text-peach underline">
                graded Senate Forecast
              </Link>
              .
            </>
          }
        />
      ) : (
        <PageHead
          kicker="Senate Battlegrounds"
          title="The races that decide the chamber"
          sub={
            <>
              Each card shows our forecast for the key 2026 races — who wins, in
              what share of {' '}
              <Link href="/senate-forecast" className="text-peach underline">
                50,000 simulations
              </Link>
              , and the median margin — built from the weighted polling average,
              fundamentals and the national environment. Click a card to chart the
              race; toggle the experimental NYT vibes adjustment or compare against
              Polymarket and Kalshi. For the chamber-control total, see the{' '}
              <Link href="/senate-forecast" className="text-peach underline">
                Senate Forecast
              </Link>
              .
            </>
          }
        />
      )}
      {!card && <DataFreshnessBanner feed="senate" />}

      {card && <PollsVsResults card={card} />}

      {keyRaces.length > 0 && (
        <Panel
          title={
            card
              ? 'Where the polls left it — final averages in the closest races'
              : 'If the election were held today — polling averages in the closest races'
          }
          className="mb-5"
        >
          <RaceDumbbellChart races={keyRaces} />
          <p className="mt-1 text-xs text-cocoa-400">
            Dots are each candidate&rsquo;s weighted polling average; the bands are the
            average&rsquo;s confidence interval, which narrows as more polls arrive. Races with at
            least five polls, closest dozen shown.
          </p>
        </Panel>
      )}

      {keyRaces.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {keyRaces.map((race) => (
            <SenateRaceCard key={race.state} race={race} scored={scored[race.state]} />
          ))}
        </div>
      ) : (
        <EmptyState>No Senate races with polling data yet.</EmptyState>
      )}

      {otherRaces.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-xl border border-cream-300 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Candidate averages</th>
                <th className="px-4 py-3 text-right">Margin</th>
                <th className="px-4 py-3 text-right">Polls</th>
              </tr>
            </thead>
            <tbody>
              {otherRaces.map((race) => {
                const ranked = Object.entries(race.candidates).sort((a, b) => b[1] - a[1]);
                return (
                  <tr key={race.state} className="border-b border-cream-100 last:border-0">
                    <td className="px-4 py-3 font-medium text-cocoa-700">{race.state}</td>
                    <td className="px-4 py-3 text-cocoa-500">
                      {ranked.slice(0, 3).map(([name, pct]) => (
                        <span key={name} className="mr-3 whitespace-nowrap">
                          {name}: <strong className="text-cocoa-700">{pct.toFixed(1)}%</strong>
                        </span>
                      ))}
                    </td>
                    <td className="px-4 py-3 text-right text-cocoa-700">
                      {race.margin != null
                        ? `${race.margin > 0 ? '+' : ''}${race.margin.toFixed(1)}`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-cocoa-400">{race.num_polls}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <VibesExplainer />
      <LastUpdated />
    </div>
  );
}

// The final polling average in each polled race against the result, worst
// miss first, with the polls-only line from the forecaster grades on top.
function PollsVsResults({ card }: { card: Scorecard }) {
  const rows = card.races
    .filter((r) => r.result?.margin != null && r.model.poll_margin != null)
    .map((r) => ({ r, err: r.result!.margin! - r.model.poll_margin! }))
    .sort((a, b) => Math.abs(b.err) - Math.abs(a.err));
  if (rows.length === 0) return null;
  const pm = card.model.poll_average_margins;
  const leaderOf = (x: (typeof rows)[number]) => x.r.model.poll_margin! > 0;
  const led = rows.filter((x) => x.r.model.poll_margin !== 0);
  const leaderRight = led.filter((x) => leaderOf(x) === x.r.result!.margin! > 0).length;
  const TOP = 8;
  const demBeat = rows.filter((x) => x.err > 0).length;
  const side = (v: number | null | undefined, r: ScorecardRace) => {
    const t = fmtMargin(v);
    return r.race?.challenger_party === 'I' ? t.replace(/^D/, 'I') : t;
  };
  return (
    <Panel title="The polling averages, graded" className="mb-5">
      <div className="flex flex-wrap items-center gap-3">
        <GradeBadge grade={card.model.poll_average_grade} size="lg" empty="—" />
        <p className="min-w-0 flex-1 text-sm leading-relaxed text-cocoa-700">
          Across {pm.n} polled races the final average missed the margin by{' '}
          <strong>{pm.mae?.toFixed(1)} points</strong>
          {pm.bias != null && (
            <>
              {' '}and ran <strong>{Math.abs(pm.bias).toFixed(1)} too {pm.bias > 0 ? 'Republican' : 'Democratic'}</strong>
            </>
          )}
          : the {demBeat > rows.length / 2 ? 'Democrat' : 'Republican'} beat the average in{' '}
          {Math.max(demBeat, rows.length - demBeat)} of {rows.length}.
          {led.length > 0 && (
            <>
              {' '}The leader in the average won {leaderRight} of {led.length}.
            </>
          )}
        </p>
      </div>
      <PollMissTable rows={rows.slice(0, TOP)} side={side} />
      {rows.length > TOP && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs font-semibold text-peach">
            Show the other {rows.length - TOP} races
          </summary>
          <PollMissTable rows={rows.slice(TOP)} side={side} />
        </details>
      )}
      <p className="mt-2 text-xs text-cocoa-400">
        Miss is the result minus the final average: D means the Democrat did better than the
        polls. For individual pollsters, see the{' '}
        <Link href="/pollsters" className="text-peach underline">
          pollster grades
        </Link>
        .
      </p>
    </Panel>
  );
}

function VibesExplainer() {
  return (
    <div className="mt-8 rounded-xl border border-peach-border bg-peach-wash p-5 text-sm text-cocoa-700">
      <h3 className="font-display text-lg text-ink">
        How the NYT &ldquo;vibes&rdquo; component works
      </h3>
      <p className="mt-2">
        The vibes layer is an <strong>experimental adjustment</strong> on top of the
        base polling average. It tries to capture momentum and scandal effects that
        polls pick up only with a lag:
      </p>
      <ol className="mt-2 list-decimal space-y-1 pl-5">
        <li>
          We pull each candidate&rsquo;s recent New York Times coverage (Archive API)
          and extract every sentence that mentions them.
        </li>
        <li>
          A sentiment model scores each mention, producing a five-point tone bucket
          from <em>overwhelmingly negative</em> (−2) to <em>overwhelmingly
          positive</em> (+2), plus a 0–1 scandal-severity score from curated
          triggers (indictment, ethics investigation, resignation, …).
        </li>
        <li>
          Each candidate&rsquo;s effect on the margin is{' '}
          <code className="rounded bg-white px-1">0.4 × tone − 2.5 × scandal</code>{' '}
          points; the race adjustment is the Democrat&rsquo;s effect minus the
          Republican&rsquo;s, capped at ±3 points so vibes can nudge — never
          overturn — what the polls say.
        </li>
      </ol>
      <p className="mt-2 text-xs text-cocoa-500">
        The coefficients are conservative priors, not fitted values; they will be
        backtested as labelled cycles accumulate. When coverage data hasn&rsquo;t been
        fetched yet, the toggle is disabled and the base average is shown.
      </p>
    </div>
  );
}

function PollMissTable({
  rows,
  side,
}: {
  rows: { r: ScorecardRace; err: number }[];
  side: (v: number | null | undefined, r: ScorecardRace) => string;
}) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full table-fixed text-sm">
        <thead>
          <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
            <th className="w-[34%] py-2 pr-3">State</th>
            <th className="py-2 pr-3 text-right">Polls</th>
            <th className="py-2 pr-3 text-right">Final avg</th>
            <th className="py-2 pr-3 text-right">Result</th>
            <th className="py-2 text-right">Miss</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ r, err }) => {
            const wrongLeader =
              r.model.poll_margin !== 0 && r.model.poll_margin! > 0 !== r.result!.margin! > 0;
            return (
              <tr key={r.state} className="border-b border-cream-100 last:border-0">
                <td className="py-2 pr-3 font-medium text-cocoa-700">
                  {r.state}
                  {wrongLeader && (
                    <span className="ml-1.5 whitespace-nowrap text-[11px] font-semibold text-rep">
                      wrong leader
                    </span>
                  )}
                </td>
                <td className="py-2 pr-3 text-right text-cocoa-400">{r.model.num_polls ?? '—'}</td>
                <td className="py-2 pr-3 text-right text-cocoa-700">{side(r.model.poll_margin, r)}</td>
                <td className="py-2 pr-3 text-right text-cocoa-700">{side(r.result!.margin, r)}</td>
                <td
                  className={`py-2 text-right ${Math.abs(err) >= 8 ? 'font-semibold text-peach' : 'text-cocoa-700'}`}
                >
                  {Number(err.toFixed(1)) === 0
                    ? '0.0'
                    : `${err > 0 ? 'D' : 'R'} +${Math.abs(err).toFixed(1)}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
