// Election-night panel: the frozen forecast rerun hourly, conditioned on the
// races called so far. Server component; data from live_forecast.json.

import type { LiveForecast } from '@/app/lib/data';
import { fmtMargin, fmtProb } from '@/app/lib/format';
import { Panel, StatCard } from '@/app/components/ui';

const PARTY_TEXT: Record<string, string> = { D: 'text-dem', R: 'text-rep', I: 'text-stamp' };
const PARTY_NAME: Record<string, string> = { D: 'Democrat', R: 'Republican', I: 'Independent' };

function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
    timeZoneName: 'short',
  });
}

function pp(delta: number): string {
  const v = Math.round(delta * 100);
  return v === 0 ? '±0' : `${v > 0 ? '+' : ''}${v} pts`;
}

export default function LiveForecastPanel({ live }: { live: LiveForecast }) {
  const pre = live.pre_election.dem_control_prob ?? null;
  const now = live.live.dem_control_prob;
  const delta = pre != null ? now - pre : null;
  const seats = live.seats_so_far;
  const need = live.dem_majority_threshold;
  const remaining = live.num_races - live.num_called;
  const decided =
    seats.D >= need ? 'D' : seats.R >= 100 - need + 1 ? 'R' : null;

  return (
    <section className="mb-6" aria-labelledby="live-forecast-title">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-peach">
            Election night, live
          </div>
          <h3 id="live-forecast-title" className="font-display text-2xl leading-tight text-ink">
            The forecast, rerun on the races called so far
          </h3>
        </div>
        <div className="text-[11.5px] text-cocoa-400">
          {live.num_called} of {live.num_races} called · updated {fmtStamp(live.generated)} · reruns hourly
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="P(Democratic control) now"
          value={fmtProb(now)}
          tone={now >= 0.5 ? 'dem' : 'rep'}
          sub={
            pre != null
              ? `${fmtProb(pre)} before polls closed${delta != null ? ` (${pp(delta)})` : ''}`
              : undefined
          }
        />
        <StatCard
          label="Seats called so far"
          value={`${seats.D} D · ${seats.R} R${seats.I ? ` · ${seats.I} I` : ''}`}
          tone={decided === 'D' ? 'dem' : decided === 'R' ? 'rep' : 'ink'}
          sub={
            decided
              ? `${PARTY_NAME[decided]}s have a majority`
              : `${need} for control · ${remaining} race${remaining === 1 ? '' : 's'} still open`
          }
        />
        <StatCard
          label="Expected Democratic seats"
          value={live.live.mean_dem_seats.toFixed(1)}
          tone="ink"
          sub={
            live.pre_election.mean_dem_seats != null
              ? `${live.pre_election.mean_dem_seats.toFixed(1)} before polls closed`
              : undefined
          }
        />
        <StatCard
          label="Called in the past hour"
          value={String(live.new_calls.length)}
          tone="peach"
          sub={live.new_calls.length ? live.new_calls.join(', ') : 'no new calls'}
        />
      </div>

      {live.history.length >= 2 && (
        <Panel title="P(Democratic control) through the night" className="mt-4">
          <History points={live.history} />
        </Panel>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title={`Called (${live.called.length})`}>
          {live.called.length === 0 ? (
            <p className="text-sm text-cocoa-500">
              No races called yet. The first calls usually land within an hour of a state&rsquo;s
              polls closing.
            </p>
          ) : (
            <ul className="divide-y divide-cream-100 text-sm">
              {live.called.map((c) => (
                <li key={c.state} className="flex items-center justify-between gap-3 py-2">
                  <div>
                    <span className="font-medium text-cocoa-700">{c.state}</span>{' '}
                    <span className={`font-semibold ${PARTY_TEXT[c.winner_party] ?? ''}`}>
                      {c.winner ?? PARTY_NAME[c.winner_party] ?? c.winner_party}
                    </span>
                    {c.margin != null && (
                      <span className="ml-1 text-xs text-cocoa-400">{fmtMargin(c.margin)}</span>
                    )}
                  </div>
                  <div className="whitespace-nowrap text-right text-xs text-cocoa-400">
                    {c.pre_election_prob != null ? (
                      <>
                        forecast gave {fmtProb(c.pre_election_prob)}
                        {c.upset && (
                          <span className="ml-1 rounded bg-peach-wash px-1.5 py-0.5 font-semibold text-peach">
                            upset
                          </span>
                        )}
                      </>
                    ) : (
                      'not modelled'
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title={`Still open (${live.remaining.length})`}>
          {live.remaining.length === 0 ? (
            <p className="text-sm text-cocoa-500">Every race has been called.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-cocoa-400">
                  <th className="py-1 pr-2">Race</th>
                  <th className="py-1 pr-2 text-right">Before</th>
                  <th className="py-1 pr-2 text-right">Now</th>
                  <th className="py-1 text-right">Shift</th>
                </tr>
              </thead>
              <tbody>
                {live.remaining.map((r) => {
                  const side = r.challenger_party === 'I' ? 'I' : 'D';
                  const d =
                    r.live_prob != null && r.pre_election_prob != null
                      ? r.live_prob - r.pre_election_prob
                      : null;
                  return (
                    <tr key={r.state} className="border-t border-cream-100">
                      <td className="py-1.5 pr-2">
                        <span className="font-medium text-cocoa-700">{r.state}</span>
                        <span className="ml-1 text-xs text-cocoa-400">P({side})</span>
                      </td>
                      <td className="py-1.5 pr-2 text-right text-cocoa-500">
                        {r.pre_election_prob != null ? fmtProb(r.pre_election_prob) : '—'}
                      </td>
                      <td className={`py-1.5 pr-2 text-right font-semibold ${
                        r.live_prob == null ? '' : r.live_prob >= 0.5 ? PARTY_TEXT[side] : 'text-rep'
                      }`}>
                        {r.live_prob != null ? fmtProb(r.live_prob) : '—'}
                      </td>
                      <td className={`py-1.5 text-right text-xs ${
                        d == null || Math.abs(d) < 0.005 ? 'text-cocoa-400' : d > 0 ? PARTY_TEXT[side] : 'text-rep'
                      }`}>
                        {d != null ? pp(d) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      <p className="mt-2 text-[11px] text-cocoa-400">
        How it works: the pre-election simulation is rerun keeping only the draws that agree with
        every call so far, so a surprise in one state shifts the odds in the states still counting.
        {live.live.condition_mode === 'forced' &&
          ' Too few draws agreed with the calls tonight, so called races were fixed instead; the other races keep their pre-election odds.'}
        {live.live.kept_simulations != null &&
          live.live.condition_mode === 'resample' &&
          ` ${live.live.kept_simulations.toLocaleString()} of ${live.live.num_simulations.toLocaleString()} simulations agree with the calls.`}
      </p>
    </section>
  );
}

function History({ points }: { points: LiveForecast['history'] }) {
  const W = 600;
  const H = 120;
  const padX = 8;
  const padY = 10;
  const n = points.length;
  const x = (i: number) => padX + (i * (W - 2 * padX)) / Math.max(1, n - 1);
  const y = (p: number) => padY + (1 - p) * (H - 2 * padY);
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.dem_control_prob).toFixed(1)}`).join(' ');
  const last = points[n - 1];
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-28 w-full" role="img" aria-label="Probability of Democratic control over time">
        <line x1={padX} x2={W - padX} y1={y(0.5)} y2={y(0.5)} stroke="#e8ddd5" strokeDasharray="4 4" />
        <text x={W - padX} y={y(0.5) - 3} textAnchor="end" fontSize="10" fill="#a0736a">50%</text>
        <path d={path} fill="none" stroke="#2563eb" strokeWidth="2.5" strokeLinejoin="round" />
        {points.map((p, i) => (
          <circle key={p.at} cx={x(i)} cy={y(p.dem_control_prob)} r={i === n - 1 ? 4 : 2.5} fill="#2563eb" />
        ))}
      </svg>
      <div className="flex justify-between text-[11px] text-cocoa-400">
        <span>{fmtStamp(points[0].at)}</span>
        <span>
          now {fmtProb(last.dem_control_prob)} · {last.num_called} called
        </span>
      </div>
    </div>
  );
}
