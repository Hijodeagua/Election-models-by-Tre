'use client';

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { SeatsVotesPoint } from '@/app/lib/data';

// The current map's seats-votes curve: expected Democratic seats at each
// national two-party margin, with the majority line and today's expected
// national margin marked.
export default function SeatsVotesChart({
  curve,
  threshold,
  expectedMargin,
  expectedSeats,
}: {
  curve: SeatsVotesPoint[];
  threshold: number;
  expectedMargin: number;
  expectedSeats: number;
}) {
  if (curve.length === 0) return null;
  const fmtMargin = (v: number) => `${v > 0 ? 'D+' : v < 0 ? 'R+' : 'Even '}${Math.abs(v)}`;
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={curve} margin={{ top: 16, right: 16, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#efe6df" vertical={false} />
        <XAxis
          dataKey="margin"
          type="number"
          domain={['dataMin', 'dataMax']}
          tick={{ fontSize: 11, fill: '#a0736a' }}
          axisLine={{ stroke: '#e8ddd5' }}
          tickLine={{ stroke: '#e8ddd5' }}
          tickFormatter={fmtMargin}
          label={{
            value: 'National two-party margin',
            position: 'insideBottom',
            offset: -2,
            fontSize: 11,
            fill: '#7c5a52',
          }}
        />
        <YAxis
          tick={{ fontSize: 11, fill: '#a0736a' }}
          axisLine={{ stroke: '#e8ddd5' }}
          tickLine={{ stroke: '#e8ddd5' }}
          domain={['auto', 'auto']}
        />
        <Tooltip
          formatter={(value: number) => [`${value.toFixed(0)} seats`, 'Expected D seats']}
          labelFormatter={(label) => `National ${fmtMargin(Number(label))}`}
          contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e8ddd5' }}
        />
        <ReferenceLine
          y={threshold}
          stroke="#2c1810"
          strokeDasharray="4 4"
          label={{ value: `Majority (${threshold})`, fontSize: 10, fill: '#5c3d2a', position: 'insideTopLeft' }}
        />
        <Line
          dataKey="dem_seats"
          stroke="#2563eb"
          strokeWidth={2.5}
          dot={{ r: 3 }}
          isAnimationActive={false}
        />
        <ReferenceDot
          x={expectedMargin}
          y={expectedSeats}
          r={6}
          fill="#c1533d"
          stroke="#fff"
          label={{ value: 'Today', fontSize: 10, fill: '#c1533d', position: 'top' }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
