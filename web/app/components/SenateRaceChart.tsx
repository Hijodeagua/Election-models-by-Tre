'use client';

import {
  Area,
  ComposedChart,
  CartesianGrid,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { SenateRaceSnapshot } from '@/app/lib/data';

const DEM = '#2563eb';
const REP = '#dc2626';

function fmtDate(iso: string): string {
  // "2026-06-24" -> "Jun 24"
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// Per-race history: our model's probability the Democrat wins, over time. The
// 50% line is the tipping point — above it we favour the Democrat, below it the
// Republican. Shown when a race card is expanded.
export default function SenateRaceChart({ race }: { race: SenateRaceSnapshot }) {
  const trend = race.trend ?? [];
  const demName = race.dem_candidate ?? 'Democrat';
  const repName = race.rep_candidate ?? 'Republican';

  if (trend.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-cocoa-400">
        Not enough polling history yet to chart this race.
      </p>
    );
  }

  const data = trend.map((p) => ({
    date: fmtDate(p.as_of),
    demProb: Math.round(p.dem_win_prob * 1000) / 10,
    margin: p.dem_margin,
  }));

  const latest = data[data.length - 1];
  const leader = latest.demProb >= 50 ? demName : repName;
  const leaderProb = latest.demProb >= 50 ? latest.demProb : 100 - latest.demProb;
  const leaderColor = latest.demProb >= 50 ? DEM : REP;

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-xs font-medium text-cocoa-500">
          Our model — probability {demName} (D) wins
        </span>
        <span className="text-xs font-semibold" style={{ color: leaderColor }}>
          {leader} {Math.round(leaderProb)}%
        </span>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#efe6df" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: '#a0736a' }}
            axisLine={{ stroke: '#e8ddd5' }}
            tickLine={{ stroke: '#e8ddd5' }}
            minTickGap={20}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={{ fontSize: 11, fill: '#a0736a' }}
            axisLine={{ stroke: '#e8ddd5' }}
            tickLine={{ stroke: '#e8ddd5' }}
            unit="%"
            width={42}
          />
          <Tooltip
            formatter={(value: number, name: string) => {
              if (name === 'demProb') {
                return [`${value.toFixed(0)}%`, `P(${demName} wins)`];
              }
              return [value, name];
            }}
            labelStyle={{ color: '#5c3d2a', fontWeight: 600 }}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e8ddd5' }}
          />
          <ReferenceLine
            y={50}
            stroke="#7c5a52"
            strokeDasharray="4 4"
            label={{ value: 'Toss-up', fontSize: 10, fill: '#7c5a52', position: 'insideTopLeft' }}
          />
          <Area
            dataKey="demProb"
            stroke="none"
            fill={DEM}
            fillOpacity={0.1}
            isAnimationActive={false}
          />
          <Line
            dataKey="demProb"
            name="demProb"
            stroke={DEM}
            strokeWidth={2.5}
            dot={{ r: 3, fill: DEM }}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="mt-2 text-[11px] leading-relaxed text-cocoa-400">
        Higher line = stronger position for {demName} (D); lower = stronger for{' '}
        {repName} (R). Each point converts our weighted polling margin on that date into a
        win probability through the same error model as the chamber simulation.
      </p>
    </div>
  );
}
