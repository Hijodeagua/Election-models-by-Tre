'use client';

import { useMemo, useState } from 'react';
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ApprovalComparisonData } from '@/app/lib/data';

type Metric = 'approve' | 'disapprove' | 'net';

const SOURCE_COLORS: Record<string, string> = {
  ours: '#2563eb',
  silver_bulletin: '#9333ea',
  votehub: '#0d9488',
  fiftyplusone: '#ea580c',
};

const METRICS: { key: Metric; label: string }[] = [
  { key: 'approve', label: 'Approve' },
  { key: 'disapprove', label: 'Disapprove' },
  { key: 'net', label: 'Net approval' },
];

// Tweakable multi-model approval chart: toggle each source on/off and switch
// between approve / disapprove / net. Series are merged by date so models with
// different publication cadences still line up on one x-axis.
export default function ApprovalComparisonChart({ data }: { data: ApprovalComparisonData }) {
  const sourceKeys = Object.keys(data.sources);
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(sourceKeys.map((k) => [k, data.sources[k].available])),
  );
  const [metric, setMetric] = useState<Metric>('net');

  const merged = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string>>();
    for (const key of sourceKeys) {
      for (const point of data.sources[key].series) {
        const row = byDate.get(point.as_of) ?? { date: point.as_of };
        row[key] = point[metric];
        byDate.set(point.as_of, row);
      }
    }
    return [...byDate.values()].sort((a, b) =>
      String(a.date).localeCompare(String(b.date)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, metric]);

  if (sourceKeys.length === 0) return null;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        {sourceKeys.map((key) => {
          const source = data.sources[key];
          return (
            <label
              key={key}
              className={`flex items-center gap-1.5 ${
                source.available ? 'cursor-pointer' : 'cursor-not-allowed opacity-40'
              }`}
              title={source.description}
            >
              <input
                type="checkbox"
                disabled={!source.available}
                checked={!!enabled[key] && source.available}
                onChange={() => setEnabled((e) => ({ ...e, [key]: !e[key] }))}
                className="accent-current"
                style={{ color: SOURCE_COLORS[key] }}
              />
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: SOURCE_COLORS[key] ?? '#64748b' }}
              />
              {source.label}
              {!source.available && <span className="text-xs">(no data yet)</span>}
            </label>
          );
        })}
        <span className="ml-auto inline-flex overflow-hidden rounded border border-slate-200 text-xs">
          {METRICS.map((m) => (
            <button
              key={m.key}
              onClick={() => setMetric(m.key)}
              className={`px-2 py-1 ${
                metric === m.key
                  ? 'bg-slate-800 text-white'
                  : 'bg-white text-slate-600 hover:bg-slate-100'
              }`}
            >
              {m.label}
            </button>
          ))}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={340}>
        <LineChart data={merged} margin={{ top: 16, right: 16, left: 0, bottom: 0 }}>
          <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
          <YAxis
            domain={metric === 'net' ? ['auto', 'auto'] : [25, 70]}
            tick={{ fontSize: 11 }}
            unit={metric === 'net' ? '' : '%'}
          />
          {metric === 'net' && <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="4 4" />}
          <Tooltip
            formatter={(value: number, name: string) => [
              `${value.toFixed(1)}${metric === 'net' ? '' : '%'}`,
              data.sources[name]?.label ?? name,
            ]}
          />
          {sourceKeys
            .filter((key) => enabled[key] && data.sources[key].available)
            .map((key) => (
              <Line
                key={key}
                dataKey={key}
                name={key}
                stroke={SOURCE_COLORS[key] ?? '#64748b'}
                dot={false}
                strokeWidth={2}
                connectNulls
                isAnimationActive={false}
              />
            ))}
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs text-slate-400">
        Hover a checkbox label for each model&apos;s methodology. Sources publish on
        different cadences; lines connect across gaps.
      </p>
    </div>
  );
}
