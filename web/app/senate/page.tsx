import Link from 'next/link';
import LastUpdated from '@/app/components/LastUpdated';
import SenateRaceCard from '@/app/components/SenateRaceCard';
import { getSenate } from '@/app/lib/data';

export default function SenatePage() {
  const { races } = getSenate();
  const keyRaces = races.filter((r) => r.dem_candidate != null);
  const otherRaces = races.filter((r) => r.dem_candidate == null);

  return (
    <div>
      <h2 className="text-2xl font-bold">Senate Race Trackers</h2>
      <p className="mt-1 text-sm text-slate-500">
        Per-race weighted polling averages for the key 2026 races. Toggle the
        experimental NYT vibes adjustment on each card, and compare against
        Polymarket and Kalshi implied odds. For win probabilities and the
        chamber-control simulation, see the{' '}
        <Link href="/senate-forecast" className="text-blue-600 underline">
          Senate Forecast
        </Link>
        .
      </p>

      {keyRaces.length > 0 ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {keyRaces.map((race) => (
            <SenateRaceCard key={race.state} race={race} />
          ))}
        </div>
      ) : (
        <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          No Senate races with polling data yet.
        </div>
      )}

      {otherRaces.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
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
                  <tr key={race.state} className="border-b border-slate-100 last:border-0">
                    <td className="px-4 py-3 font-medium">{race.state}</td>
                    <td className="px-4 py-3">
                      {ranked.slice(0, 3).map(([name, pct]) => (
                        <span key={name} className="mr-3 whitespace-nowrap">
                          {name}: <strong>{pct.toFixed(1)}%</strong>
                        </span>
                      ))}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {race.margin != null
                        ? `${race.margin > 0 ? '+' : ''}${race.margin.toFixed(1)}`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-500">{race.num_polls}</td>
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

function VibesExplainer() {
  return (
    <div className="mt-8 rounded-lg border border-indigo-100 bg-indigo-50/50 p-5 text-sm text-slate-700">
      <h3 className="font-semibold text-slate-900">
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
      <p className="mt-2 text-xs text-slate-500">
        The coefficients are conservative priors, not fitted values; they will be
        backtested as labelled cycles accumulate. When coverage data hasn&rsquo;t been
        fetched yet, the toggle is disabled and the base average is shown.
      </p>
    </div>
  );
}
