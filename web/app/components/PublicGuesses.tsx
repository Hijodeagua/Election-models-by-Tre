'use client';

// Phase 5 — public guesses vs the model. One form (display name + a winner and
// optional margin per board race), stored on the server; an edit token kept
// in this browser lets the same person change their entry until the lock.

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Party } from '@/app/lib/predictions-shared';
import {
  GUESSES_API,
  LOCK_AT_ISO,
  MAX_MARGIN,
  MAX_NAME_LEN,
  guessesDisagree,
  isLocked,
  type GuessEntry,
  type GuessMap,
  type GuessesPayload,
  type MarketCall,
  type RaceGuess,
} from '@/app/lib/guesses-shared';
import { Panel } from '@/app/components/ui';

export interface GuessRace {
  abbr: string;
  state: string;
  dem_candidate: string | null;
  rep_candidate: string | null;
  ind_candidate: string | null;
  allowed: Party[];
  // Hijodeagua's published guess and the model's call, in the same shape.
  hijodeagua: RaceGuess | null;
  model: RaceGuess | null;
  // Prediction markets' favourite and its win probability.
  market: MarketCall | null;
}

const TOKEN_KEY = 'election-oracle:guess-token:v1';
const PARTY_TEXT: Record<Party, string> = { D: 'text-dem', R: 'text-rep', I: 'text-stamp' };
const PARTY_BTN: Record<Party, string> = {
  D: 'border-dem bg-dem text-white',
  R: 'border-rep bg-rep text-white',
  I: 'border-stamp bg-stamp text-white',
};

interface Draft {
  pick: Party | null;
  margin: string; // raw input text; validated server-side too
}

interface Credentials {
  id: string;
  token: string;
}

function fmtGuess(g: RaceGuess | null): string {
  if (!g) return '—';
  return g.margin == null ? g.pick : `${g.pick}+${g.margin.toFixed(1)}`;
}

function lockLabel(): string {
  // Fixed wall-clock time the server enforces; shown as written, not converted.
  return 'Nov 3, 2026, 6:00 PM ET';
}

export default function PublicGuesses({ races }: { races: GuessRace[] }) {
  const [payload, setPayload] = useState<GuessesPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creds, setCreds] = useState<Credentials | null>(null);
  const [name, setName] = useState('');
  const [draft, setDraft] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const locked = payload ? payload.locked : isLocked();

  const load = useCallback(async () => {
    try {
      const res = await fetch(GUESSES_API, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPayload((await res.json()) as GuessesPayload);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'failed to load');
    }
  }, []);

  useEffect(() => {
    void load();
    try {
      const raw = window.localStorage.getItem(TOKEN_KEY);
      if (raw) setCreds(JSON.parse(raw) as Credentials);
    } catch {
      /* storage unavailable: submitting still works, editing later will not */
    }
  }, [load]);

  // When this browser owns an entry, seed the form from the server copy.
  const mine = useMemo(
    () => (creds && payload ? payload.entries.find((e) => e.id === creds.id) ?? null : null),
    [creds, payload],
  );
  useEffect(() => {
    if (!mine) return;
    setName(mine.name);
    const d: Record<string, Draft> = {};
    for (const [abbr, g] of Object.entries(mine.guesses)) {
      d[abbr] = { pick: g.pick, margin: g.margin == null ? '' : String(g.margin) };
    }
    setDraft(d);
  }, [mine]);

  function setPick(abbr: string, pick: Party | null) {
    setDraft((prev) => {
      const cur = prev[abbr] ?? { pick: null, margin: '' };
      const same = cur.pick === pick;
      return { ...prev, [abbr]: { pick: same ? null : pick, margin: same ? '' : cur.margin } };
    });
  }

  function setMargin(abbr: string, margin: string) {
    setDraft((prev) => ({ ...prev, [abbr]: { ...(prev[abbr] ?? { pick: null }), margin } }));
  }

  const guessCount = Object.values(draft).filter((d) => d.pick != null).length;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setNotice(null);
    const guesses: Record<string, { pick: Party; margin: number | null } | null> = {};
    for (const r of races) {
      const d = draft[r.abbr];
      if (!d || d.pick == null) continue;
      const m = d.margin.trim() === '' ? null : Number(d.margin);
      guesses[r.abbr] = { pick: d.pick, margin: m };
    }
    setBusy(true);
    try {
      const editing = creds != null && mine != null;
      const res = await fetch(editing ? `${GUESSES_API}/${creds.id}` : GUESSES_API, {
        method: editing ? 'PUT' : 'POST',
        headers: {
          'content-type': 'application/json',
          ...(editing ? { authorization: `Bearer ${creds.token}` } : {}),
        },
        body: JSON.stringify({ name, guesses }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        error?: string;
        id?: string;
        token?: string;
        entry?: GuessEntry;
      };
      if (!res.ok) {
        setNotice({ tone: 'err', text: data.error ?? `Could not save (HTTP ${res.status})` });
        if (res.status === 403 || res.status === 404) {
          // Token no longer matches: forget it so the next save starts fresh.
          setCreds(null);
          try {
            window.localStorage.removeItem(TOKEN_KEY);
          } catch {
            /* ignore */
          }
        }
        return;
      }
      if (!editing && data.id && data.token) {
        const c = { id: data.id, token: data.token };
        setCreds(c);
        try {
          window.localStorage.setItem(TOKEN_KEY, JSON.stringify(c));
        } catch {
          /* ignore */
        }
      }
      setNotice({
        tone: 'ok',
        text: editing ? 'Your guesses were updated.' : 'Saved. You can come back in this browser to edit.',
      });
      await load();
    } catch (err) {
      setNotice({ tone: 'err', text: err instanceof Error ? err.message : 'Could not save' });
    } finally {
      setBusy(false);
    }
  }

  const entries = payload?.entries ?? [];
  const configured = payload?.configured ?? true;
  const showForm = formOpen || mine != null;

  return (
    <section className="mt-8" id="public-guesses">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-peach">
            Everyone&rsquo;s guesses
          </div>
          <h3 className="font-display text-2xl leading-tight text-ink">
            Your call vs. the model
          </h3>
          <p className="mt-1 max-w-2xl text-sm text-cocoa-500">
            Add a display name and a winner for each race (margin optional). No login — an edit
            token stays in this browser so you can change your mind until{' '}
            <strong className="text-cocoa-700">{lockLabel()}</strong>, when every entry locks.
          </p>
        </div>
        {!locked && !showForm && configured && (
          <button
            type="button"
            onClick={() => setFormOpen(true)}
            className="rounded-lg bg-peach px-3.5 py-2 text-xs font-semibold text-white hover:bg-peach-hover"
          >
            Add my guesses
          </button>
        )}
      </div>

      {locked && (
        <div className="mb-3 rounded-xl border border-cream-300 bg-cream-100 px-4 py-3 text-sm text-cocoa-700">
          <strong>Guesses are locked.</strong> Entries closed at {lockLabel()} and are read-only.
        </div>
      )}
      {!configured && (
        <div className="mb-3 rounded-xl border border-cream-300 bg-cream-100 px-4 py-3 text-sm text-cocoa-700">
          Guess storage is not configured on this deployment, so the form is unavailable.
        </div>
      )}
      {loadError && (
        <div className="mb-3 rounded-xl border border-rep-border bg-rep-wash px-4 py-3 text-sm text-rep">
          Could not load guesses ({loadError}).
        </div>
      )}

      {showForm && configured && (
        <Panel className="mb-4" title={mine ? 'Edit my guesses' : 'Add my guesses'}>
          <form onSubmit={submit}>
            <label className="block text-xs font-semibold text-cocoa-700">
              Display name
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value.slice(0, MAX_NAME_LEN))}
                maxLength={MAX_NAME_LEN}
                required
                disabled={locked || busy}
                placeholder="Shown on the board"
                className="mt-1 block w-full max-w-xs rounded-lg border border-cream-300 bg-cream-50 px-3 py-2 text-sm font-normal text-ink focus:border-peach focus:outline-none disabled:opacity-60"
              />
              <span className="mt-1 block text-[11px] font-normal text-cocoa-400">
                {name.length}/{MAX_NAME_LEN}
              </span>
            </label>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
                    <th className="py-2 pr-3">Race</th>
                    <th className="py-2 pr-3">Winner</th>
                    <th className="py-2 pr-3">Margin (pts, optional)</th>
                  </tr>
                </thead>
                <tbody>
                  {races.map((r) => {
                    const d = draft[r.abbr] ?? { pick: null, margin: '' };
                    return (
                      <tr key={r.abbr} className="border-b border-cream-100 last:border-0">
                        <td className="py-2 pr-3 align-top">
                          <div className="font-medium text-cocoa-700">{r.state}</div>
                          <div className="text-[11px] text-cocoa-400">
                            {[
                              r.dem_candidate && `${r.dem_candidate} (D)`,
                              r.rep_candidate && `${r.rep_candidate} (R)`,
                              r.ind_candidate && `${r.ind_candidate} (I)`,
                            ]
                              .filter(Boolean)
                              .join(' v. ')}
                          </div>
                        </td>
                        <td className="py-2 pr-3 align-top">
                          <div className="flex flex-wrap gap-1.5" role="group" aria-label={`${r.state} winner`}>
                            {r.allowed.map((p) => (
                              <button
                                key={p}
                                type="button"
                                disabled={locked || busy}
                                aria-pressed={d.pick === p}
                                onClick={() => setPick(r.abbr, p)}
                                className={`rounded-lg border px-2.5 py-1 text-xs font-semibold transition-colors disabled:opacity-60 ${
                                  d.pick === p
                                    ? PARTY_BTN[p]
                                    : 'border-cream-300 bg-cream-50 text-cocoa-700 hover:border-peach'
                                }`}
                              >
                                {p}
                              </button>
                            ))}
                          </div>
                        </td>
                        <td className="py-2 pr-3 align-top">
                          <input
                            type="number"
                            inputMode="decimal"
                            min={0}
                            max={MAX_MARGIN}
                            step={0.5}
                            value={d.margin}
                            disabled={locked || busy || d.pick == null}
                            onChange={(e) => setMargin(r.abbr, e.target.value)}
                            placeholder={d.pick ? `${d.pick}+?` : '—'}
                            aria-label={`${r.state} margin`}
                            className="w-24 rounded-lg border border-cream-300 bg-cream-50 px-2 py-1 text-sm text-ink focus:border-peach focus:outline-none disabled:opacity-50"
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={locked || busy || guessCount === 0 || name.trim().length === 0}
                className="rounded-lg bg-peach px-4 py-2 text-sm font-semibold text-white hover:bg-peach-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? 'Saving…' : mine ? 'Update my guesses' : 'Save my guesses'}
              </button>
              <span className="text-xs text-cocoa-400">
                {guessCount} of {races.length} races called
              </span>
              {notice && (
                <span
                  role="status"
                  className={`text-xs font-semibold ${notice.tone === 'ok' ? 'text-stamp' : 'text-rep'}`}
                >
                  {notice.text}
                </span>
              )}
            </div>
          </form>
        </Panel>
      )}

      <ComparisonTable races={races} entries={entries} mineId={mine?.id ?? null} loading={!payload && !loadError} />
    </section>
  );
}

function GuessCell({
  guess,
  model,
  muted = false,
}: {
  guess: RaceGuess | null;
  model: RaceGuess | null;
  muted?: boolean;
}) {
  const differs = guessesDisagree(guess, model);
  return (
    <td
      className={`whitespace-nowrap px-3 py-2 text-right ${
        differs ? 'bg-peach-wash ring-1 ring-inset ring-peach-border' : ''
      }`}
      title={differs ? 'Differs from the model' : undefined}
    >
      {guess ? (
        <span className={`font-semibold ${muted ? 'text-cocoa-500' : PARTY_TEXT[guess.pick]}`}>
          {fmtGuess(guess)}
          {differs && <span className="ml-1 text-[10px] font-bold text-peach">≠</span>}
        </span>
      ) : (
        <span className="text-cocoa-300">—</span>
      )}
    </td>
  );
}

function ComparisonTable({
  races,
  entries,
  mineId,
  loading,
}: {
  races: GuessRace[];
  entries: GuessEntry[];
  mineId: string | null;
  loading: boolean;
}) {
  const differCount = (guesses: GuessMap) =>
    races.filter((r) => guessesDisagree(guesses[r.abbr] ?? null, r.model)).length;
  const hijoCount = races.filter((r) => guessesDisagree(r.hijodeagua, r.model)).length;

  return (
    <div className="overflow-x-auto rounded-xl border border-cream-300 bg-white">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
            <th className="sticky left-0 z-10 bg-white px-3 py-3">Race</th>
            <th className="px-3 py-3 text-right">Model</th>
            <th className="px-3 py-3 text-right" title="Polymarket / Kalshi favourite and win chance">
              Markets
            </th>
            <th className="px-3 py-3 text-right">Hijodeagua</th>
            {entries.map((e) => (
              <th key={e.id} className="max-w-[9rem] truncate px-3 py-3 text-right normal-case" title={e.name}>
                {e.name}
                {e.id === mineId && <span className="ml-1 text-[10px] text-peach">(you)</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {races.map((r) => (
            <tr key={r.abbr} className="border-b border-cream-100 last:border-0">
              <td className="sticky left-0 z-10 bg-white px-3 py-2 font-medium text-cocoa-700">
                {r.state}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-right">
                {r.model ? (
                  <span className={`font-semibold ${PARTY_TEXT[r.model.pick]}`}>{fmtGuess(r.model)}</span>
                ) : (
                  <span className="text-cocoa-300">—</span>
                )}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-right">
                {r.market ? (
                  <span className={`font-semibold ${PARTY_TEXT[r.market.pick]}`}>
                    {r.market.pick} {Math.round(r.market.prob * 100)}%
                  </span>
                ) : (
                  <span className="text-cocoa-300">—</span>
                )}
              </td>
              <GuessCell guess={r.hijodeagua} model={r.model} />
              {entries.map((e) => (
                <GuessCell key={e.id} guess={e.guesses[r.abbr] ?? null} model={r.model} />
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-cream-300 text-xs text-cocoa-500">
            <td className="sticky left-0 z-10 bg-white px-3 py-2">Differs from model</td>
            <td className="px-3 py-2 text-right text-cocoa-300">—</td>
            <td className="px-3 py-2 text-right font-semibold">
              {races.filter((r) => r.market && r.model && r.market.pick !== r.model.pick).length}
            </td>
            <td className="px-3 py-2 text-right font-semibold">{hijoCount}</td>
            {entries.map((e) => (
              <td key={e.id} className="px-3 py-2 text-right font-semibold">
                {differCount(e.guesses)}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
      {loading && <p className="px-3 py-2 text-xs text-cocoa-400">Loading guesses…</p>}
      {!loading && entries.length === 0 && (
        <p className="px-3 py-2 text-xs text-cocoa-400">No public guesses yet — be the first.</p>
      )}
      <p className="border-t border-cream-100 px-3 py-2 text-[11px] text-cocoa-400">
        Model = the simulation&rsquo;s median winner and margin. Markets = the Polymarket /
        Kalshi favourite and its win chance, refreshed with the site data. Shaded cells with ≠
        call a different winner than the model. Scoring against results comes after election day.
      </p>
    </div>
  );
}
