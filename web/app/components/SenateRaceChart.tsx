'use client';

import {
  Area,
  ComposedChart,
  CartesianGrid,
  ReferenceDot,
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
  const demLeads = latest.demProb >= 50;
  const leader = demLeads ? demName : repName;
  const leaderProb = demLeads ? latest.demProb : 100 - latest.demProb;
  const leaderColor = demLeads ? DEM : REP;
  const gradId = `race-grad-${race.state.replace(/\s+/g, '')}`;

  return (
    <div className="rounded-lg bg-cream-50/60 p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-cocoa-400">
          Probability {demName} (D) wins
        </span>
        <span
          className="rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{ color: leaderColor, backgroundColor: `${leaderColor}14` }}
        >
          {leader} {Math.round(leaderProb)}%
        </span>
      </div>
      <ResponsiveContainer width="100%" height={208}>
        <ComposedChart data={data} margin={{ top: 10, right: 14, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={DEM} stopOpacity={0.28} />
              <stop offset="100%" stopColor={DEM} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="2 4" stroke="#ece2da" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10.5, fill: '#b69a90' }}
            axisLine={false}
            tickLine={false}
            minTickGap={28}
            padding={{ left: 6, right: 6 }}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 50, 100]}
            tick={{ fontSize: 10.5, fill: '#b69a90' }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `${v}%`}
            width={40}
          />
          <Tooltip
            cursor={{ stroke: '#cbb6ab', strokeDasharray: '3 3' }}
            formatter={(value: number) => [`${value.toFixed(0)}%`, `P(${demName})`]}
            labelStyle={{ color: '#5c3d2a', fontWeight: 600, marginBottom: 2 }}
            contentStyle={{
              fontSize: 12,
              borderRadius: 10,
              border: '1px solid #ece2da',
              boxShadow: '0 4px 12px rgba(80,50,40,0.08)',
              padding: '6px 10px',
            }}
          />
          <ReferenceLine y={50} stroke="#d8c3b8" strokeWidth={1} strokeDasharray="4 4" />
          <Area
            type="monotone"
            dataKey="demProb"
            stroke={DEM}
            strokeWidth={2.5}
            fill={`url(#${gradId})`}
            dot={false}
            activeDot={{ r: 4, fill: DEM, stroke: '#fff', strokeWidth: 2 }}
            isAnimationActive={false}
          />
          {/* Emphasise the current value. */}
          <ReferenceDot
            x={latest.date}
            y={latest.demProb}
            r={4.5}
            fill={leaderColor}
            stroke="#fff"
            strokeWidth={2}
            isFront
          />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="mt-1.5 flex items-center gap-1.5 text-[11px] leading-relaxed text-cocoa-400">
        <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: DEM }} />
        Above the 50% line favours {demName} (D); below favours {repName} (R). Each point runs
        our weighted polling margin that day through the same error model as the chamber
        simulation.
      </p>
    </div>
  );
}
