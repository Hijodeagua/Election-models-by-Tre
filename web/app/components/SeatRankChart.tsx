import type { RaceForecast } from '@/app/lib/data';

// Every seat on the ballot, ranked most- to least-Democratic by the model's
// win probability, snaking across two rows so the two ends meet: the top row
// runs left→right from the safest D seat, the bottom row runs right→left to
// the safest R seat. Democrats hold 34 seats not up, so the 17th seat is the
// majority line. A heavy outline marks a seat the model expects to flip.

type Rating = 'safe-d' | 'likely-d' | 'lean-d' | 'tossup' | 'lean-r' | 'likely-r' | 'safe-r';

const RATINGS: { key: Rating; label: string; range: string; fill: string; ink: string; min: number }[] = [
  { key: 'safe-d', label: 'Safe D', range: '>99%', fill: '#1e3a8a', ink: '#ffffff', min: 0.99 },
  { key: 'likely-d', label: 'Likely D', range: '80–99%', fill: '#2563eb', ink: '#ffffff', min: 0.8 },
  { key: 'lean-d', label: 'Lean D', range: '60–80%', fill: '#93c5fd', ink: '#2c1810', min: 0.6 },
  { key: 'tossup', label: 'Toss-up', range: '40–60%', fill: '#d9cfc7', ink: '#2c1810', min: 0.4 },
  { key: 'lean-r', label: 'Lean R', range: '20–40%', fill: '#fca5a5', ink: '#2c1810', min: 0.2 },
  { key: 'likely-r', label: 'Likely R', range: '1–20%', fill: '#dc2626', ink: '#ffffff', min: 0.01 },
  { key: 'safe-r', label: 'Safe R', range: '<1%', fill: '#7f1d1d', ink: '#ffffff', min: -1 },
];

const ABBR: Record<string, string> = {
  Alabama: 'AL', Alaska: 'AK', Arkansas: 'AR', Colorado: 'CO', Delaware: 'DE', Florida: 'FL',
  Georgia: 'GA', Idaho: 'ID', Illinois: 'IL', Iowa: 'IA', Kansas: 'KS', Kentucky: 'KY',
  Louisiana: 'LA', Maine: 'ME', Massachusetts: 'MA', Michigan: 'MI', Minnesota: 'MN',
  Mississippi: 'MS', Montana: 'MT', Nebraska: 'NE', 'New Hampshire': 'NH', 'New Jersey': 'NJ',
  'New Mexico': 'NM', 'North Carolina': 'NC', Ohio: 'OH', Oklahoma: 'OK', Oregon: 'OR',
  'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD', Tennessee: 'TN',
  Texas: 'TX', Virginia: 'VA', 'West Virginia': 'WV', Wyoming: 'WY',
};

function rating(p: number): (typeof RATINGS)[number] {
  return RATINGS.find((r) => p >= r.min) ?? RATINGS[RATINGS.length - 1];
}

export default function SeatRankChart({
  races,
  demHoldovers,
  threshold,
}: {
  races: RaceForecast[];
  demHoldovers: number;
  threshold: number;
}) {
  const ranked = races
    .map((r) => ({
      state: r.state,
      abbr: ABBR[r.state] ?? r.state.slice(0, 2).toUpperCase(),
      p: r.dem_win_prob_sim ?? r.dem_win_prob_blended ?? 0.5,
      heldBy: r.held_by ?? null,
    }))
    .sort((a, b) => b.p - a.p);
  const needed = threshold - demHoldovers; // seats Dems must win from this list
  const perRow = Math.ceil(ranked.length / 2);
  // Layout: top row left→right (most D first); bottom row right→left so the
  // most-R seat sits under the top row's right end, like a horseshoe.
  const tile = 46;
  const gap = 6;
  const rowGap = 44; // room for the bracket labels under the top row
  const padX = 8;
  const W = padX * 2 + perRow * tile + (perRow - 1) * gap;
  const H = 24 + tile + rowGap + tile + 36;
  const xAt = (i: number) => padX + i * (tile + gap);
  const topY = 24;
  const bottomY = topY + tile + rowGap;

  const counts = RATINGS.map((r) => ({
    ...r,
    n: ranked.filter((s) => rating(s.p).key === r.key).length,
  }));

  // Contiguous rating groups along the ranked order, for bracket labels.
  const groups: { key: Rating; label: string; start: number; end: number }[] = [];
  ranked.forEach((s, i) => {
    const r = rating(s.p);
    const last = groups[groups.length - 1];
    if (last && last.key === r.key) last.end = i;
    else groups.push({ key: r.key, label: r.label, start: i, end: i });
  });

  // Position helpers for a ranked index: row 0 (top) or 1 (bottom) and x.
  const pos = (i: number) => {
    if (i < perRow) return { row: 0, x: xAt(i), y: topY };
    // Bottom row runs right→left: ranked index perRow sits under the top
    // row's right-hand end and the ranking continues leftward.
    const col = perRow - 1 - (i - perRow);
    return { row: 1, x: xAt(Math.max(0, col)), y: bottomY };
  };

  // Split any rating group that wraps from the top row to the bottom row so
  // each row gets its own bracket.
  const segments = groups.flatMap((g) => {
    if (g.start < perRow && g.end >= perRow) {
      return [
        { ...g, end: perRow - 1 },
        { ...g, start: perRow },
      ];
    }
    return [g];
  });

  return (
    <div>
      <p className="mb-2 text-xs text-cocoa-500">
        The {ranked.length} races, ranked from most to least Democratic. With {demHoldovers}{' '}
        Democratic seats not up, Democrats need the {needed} most Democratic for {threshold}.
      </p>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-auto w-full min-w-[640px]"
          role="img"
          aria-label="Senate seats ranked by Democratic win probability"
        >
          <text x={padX} y={12} fontSize="10" fill="#a0736a">
            Most Democratic
          </text>
          {/* The bottom row runs right→left, so its Republican end is on the left. */}
          <text x={padX} y={H - 6} fontSize="10" fill="#a0736a">
            Most Republican
          </text>

          {/* majority line after the `needed`-th seat (top row) */}
          {needed > 0 && needed <= perRow && (
            <g>
              <line
                x1={xAt(needed) - gap / 2}
                x2={xAt(needed) - gap / 2}
                y1={topY - 10}
                y2={topY + tile + 10}
                stroke="#2c1810"
                strokeWidth="1.5"
                strokeDasharray="3 3"
              />
              <text
                x={xAt(needed) - gap / 2}
                y={topY - 14}
                fontSize="10"
                fontWeight="700"
                fill="#2c1810"
                textAnchor="middle"
              >
                {threshold} for a majority
              </text>
            </g>
          )}

          {ranked.map((s, i) => {
            const r = rating(s.p);
            const { x, y } = pos(i);
            const favored = s.p >= 0.5 ? 'D' : 'R';
            const flip = s.heldBy != null && s.heldBy !== favored;
            return (
              <g key={s.state}>
                <rect
                  x={x}
                  y={y}
                  width={tile}
                  height={tile}
                  rx={5}
                  fill={r.fill}
                  stroke={flip ? '#2c1810' : '#ffffff'}
                  strokeWidth={flip ? 2.5 : 1}
                />
                <text
                  x={x + tile / 2}
                  y={y + tile / 2 + 1}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize="12.5"
                  fontWeight="700"
                  fill={r.ink}
                  fontFamily="var(--font-serif-body), Georgia, serif"
                >
                  {s.abbr}
                </text>
                <title>{`${s.state}: ${Math.round(s.p * 100)}% D${flip ? ' (flip)' : ''}`}</title>
              </g>
            );
          })}

          {/* bracket labels under each contiguous rating group */}
          {segments.map((g) => {
            const a = pos(g.start);
            const b = pos(g.end);
            const left = Math.min(a.x, b.x);
            const right = Math.max(a.x, b.x) + tile;
            const y = a.row === 0 ? topY + tile + 6 : bottomY + tile + 6;
            return (
              <g key={`${g.key}-${g.start}`}>
                <path
                  d={`M${left + 2},${y} v5 H${right - 2} v-5`}
                  fill="none"
                  stroke="#c9b3a8"
                  strokeWidth="1"
                />
                <text x={(left + right) / 2} y={y + 17} fontSize="10" fill="#7c5a52" textAnchor="middle">
                  {g.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-4 grid grid-cols-4 gap-1.5 sm:grid-cols-7">
        {counts.map((r) => (
          <div
            key={r.key}
            className="rounded-lg px-2 py-2 text-center"
            style={{ backgroundColor: r.fill, color: r.ink }}
          >
            <div className="text-[12px] font-bold">{r.label}</div>
            <div className="text-[10px] opacity-90">{r.range}</div>
            <div className="mt-1 font-display text-lg leading-none">{r.n}</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-cocoa-400">
        Each box is a seat, shaded by the party our simulation favors and how strongly. A heavy
        outline marks a seat the model expects to change hands. Hover a box for its probability.
      </p>
    </div>
  );
}
