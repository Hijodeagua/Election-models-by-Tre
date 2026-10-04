import Link from 'next/link';
import LastUpdated from '@/app/components/LastUpdated';
import SeatHistogram from '@/app/components/SeatHistogram';
import SeatsVotesChart from '@/app/components/SeatsVotesChart';
import { EmptyState, PageHead, Panel, StatCard } from '@/app/components/ui';
import {
  getHouseForecast,
  type HouseDistrictForecast,
  type HouseForecastData,
} from '@/app/lib/data';

export default function HouseForecastPage() {
  const forecast = getHouseForecast();

  if (!forecast) {
    return (
      <div>
        <PageHead kicker="House Forecast" title="Who controls the House after November?" />
        <EmptyState>No House simulation output yet — run scripts/export_json.py.</EmptyState>
      </div>
    );
  }

  const demPct = (forecast.dem_majority_prob * 100).toFixed(0);
  const repPct = ((1 - forecast.dem_majority_prob) * 100).toFixed(0);
  const districtsByLabel = new Map(forecast.districts.map((d) => [d.label, d]));
  const competitive = forecast.competitive
    .map((label) => districtsByLabel.get(label))
    .filter((d): d is HouseDistrictForecast => Boolean(d));
  const redrawn = new Set(forecast.redrawn_states ?? []);
  const netGain = forecast.mean_dem_seats - forecast.seats_2024.D;

  return (
    <div>
      <PageHead
        kicker="House Forecast"
        title="Who controls the House after November?"
        sub={
          <>
            {forecast.num_simulations.toLocaleString()} simulated elections across all{' '}
            {forecast.total_seats} districts: the national environment swung uniformly from
            each district&rsquo;s 2024 result, with correlated national error and
            district-level noise.{' '}
            <span className="font-medium text-peach">{forecast.label}</span>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="D majority" value={`${demPct}%`} tone="dem" />
        <StatCard label="R majority" value={`${repPct}%`} tone="rep" />
        <StatCard
          label="Mean D seats"
          value={forecast.mean_dem_seats.toFixed(0)}
          tone="ink"
          sub={`80% range ${forecast.seats_p10.toFixed(0)}–${forecast.seats_p90.toFixed(0)}`}
        />
        <StatCard
          label="Expected net D change"
          value={`${netGain >= 0 ? '+' : ''}${netGain.toFixed(0)}`}
          tone={netGain >= 0 ? 'dem' : 'rep'}
          sub={`from ${forecast.seats_2024.D} D / ${forecast.seats_2024.R} R in 2024`}
        />
      </div>

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

      <NationalEnvironmentPanel forecast={forecast} />

      <Panel
        title={`Seat distribution across ${forecast.num_simulations.toLocaleString()} simulations`}
        className="mt-4"
      >
        <SeatHistogram
          distribution={forecast.seat_distribution}
          threshold={forecast.dem_majority_threshold}
          numSimulations={forecast.num_simulations}
          binWidth={2}
        />
        <p className="mt-1 text-xs text-cocoa-400">
          Democrats need {forecast.dem_majority_threshold} of {forecast.total_seats} seats.
          Median outcome {forecast.median_dem_seats.toFixed(0)} D seats; 80% of simulations
          land between {forecast.seats_p10.toFixed(0)} and {forecast.seats_p90.toFixed(0)}.
        </p>
      </Panel>

      <Panel title="The map's seats-votes curve" className="mt-4">
        <SeatsVotesChart
          curve={forecast.seats_by_margin}
          threshold={forecast.dem_majority_threshold}
          expectedMargin={forecast.expected_national_margin}
          expectedSeats={forecast.mean_dem_seats}
        />
        <p className="mt-1 text-xs text-cocoa-400">
          Expected Democratic seats at each national two-party margin, district noise
          included.{' '}
          {forecast.tipping_point_margin != null && (
            <>
              The majority line is crossed at a national{' '}
              <strong className="text-cocoa-700">{fmtMargin(forecast.tipping_point_margin)}</strong>{' '}
              margin — the structural tilt of the current map after the configured
              redistricting shift.
            </>
          )}
        </p>
      </Panel>

      <Panel
        title={`Closest ${competitive.length} districts (P(D) between 10% and 90%)`}
        className="mt-4"
      >
        <p className="mb-3 text-xs text-cocoa-400">
          Expected flips: {forecast.expected_flips.r_to_d.toFixed(1)} Republican-held seats to
          Democrats, {forecast.expected_flips.d_to_r.toFixed(1)} Democratic-held seats to
          Republicans. Lean = {forecast.lean_weight_2024?.toFixed(2) ?? '1.00'}×2024 +{' '}
          {forecast.lean_weight_2022?.toFixed(2) ?? '0.00'}×2022 two-party margin (2024 alone
          where 2022 is unavailable); an open seat loses the departing incumbent&rsquo;s{' '}
          {forecast.incumbency_advantage ?? 0}-pt advantage ({forecast.num_open_seats ?? 0} open
          seats configured). Expected margin = lean + incumbency adjustment + national swing.
          Districts marked ↻ are in states redrawn since 2024 — their numbers are on the old
          lines and the state&rsquo;s net effect is applied separately (see below).
        </p>
        <div className="grid gap-2 sm:hidden">
          {competitive.map((d) => (
            <div key={d.label} className="rounded-lg border border-cream-300 bg-white px-3 py-2">
              <div className="flex items-center justify-between">
                <span className="font-medium text-cocoa-700">
                  {d.label}
                  {redrawn.has(d.state) ? ' ↻' : ''}
                </span>
                <span
                  className={`text-sm font-semibold ${d.dem_win_prob >= 0.5 ? 'text-dem' : 'text-rep'}`}
                >
                  {probLabel(d.dem_win_prob)}
                </span>
              </div>
              <div className="mt-0.5 text-xs text-cocoa-400">
                2024: {fmtMargin(d.margin_2024)} ({d.winner_2024})
                {d.margin_2022 != null ? ` · 2022: ${fmtMargin(d.margin_2022)}` : ''}
                {d.open_seat ? ' · open seat' : ''} · today: {fmtMargin(d.expected_margin)}
              </div>
            </div>
          ))}
        </div>
        <div className="hidden overflow-x-auto sm:block">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
                <th className="px-3 py-2">District</th>
                <th className="px-3 py-2 text-right">2024 result</th>
                <th className="px-3 py-2 text-right">2022 result</th>
                <th className="px-3 py-2 text-right">Lean</th>
                <th className="px-3 py-2 text-right">Incumbent</th>
                <th className="px-3 py-2 text-right">Expected 2026 margin</th>
                <th className="px-3 py-2 text-right">80% range</th>
                <th className="px-3 py-2 text-right">P(D win)</th>
              </tr>
            </thead>
            <tbody>
              {competitive.map((d) => (
                <tr key={d.label} className="border-b border-cream-100 last:border-0">
                  <td className="px-3 py-2 font-medium text-cocoa-700">
                    {d.label}
                    {redrawn.has(d.state) && (
                      <span
                        className="ml-1.5 text-xs text-cocoa-400"
                        title="State redrawn since 2024"
                      >
                        ↻
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-cocoa-500">
                    {fmtMargin(d.margin_2024)}{' '}
                    <span className={d.winner_2024 === 'D' ? 'text-dem' : 'text-rep'}>
                      ({d.winner_2024})
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right text-cocoa-500">
                    {d.margin_2022 != null ? fmtMargin(d.margin_2022) : '—'}
                  </td>
                  <td className="px-3 py-2 text-right text-cocoa-500">
                    {d.lean != null ? fmtMargin(d.lean) : '—'}
                  </td>
                  <td className="px-3 py-2 text-right text-cocoa-500">
                    {d.open_seat ? (
                      <span title={d.open_seat_reason}>
                        open ({d.incumbency_adjust != null && d.incumbency_adjust !== 0
                          ? `${d.incumbency_adjust > 0 ? '+' : ''}${d.incumbency_adjust.toFixed(1)}`
                          : '0'})
                      </span>
                    ) : (
                      d.incumbent_party || '—'
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-cocoa-700">
                    {fmtMargin(d.expected_margin)}
                  </td>
                  <td className="px-3 py-2 text-right text-cocoa-400">
                    {fmtMargin(d.margin_p10)} to {fmtMargin(d.margin_p90)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-semibold ${
                      d.dem_win_prob >= 0.5 ? 'text-dem' : 'text-rep'
                    }`}
                  >
                    {probLabel(d.dem_win_prob)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {forecast.redistricting_states.length > 0 && (
        <Panel title="Mid-decade redistricting (applied as a net seat shift)" className="mt-4">
          <div className="grid gap-2 sm:grid-cols-2">
            {forecast.redistricting_states.map((r) => (
              <div
                key={r.state}
                className="rounded-lg border border-cream-300 bg-cream-50 px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-cocoa-700">{r.state}</span>
                  <span
                    className={`font-semibold ${r.dem_seat_shift >= 0 ? 'text-dem' : 'text-rep'}`}
                  >
                    {r.dem_seat_shift >= 0 ? 'D' : 'R'} +{Math.abs(r.dem_seat_shift)}
                    {r.sd > 0 ? ` ± ${r.sd}` : ''}
                  </span>
                </div>
                {r.note && <div className="mt-0.5 text-cocoa-400">{r.note}</div>}
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-cocoa-400">
            Net expected shift versus the 2024 map:{' '}
            <strong className="text-cocoa-700">
              {forecast.redistricting_shift_mean >= 0 ? 'D' : 'R'} +
              {Math.abs(forecast.redistricting_shift_mean).toFixed(0)} seats
            </strong>
            . These are configured estimates of each new map&rsquo;s intended effect, not
            district-level simulations of the new lines; a strong national wave typically
            delivers fewer of a gerrymander&rsquo;s intended seats than listed here.
          </p>
        </Panel>
      )}

      <div className="mt-8 rounded-xl border border-cream-300 bg-cream-100 p-5 text-sm text-cocoa-700">
        <h3 className="font-display text-lg text-ink">How the simulation works</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            Every district starts from a structural lean blending its 2024 and 2022 two-party
            results (uncontested seats take the other cycle&rsquo;s margin or a safe
            placeholder; states redrawn for 2024 use 2024 alone). Seats whose incumbent is not
            running lose that incumbent&rsquo;s advantage. All of these values are in the
            table above and in <code>house_forecast.json</code>.
          </li>
          <li>
            The expected national margin blends the{' '}
            <Link href="/generic-ballot" className="text-peach underline">
              generic ballot
            </Link>{' '}
            (two-party {fmtMargin(forecast.generic_ballot_two_party ?? 0)}, weight 75%) with
            the margin implied by{' '}
            <Link href="/" className="text-peach underline">
              presidential approval
            </Link>{' '}
            ({fmtMargin(forecast.approval_implied_margin ?? 0)}, weight 25%), then applies
            the historical generic-ballot bias ({forecast.generic_ballot_bias.toFixed(1)} pts
            — final polling averages have run about a point too Democratic on average).
            Result: {fmtMargin(forecast.expected_national_margin)}, a{' '}
            {fmtMargin(forecast.national_swing)} swing from 2024&rsquo;s{' '}
            {fmtMargin(forecast.baseline_margin)}.
          </li>
          <li>
            Each simulation draws one national error shared by every district (σ ={' '}
            {forecast.national_sigma.toFixed(2)}: {forecast.polling_sigma.toFixed(1)} from
            historical generic-ballot misses plus {forecast.campaign_drift_sigma.toFixed(2)}{' '}
            for campaign movement over the {forecast.days_to_election} days to election day)
            and an independent per-district error (σ = {forecast.district_sigma}, sized to how
            much districts have deviated from the national swing between recent cycles). Both
            are fat-tailed Student-t{forecast.tail_dof ? `(${forecast.tail_dof})` : ''}.
          </li>
          <li>
            Seats are counted against the {forecast.dem_majority_threshold}-seat majority
            line, after the redistricting shift above. No district polling, candidate quality
            or retirements yet — the district error term stands in for them.
          </li>
          <li>
            This shows where the House stands today given current national polling. A work
            in progress from the team at Policy y Peaches —{' '}
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

function NationalEnvironmentPanel({ forecast }: { forecast: HouseForecastData }) {
  return (
    <Panel title="National environment" className="mt-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Generic ballot (two-party)"
          value={fmtMargin(forecast.generic_ballot_two_party ?? 0)}
          tone="ink"
          sub={
            forecast.generic_ballot_raw_margin != null
              ? `raw ${fmtMargin(forecast.generic_ballot_raw_margin)}`
              : undefined
          }
        />
        <StatCard
          label="Approval-implied margin"
          value={fmtMargin(forecast.approval_implied_margin ?? 0)}
          tone="ink"
          sub={
            forecast.approval_net != null
              ? `net approval ${forecast.approval_net.toFixed(1)}`
              : undefined
          }
        />
        <StatCard
          label="Expected national margin"
          value={fmtMargin(forecast.expected_national_margin)}
          tone={forecast.expected_national_margin >= 0 ? 'dem' : 'rep'}
          sub={`after ${forecast.generic_ballot_bias.toFixed(1)} pt poll-bias adjustment`}
        />
        <StatCard
          label="Swing vs 2024"
          value={fmtMargin(forecast.national_swing)}
          tone={forecast.national_swing >= 0 ? 'dem' : 'rep'}
          sub={`2024 House vote ${fmtMargin(forecast.baseline_margin)}`}
        />
      </div>
    </Panel>
  );
}

function fmtMargin(v: number): string {
  if (Math.abs(v) < 0.05) return 'Even';
  return `${v > 0 ? 'D' : 'R'}+${Math.abs(v).toFixed(1)}`;
}

function probLabel(p: number): string {
  return `${(p * 100).toFixed(0)}%`;
}
