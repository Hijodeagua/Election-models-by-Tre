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
import type { SenateForecastData } from '@/app/lib/data';

// Histogram of Democratic seat totals across the Monte Carlo simulations,
// with the majority threshold marked.
export default function SeatDistributionChart({ forecast }: { forecast: SenateForecastData }) {
  const seats = Object.keys(forecast.seat_distribution)
    .map(Number)
    .sort((a, b) => a - b);
  if (seats.length === 0) return null;

  // Fill gaps so the x-axis is continuous.
  const data: { seats: number; sims: number }[] = [];
  for (let s = seats[0]; s <= seats[seats.length - 1]; s += 1) {
    data.push({ seats: s, sims: forecast.seat_distribution[String(s)] ?? 0 });
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 16, right: 16, left: 0, bottom: 4 }}>
        <XAxis
          dataKey="seats"
          tick={{ fontSize: 11 }}
          label={{ value: 'Democratic seats', position: 'insideBottom', offset: -2, fontSize: 11 }}
        />
        <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
        <Tooltip
          formatter={(value: number) => [
            `${value} of ${forecast.num_simulations} simulations`,
            'Outcomes',
          ]}
          labelFormatter={(label) => `${label} Democratic seats`}
        />
        <ReferenceLine
          x={forecast.dem_majority_threshold}
          stroke="#475569"
          strokeDasharray="4 4"
          label={{
            value: `D majority (${forecast.dem_majority_threshold})`,
            fontSize: 10,
            fill: '#475569',
            position: 'top',
          }}
        />
        <Bar dataKey="sims" isAnimationActive={false}>
          {data.map((d) => (
            <Cell
              key={d.seats}
              fill={d.seats >= forecast.dem_majority_threshold ? '#2563eb' : '#dc2626'}
              fillOpacity={0.8}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
