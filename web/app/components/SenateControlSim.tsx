'use client';

import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { SenateControlData } from '@/app/lib/data';

// Aggregate "who wins the Senate" view: the seat histogram from the Monte
// Carlo simulation, headline control probabilities, and the prediction-market
// comparison.
export default function SenateControlSim({ data }: { data: SenateControlData }) {
  const sim = data.simulation;
  if (!sim) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
        No simulation output yet.
      </div>
    );
  }

  const hist = Object.entries(sim.seat_histogram)
    .map(([seats, count]) => ({
      seats: Number(seats),
      pct: (count / sim.n_sims) * 100,
    }))
    .sort((a, b) => a.seats - b.seats);

  const tipping = Object.entries(sim.tipping_point_freq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  return (
    <div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat
          label="Dem control"
          value={`${(sim.dem_control_prob * 100).toFixed(0)}%`}
          accent="text-dem"
        />
        <Stat
          label="Rep control"
          value={`${(sim.rep_control_prob * 100).toFixed(0)}%`}
          accent="text-rep"
        />
        <Stat label="Mean Dem seats" value={sim.mean_dem_seats.toFixed(1)} />
        <Stat label="Simulations" value={sim.n_sims.toLocaleString()} />
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-700">
          Distribution of Democratic seats ({sim.n_sims.toLocaleString()} simulations,
          {` ${sim.dem_seats_needed}`} needed for control)
        </h3>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={hist} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
            <XAxis dataKey="seats" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} unit="%" />
            <Tooltip
              formatter={(value: number) => [`${value.toFixed(1)}% of sims`, 'Frequency']}
              labelFormatter={(seats) => `${seats} Dem seats`}
            />
            <ReferenceLine x={sim.dem_seats_needed} stroke="#0f172a" strokeDasharray="4 4" />
            <Bar dataKey="pct" isAnimationActive={false}>
              {hist.map((d) => (
                <Cell
                  key={d.seats}
                  fill={d.seats >= sim.dem_seats_needed ? '#2563eb' : '#dc2626'}
                  fillOpacity={0.8}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">vs. prediction markets</h3>
          {data.market_control_odds.length > 0 ? (
            <ul className="space-y-1 text-sm">
              {data.market_control_odds.map((q) => {
                const dem = q.dem_win_prob ?? (q.rep_win_prob != null ? 1 - q.rep_win_prob : null);
                return (
                  <li key={`${q.source}-${q.market_id}`} className="flex justify-between">
                    <span className="text-slate-600">
                      {q.source === 'polymarket' ? 'Polymarket' : 'Kalshi'} — {q.title}
                    </span>
                    <span className="font-semibold">
                      {dem != null ? `${(dem * 100).toFixed(0)}% Dem` : '—'}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">
              No open chamber-control market quotes yet — they will appear after the
              next data refresh finds them.
            </p>
          )}
          <p className="mt-2 text-xs text-slate-400">
            Market prices are also blended into each race&apos;s probability before
            simulation (weight {data.market_blend_weight}), so they inform the model —
            not just this comparison.
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">Most likely tipping-point seats</h3>
          {tipping.length > 0 ? (
            <ul className="space-y-1 text-sm">
              {tipping.map(([state, freq]) => (
                <li key={state} className="flex justify-between">
                  <span className="text-slate-600">{state}</span>
                  <span className="font-semibold">{(freq * 100).toFixed(0)}%</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">Not enough data.</p>
          )}
        </div>
      </div>
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
