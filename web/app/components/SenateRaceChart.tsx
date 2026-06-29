'use client';

import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { SenateRaceSnapshot } from '@/app/lib/data';

const DEM = '#2563eb';
const REP = '#dc2626';

function marginLabel(v: number): string {
  if (v === 0) return 'Tie';
  return v > 0 ? `D+${Math.abs(v).toFixed(0)}` : `R+${Math.abs(v).toFixed(0)}`;
}

// Per-race histogram of the 50,000 simulated Dem−Rep margins. Democratic-win
// outcomes sit on the LEFT in blue, Republican-win outcomes on the RIGHT in red,
// with a reference line at the 50/50 tipping point (margin 0). Shown when a race
// card is expanded.
export default function SenateRaceChart({ race }: { race: SenateRaceSnapshot }) {
  const demName = race.dem_candidate ?? 'Democrat';
  const repName = race.rep_candidate ?? 'Republican';
  const fc = race.forecast;
  const bins = fc?.margin_hist ?? [];

  if (bins.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-cocoa-400">
        No simulation distribution available for this race yet.
      </p>
    );
  }

  const data = bins.map((b) => ({ mid: b.mid, pct: Math.round(b.pct * 1000) / 10 }));
  const demWinProb = fc?.dem_win_prob ?? null;
  const demPct = demWinProb != null ? Math.round(demWinProb * 100) : null;
  const repPct = demPct != null ? 100 - demPct : null;
  const median = fc?.median_margin ?? null;
  const nSims = fc?.num_simulations ?? null;

  return (
    <div className="rounded-lg bg-cream-50/60 p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-cocoa-400">
          {nSims ? `${nSims.toLocaleString()} simulated outcomes` : 'Simulated outcomes'}
        </span>
        {demPct != null && repPct != null && (
          <span className="text-xs font-semibold">
            <span style={{ color: DEM }}>{demName} {demPct}%</span>
            <span className="mx-1 text-cocoa-300">·</span>
            <span style={{ color: REP }}>{repName} {repPct}%</span>
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={216}>
        <BarChart data={data} margin={{ top: 16, right: 10, left: 0, bottom: 4 }} barCategoryGap={1}>
          <CartesianGrid strokeDasharray="2 4" stroke="#ece2da" vertical={false} />
          <XAxis
            dataKey="mid"
            type="number"
            domain={[-30, 30]}
            ticks={[-20, -10, 0, 10, 20]}
            reversed
            tick={{ fontSize: 10.5, fill: '#b69a90' }}
            tickFormatter={marginLabel}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 10.5, fill: '#b69a90' }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `${v}%`}
            width={34}
          />
          <Tooltip
            cursor={{ fill: 'rgba(203,182,171,0.15)' }}
            formatter={(value: number) => [`${value.toFixed(1)}% of sims`, 'Frequency']}
            labelFormatter={(v: number) => `Margin ${marginLabel(Number(v))}`}
            labelStyle={{ color: '#5c3d2a', fontWeight: 600, marginBottom: 2 }}
            contentStyle={{
              fontSize: 12,
              borderRadius: 10,
              border: '1px solid #ece2da',
              boxShadow: '0 4px 12px rgba(80,50,40,0.08)',
              padding: '6px 10px',
            }}
          />
          {/* The 50/50 line: everything left of it (blue) is a Democratic win. */}
          <ReferenceLine
            x={0}
            stroke="#7c6a5d"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            label={{ value: '50/50', position: 'top', fontSize: 10, fill: '#7c6a5d' }}
          />
          {median != null && (
            <ReferenceLine
              x={median}
              stroke={median > 0 ? DEM : REP}
              strokeWidth={1}
              label={{
                value: `median ${marginLabel(median)}`,
                position: 'insideTopRight',
                fontSize: 9.5,
                fill: median > 0 ? DEM : REP,
              }}
            />
          )}
          <Bar dataKey="pct" isAnimationActive={false} maxBarSize={16} radius={[2, 2, 0, 0]}>
            {data.map((d) => (
              <Cell key={d.mid} fill={d.mid > 0 ? DEM : REP} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-1.5 flex items-center gap-1.5 text-[11px] leading-relaxed text-cocoa-400">
        <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: DEM }} />
        Left of the 50/50 line, {demName} (D) wins;
        <span className="ml-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: REP }} />
        right of it, {repName} (R) wins. Each bar is the share of the chamber
        simulation&rsquo;s 50,000 runs landing on that Dem−Rep margin.
      </p>
    </div>
  );
}
