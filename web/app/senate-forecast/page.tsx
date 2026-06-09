import Link from 'next/link';
import LastUpdated from '@/app/components/LastUpdated';
import SeatDistributionChart from '@/app/components/SeatDistributionChart';
import { getSenateForecast } from '@/app/lib/data';

const MARKET_LABELS: Record<string, string> = {
  polymarket: 'Polymarket',
  kalshi: 'Kalshi',
};

export default function SenateForecastPage() {
  const forecast = getSenateForecast();

  if (!forecast) {
    return (
      <div>
        <h2 className="text-2xl font-bold">Who Wins the Senate?</h2>
        <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          No simulation output yet — run scripts/export_json.py.
        </div>
      </div>
    );
  }

  const demPct = (forecast.dem_control_prob * 100).toFixed(0);
  const repPct = ((1 - forecast.dem_control_prob) * 100).toFixed(0);

  return (
    <div>
      <h2 className="text-2xl font-bold">Who Wins the Senate?</h2>
      <p className="mt-1 text-sm text-slate-500">
        {forecast.num_simulations.toLocaleString()} Monte Carlo simulations of the
        key races, with correlated national polling error.{' '}
        <span className="font-medium text-amber-700">{forecast.label}</span>
      </p>

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="D keeps/takes control" value={`${demPct}%`} accent="text-dem" />
        <Stat label="R control" value={`${repPct}%`} accent="text-rep" />
        <Stat label="Mean D seats" value={forecast.mean_dem_seats.toFixed(1)} />
        <Stat label="Median D seats" value={forecast.median_dem_seats.toFixed(0)} />
      </div>

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-700">
          Seat distribution across {forecast.num_simulations.toLocaleString()} simulations
        </h3>
        <SeatDistributionChart forecast={forecast} />
        <p className="mt-1 text-xs text-slate-400">
          Baseline: {forecast.dem_safe_seats} safe D seats + {forecast.rep_safe_seats} safe R
          seats; {forecast.races.length} competitive races simulated. Democrats need{' '}
          {forecast.dem_majority_threshold} seats for control.
        </p>
      </div>

      {Object.keys(forecast.market_control_dem_prob).length > 0 && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">
            Our simulation vs prediction markets — P(Democratic control)
          </h3>
          <div className="flex flex-wrap gap-3">
            <ComparisonChip label="Our model" pct={forecast.dem_control_prob} highlight />
            {Object.entries(forecast.market_control_dem_prob).map(([source, prob]) => (
              <ComparisonChip
                key={source}
                label={MARKET_LABELS[source] ?? source}
                pct={prob}
              />
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-400">
            Market odds also feed the per-race blend (weight{' '}
            {(forecast.market_weight * 100).toFixed(0)}% market /{' '}
            {((1 - forecast.market_weight) * 100).toFixed(0)}% polls).
          </p>
        </div>
      )}

      <div className="mt-6 overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="px-4 py-3">Race</th>
              <th className="px-4 py-3 text-right">Polling margin</th>
              <th className="px-4 py-3 text-right">P(D) polls only</th>
              <th className="px-4 py-3 text-right">P(D) blended</th>
              <th className="px-4 py-3 text-right">Polymarket</th>
              <th className="px-4 py-3 text-right">Kalshi</th>
            </tr>
          </thead>
          <tbody>
            {forecast.races.map((race) => (
              <tr key={race.state} className="border-b border-slate-100 last:border-0">
                <td className="px-4 py-3 font-medium">
                  {race.state}
                  <span className="ml-2 text-xs font-normal text-slate-400">
                    {race.dem_candidate} (D) v. {race.rep_candidate} (R)
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {race.margin != null
                    ? `${race.margin > 0 ? 'D' : 'R'} +${Math.abs(race.margin).toFixed(1)}`
                    : '—'}
                </td>
                <Prob value={race.dem_win_prob_polls} />
                <Prob value={race.dem_win_prob_blended} bold />
                <Prob value={race.market_dem_prob.polymarket ?? null} />
                <Prob value={race.market_dem_prob.kalshi ?? null} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-8 rounded-lg border border-slate-200 bg-slate-50 p-5 text-sm text-slate-700">
        <h3 className="font-semibold text-slate-900">How the simulation works</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            Each race&rsquo;s <Link href="/senate" className="text-blue-600 underline">polling
            average</Link> margin is converted to a win probability using a normal
            error model: a national error (σ = {forecast.national_sigma}) shared by every
            race plus an independent per-race error (σ = {forecast.race_sigma}), sized to
            historical Senate polling misses.
          </li>
          <li>
            Prediction-market odds are blended in at{' '}
            {(forecast.market_weight * 100).toFixed(0)}% weight — markets aggregate
            information polls miss, and the weight is a tunable model parameter.
          </li>
          <li>
            We then simulate {forecast.num_simulations.toLocaleString()} elections. The
            shared national error is what makes sweeps (all close races breaking one
            way) more likely than independent coin flips would suggest.
          </li>
          <li>
            This is a <strong>nowcast</strong> — &ldquo;if the election were held
            today&rdquo; — not a calibrated election-day forecast. It will graduate
            once backtesting across past cycles is complete.
          </li>
        </ul>
      </div>

      <LastUpdated />
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 text-center">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${accent ?? 'text-slate-900'}`}>{value}</div>
    </div>
  );
}

function ComparisonChip({
  label,
  pct,
  highlight,
}: {
  label: string;
  pct: number;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border px-4 py-2 text-center ${
        highlight ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white'
      }`}
    >
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-bold text-slate-900">{(pct * 100).toFixed(0)}%</div>
    </div>
  );
}

function Prob({ value, bold }: { value: number | null; bold?: boolean }) {
  return (
    <td className={`px-4 py-3 text-right ${bold ? 'font-semibold' : 'text-slate-600'}`}>
      {value != null ? `${(value * 100).toFixed(0)}%` : '—'}
    </td>
  );
}
