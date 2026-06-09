'use client';

import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { GenericBallotSnapshot } from '@/app/lib/data';

// Generic-ballot D−R margin trend. Positive = Democratic advantage.
export default function MarginChart({ trend }: { trend: GenericBallotSnapshot[] }) {
  const data = trend.map((s) => ({ date: s.as_of, margin: s.margin }));

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
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
        />
        <Tooltip
          formatter={(value: number) => {
            const lead = value >= 0 ? 'D' : 'R';
            return [`${lead}+${Math.abs(value).toFixed(1)}`, 'Margin'];
          }}
        />
        <ReferenceLine y={0} stroke="#c9b3a8" strokeDasharray="3 3" />
        <Line dataKey="margin" name="D−R margin" stroke="#2563eb" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
