import type { SenateRaceSnapshot } from '@/app/lib/data';

// "If the election were held today": each key race as two dots — the
// Democrat's and the Republican's weighted polling average — with the
// average's confidence band behind each, on one shared percentage axis.
// Sorted by the Democrat's lead so the toss-ups cluster at the bottom.

const DEM = '#2563eb';
const REP = '#dc2626';
const DEM_BAND = 'rgba(37, 99, 235, 0.22)';
const REP_BAND = 'rgba(220, 38, 38, 0.22)';

interface Row {
  state: string;
  dem: string;
  rep: string;
  demPct: number;
  repPct: number;
  demCi: [number, number] | null;
  repCi: [number, number] | null;
  polls: number;
}

function findPct(c: Record<string, number>, name: string): number | null {
  const key = Object.keys(c).find(
    (k) => k.toLowerCase().includes(name.toLowerCase()) || name.toLowerCase().includes(k.toLowerCase()),
  );
  return key != null ? c[key] : null;
}

function findCi(
  ci: Record<string, [number, number] | null> | null | undefined,
  name: string,
): [number, number] | null {
  if (!ci) return null;
  const key = Object.keys(ci).find(
    (k) => k.toLowerCase().includes(name.toLowerCase()) || name.toLowerCase().includes(k.toLowerCase()),
  );
  return key != null ? ci[key] : null;
}

function surname(name: string): string {
  const parts = name.replace(/\s+(Jr\.|Sr\.|II|III|IV)$/i, '').split(/\s+/);
  return parts[parts.length - 1];
}

export default function RaceDumbbellChart({
  races,
  maxRows = 12,
  minPolls = 5,
}: {
  races: SenateRaceSnapshot[];
  maxRows?: number;
  minPolls?: number;
}) {
  const rows: Row[] = races
    .filter((r) => r.dem_candidate && r.rep_candidate && r.num_polls >= minPolls)
    .map((r) => {
      const demPct = findPct(r.candidates, r.dem_candidate!);
      const repPct = findPct(r.candidates, r.rep_candidate!);
      if (demPct == null || repPct == null) return null;
      return {
        state: r.state,
        dem: r.dem_candidate!,
        rep: r.rep_candidate!,
        demPct,
        repPct,
        demCi: findCi(r.candidate_ci, r.dem_candidate!),
        repCi: findCi(r.candidate_ci, r.rep_candidate!),
        polls: r.num_polls,
      };
    })
    .filter((r): r is Row => r != null)
    .sort((a, b) => Math.abs(a.demPct - a.repPct) - Math.abs(b.demPct - b.repPct))
    .slice(0, maxRows)
    .sort((a, b) => b.demPct - b.repPct - (a.demPct - a.repPct));

  if (rows.length === 0) return null;

  // Axis range from the data, padded, snapped to even numbers.
  const vals = rows.flatMap((r) => [
    r.demPct, r.repPct, ...(r.demCi ?? []), ...(r.repCi ?? []),
  ]);
  const lo = Math.floor((Math.min(...vals) - 1) / 2) * 2;
  const hi = Math.ceil((Math.max(...vals) + 1) / 2) * 2;
  const W = 640;
  const labelW = 118;
  const padR = 16;
  const rowH = 58;
  const topPad = 16;
  const axisH = 28;
  const H = topPad + rows.length * rowH + axisH;
  const plotW = W - labelW - padR;
  const x = (v: number) => labelW + ((v - lo) / (hi - lo)) * plotW;
  const ticks: number[] = [];
  for (let t = lo; t <= hi; t += 4) ticks.push(t);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full min-w-[560px]"
        role="img"
        aria-label="Polling averages for the key Senate races, Democrat versus Republican, with confidence bands"
      >
        {/* grid */}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={topPad} y2={H - axisH + 4} stroke="#f0ebe5" />
            <text x={x(t)} y={H - 8} fontSize="10" fill="#a0736a" textAnchor="middle">
              {t}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const yTop = topPad + i * rowH;
          const yD = yTop + 18;
          const yR = yTop + 38;
          const demLeads = r.demPct >= r.repPct;
          return (
            <g key={r.state}>
              <text
                x={labelW - 12}
                y={yTop + rowH / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize="13"
                fontWeight="600"
                fill="#2c1810"
                fontFamily="var(--font-serif-body), Georgia, serif"
              >
                {r.state}
              </text>
              {/* bands */}
              {r.demCi && (
                <rect x={x(r.demCi[0])} y={yD - 4} width={Math.max(2, x(r.demCi[1]) - x(r.demCi[0]))} height={8} rx={4} fill={DEM_BAND} />
              )}
              {r.repCi && (
                <rect x={x(r.repCi[0])} y={yR - 4} width={Math.max(2, x(r.repCi[1]) - x(r.repCi[0]))} height={8} rx={4} fill={REP_BAND} />
              )}
              {/* dots */}
              <circle cx={x(r.demPct)} cy={yD} r={4.5} fill={DEM} stroke="#fff" strokeWidth="1.5" />
              <circle cx={x(r.repPct)} cy={yR} r={4.5} fill={REP} stroke="#fff" strokeWidth="1.5" />
              {/* labels: value in bold, surname after; leader's label above its dot, trailer's below */}
              <text
                x={x(r.demPct)}
                y={yD - 9}
                fontSize="11"
                fill={DEM}
                textAnchor={demLeads ? 'start' : 'end'}
                dx={demLeads ? 6 : -6}
              >
                <tspan fontWeight="700">{r.demPct.toFixed(0)}{i === 0 ? '%' : ''}</tspan> {surname(r.dem)}
              </text>
              <text
                x={x(r.repPct)}
                y={yR + 15}
                fontSize="11"
                fill={REP}
                textAnchor={demLeads ? 'end' : 'start'}
                dx={demLeads ? -6 : 6}
              >
                <tspan fontWeight="700">{r.repPct.toFixed(0)}{i === 0 ? '%' : ''}</tspan> {surname(r.rep)}
              </text>
              <title>{`${r.state}: ${r.dem} ${r.demPct.toFixed(1)}, ${r.rep} ${r.repPct.toFixed(1)} (${r.polls} polls)`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
