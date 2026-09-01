import Link from 'next/link';
import LastUpdated from '@/app/components/LastUpdated';
import SeatDistributionChart from '@/app/components/SeatDistributionChart';
import { EmptyState, PageHead, Panel, StatCard } from '@/app/components/ui';
import { getSenateForecast, type NationalEnvironment } from '@/app/lib/data';

const MARKET_LABELS: Record<string, string> = {
  polymarket: 'Polymarket',
  kalshi: 'Kalshi',
};

export default function SenateForecastPage() {
  const forecast = getSenateForecast();

  if (!forecast) {
    return (
      <div>
        <PageHead kicker="Senate Forecast" title="Who controls the Senate after November?" />
        <EmptyState>No simulation output yet — run scripts/export_json.py.</EmptyState>
      </div>
    );
  }

  const demPct = (forecast.dem_control_prob * 100).toFixed(0);
  const repPct = ((1 - forecast.dem_control_prob) * 100).toFixed(0);

  return (
    <div>
      <PageHead
        kicker="Senate Forecast"
        title="Who controls the Senate after November?"
        sub={
          <>
            {forecast.num_simulations.toLocaleString()} simulated elections,
            seeding each race with its polling average, correlated polling
            error, and a prediction-market prior.{' '}
            <span className="font-medium text-peach">{forecast.label}</span>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="D keeps/takes control" value={`${demPct}%`} tone="dem" />
        <StatCard label="R control" value={`${repPct}%`} tone="rep" />
        <StatCard label="Mean D seats" value={forecast.mean_dem_seats.toFixed(1)} tone="ink" />
        <StatCard
          label="Median D seats"
          value={forecast.median_dem_seats.toFixed(0)}
          tone="ink"
        />
      </div>

      {/* Chamber control probability split */}
      <Panel title="Chamber control probability" className="mt-4">
        <div className="mb-1.5 flex justify-between text-[11px] font-bold">
          <span className="text-dem">Democrats {demPct}%</span>
          <span className="text-rep">Republicans {repPct}%</span>
        </div>
        <div className="flex h-3.5 overflow-hidden rounded-full">
          <div className="bg-dem" style={{ width: `${demPct}%` }} />
          <div className="bg-rep" style={{ width: `${repPct}%` }} />
        </div>
      </Panel>

      {forecast.national_environment?.available && (
        <NationalEnvironmentPanel env={forecast.national_environment} />
      )}

      <Panel
        title={`Seat distribution across ${forecast.num_simulations.toLocaleString()} simulations`}
        className="mt-4"
      >
        <SeatDistributionChart forecast={forecast} />
        <p className="mt-1 text-xs text-cocoa-400">
          Baseline: {forecast.dem_safe_seats} safe D seats + {forecast.rep_safe_seats} safe R
          seats; {forecast.races.length} competitive races simulated. Democrats need{' '}
          {forecast.dem_majority_threshold} seats for control.
        </p>
      </Panel>

      {Object.keys(forecast.market_control_dem_prob).length > 0 && (
        <Panel
          title="Our simulation vs prediction markets — P(Democratic control)"
          className="mt-4"
        >
          <div className="flex flex-wrap gap-3">
            <ComparisonChip label="Our model" pct={forecast.dem_control_prob} highlight />
            {Object.entries(forecast.market_control_dem_prob).map(([source, prob]) => (
              <ComparisonChip
                key={source}
                label={MARKET_LABELS[source] ?? source}
                pct={prob}
                href={forecast.market_control_urls?.[source]}
              />
            ))}
          </div>
          <p className="mt-2 text-xs text-cocoa-400">
            Market odds also feed the per-race blend (weight{' '}
            {(forecast.market_weight * 100).toFixed(0)}% market /{' '}
            {((1 - forecast.market_weight) * 100).toFixed(0)}% polls).
          </p>
        </Panel>
      )}

      <div className="mt-4 grid gap-3 sm:hidden">
        {forecast.races.map((race) => (
          <div key={race.state} className="rounded-xl border border-cream-300 bg-white p-4">
            <div className="font-medium text-cocoa-700">{race.state}</div>
            <div className="mt-0.5 text-xs text-cocoa-400">
              {race.dem_candidate} (D) v. {race.rep_candidate} (R)
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <MobileDatum label="Polling margin" value={formatRaceMargin(race.margin)} />
              <MobileDatum label="P(D), polls" value={formatProbability(race.dem_win_prob_polls)} />
              <MobileDatum label="P(D), blended" value={formatProbability(race.dem_win_prob_blended)} bold />
              <MobileDatum
                label="Polymarket"
                value={formatProbability(race.market_dem_prob.polymarket)}
                href={race.market_urls?.polymarket}
              />
              <MobileDatum
                label="Kalshi"
                value={formatProbability(race.market_dem_prob.kalshi)}
                href={race.market_urls?.kalshi}
              />
            </dl>
          </div>
        ))}
      </div>

      <div className="mt-4 hidden overflow-x-auto rounded-xl border border-cream-300 bg-white sm:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
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
              <tr key={race.state} className="border-b border-cream-100 last:border-0">
                <td className="px-4 py-3 font-medium text-cocoa-700">
                  {race.state}
                  <span className="ml-2 text-xs font-normal text-cocoa-400">
                    {race.dem_candidate} (D) v. {race.rep_candidate} (R)
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-cocoa-700">
                  {race.margin != null
                    ? `${race.margin > 0 ? 'D' : 'R'} +${Math.abs(race.margin).toFixed(1)}`
                    : '—'}
                </td>
                <Prob value={race.dem_win_prob_polls} />
                <Prob value={race.dem_win_prob_blended} bold />
                <Prob
                  value={race.market_dem_prob.polymarket ?? null}
                  href={race.market_urls?.polymarket}
                />
                <Prob value={race.market_dem_prob.kalshi ?? null} href={race.market_urls?.kalshi} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-8 rounded-xl border border-cream-300 bg-cream-100 p-5 text-sm text-cocoa-700">
        <h3 className="font-display text-lg text-ink">How the simulation works</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            Each race&rsquo;s <Link href="/senate" className="text-peach underline">polling
            average</Link> margin is converted to a win probability using a fat-tailed
            Student-t error model: a national error (σ = {forecast.national_sigma}) shared by
            every race plus an independent per-race error (σ = {forecast.race_sigma}), sized
            to historical Senate polling misses. A shared tail shock allows unusually large
            misses to move several races together.
          </li>
          {forecast.national_environment?.available && (
            <li>
              The national midterm climate — the president&rsquo;s approval and the
              generic congressional ballot — is folded into each race&rsquo;s
              fundamentals prior as a uniform{' '}
              {forecast.national_environment.national_swing >= 0 ? 'D' : 'R'}+
              {Math.abs(forecast.national_environment.national_swing).toFixed(1)} swing
              versus the 2024 House result. It mainly lifts thinly-polled seats; heavily
              polled races already price the climate in.
            </li>
          )}
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
            This shows where the race stands today, given current polling and market
            prices. A work in progress from the team at Policy y Peaches —{' '}
            <a
              href="https://policyypeaches.substack.com/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-peach underline"
            >
              learn more here
            </a>
            .
          </li>
        </ul>
      </div>

      <LastUpdated />
    </div>
  );
}

function NationalEnvironmentPanel({ env }: { env: NationalEnvironment }) {
  const swing = env.national_swing;
  const dir = swing >= 0 ? 'D' : 'R';
  const fmt = (v: number | null | undefined, d = 1) =>
    v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(d)}`;
  return (
    <Panel title="National environment" className="mt-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Net presidential approval"
          value={fmt(env.approval_net)}
          tone="ink"
        />
        <StatCard label="Generic ballot (D−R)" value={fmt(env.generic_margin)} tone="ink" />
        <StatCard
          label="2024 House baseline"
          value={fmt(env.house_baseline_2024)}
          tone="ink"
        />
        <StatCard
          label="Applied swing"
          value={`${dir}+${Math.abs(swing).toFixed(1)}`}
          tone={swing >= 0 ? 'dem' : 'rep'}
        />
      </div>
      <p className="mt-2 text-xs text-cocoa-400">
        Today&rsquo;s climate ({env.president_party === 'R' ? 'Republican' : 'Democratic'}{' '}
        president) implies a national {dir}+{Math.abs(env.expected_national_margin ?? 0).toFixed(1)}{' '}
        margin. Measured against the 2024 House result, that is a uniform{' '}
        {dir}+{Math.abs(swing).toFixed(1)} swing applied to every state&rsquo;s fundamentals
        prior. It moves thinly-polled races the most.
      </p>
    </Panel>
  );
}

function ComparisonChip({
  label,
  pct,
  highlight,
  href,
}: {
  label: string;
  pct: number;
  highlight?: boolean;
  href?: string;
}) {
  const body = (
    <>
      <div className="text-xs text-cocoa-500">
        {label}
        {href ? ' ↗' : ''}
      </div>
      <div className="font-display text-lg text-ink">{(pct * 100).toFixed(0)}%</div>
    </>
  );
  const chipClass = `rounded-lg border px-4 py-2 text-center ${
    highlight ? 'border-peach-border bg-peach-wash' : 'border-cream-300 bg-white'
  }`;
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`${chipClass} transition-colors hover:border-cocoa-400`}
      title="View the market"
    >
      {body}
    </a>
  ) : (
    <div className={chipClass}>{body}</div>
  );
}

function Prob({ value, bold, href }: { value: number | null; bold?: boolean; href?: string }) {
  const text = value != null ? `${(value * 100).toFixed(0)}%` : '—';
  return (
    <td
      className={`px-4 py-3 text-right ${bold ? 'font-semibold text-ink' : 'text-cocoa-500'}`}
    >
      {href && value != null ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="underline decoration-cream-300 underline-offset-2 hover:text-cocoa-700 hover:decoration-cocoa-400"
          title="View the market"
        >
          {text}
        </a>
      ) : (
        text
      )}
    </td>
  );
}

function formatProbability(value: number | null | undefined): string {
  return value != null ? `${(value * 100).toFixed(0)}%` : '—';
}

function formatRaceMargin(value: number | null): string {
  return value != null ? `${value > 0 ? 'D' : 'R'} +${Math.abs(value).toFixed(1)}` : '—';
}

function MobileDatum({
  label,
  value,
  bold,
  href,
}: {
  label: string;
  value: string;
  bold?: boolean;
  href?: string;
}) {
  return (
    <div>
      <dt className="text-cocoa-400">{label}</dt>
      <dd className={`mt-0.5 text-sm ${bold ? 'font-semibold text-ink' : 'text-cocoa-700'}`}>
        {href && value !== '—' ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="underline decoration-cream-300 underline-offset-2 hover:text-cocoa-700"
            title="View the market"
          >
            {value}
          </a>
        ) : (
          value
        )}
      </dd>
    </div>
  );
}
