'use client';

import { useState } from 'react';
import type { MarginDistribution as Dist } from '@/app/lib/data';
import { fmtMargin } from '@/app/lib/format';

// Histogram of the Dem − Rep margin: red bars left of Even, blue bars right,
// the 80% band shaded behind, the median as a hairline and the user's own
// call as a peach marker. One axis, direct labels, no legend needed (the two
// hues are the two parties, named in the axis labels).
export default function MarginDistributionChart({
  dist,
  pickMargin,
  compact = false,
}: {
  dist: Dist;
  pickMargin: number | null;
  compact?: boolean;
}) {
  const [hoverBin, setHoverBin] = useState<number | null>(null);
  const W = compact ? 200 : 320;
  const H = compact ? 54 : 120;
  const padX = compact ? 4 : 10;
  const padTop = compact ? 4 : 10;
  const axisH = compact ? 12 : 18;
  const plotH = H - padTop - axisH;
  const bins = dist.hist;
  const maxP = Math.max(...bins.map((b) => b.pct), 1e-6);
  const lo = bins[0].mid - 1;
  const hi = bins[bins.length - 1].mid + 1;
  const x = (m: number) => padX + ((m - lo) / (hi - lo)) * (W - 2 * padX);
  const binW = x(bins[1].mid) - x(bins[0].mid);
  const gap = compact ? 1 : 2;
  const hovered = hoverBin != null ? bins[hoverBin] : null;

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={compact ? 'h-auto w-full' : 'h-auto w-full'}
        role="img"
        aria-label={`Distribution of the Democratic minus Republican margin, median ${fmtMargin(dist.median)}`}
        onPointerLeave={() => setHoverBin(null)}
      >
        {/* 80% band */}
        {dist.p10 != null && dist.p90 != null && (
          <rect
            x={x(dist.p10)}
            y={padTop}
            width={Math.max(0, x(dist.p90) - x(dist.p10))}
            height={plotH}
            fill="#f0ebe5"
          />
        )}
        {/* bars */}
        {bins.map((b, i) => {
          const h = (b.pct / maxP) * plotH;
          const isHov = hoverBin === i;
          return (
            <g key={b.mid}>
              <rect
                x={x(b.mid) - binW / 2 + gap / 2}
                y={padTop + plotH - h}
                width={Math.max(0.5, binW - gap)}
                height={h}
                rx={compact ? 0.5 : 1.5}
                fill={b.mid < 0 ? '#dc2626' : '#2563eb'}
                opacity={isHov ? 1 : 0.85}
              />
              {!compact && (
                <rect
                  x={x(b.mid) - binW / 2}
                  y={padTop}
                  width={binW}
                  height={plotH}
                  fill="transparent"
                  onPointerEnter={() => setHoverBin(i)}
                />
              )}
            </g>
          );
        })}
        {/* baseline + Even tick */}
        <line x1={padX} x2={W - padX} y1={padTop + plotH} y2={padTop + plotH} stroke="#e8ddd5" />
        <line
          x1={x(0)}
          x2={x(0)}
          y1={padTop}
          y2={padTop + plotH}
          stroke="#c9b3a8"
          strokeDasharray="2 2"
        />
        {/* median */}
        {dist.median != null && (
          <line
            x1={x(dist.median)}
            x2={x(dist.median)}
            y1={padTop - 2}
            y2={padTop + plotH}
            stroke="#2c1810"
            strokeWidth={compact ? 1 : 1.5}
          />
        )}
        {/* the user's call */}
        {pickMargin != null && (
          <g>
            <line
              x1={x(pickMargin)}
              x2={x(pickMargin)}
              y1={padTop - 2}
              y2={padTop + plotH}
              stroke="#c1533d"
              strokeWidth={compact ? 1.5 : 2}
            />
            {!compact && (
              <text
                x={x(pickMargin)}
                y={padTop + 8}
                dx={pickMargin >= (dist.median ?? 0) ? 4 : -4}
                textAnchor={pickMargin >= (dist.median ?? 0) ? 'start' : 'end'}
                fontSize="9"
                fontWeight="700"
                fill="#c1533d"
              >
                my call
              </text>
            )}
          </g>
        )}
        {/* axis labels */}
        <g fontSize={compact ? 7 : 9} fill="#a0736a">
          <text x={x(-20)} y={H - 3} textAnchor="middle">
            R+20
          </text>
          <text x={x(0)} y={H - 3} textAnchor="middle">
            Even
          </text>
          <text x={x(20)} y={H - 3} textAnchor="middle">
            D+20
          </text>
        </g>
      </svg>
      {!compact && (
        <div className="mt-1 flex items-center justify-between text-[11px] text-cocoa-400">
          <span>
            <span className="mr-1 inline-block h-2.5 w-0.5 bg-ink align-middle" /> median{' '}
            <strong className="text-cocoa-700">{fmtMargin(dist.median)}</strong>
            {dist.p10 != null && dist.p90 != null && (
              <>
                {' '}· 80% band {fmtMargin(dist.p10)} to {fmtMargin(dist.p90)}
              </>
            )}
          </span>
          <span>
            {hovered
              ? `${fmtMargin(hovered.mid - 1, 0)} to ${fmtMargin(hovered.mid + 1, 0)}: ${(hovered.pct * 100).toFixed(1)}%`
              : 'hover a bar'}
          </span>
        </div>
      )}
    </div>
  );
}
