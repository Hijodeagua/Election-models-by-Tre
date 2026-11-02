'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { Party, PredictionRaceView } from '@/app/lib/predictions-shared';
import { marginBucket, toDemMargin, toPredictionsFile } from '@/app/lib/predictions-shared';
import { US_MAP_VIEWBOX, US_STATES, US_STATE_BORDERS } from '@/app/lib/us-states-paths';
import { fmtMargin, fmtProb } from '@/app/lib/format';
import { Panel, StatCard } from '@/app/components/ui';
import MarginDistributionChart from '@/app/components/MarginDistribution';
import type { SenateContest } from '@/app/lib/data';
import {
  FILL,
  FILL_NOT_RACE,
  FILL_NO_PICK,
  LABEL_ADJUST,
  boardSummary,
  fmtNet,
  fmtWinnerMargin,
  senateTotal,
  stateFill,
} from '@/app/lib/predictions-map';
import ShareDialog from '@/app/components/ShareDialog';

const PARTY_LABEL: Record<Party, string> = { D: 'Democrat', R: 'Republican', I: 'Independent' };
const PARTY_TEXT: Record<Party, string> = { D: 'text-dem', R: 'text-rep', I: 'text-stamp' };

const STORAGE_KEY = 'election-oracle:predictions-overrides:v1';

interface Override {
  pick: Party | null;
  margin: number | null;
}

type Effective = PredictionRaceView;

function candidateFor(race: Effective, party: Party | null): string | null {
  if (party === 'D') return race.dem_candidate;
  if (party === 'R') return race.rep_candidate;
  if (party === 'I') return race.ind_candidate;
  return null;
}

export default function PredictionsBoard({
  races,
  asOf,
}: {
  races: PredictionRaceView[];
  asOf: string;
}) {
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<{ abbr: string; x: number; y: number } | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [copied, setCopied] = useState(false);
  const [sharing, setSharing] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Local edits live in this browser only; the committed JSON stays the
  // published truth. Read them after mount so SSR and first paint agree.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setOverrides(JSON.parse(raw) as Record<string, Override>);
    } catch {
      /* storage unavailable — fall through to published picks */
    }
  }, []);

  const effective: Effective[] = useMemo(
    () => races.map((r) => (overrides[r.abbr] ? { ...r, ...overrides[r.abbr] } : r)),
    [races, overrides],
  );
  const byAbbr = useMemo(() => new Map(effective.map((r) => [r.abbr, r])), [effective]);
  const hasOverrides = Object.keys(overrides).length > 0;

  function update(abbr: string, patch: Partial<Override>) {
    const base = byAbbr.get(abbr);
    if (!base) return;
    const current: Override = overrides[abbr] ?? { pick: base.pick, margin: base.margin };
    const next: Record<string, Override> = {
      ...overrides,
      [abbr]: { ...current, ...patch },
    };
    // A pick with no party has no margin either.
    if (next[abbr].pick == null) next[abbr].margin = null;
    setOverrides(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }

  function discardOverrides() {
    setOverrides({});
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }

  const exportJson = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return JSON.stringify(toPredictionsFile(effective, hasOverrides ? today : asOf), null, 2);
  }, [effective, asOf, hasOverrides]);

  async function copyJson() {
    try {
      await navigator.clipboard.writeText(exportJson);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setShowJson(true);
    }
  }

  // Summary numbers
  const { picks, flipsToD, flipsToR, uncalled, net: netFlips, indFlips } = boardSummary(effective);
  const total = senateTotal(effective);

  const sel = selected ? byAbbr.get(selected) ?? null : null;
  const hov = hover ? byAbbr.get(hover.abbr) ?? null : null;

  function onPointerMove(e: React.PointerEvent, abbr: string) {
    const box = wrapRef.current?.getBoundingClientRect();
    if (!box) return;
    setHover({ abbr, x: e.clientX - box.left, y: e.clientY - box.top });
  }

  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Called for Democrats"
          value={String(picks.D)}
          tone="dem"
          sub={flipsToD > 0 ? `${flipsToD} pickup${flipsToD === 1 ? '' : 's'}` : 'holds only'}
        />
        <StatCard
          label="Called for Republicans"
          value={String(picks.R)}
          tone="rep"
          sub={flipsToR > 0 ? `${flipsToR} pickup${flipsToR === 1 ? '' : 's'}` : 'holds only'}
        />
        <StatCard
          label="Net seat change"
          value={fmtNet(netFlips)}
          tone={netFlips > 0 ? 'dem' : netFlips < 0 ? 'rep' : 'ink'}
          sub={
            indFlips > 0
              ? `${indFlips} to an independent`
              : `across ${effective.length} races on the board`
          }
        />
        <StatCard
          label="Still to call"
          value={String(uncalled)}
          tone="peach"
          sub={uncalled === 0 ? 'every race has a guess' : 'hatched on the map'}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-xl border border-cream-300 bg-white px-4 py-3">
        <div className="font-display text-xl text-ink sm:text-2xl">
          Senate after these guesses:{' '}
          <span className="text-dem">{total.D} D</span>,{' '}
          <span className="text-rep">{total.R} R</span>
          {total.I > 0 && (
            <>
              , <span className="text-stamp">{total.I} I</span>
            </>
          )}
          {total.uncalled > 0 && (
            <span className="text-cocoa-400">, {total.uncalled} still to call</span>
          )}
        </div>
        <div className="text-[11px] text-cocoa-400">
          34 D and 31 R seats not up, plus 9 safe D and 9 safe R holds, plus the board
        </div>
      </div>

      <Panel className="mt-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <Legend />
          <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setSharing(true)}
            className="rounded-lg border border-peach bg-peach px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-peach-hover"
          >
            Share
          </button>
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            aria-pressed={editing}
            className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
              editing
                ? 'border-peach bg-peach text-white hover:bg-peach-hover'
                : 'border-cream-300 bg-cream-50 text-cocoa-700 hover:border-peach hover:text-peach'
            }`}
          >
            {editing ? 'Done editing' : 'Edit guesses'}
          </button>
          </div>
        </div>

        <div ref={wrapRef} className="relative" onPointerLeave={() => setHover(null)}>
          <svg
            viewBox={US_MAP_VIEWBOX}
            role="img"
            aria-label="Map of the United States shaded by predicted Senate winner and margin"
            className="h-auto w-full select-none"
          >
            <defs>
              <pattern
                id="no-pick-hatch"
                width="6"
                height="6"
                patternUnits="userSpaceOnUse"
                patternTransform="rotate(45)"
              >
                <rect width="6" height="6" fill={FILL_NO_PICK} />
                <line x1="0" y1="0" x2="0" y2="6" stroke="#b9a99f" strokeWidth="1.5" />
              </pattern>
            </defs>

            {/* States off the board: safe holds in their party's safe shade
                (unlabelled), everything else as "no 2026 race". */}
            {Object.entries(US_STATES).map(([abbr, s]) =>
              byAbbr.has(abbr) ? null : (
                <path
                  key={abbr}
                  d={s.d}
                  fill={stateFill(abbr, undefined, marginBucket, '').fill}
                  stroke="none"
                />
              ),
            )}

            {/* Interior borders in one stroke so adjacent fills keep a 1px gap */}
            <path d={US_STATE_BORDERS} fill="none" stroke="#ffffff" strokeWidth="1" />

            {/* Race states */}
            {effective.map((r) => {
              const s = US_STATES[r.abbr];
              if (!s) return null;
              const fill = stateFill(r.abbr, r, marginBucket, 'url(#no-pick-hatch)').fill;
              const isSel = selected === r.abbr;
              const isHov = hover?.abbr === r.abbr;
              return (
                <path
                  key={r.abbr}
                  d={s.d}
                  fill={fill}
                  stroke={isSel ? '#2c1810' : '#ffffff'}
                  strokeWidth={isSel ? 2.5 : 1}
                  strokeLinejoin="round"
                  opacity={isHov && !isSel ? 0.85 : 1}
                  tabIndex={0}
                  role="button"
                  aria-label={`${r.state}: ${
                    r.pick ? `${PARTY_LABEL[r.pick]} ${fmtWinnerMargin(r.pick, r.margin)}` : 'no guess yet'
                  }`}
                  // Focus fires before click, so a click must select (not
                  // toggle) or the pointer path would immediately deselect.
                  onClick={() => setSelected(r.abbr)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setSelected(r.abbr);
                    }
                  }}
                  onFocus={() => setSelected(r.abbr)}
                  onPointerMove={(e) => onPointerMove(e, r.abbr)}
                  className="cursor-pointer outline-none transition-opacity focus-visible:[stroke:#c1533d] focus-visible:[stroke-width:3]"
                />
              );
            })}

            {/* Labels on top of every race state */}
            {effective.map((r) => {
              const s = US_STATES[r.abbr];
              if (!s) return null;
              const adj = LABEL_ADJUST[r.abbr] ?? { dx: 0, dy: 0 };
              const x = s.cx + adj.dx;
              const y = s.cy + adj.dy;
              const bucket = marginBucket(r.margin);
              const onLight = r.pick == null || bucket === 'lean' || adj.leader;
              const colour = onLight ? '#2c1810' : '#ffffff';
              const marginTxt = r.pick == null ? '—' : fmtWinnerMargin(r.pick, r.margin);
              return (
                <g key={`${r.abbr}-label`} pointerEvents="none">
                  {adj.leader && (
                    <line
                      x1={s.cx}
                      y1={s.cy}
                      x2={x - 14}
                      y2={y - 4}
                      stroke="#7c5a52"
                      strokeWidth="1"
                    />
                  )}
                  <text
                    x={x}
                    y={y - 2}
                    textAnchor="middle"
                    fill={colour}
                    fontSize="12.5"
                    fontWeight="700"
                    fontFamily="var(--font-serif-body), Georgia, serif"
                  >
                    {r.abbr}
                  </text>
                  <text
                    x={x}
                    y={y + 10}
                    textAnchor="middle"
                    fill={colour}
                    fontSize="10"
                    fontWeight="600"
                    fontFamily="var(--font-serif-body), Georgia, serif"
                    className="hidden sm:block"
                  >
                    {marginTxt}
                  </text>
                </g>
              );
            })}
          </svg>

          {hov && hover && (
            <div
              role="tooltip"
              className="pointer-events-none absolute z-10 w-[250px] rounded-lg border border-cream-300 bg-white px-3 py-2 text-xs shadow-md"
              style={{
                left: Math.max(0, Math.min(hover.x + 14, (wrapRef.current?.clientWidth ?? 400) - 260)),
                // Flip above the pointer in the lower half so the card never
                // runs off the bottom of the map.
                ...(hover.y > (wrapRef.current?.clientHeight ?? 600) / 2
                  ? { bottom: (wrapRef.current?.clientHeight ?? 600) - hover.y + 14 }
                  : { top: hover.y + 14 }),
              }}
            >
              <div className="font-display text-sm text-ink">{hov.state}</div>
              <div className="mt-0.5 text-cocoa-700">
                {hov.pick ? (
                  <>
                    <strong className={PARTY_TEXT[hov.pick]}>
                      {candidateFor(hov, hov.pick) ?? PARTY_LABEL[hov.pick]}
                    </strong>{' '}
                    {hov.margin != null ? (
                      <>
                        by <strong>{hov.margin.toFixed(1)}</strong>
                      </>
                    ) : (
                      <span className="text-cocoa-400">(margin not set)</span>
                    )}
                  </>
                ) : (
                  <span className="text-cocoa-400">No guess yet</span>
                )}
              </div>
              <TooltipFacts race={hov} />
            </div>
          )}
        </div>

        <p className="mt-2 text-xs text-cocoa-400">
          Click or tab to a state for the full matchup. Shading deepens with the predicted
          margin: under 3 points lean, 3–8 likely, 8+ safe. Unlabelled dark states are the
          safe holds not on the board; grey states have no Senate race this cycle.
        </p>
      </Panel>

      {/* Selected race detail */}
      <Panel className="mt-4" title={sel ? `${sel.state} Senate` : 'Race detail'}>
        {sel ? (
          <RaceDetail race={sel} editing={editing} onChange={(patch) => update(sel.abbr, patch)} />
        ) : (
          <p className="text-sm text-cocoa-500">
            Choose a state on the map or a row in the table below to see the matchup, the guess
            and how it compares to the model.
          </p>
        )}
      </Panel>

      {/* All races */}
      <div className="mt-4 overflow-x-auto rounded-xl border border-cream-300 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
              <th className="px-4 py-3">State</th>
              <th className="px-4 py-3">Held by</th>
              <th className="px-4 py-3">Matchup</th>
              <th className="px-4 py-3 text-right">Hijodeagua&rsquo;s guesses</th>
              <th className="px-4 py-3 text-right">Model</th>
              <th className="px-4 py-3 text-right" title="Your Dem−Rep margin minus the model's median">
                Δ vs model
              </th>
            </tr>
          </thead>
          <tbody>
            {effective.map((r) => {
              const mine = toDemMargin(r.pick, r.margin);
              const modelMed = r.model?.median_margin ?? null;
              const delta = mine != null && modelMed != null ? mine - modelMed : null;
              const isSel = selected === r.abbr;
              return (
                <tr
                  key={r.abbr}
                  onClick={() => setSelected(isSel ? null : r.abbr)}
                  className={`cursor-pointer border-b border-cream-100 last:border-0 ${
                    isSel ? 'bg-peach-wash' : 'hover:bg-cream-50'
                  }`}
                >
                  <td className="px-4 py-3 font-medium text-cocoa-700">
                    {r.state}
                    {r.note && (
                      <span className="ml-1 text-cocoa-400" title={r.note}>
                        *
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${PARTY_TEXT[r.held_by]}`}>{r.held_by}</span>
                    {r.open && <span className="ml-1 text-xs text-cocoa-400">open</span>}
                  </td>
                  <td className="px-4 py-3 text-cocoa-500">
                    <Matchup race={r} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {r.pick ? (
                      <strong className={PARTY_TEXT[r.pick]}>{fmtWinnerMargin(r.pick, r.margin)}</strong>
                    ) : (
                      <span className="text-cocoa-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-cocoa-700">
                    {modelMed != null ? (
                      <>
                        <span className={modelMed > 0 ? 'text-dem' : modelMed < 0 ? 'text-rep' : ''}>
                          {fmtMargin(modelMed)}
                        </span>
                        {r.model?.dem_win_prob != null && (
                          <span className="ml-1 text-xs text-cocoa-400">
                            {fmtProb(r.model.dem_win_prob)} D
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-cocoa-400">not modelled</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-cocoa-700">
                    {delta != null ? (
                      <span className={Math.abs(delta) < 0.05 ? '' : delta > 0 ? 'text-dem' : 'text-rep'}>
                        {delta > 0 ? '+' : ''}
                        {delta.toFixed(1)}
                      </span>
                    ) : (
                      <span className="text-cocoa-400">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-cocoa-400">
        Model columns come from the Senate simulation on this site (median Dem−Rep margin and
        the Democrat&rsquo;s win probability). * marks a special election or other note; hover
        the asterisk to read it.
      </p>

      {sharing && (
        <ShareDialog
          races={effective}
          asOf={hasOverrides ? new Date().toISOString().slice(0, 10) : asOf}
          onClose={() => setSharing(false)}
        />
      )}

      {(editing || hasOverrides) && (
        <div className="mt-6 rounded-xl border border-peach-border bg-peach-wash p-4 text-sm text-cocoa-700">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <strong>Edits are saved in this browser only.</strong>{' '}
              To publish them, copy the JSON and paste it over{' '}
              <code className="rounded bg-white px-1 text-xs">web/content/predictions.json</code>, then
              commit.
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={copyJson}
                className="rounded-lg bg-peach px-3 py-1.5 text-xs font-semibold text-white hover:bg-peach-hover"
              >
                {copied ? 'Copied!' : 'Copy predictions.json'}
              </button>
              <button
                type="button"
                onClick={() => setShowJson((v) => !v)}
                className="rounded-lg border border-peach-border bg-white px-3 py-1.5 text-xs font-semibold text-peach hover:border-peach"
              >
                {showJson ? 'Hide JSON' : 'Show JSON'}
              </button>
              {hasOverrides && (
                <button
                  type="button"
                  onClick={discardOverrides}
                  className="rounded-lg border border-cream-300 bg-white px-3 py-1.5 text-xs font-semibold text-cocoa-500 hover:text-ink"
                >
                  Discard local edits
                </button>
              )}
            </div>
          </div>
          {showJson && (
            <textarea
              readOnly
              value={exportJson}
              onFocus={(e) => e.currentTarget.select()}
              className="mt-3 h-64 w-full rounded-lg border border-cream-300 bg-white p-3 font-mono text-[11px] text-cocoa-700"
            />
          )}
        </div>
      )}
    </div>
  );
}

function Matchup({ race }: { race: Effective }) {
  const parts: React.ReactNode[] = [];
  if (race.dem_candidate)
    parts.push(
      <span key="d" className="whitespace-nowrap">
        {race.dem_candidate} <span className="text-dem">(D)</span>
      </span>,
    );
  if (race.rep_candidate)
    parts.push(
      <span key="r" className="whitespace-nowrap">
        {race.rep_candidate} <span className="text-rep">(R)</span>
      </span>,
    );
  if (race.ind_candidate)
    parts.push(
      <span key="i" className="whitespace-nowrap">
        {race.ind_candidate} <span className="text-stamp">(I)</span>
      </span>,
    );
  if (parts.length === 0) {
    return (
      <span className="text-cocoa-400">
        {race.incumbent ? `${race.incumbent} (${race.held_by})${race.open ? ', retiring' : ''}` : 'TBD'}
      </span>
    );
  }
  return (
    <>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && <span className="mx-1 text-cocoa-300">v.</span>}
          {p}
        </span>
      ))}
    </>
  );
}

function RaceDetail({
  race,
  editing,
  onChange,
}: {
  race: Effective;
  editing: boolean;
  onChange: (patch: Partial<Override>) => void;
}) {
  const winner = race.pick ? candidateFor(race, race.pick) ?? PARTY_LABEL[race.pick] : null;
  const mine = toDemMargin(race.pick, race.margin);
  const m = race.model;
  const parties: Party[] = ['D', 'R', 'I'];

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-cocoa-400">
          Matchup
        </div>
        <p className="mt-1 text-sm text-cocoa-700">
          <Matchup race={race} />
        </p>
        <p className="mt-1 text-xs text-cocoa-400">
          Seat held by{' '}
          <span className={`font-semibold ${PARTY_TEXT[race.held_by]}`}>
            {PARTY_LABEL[race.held_by]}s
          </span>
          {race.incumbent && ` (${race.incumbent}${race.open ? ', not running' : ''})`}.
          {race.note && ` ${race.note}`}
        </p>

        <div className="mt-4 text-[11px] font-bold uppercase tracking-[0.1em] text-cocoa-400">
          Hijodeagua&rsquo;s guess
        </div>
        {editing ? (
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            {parties.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => onChange({ pick: p })}
                aria-pressed={race.pick === p}
                className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                  race.pick === p
                    ? p === 'D'
                      ? 'border-dem bg-dem text-white'
                      : p === 'R'
                        ? 'border-rep bg-rep text-white'
                        : 'border-stamp bg-stamp text-white'
                    : 'border-cream-300 bg-cream-50 text-cocoa-700 hover:border-cocoa-300'
                }`}
              >
                {candidateFor(race, p) ?? PARTY_LABEL[p]}
              </button>
            ))}
            <button
              type="button"
              onClick={() => onChange({ pick: null, margin: null })}
              className="rounded-lg border border-transparent px-2 py-1.5 text-xs text-cocoa-400 hover:text-ink"
            >
              Clear
            </button>
            <label className="ml-auto flex items-center gap-2 text-xs text-cocoa-500">
              by
              <input
                type="number"
                inputMode="decimal"
                min={0}
                max={60}
                step={0.5}
                value={race.margin ?? ''}
                disabled={race.pick == null}
                placeholder="pts"
                onChange={(e) =>
                  onChange({ margin: e.target.value === '' ? null : Math.max(0, Number(e.target.value)) })
                }
                className="w-20 rounded-lg border border-cream-300 bg-white px-2 py-1.5 text-sm text-ink disabled:opacity-50"
              />
              pts
            </label>
          </div>
        ) : (
          <p className="mt-1 text-sm text-cocoa-700">
            {race.pick ? (
              <>
                <strong className={PARTY_TEXT[race.pick]}>{winner}</strong>
                {race.margin != null ? (
                  <>
                    {' '}
                    wins by <strong>{race.margin.toFixed(1)}</strong> points
                    {race.pick !== race.held_by && (
                      <span className="ml-2 inline-flex rounded-full border border-peach-border bg-peach-wash px-2 py-0.5 text-[11px] font-semibold text-peach">
                        {race.pick === 'I' ? 'Flip to I' : `${race.held_by}→${race.pick} flip`}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-cocoa-400"> — margin not set</span>
                )}
              </>
            ) : (
              <span className="text-cocoa-400">No guess yet. Turn on Edit guesses to make one.</span>
            )}
          </p>
        )}
      </div>

      <div>
        <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-cocoa-400">
          Versus the model
        </div>
        {m ? (
          <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-cocoa-400">Polling average</dt>
            <dd className="text-right font-medium text-cocoa-700">{fmtMargin(m.poll_margin)}</dd>
            <dt className="text-cocoa-400">Simulation median</dt>
            <dd className="text-right font-medium text-cocoa-700">{fmtMargin(m.median_margin)}</dd>
            <dt className="text-cocoa-400">P(Democrat wins)</dt>
            <dd className="text-right font-medium text-cocoa-700">
              {m.dem_win_prob != null ? fmtProb(m.dem_win_prob) : '—'}
            </dd>
            <dt className="text-cocoa-400">Guessed margin</dt>
            <dd className="text-right font-medium text-cocoa-700">
              {race.pick === 'I' ? `I+${race.margin?.toFixed(1) ?? '?'}` : fmtMargin(mine)}
            </dd>
            {mine != null && m.median_margin != null && (
              <>
                <dt className="text-cocoa-400">Difference</dt>
                <dd className="text-right font-medium text-cocoa-700">
                  {describeDelta(mine - m.median_margin)}
                </dd>
              </>
            )}
          </dl>
        ) : (
          <p className="mt-1 text-sm text-cocoa-400">
            This race isn&rsquo;t polled enough for the simulation, so the distribution below
            is the model&rsquo;s fundamentals-only prior.
          </p>
        )}
      </div>

      <div className="sm:col-span-2">
        <StateContext race={race} pickMargin={mine} />
      </div>
    </div>
  );
}

// Three quick facts under the hover card: where the state sits, what it did
// last time, and what the distribution says.
function TooltipFacts({ race }: { race: Effective }) {
  const f = race.features;
  const dist = f?.distribution ?? null;
  const last = f?.senate_history?.[0];
  const mine = toDemMargin(race.pick, race.margin);
  return (
    <div className="mt-1.5 border-t border-cream-100 pt-1.5 text-[11px] text-cocoa-500">
      {dist && (
        <>
          <MarginDistributionChart dist={dist} pickMargin={mine} compact />
          <div className="mt-0.5 flex justify-between">
            <span>
              {dist.source === 'simulation' ? 'Model' : 'Prior'}{' '}
              <strong className="text-cocoa-700">{fmtMargin(dist.median)}</strong>
            </span>
            {dist.dem_win_prob != null && (
              <span>
                P(D) <strong className="text-cocoa-700">{fmtProb(dist.dem_win_prob)}</strong>
              </span>
            )}
          </div>
        </>
      )}
      {f?.pres_2024 != null && (
        <div className="mt-0.5">
          Pres. 2024 <strong className="text-cocoa-700">{fmtMargin(f.pres_2024)}</strong>
          {f.pres_2020 != null && (
            <>
              {' '}· 2020 <strong className="text-cocoa-700">{fmtMargin(f.pres_2020)}</strong>
            </>
          )}
        </div>
      )}
      {last && (
        <div className="mt-0.5 truncate">
          Last Senate: <strong className="text-cocoa-700">{shortName(last.winner)}</strong> (
          {last.winner_party}) +{last.margin.toFixed(1)}, {last.cycle}
        </div>
      )}
      {f?.unemployment && (
        <div className="mt-0.5">
          Unemployment <strong className="text-cocoa-700">{f.unemployment.rate.toFixed(1)}%</strong>{' '}
          <span className="text-cocoa-400">({f.unemployment.period})</span>
        </div>
      )}
      <div className="mt-1 text-cocoa-400">Click for the full picture</div>
    </div>
  );
}

function shortName(name: string): string {
  // "Raphael Warnock" → "Warnock"; strips suffixes like "Jr." and middle initials.
  const parts = name.replace(/,?\s+(Jr\.|Sr\.|II|III|IV)$/i, '').split(/\s+/);
  return parts[parts.length - 1];
}

const PARTY_INK: Record<string, string> = {
  D: 'text-dem',
  R: 'text-rep',
  I: 'text-stamp',
  O: 'text-cocoa-500',
};

// The per-state "vitals": full distribution, structural lean, the model's
// prior, recent Senate contests, and the labour market when the pipeline
// could fetch it.
function StateContext({ race, pickMargin }: { race: Effective; pickMargin: number | null }) {
  const f = race.features;
  if (!f) {
    return (
      <p className="mt-2 text-xs text-cocoa-400">
        State context not exported yet — run scripts/export_state_features.py.
      </p>
    );
  }
  const dist = f.distribution;
  const unemp = f.unemployment;
  const unempDelta =
    unemp && unemp.year_ago != null ? Number((unemp.rate - unemp.year_ago).toFixed(1)) : null;

  return (
    <div className="mt-2 grid gap-5 border-t border-cream-100 pt-4 sm:grid-cols-5">
      <div className="sm:col-span-3">
        <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-cocoa-400">
          Who wins — margin distribution
        </div>
        {dist ? (
          <>
            <div className="mt-2">
              <MarginDistributionChart dist={dist} pickMargin={pickMargin} />
            </div>
            <p className="mt-2 text-xs text-cocoa-400">
              {dist.source === 'simulation' && dist.num_polls === 0 ? (
                <>
                  From {dist.num_simulations?.toLocaleString() ?? 'the'} simulations of this race.
                  No polls yet, so it runs on the fundamentals prior alone (presidential lean plus
                  this year&rsquo;s national swing) with the calibrated error and any market odds.
                  {dist.dem_win_prob != null && (
                    <>
                      {' '}
                      Democrat wins in <strong className="text-cocoa-700">{fmtProb(dist.dem_win_prob)}</strong>.
                    </>
                  )}
                </>
              ) : dist.source === 'simulation' ? (
                <>
                  From {dist.num_simulations?.toLocaleString() ?? 'the'} simulations of this race:
                  polling average, fundamentals and correlated national error.
                  {dist.dem_win_prob != null && (
                    <>
                      {' '}
                      Democrat wins in <strong className="text-cocoa-700">{fmtProb(dist.dem_win_prob)}</strong>.
                    </>
                  )}
                </>
              ) : (
                <>
                  Not polled enough to simulate, so this is the model&rsquo;s fundamentals-only prior:
                  the state&rsquo;s presidential lean shifted by the national environment, with the
                  calibrated error spread.
                  {dist.dem_win_prob != null && (
                    <>
                      {' '}
                      Democrat wins in <strong className="text-cocoa-700">{fmtProb(dist.dem_win_prob)}</strong>.
                    </>
                  )}
                </>
              )}
            </p>
          </>
        ) : (
          <p className="mt-2 text-xs text-cocoa-400">No distribution available.</p>
        )}
      </div>

      <div className="sm:col-span-2">
        <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-cocoa-400">
          State vitals
        </div>
        <dl className="mt-1 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-cocoa-400">Presidential 2024</dt>
          <dd className={`text-right font-medium ${marginInk(f.pres_2024)}`}>{fmtMargin(f.pres_2024)}</dd>
          <dt className="text-cocoa-400">Presidential 2020</dt>
          <dd className={`text-right font-medium ${marginInk(f.pres_2020)}`}>{fmtMargin(f.pres_2020)}</dd>
          <dt className="text-cocoa-400" title="Model's structural lean: 2024 weighted 75%, 2020 25%">
            Blended lean
          </dt>
          <dd className={`text-right font-medium ${marginInk(f.pres_lean)}`}>{fmtMargin(f.pres_lean)}</dd>
          <dt className="text-cocoa-400" title="Lean plus this year's national swing toward the out-party">
            Fundamentals prior
          </dt>
          <dd className={`text-right font-medium ${marginInk(f.fundamentals_prior)}`}>
            {fmtMargin(f.fundamentals_prior)}
          </dd>
          {unemp && (
            <>
              <dt className="text-cocoa-400">Unemployment ({unemp.period})</dt>
              <dd className="text-right font-medium text-cocoa-700">
                {unemp.rate.toFixed(1)}%
                {unempDelta != null && (
                  <span className="ml-1 text-xs text-cocoa-400">
                    {unempDelta > 0 ? '+' : ''}
                    {unempDelta.toFixed(1)} y/y
                  </span>
                )}
              </dd>
            </>
          )}
        </dl>

        {f.senate_history.length > 0 && (
          <>
            <div className="mt-4 text-[11px] font-bold uppercase tracking-[0.1em] text-cocoa-400">
              Recent Senate results here
            </div>
            <ul className="mt-1 space-y-1 text-sm">
              {f.senate_history.map((c) => (
                <HistoryRow key={`${c.cycle}-${c.special}`} c={c} />
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

function HistoryRow({ c }: { c: SenateContest }) {
  return (
    <li className="flex items-baseline justify-between gap-2">
      <span className="truncate text-cocoa-700">
        <span className="text-cocoa-400">{c.cycle}{c.special ? ' sp.' : ''}</span>{' '}
        <strong className={PARTY_INK[c.winner_party] ?? ''}>{shortName(c.winner)}</strong>
        {c.runner_up && (
          <span className="text-cocoa-400">
            {' '}
            over {shortName(c.runner_up)} ({c.runner_up_party})
          </span>
        )}
      </span>
      <span className={`shrink-0 font-medium ${PARTY_INK[c.winner_party] ?? ''}`}>
        {c.winner_party}+{c.margin.toFixed(1)}
      </span>
    </li>
  );
}

function marginInk(m: number | null | undefined): string {
  if (m == null || Math.abs(m) < 0.05) return 'text-cocoa-700';
  return m > 0 ? 'text-dem' : 'text-rep';
}

function describeDelta(delta: number): string {
  const r = Math.abs(delta);
  if (r < 0.05) return 'Same as the model';
  return `${r.toFixed(1)} pts more ${delta > 0 ? 'Democratic' : 'Republican'} than the model`;
}

function Legend() {
  const sw = (fill: string, hatched = false) => (
    <span
      className="inline-block h-3 w-3 rounded-[3px] border border-white shadow-[0_0_0_1px_#e8ddd5]"
      style={
        hatched
          ? {
              backgroundImage: `repeating-linear-gradient(45deg, #b9a99f 0 1px, ${fill} 1px 5px)`,
            }
          : { backgroundColor: fill }
      }
    />
  );
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-cocoa-500">
      <span className="flex items-center gap-1">
        {sw(FILL.D.safe)}
        {sw(FILL.D.likely)}
        {sw(FILL.D.lean)}
        <span className="ml-1 font-semibold text-dem">D</span> safe · likely · lean
      </span>
      <span className="flex items-center gap-1">
        {sw(FILL.R.lean)}
        {sw(FILL.R.likely)}
        {sw(FILL.R.safe)}
        <span className="ml-1 font-semibold text-rep">R</span> lean · likely · safe
      </span>
      <span className="flex items-center gap-1">
        {sw(FILL.I.likely)} <span className="font-semibold text-stamp">I</span>
      </span>
      <span className="flex items-center gap-1">{sw(FILL_NO_PICK, true)} no guess yet</span>
      <span className="flex items-center gap-1">
        {sw(FILL.D.safe)}
        {sw(FILL.R.safe)} safe hold, not on the board
      </span>
      <span className="flex items-center gap-1">{sw(FILL_NOT_RACE)} no 2026 race</span>
    </div>
  );
}
