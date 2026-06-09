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
import type { ApprovalComparison, ComparisonSourceKey } from '@/app/lib/data';

const COLORS: Record<ComparisonSourceKey, string> = {
  our_model: '#2563eb',
  silver_bulletin: '#7c3aed',
  votehub_raw: '#059669',
  fifty_plus_one: '#d97706',
};

const ALL_SOURCES: ComparisonSourceKey[] = [
  'our_model',
  'silver_bulletin',
  'votehub_raw',
  'fifty_plus_one',
];

type Metric = 'approve' | 'net';

// Tweakable multi-source approval chart: toggle each source on/off and switch
// between approval % and net approval.
export default function ApprovalComparisonChart({ data }: { data: ApprovalComparison }) {
  const [metric, setMetric] = useState<Metric>('approve');
  const [enabled, setEnabled] = useState<Set<ComparisonSourceKey>>(
    () => new Set(data.available),
  );

  const merged = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string>>();
    for (const key of ALL_SOURCES) {
      for (const point of data.series[key] ?? []) {
        const row = byDate.get(point.as_of) ?? { date: point.as_of };
        row[key] = point[metric];
        byDate.set(point.as_of, row);
      }
    }
    return [...byDate.values()].sort((a, b) =>
      String(a.date) < String(b.date) ? -1 : 1,
    );
  }, [data, metric]);

  const toggle = (key: ComparisonSourceKey) =>
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        {ALL_SOURCES.map((key) => {
          const available = data.available.includes(key);
          return (
            <label
              key={key}
              className={`flex items-center gap-1.5 ${available ? 'cursor-pointer' : 'cursor-not-allowed opacity-40'}`}
            >
              <input
                type="checkbox"
                disabled={!available}
                checked={available && enabled.has(key)}
                onChange={() => toggle(key)}
                className="accent-current"
                style={{ accentColor: COLORS[key] }}
              />
              <span style={{ color: COLORS[key] }}>{data.labels[key]}</span>
              {!available && <span className="text-xs text-slate-400">(no data yet)</span>}
            </label>
          );
        })}
        <span className="ml-auto inline-flex overflow-hidden rounded-md border border-slate-300 text-xs">
          {(['approve', 'net'] as Metric[]).map((m) => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              className={`px-2 py-1 ${metric === m ? 'bg-slate-800 text-white' : 'bg-white text-slate-600'}`}
            >
              {m === 'approve' ? 'Approval %' : 'Net approval'}
            </button>
          ))}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={merged} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
          <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
          <YAxis
            domain={metric === 'approve' ? [30, 60] : [-25, 10]}
            tick={{ fontSize: 11 }}
            unit={metric === 'approve' ? '%' : ''}
          />
          {metric === 'net' && <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="4 4" />}
          <Tooltip
            formatter={(value: number, name: string) => [
              `${value.toFixed(1)}${metric === 'approve' ? '%' : ''}`,
              data.labels[name as ComparisonSourceKey] ?? name,
            ]}
          />
          {ALL_SOURCES.filter((key) => enabled.has(key)).map((key) => (
            <Line
              key={key}
              dataKey={key}
              stroke={COLORS[key]}
              dot={false}
              strokeWidth={2}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
