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
import { fmtMargin, fmtProb } from '@/app/lib/format';

// Hex twins of the text-dem / text-rep Tailwind colors, for SVG chart props.
const DEM = '#2563eb';
const REP = '#dc2626';
const NEUTRAL = '#7c6a5d';

// Per-race histogram of the simulated Dem−Rep margins. Democratic-win
// outcomes sit on the LEFT in blue, Republican-win outcomes on the RIGHT in red,
// with a reference line at the 50/50 tipping point (margin 0). Shown when a race
// card is expanded.
export default function SenateRaceChart({ race }: { race: SenateRaceSnapshot }) {
  const demName = race.dem_candidate ?? 'Democrat';
  const repName = race.rep_candidate ?? 'Republican';
  const fc = race.forecast;

  if (!fc?.margin_hist?.length) {
    return (
      <p className="py-6 text-center text-xs text-cocoa-400">
        No simulation distribution available for this race yet.
      </p>
    );
  }

  const data = fc.margin_hist.map((b) => ({ mid: b.mid, pct: b.pct * 100 }));
  const demProb = fc.dem_win_prob;
  const median = fc.median_margin;
  const nSims = fc.num_simulations;

  // Derive the axis from the bins themselves so a Python-side change to the
  // histogram range/width can't silently clip the chart.
  const step = data.length > 1 ? Math.abs(data[1].mid - data[0].mid) : 2;
  const loMid = data[0].mid;
  const hiMid = data[data.length - 1].mid;
  const domainLo = loMid - step / 2;
  const domainHi = hiMid + step / 2;
  const ticks: number[] = [];
  for (let t = Math.ceil((domainLo + 1) / 10) * 10; t < domainHi; t += 10) ticks.push(t);

  // The end bins are catch-alls (tail mass beyond the range is clipped into
  // them), so label them as open-ended rather than as a specific margin.
  const binLabel = (mid: number) => {
    if (mid >= hiMid) return `Margin ${fmtMargin(mid - step / 2, 0)} or more`;
    if (mid <= loMid) return `Margin ${fmtMargin(mid + step / 2, 0)} or more`;
    return `Margin ${fmtMargin(mid, 0)}`;
  };
  const medianColor = median == null || Math.abs(median) < 0.05
    ? NEUTRAL
    : median > 0 ? DEM : REP;

  return (
    <div className="rounded-lg bg-cream-50/60 p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-cocoa-400">
          {nSims ? `${nSims.toLocaleString()} simulated outcomes` : 'Simulated outcomes'}
        </span>
        {demProb != null && (
          <span className="text-xs font-semibold">
            <span className="text-dem">{demName} {fmtProb(demProb)}</span>
            <span className="mx-1 text-cocoa-300">·</span>
            <span className="text-rep">{repName} {fmtProb(1 - demProb)}</span>
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={216}>
        <BarChart data={data} margin={{ top: 16, right: 10, left: 0, bottom: 4 }} barCategoryGap={1}>
          <CartesianGrid strokeDasharray="2 4" stroke="#ece2da" vertical={false} />
          <XAxis
            dataKey="mid"
            type="number"
            domain={[domainLo, domainHi]}
            ticks={ticks}
            reversed
            tick={{ fontSize: 10.5, fill: '#b69a90' }}
            tickFormatter={(v: number) => fmtMargin(v, 0)}
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
            formatter={(value: number) => [
              value > 0 && value < 0.05 ? '<0.1% of sims' : `${value.toFixed(1)}% of sims`,
              'Frequency',
            ]}
            labelFormatter={(v: number) => binLabel(Number(v))}
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
            stroke={NEUTRAL}
            strokeWidth={1.5}
            strokeDasharray="4 3"
            label={{ value: '50/50', position: 'top', fontSize: 10, fill: NEUTRAL }}
          />
          {median != null && (
            <ReferenceLine
              x={median}
              stroke={medianColor}
              strokeWidth={1}
              label={{
                value: `median ${fmtMargin(median, 1)}`,
                position: 'insideTopRight',
                fontSize: 9.5,
                fill: medianColor,
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
        <span className="inline-block h-2 w-2 rounded-full bg-dem" />
        Left of the 50/50 line, {demName} (D) wins;
        <span className="ml-1 inline-block h-2 w-2 rounded-full bg-rep" />
        right of it, {repName} (R) wins. Each bar is the share of the chamber
        simulation&rsquo;s {nSims ? `${nSims.toLocaleString()} ` : ''}runs landing on that
        Dem−Rep margin.
      </p>
    </div>
  );
}
