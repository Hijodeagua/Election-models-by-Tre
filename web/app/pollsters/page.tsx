import LastUpdated from '@/app/components/LastUpdated';
import { EmptyState, PageHead, Panel } from '@/app/components/ui';
import {
  getPollsters,
  type NationalPollsterGrade,
  type StatePoll,
  type StatePolls,
} from '@/app/lib/data';
import { fmtMargin } from '@/app/lib/format';

const GRADE_TONE: Record<string, string> = {
  A: 'bg-stamp-wash text-stamp border-[#cfe2c6]',
  'A-': 'bg-stamp-wash text-stamp border-[#cfe2c6]',
  'B+': 'bg-dem-wash text-dem border-dem-border',
  B: 'bg-dem-wash text-dem border-dem-border',
  'B-': 'bg-cream-100 text-cocoa-700 border-cream-300',
  'C+': 'bg-peach-wash text-peach border-peach-border',
  C: 'bg-rep-wash text-rep border-rep-border',
  'C-': 'bg-rep-wash text-rep border-rep-border',
};

function GradeBadge({ grade }: { grade: string | null }) {
  if (!grade) {
    return (
      <span className="inline-flex items-center rounded-full border border-dashed border-cocoa-300 bg-white px-2 py-0.5 text-[11px] font-semibold text-cocoa-400">
        unrated
      </span>
    );
  }
  const tone = GRADE_TONE[grade] ?? 'bg-cream-100 text-cocoa-700 border-cream-300';
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-bold ${tone}`}>
      {grade}
    </span>
  );
}

// Mean error is actual − poll: negative = the pollster overstated Democrats.
function leanText(meanError: number): string {
  if (meanError === 0) return 'no lean';
  const side = meanError < 0 ? 'D' : 'R';
  return `leans ${side} ${Math.abs(meanError).toFixed(1)}`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
}

export default function PollstersPage() {
  const data = getPollsters();
  const statesWithPolls = data.states.filter((s) => s.num_polls > 0);

  return (
    <div>
      <PageHead
        kicker="Pollster Grades"
        title="Who's polling these races — and how good are they?"
        sub={
          <>
            Every poll behind the 2026 Senate battlegrounds, with each
            pollster&rsquo;s grade. Grades blend Silver Bulletin&rsquo;s
            pollster-error ratings (the national grade) with our own
            historical actual-minus-poll track record. Lower error and smaller
            house effects earn higher grades.
          </>
        }
      />

      {/* ── Polls by state ─────────────────────────────────────────────── */}
      <h2 className="mt-6 font-display text-xl text-ink">Polls by state</h2>
      {statesWithPolls.length === 0 ? (
        <EmptyState>No state-level polls in the current feed yet.</EmptyState>
      ) : (
        <div className="mt-3 space-y-4">
          {statesWithPolls.map((state) => (
            <StatePollPanel key={state.state} state={state} />
          ))}
        </div>
      )}

      {/* ── National grades ────────────────────────────────────────────── */}
      <h2 className="mt-8 font-display text-xl text-ink">National pollster grades</h2>
      <p className="mt-1 text-sm text-cocoa-500">
        The rated pollster pool, best to worst. &ldquo;SB error&rdquo; is the
        Silver Bulletin absolute-error estimate (points; lower is better).
        &ldquo;Our track record&rdquo; is the mean actual-minus-poll error
        across the Senate races in our 2018–2024 backtest, where we have at
        least five of a pollster&rsquo;s polls.
      </p>
      <NationalGradeTable national={data.national} />

      <div className="mt-8 rounded-xl border border-cream-300 bg-cream-100 p-5 text-sm text-cocoa-700">
        <h3 className="font-display text-lg text-ink">How to read the grades</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            <strong>National grade</strong> comes from Silver Bulletin&rsquo;s
            pollster-error ratings, mapped to an A–C scale. Unrated feeds
            (aggregators, one-off shops) show as <em>unrated</em> and fall back
            to a {data.unknown_default_grade ?? 'B'} prior in the model.
          </li>
          <li>
            <strong>In-state track record</strong> is each pollster&rsquo;s mean
            error in that specific state from our backtest. State samples are
            thin, so treat it as a directional signal, not a precise grade — it
            appears under a state once a pollster has a multi-cycle history
            there.
          </li>
          <li>
            A negative error means the pollster <em>overstated Democrats</em>
            (Republicans beat the poll); positive means it overstated
            Republicans. This is the same actual-minus-poll convention used in
            the forecast calibration.
          </li>
        </ul>
      </div>

      <LastUpdated />
    </div>
  );
}

function StatePollPanel({ state }: { state: StatePolls }) {
  return (
    <Panel title={`${state.state} · ${state.num_polls} poll${state.num_polls === 1 ? '' : 's'}`}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
              <th className="px-2 py-2">Pollster</th>
              <th className="px-2 py-2">Grade</th>
              <th className="px-2 py-2">Dates</th>
              <th className="px-2 py-2 text-right">Sample</th>
              <th className="px-2 py-2 text-right">D</th>
              <th className="px-2 py-2 text-right">R</th>
              <th className="px-2 py-2 text-right">Margin</th>
            </tr>
          </thead>
          <tbody>
            {state.polls.map((poll, i) => (
              <PollRow key={`${poll.pollster}-${poll.end_date}-${i}`} poll={poll} />
            ))}
          </tbody>
        </table>
      </div>

      {state.pollster_history.length > 0 && (
        <div className="mt-3 border-t border-cream-100 pt-3">
          <div className="text-[11px] font-bold uppercase tracking-wide text-cocoa-400">
            In-state track record (actual − poll, our backtest)
          </div>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {state.pollster_history.map((h) => (
              <span
                key={h.pollster}
                className="rounded-lg border border-cream-300 bg-cream-50 px-2.5 py-1 text-xs text-cocoa-600"
                title={`${h.n_polls} polls · σ ${h.std_error}`}
              >
                {h.pollster}: <strong>{leanText(h.mean_error)}</strong>{' '}
                <span className="text-cocoa-400">(n={h.n_polls})</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

function PollRow({ poll }: { poll: StatePoll }) {
  return (
    <tr className="border-b border-cream-100 last:border-0">
      <td className="px-2 py-2 font-medium text-cocoa-700">
        {poll.pollster}
        {poll.partisan && <span className="ml-1 text-[10px] text-peach">partisan</span>}
      </td>
      <td className="px-2 py-2">
        <GradeBadge grade={poll.grade} />
      </td>
      <td className="px-2 py-2 whitespace-nowrap text-cocoa-500">
        {fmtDate(poll.start_date)} – {fmtDate(poll.end_date)}
      </td>
      <td className="px-2 py-2 text-right text-cocoa-500">
        {poll.sample_size != null ? poll.sample_size.toLocaleString() : '—'}
        {poll.population ? (
          <span className="ml-1 text-[10px] uppercase text-cocoa-400">{poll.population}</span>
        ) : null}
      </td>
      <td className="px-2 py-2 text-right text-dem">
        {poll.dem_pct != null ? poll.dem_pct.toFixed(0) : '—'}
      </td>
      <td className="px-2 py-2 text-right text-rep">
        {poll.rep_pct != null ? poll.rep_pct.toFixed(0) : '—'}
      </td>
      <td
        className={`px-2 py-2 text-right font-semibold ${
          poll.margin == null ? 'text-cocoa-300' : poll.margin > 0 ? 'text-dem' : 'text-rep'
        }`}
      >
        {fmtMargin(poll.margin)}
      </td>
    </tr>
  );
}

function NationalGradeTable({ national }: { national: NationalPollsterGrade[] }) {
  if (national.length === 0) {
    return <EmptyState>No pollster ratings available.</EmptyState>;
  }
  return (
    <div className="mt-3 overflow-x-auto rounded-xl border border-cream-300 bg-white">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
            <th className="px-4 py-3">Pollster</th>
            <th className="px-4 py-3">Grade</th>
            <th className="px-4 py-3 text-right">SB error</th>
            <th className="px-4 py-3 text-right">Our track record</th>
          </tr>
        </thead>
        <tbody>
          {national.map((p) => (
            <tr key={p.pollster} className="border-b border-cream-100 last:border-0">
              <td className="px-4 py-3 font-medium text-cocoa-700">{p.pollster}</td>
              <td className="px-4 py-3">
                <GradeBadge grade={p.grade} />
              </td>
              <td className="px-4 py-3 text-right text-cocoa-500">{p.sb_error.toFixed(1)}</td>
              <td className="px-4 py-3 text-right text-cocoa-500">
                {p.empirical ? (
                  <span title={`σ ${p.empirical.std_error}`}>
                    {leanText(p.empirical.mean_error)}{' '}
                    <span className="text-cocoa-400">(n={p.empirical.n_polls})</span>
                  </span>
                ) : (
                  '—'
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
