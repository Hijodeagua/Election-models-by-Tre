'use client';

import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

// Histogram of Democratic seat totals across Monte Carlo simulations, with the
// majority line marked. Shared by the Senate and House forecast pages.
export default function SeatHistogram({
  distribution,
  threshold,
  numSimulations,
  axisLabel = 'Democratic seats',
  binWidth = 1,
}: {
  distribution: Record<string, number>;
  threshold: number;
  numSimulations: number;
  axisLabel?: string;
  binWidth?: number;
}) {
  const seats = Object.keys(distribution)
    .map(Number)
    .sort((a, b) => a - b);
  if (seats.length === 0) return null;

  // Fill gaps so the x-axis is continuous; optionally bin wide ranges.
  const lo = Math.floor(seats[0] / binWidth) * binWidth;
  const hi = Math.floor(seats[seats.length - 1] / binWidth) * binWidth;
  const data: { seats: number; sims: number }[] = [];
  for (let s = lo; s <= hi; s += binWidth) {
    let sims = 0;
    for (let k = s; k < s + binWidth; k += 1) sims += distribution[String(k)] ?? 0;
    data.push({ seats: s, sims });
  }
  const pct = (sims: number) => `${((sims / numSimulations) * 100).toFixed(1)}%`;

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 16, right: 16, left: 0, bottom: 4 }}>
        <XAxis
          dataKey="seats"
          tick={{ fontSize: 11, fill: '#a0736a' }}
          axisLine={{ stroke: '#e8ddd5' }}
          tickLine={{ stroke: '#e8ddd5' }}
          minTickGap={16}
          label={{
            value: axisLabel,
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
          allowDecimals={false}
        />
        <Tooltip
          formatter={(value: number) => [
            `${value.toLocaleString()} of ${numSimulations.toLocaleString()} simulations (${pct(value)})`,
            'Outcomes',
          ]}
          labelFormatter={(label) =>
            binWidth > 1
              ? `${label}–${Number(label) + binWidth - 1} Democratic seats`
              : `${label} Democratic seats`
          }
          contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e8ddd5' }}
        />
        <ReferenceLine
          x={Math.floor(threshold / binWidth) * binWidth}
          stroke="#2c1810"
          strokeDasharray="4 4"
          label={{
            value: `D majority (${threshold})`,
            fontSize: 10,
            fill: '#5c3d2a',
            position: 'top',
          }}
        />
        <Bar dataKey="sims" isAnimationActive={false}>
          {data.map((d) => (
            <Cell
              key={d.seats}
              fill={d.seats + binWidth - 1 >= threshold ? '#2563eb' : '#dc2626'}
              fillOpacity={0.8}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
