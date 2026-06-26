'use client';

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { GenericBallotSnapshot } from '@/app/lib/data';

function fmtDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });
}

// Generic-ballot D−R margin trend. Positive = Democratic advantage.
export default function MarginChart({ trend }: { trend: GenericBallotSnapshot[] }) {
  const data = trend.map((s) => ({ date: fmtDate(s.as_of), margin: s.margin }));

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#efe6df" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11, fill: '#a0736a' }}
          axisLine={{ stroke: '#e8ddd5' }}
          tickLine={{ stroke: '#e8ddd5' }}
          minTickGap={40}
        />
        <YAxis
          tick={{ fontSize: 11, fill: '#a0736a' }}
          axisLine={{ stroke: '#e8ddd5' }}
          tickLine={{ stroke: '#e8ddd5' }}
          tickFormatter={(v: number) => `${v > 0 ? 'D+' : v < 0 ? 'R+' : ''}${Math.abs(v)}`}
        />
        <Tooltip
          formatter={(value: number) => {
            const lead = value >= 0 ? 'D' : 'R';
            return [`${lead}+${Math.abs(value).toFixed(1)}`, 'Margin'];
          }}
          contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e8ddd5' }}
          labelStyle={{ color: '#5c3d2a', fontWeight: 600 }}
        />
        <ReferenceLine
          y={0}
          stroke="#c9b3a8"
          strokeDasharray="3 3"
          label={{ value: 'Tie', fontSize: 10, fill: '#7c5a52', position: 'insideTopLeft' }}
        />
        <Line
          dataKey="margin"
          name="D−R margin"
          stroke="#2563eb"
          dot={false}
          strokeWidth={2.5}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
