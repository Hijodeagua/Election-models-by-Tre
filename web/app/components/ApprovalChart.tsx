'use client';

import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ApprovalSnapshot } from '@/app/lib/data';

// Approve line with a shaded confidence band. The band is drawn as a stacked
// area: a transparent base up to the lower bound, then a visible area covering
// (upper - lower).
export default function ApprovalChart({ trend }: { trend: ApprovalSnapshot[] }) {
  const data = trend.map((s) => {
    const lo = s.ci_approve ? s.ci_approve[0] : s.approve;
    const hi = s.ci_approve ? s.ci_approve[1] : s.approve;
    return {
      date: s.as_of,
      approve: s.approve,
      disapprove: s.disapprove,
      ciBase: lo,
      ciSpan: Math.max(0, hi - lo),
    };
  });

  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
        <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
        <YAxis domain={[30, 70]} tick={{ fontSize: 11 }} unit="%" />
        <Tooltip
          formatter={(value: number, name: string) =>
            name === 'ciBase' || name === 'ciSpan'
              ? [`${value.toFixed(1)}`, 'CI']
              : [`${value.toFixed(1)}%`, name]
          }
        />
        {/* Confidence band for the approve series. */}
        <Area dataKey="ciBase" stackId="ci" stroke="none" fill="transparent" isAnimationActive={false} />
        <Area
          dataKey="ciSpan"
          stackId="ci"
          stroke="none"
          fill="#2563eb"
          fillOpacity={0.15}
          isAnimationActive={false}
        />
        <Line dataKey="approve" name="Approve" stroke="#2563eb" dot={false} strokeWidth={2} />
        <Line dataKey="disapprove" name="Disapprove" stroke="#dc2626" dot={false} strokeWidth={2} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
