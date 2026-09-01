'use client';

import type { SenateForecastData } from '@/app/lib/data';

// Parliament-style hemicycle of all 100 Senate seats. Seats are ordered from
// the Democratic side (left) to the Republican side (right) and each dot is
// shaded by the share of simulations in which Democrats win at least that
// many seats — so safe seats read solid blue/red and the contested band in
// the middle fades through a neutral toss-up gray.

const DEM = { r: 0x25, g: 0x63, b: 0xeb }; // #2563eb — matches bg-dem
const REP = { r: 0xdc, g: 0x26, b: 0x26 }; // #dc2626 — matches bg-rep
const MID = { r: 0xb3, g: 0xa8, b: 0x9f }; // neutral warm gray at 50/50

// Concentric row sizes, innermost first (sums to 100).
const ROWS = [16, 18, 20, 22, 24];
const CX = 200;
const CY = 214;
const INNER_RADIUS = 104;
const ROW_GAP = 20;
const DOT_RADIUS = 7;

type Rgb = { r: number; g: number; b: number };

function mix(a: Rgb, b: Rgb, t: number): string {
  const ch = (x: number, y: number) => Math.round(x + (y - x) * t);
  return `rgb(${ch(a.r, b.r)}, ${ch(a.g, b.g)}, ${ch(a.b, b.b)})`;
}

// p = P(seat is Democratic). Diverging: red → neutral → blue.
function seatColor(p: number): string {
  return p >= 0.5 ? mix(MID, DEM, (p - 0.5) * 2) : mix(REP, MID, p * 2);
}

export default function SenateHemicycle({ forecast }: { forecast: SenateForecastData }) {
  const total = forecast.num_simulations;
  const dist = forecast.seat_distribution;
  const simulatedSeats = Object.keys(dist).map(Number);
  if (!total || simulatedSeats.length === 0) return null;
  const maxSimulated = Math.max(...simulatedSeats);

  // P(Democrats win at least k seats). Below the simulated range every
  // simulation clears k (the safe-seat floor); above it none do.
  const pAtLeast = (k: number): number => {
    if (k > maxSimulated) return 0;
    let sims = 0;
    for (const [s, count] of Object.entries(dist)) {
      if (Number(s) >= k) sims += count;
    }
    return Math.min(1, sims / total);
  };
  const probs = Array.from({ length: 100 }, (_, i) => pAtLeast(i + 1));

  // Lay the dots out row by row, then order them by angle (left → right) so
  // seat 1 sits on the Democratic edge and seat 100 on the Republican edge.
  const positions: { x: number; y: number; theta: number; radius: number }[] = [];
  ROWS.forEach((count, row) => {
    const radius = INNER_RADIUS + row * ROW_GAP;
    for (let j = 0; j < count; j += 1) {
      const theta = Math.PI - (Math.PI * j) / (count - 1);
      positions.push({
        x: CX + radius * Math.cos(theta),
        y: CY - radius * Math.sin(theta),
        theta,
        radius,
      });
    }
  });
  positions.sort((a, b) => b.theta - a.theta || a.radius - b.radius);

  // Majority divider at the angle of the threshold seat.
  const thresholdSeat = positions[forecast.dem_majority_threshold - 1];
  const dividerInner = INNER_RADIUS - 14;
  const dividerOuter = INNER_RADIUS + (ROWS.length - 1) * ROW_GAP + 14;
  const labelRadius = dividerOuter + 8;

  return (
    <div>
      <svg
        viewBox="0 0 400 224"
        role="img"
        aria-label={`Hemicycle of 100 Senate seats shaded by the probability Democrats win each seat, from ${forecast.num_simulations.toLocaleString()} simulations. Democrats reach the ${forecast.dem_majority_threshold}-seat majority in ${(forecast.dem_control_prob * 100).toFixed(0)}% of simulations.`}
        className="mx-auto block w-full max-w-xl"
      >
        {positions.map((pos, i) => {
          const seat = i + 1;
          const p = probs[i];
          return (
            <circle key={seat} cx={pos.x} cy={pos.y} r={DOT_RADIUS} fill={seatColor(p)}>
              <title>
                {`Seat ${seat} of 100 — Democratic in ${(p * 100).toFixed(p >= 0.995 || p <= 0.005 ? 1 : 0)}% of simulations`}
              </title>
            </circle>
          );
        })}
        <line
          x1={CX + dividerInner * Math.cos(thresholdSeat.theta)}
          y1={CY - dividerInner * Math.sin(thresholdSeat.theta)}
          x2={CX + dividerOuter * Math.cos(thresholdSeat.theta)}
          y2={CY - dividerOuter * Math.sin(thresholdSeat.theta)}
          stroke="#2c1810"
          strokeWidth={1.5}
          strokeDasharray="4 4"
          strokeOpacity={0.85}
        />
        <text
          x={CX + labelRadius * Math.cos(thresholdSeat.theta)}
          y={CY - labelRadius * Math.sin(thresholdSeat.theta) - 2}
          textAnchor="middle"
          fontSize={10}
          fill="#5c3d2a"
        >
          {`D majority (${forecast.dem_majority_threshold})`}
        </text>
      </svg>
      <div className="mx-auto mt-3 max-w-sm">
        <div
          className="h-2.5 rounded-full"
          style={{
            background: `linear-gradient(to right, rgb(${DEM.r}, ${DEM.g}, ${DEM.b}), rgb(${MID.r}, ${MID.g}, ${MID.b}) 50%, rgb(${REP.r}, ${REP.g}, ${REP.b}))`,
          }}
        />
        <div className="mt-1 flex justify-between text-[10px] text-cocoa-400">
          <span>Always D</span>
          <span>Toss-up</span>
          <span>Always R</span>
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-cocoa-400">
        Each dot is one seat, shaded by the share of simulations in which Democrats hold
        it — hover a dot for the exact number.
      </p>
    </div>
  );
}
