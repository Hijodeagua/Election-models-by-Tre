// Election-night results map in the style of the wire-service maps: called
// states filled for the winner (darker when the seat flipped), states still
// counting hatched with the share of the expected vote in, states with no
// results in grey, states with no Senate race in the quiet background.
// Server component; no interactivity needed.

import type { LiveForecastCall, LiveForecastRemaining } from '@/app/lib/data';
import { FILL, FILL_NOT_RACE } from '@/app/lib/predictions-map';
import { US_MAP_VIEWBOX, US_STATES, US_STATE_BORDERS } from '@/app/lib/us-states-paths';

const WIN: Record<string, string> = { D: FILL.D.likely, R: FILL.R.likely, I: FILL.I.likely };
const FLIP: Record<string, string> = { D: FILL.D.safe, R: FILL.R.safe, I: FILL.I.safe };
const NO_RESULTS = '#e4ddd6';
const REPORTING_BASE = '#ece6df';
const INK = '#2c1810';

// Small states whose label belongs off the shape.
const OFFSET: Record<string, { dx: number; dy: number }> = {
  NH: { dx: 62, dy: 24 },
  MA: { dx: 60, dy: 8 },
  RI: { dx: 48, dy: 22 },
  DE: { dx: 42, dy: 14 },
  NJ: { dx: 36, dy: 12 },
  MI: { dx: 22, dy: 42 },
  FL: { dx: 18, dy: 6 },
  LA: { dx: -10, dy: -4 },
  AK: { dx: 0, dy: 8 },
};

export default function LiveResultsMap({
  called,
  remaining,
}: {
  called: LiveForecastCall[];
  remaining: LiveForecastRemaining[];
}) {
  const abbrByName = new Map(Object.entries(US_STATES).map(([abbr, s]) => [s.name, abbr]));
  const calledBy = new Map(called.map((c) => [abbrByName.get(c.state), c]));
  const openBy = new Map(remaining.map((r) => [abbrByName.get(r.state), r]));

  return (
    <div>
      <svg
        viewBox={US_MAP_VIEWBOX}
        role="img"
        aria-label="Map of called and counting Senate races"
        className="h-auto w-full select-none"
      >
        <defs>
          <pattern
            id="reporting-hatch"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="6" height="6" fill={REPORTING_BASE} />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#b9a99f" strokeWidth="1.5" />
          </pattern>
        </defs>
        {Object.entries(US_STATES).map(([abbr, s]) => {
          const c = calledBy.get(abbr);
          const r = openBy.get(abbr);
          let fill = FILL_NOT_RACE;
          if (c) fill = (c.flip ? FLIP : WIN)[c.winner_party] ?? WIN.D;
          else if (r) fill = r.status === 'reporting' ? 'url(#reporting-hatch)' : NO_RESULTS;
          return <path key={abbr} d={s.d} fill={fill} stroke="#ffffff" strokeWidth="1" />;
        })}
        <path d={US_STATE_BORDERS} fill="none" stroke="#ffffff" strokeWidth="1" />
        {Object.entries(US_STATES).map(([abbr, s]) => {
          const c = calledBy.get(abbr);
          const r = openBy.get(abbr);
          if (!c && !r) return null;
          const off = OFFSET[abbr] ?? { dx: 0, dy: 0 };
          const x = s.cx + off.dx;
          const y = s.cy + off.dy;
          const onDark = !!c;
          const sub = c
            ? c.flip
              ? 'Flip'
              : ''
            : r && r.status === 'reporting' && r.eevp != null
              ? `${Math.round(r.eevp)}%`
              : '';
          return (
            <g key={`${abbr}-label`} pointerEvents="none">
              {off.dx !== 0 && (
                <line x1={s.cx} y1={s.cy} x2={x - 12} y2={y - 4} stroke="#7c5a52" strokeWidth="0.8" />
              )}
              <text
                x={x}
                y={sub ? y - 2 : y + 4}
                textAnchor="middle"
                fill={onDark && off.dx === 0 ? '#ffffff' : INK}
                fontSize="12"
                fontWeight="700"
                fontFamily="var(--font-serif-body), Georgia, serif"
              >
                {abbr}
              </text>
              {sub && (
                <text
                  x={x}
                  y={y + 10}
                  textAnchor="middle"
                  fill={onDark && off.dx === 0 ? '#ffffff' : INK}
                  fontSize="9.5"
                  fontWeight="600"
                  fontFamily="var(--font-serif-body), Georgia, serif"
                >
                  {sub}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-cocoa-500">
        <Legend fills={[WIN.D, FLIP.D]} label="Dem. win · flip" />
        <Legend fills={[WIN.R, FLIP.R]} label="Rep. win · flip" />
        <Legend fills={[WIN.I]} label="Ind. win" />
        <Legend fills={['url(#reporting-hatch)']} label="Counting (% of expected vote in)" hatched />
        <Legend fills={[NO_RESULTS]} label="No results yet" />
        <Legend fills={[FILL_NOT_RACE]} label="No Senate race" />
      </div>
    </div>
  );
}

function Legend({ fills, label, hatched = false }: { fills: string[]; label: string; hatched?: boolean }) {
  return (
    <span className="flex items-center gap-1">
      {fills.map((f, i) => (
        <span
          key={i}
          className="inline-block h-3 w-3 rounded-[3px] border border-white shadow-[0_0_0_1px_#e8ddd5]"
          style={
            hatched
              ? { backgroundImage: `repeating-linear-gradient(45deg, #b9a99f 0 1px, ${REPORTING_BASE} 1px 5px)` }
              : { backgroundColor: f }
          }
        />
      ))}
      <span className="ml-0.5">{label}</span>
    </span>
  );
}
