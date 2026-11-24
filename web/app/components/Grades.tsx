// Letter grades for the post-election pages: the badge, our own report card,
// the forecaster table and the pollster table. All server components, all
// fed from scorecard.json (scripts/score_forecast.py + grade_forecast.py).

import { Panel } from '@/app/components/ui';
import type {
  ForecasterGrade,
  GradeRubricStep,
  PollsterGrades,
  ReportCard,
} from '@/app/lib/data';
import { fmtMargin } from '@/app/lib/format';

const GRADE_TONE: Record<string, string> = {
  A: 'bg-stamp-wash text-stamp border-[#cfe2c6]',
  'A-': 'bg-stamp-wash text-stamp border-[#cfe2c6]',
  'B+': 'bg-dem-wash text-dem border-dem-border',
  B: 'bg-dem-wash text-dem border-dem-border',
  'B-': 'bg-cream-100 text-cocoa-700 border-cream-300',
  'C+': 'bg-peach-wash text-peach border-peach-border',
  C: 'bg-peach-wash text-peach border-peach-border',
  'C-': 'bg-rep-wash text-rep border-rep-border',
  D: 'bg-rep-wash text-rep border-rep-border',
  F: 'bg-rep-wash text-rep border-rep-border',
};

export function GradeBadge({
  grade,
  size = 'sm',
  empty = 'unrated',
}: {
  grade: string | null | undefined;
  size?: 'sm' | 'lg';
  empty?: string;
}) {
  if (!grade) {
    return (
      <span className="inline-flex items-center whitespace-nowrap rounded-full border border-dashed border-cocoa-300 bg-white px-2 py-0.5 text-[11px] font-semibold text-cocoa-400">
        {empty}
      </span>
    );
  }
  const tone = GRADE_TONE[grade] ?? 'bg-cream-100 text-cocoa-700 border-cream-300';
  const sizing =
    size === 'lg'
      ? 'h-12 w-12 justify-center rounded-xl font-display text-2xl'
      : 'rounded-full px-2 py-0.5 text-[11px] font-bold';
  return (
    <span className={`inline-flex shrink-0 items-center border ${sizing} ${tone}`}>{grade}</span>
  );
}

// "≤0.05 A · ≤0.075 A- · …"
function rubricLine(steps: GradeRubricStep[], fmt: (n: number) => string): string {
  return steps.map((s) => `${s.grade} ≤ ${fmt(s.max)}`).join(' · ') + ' · F beyond that';
}

function signedPts(n: number): string {
  const r = Number(n.toFixed(1));
  return `${r > 0 ? '+' : ''}${r.toFixed(1)}`;
}

// Bias as a plain sentence fragment: who the number was too kind to.
function biasText(bias: number): string {
  const r = Number(bias.toFixed(1));
  if (r === 0) return 'no lean';
  return `${Math.abs(r).toFixed(1)} too ${r > 0 ? 'Republican' : 'Democratic'}`;
}

/* ── Our own report card ─────────────────────────────────────────────── */

export function ReportCardPanel({
  card,
  title = 'Report card — our Senate forecast',
  className = '',
}: {
  card: ReportCard;
  title?: string;
  className?: string;
}) {
  return (
    <Panel title={title} className={className}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-stretch">
        <div className="flex items-center gap-3 rounded-xl border border-peach-border bg-peach-wash px-4 py-3 sm:w-44 sm:flex-col sm:justify-center sm:text-center">
          <div className="font-display text-5xl leading-none text-ink">{card.overall ?? '—'}</div>
          <div className="text-[11.5px] leading-snug text-cocoa-500">
            overall, the average of the four subjects
          </div>
        </div>
        <div className="grid flex-1 grid-cols-1 gap-2 sm:grid-cols-2">
          {card.subjects.map((s) => (
            <div
              key={s.key}
              className="flex items-center gap-3 rounded-lg border border-cream-300 bg-cream-50 px-3 py-2.5"
            >
              <GradeBadge grade={s.grade} size="lg" empty="—" />
              <div className="min-w-0">
                <div className="text-[11.5px] text-cocoa-400">{s.label}</div>
                <div className="text-sm font-semibold text-cocoa-700">{s.value ?? 'pending'}</div>
                <div className="text-[11px] leading-snug text-cocoa-400">{s.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

/* ── Forecasters ─────────────────────────────────────────────────────── */

const KIND_LABEL: Record<string, string> = {
  model: 'ours',
  market: 'market',
  forecaster: 'forecaster',
  rater: 'ratings',
  picks: 'hand picks',
};

export function ForecasterGradesPanel({
  forecasters,
  numRaces,
  className = '',
}: {
  forecasters: ForecasterGrade[];
  numRaces: number;
  className?: string;
}) {
  if (forecasters.length === 0) return null;
  return (
    <Panel title="Forecaster grades — everyone who called these races" className={className}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
              <th className="py-2 pr-3">Grade</th>
              <th className="py-2 pr-3">Forecaster</th>
              <th className="py-2 pr-3 text-right">Races</th>
              <th className="py-2 pr-3 text-right">Calls right</th>
              <th className="py-2 pr-3 text-right">Brier</th>
              <th className="py-2 pr-3 text-right">Ours, same races</th>
              <th className="py-2 text-right">Margin miss</th>
            </tr>
          </thead>
          <tbody>
            {forecasters.map((f) => {
              const ours = f.kind === 'model' && f.key === 'model';
              const beatUs =
                f.brier != null && f.model_brier_same_races != null && f.brier < f.model_brier_same_races;
              return (
                <tr
                  key={f.key}
                  className={`border-b border-cream-100 align-top last:border-0 ${ours ? 'bg-peach-wash' : ''}`}
                >
                  <td className="py-2.5 pr-3">
                    <GradeBadge grade={f.grade} empty="—" />
                  </td>
                  <td className="py-2.5 pr-3">
                    <div className="font-medium text-cocoa-700">
                      {f.label}
                      <span className="ml-2 text-[10px] font-normal uppercase tracking-wide text-cocoa-400">
                        {KIND_LABEL[f.kind] ?? f.kind}
                      </span>
                    </div>
                    {f.misses.length > 0 && (
                      <div className="mt-0.5 text-[11px] text-cocoa-400">
                        missed {f.misses.join(', ')}
                      </div>
                    )}
                  </td>
                  <td className="py-2.5 pr-3 text-right text-cocoa-500">
                    {f.n}
                    {f.n < numRaces && <span className="text-cocoa-300"> of {numRaces}</span>}
                  </td>
                  <td className="py-2.5 pr-3 text-right text-cocoa-700">
                    {f.calls_made ? `${f.calls_right}/${f.calls_made}` : '—'}
                  </td>
                  <td className="py-2.5 pr-3 text-right font-semibold text-cocoa-700">
                    {f.brier != null ? f.brier.toFixed(3) : '—'}
                  </td>
                  <td className="py-2.5 pr-3 text-right text-cocoa-500">
                    {ours || f.model_brier_same_races == null ? (
                      '—'
                    ) : (
                      <>
                        {f.model_brier_same_races.toFixed(3)}
                        <span className={`ml-1 text-[11px] ${beatUs ? 'text-rep' : 'text-stamp'}`}>
                          {beatUs ? 'beat us' : 'we won'}
                        </span>
                      </>
                    )}
                  </td>
                  <td className="py-2.5 text-right text-cocoa-700">
                    {f.margin_mae != null ? `${f.margin_mae.toFixed(1)} pts` : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-cocoa-400">
        Graded on the Brier score of each forecaster&rsquo;s win probabilities, on the races it
        covered. The slates differ: raters and Kalshi were recorded for the 22 researched races
        (mostly safe seats), the picks cover the 17 closest. &ldquo;Ours, same races&rdquo; is our
        simulation&rsquo;s Brier on that same slate, which is the fair comparison. Cook, Sabato and
        Inside Elections publish ratings, not probabilities, so a rating is read as Solid 98%,
        Likely 90%, Lean 75%, Tilt 60%, Toss-up 50%; a toss-up counts toward Brier but is not a
        call.
      </p>
    </Panel>
  );
}

/* ── Pollsters ───────────────────────────────────────────────────────── */

function fmtDay(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function PollsterGradesPanel({
  grades,
  limit,
  className = '',
  moreHref,
}: {
  grades: PollsterGrades;
  // Show only the graded pollsters (enough polls for a letter), capped here.
  limit?: number;
  className?: string;
  moreHref?: React.ReactNode;
}) {
  const graded = grades.pollsters.filter((p) => p.grade);
  const thin = grades.pollsters.filter((p) => !p.grade);
  const shown = limit ? graded.slice(0, limit) : graded;
  const f = grades.field;
  return (
    <Panel title="Pollster grades — final polls against the results" className={className}>
      <p className="mb-3 text-sm leading-relaxed text-cocoa-700">
        {f.n_polls} polls from {f.n_pollsters} pollsters finished in the last three weeks (
        {fmtDay(grades.window.start)} to {fmtDay(grades.window.end)}) across {f.n_races} Senate
        races.{' '}
        {f.mae != null && f.bias != null && (
          <>
            The average poll missed the margin by <strong>{f.mae.toFixed(1)} points</strong> and
            the field as a whole ran <strong>{biasText(f.bias)}</strong>.
          </>
        )}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
              <th className="py-2 pr-3">2026</th>
              <th className="py-2 pr-3">Pollster</th>
              <th className="py-2 pr-3 text-right">Polls</th>
              <th className="py-2 pr-3 text-right">Avg miss</th>
              <th className="py-2 pr-3 text-right">Lean</th>
              <th className="py-2 pr-3 text-right">vs field</th>
              <th className="py-2 pr-3 text-right">Leader right</th>
              <th className="py-2 text-right">Going in</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((p) => (
              <tr key={p.pollster} className="border-b border-cream-100 last:border-0">
                <td className="py-2 pr-3">
                  <GradeBadge grade={p.grade} />
                </td>
                <td className="py-2 pr-3 font-medium text-cocoa-700">
                  {p.pollster}
                  {p.partisan_tag && (
                    <span className="ml-1 text-[10px] text-peach">({p.partisan_tag})</span>
                  )}
                </td>
                <td
                  className="py-2 pr-3 text-right text-cocoa-500"
                  title={p.states.join(', ')}
                >
                  {p.n_polls}
                  <span className="text-cocoa-300"> · {p.n_races} st.</span>
                </td>
                <td className="py-2 pr-3 text-right font-semibold text-cocoa-700">
                  {p.mae.toFixed(1)}
                </td>
                <td
                  className={`py-2 pr-3 text-right ${p.bias > 0 ? 'text-rep' : p.bias < 0 ? 'text-dem' : 'text-cocoa-500'}`}
                  title={`Worst: ${p.worst.state}, poll ${fmtMargin(p.worst.poll_margin)} vs result ${fmtMargin(p.worst.actual_margin)}`}
                >
                  {p.bias === 0 ? '—' : `${p.bias > 0 ? 'R' : 'D'} ${signedPts(Math.abs(p.bias))}`}
                </td>
                <td
                  className={`py-2 pr-3 text-right ${p.vs_field < 0 ? 'text-stamp' : 'text-cocoa-500'}`}
                >
                  {signedPts(p.vs_field)}
                </td>
                <td className="py-2 pr-3 text-right text-cocoa-700">
                  {p.leaders_called ? `${p.leaders_right}/${p.leaders_called}` : '—'}
                </td>
                <td className="py-2 text-right">
                  <GradeBadge grade={p.prior_grade} empty="—" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {limit && graded.length > shown.length && moreHref && (
        <p className="mt-2 text-xs text-cocoa-500">
          Showing the top {shown.length} of {graded.length} graded pollsters. {moreHref}
        </p>
      )}
      {!limit && thin.length > 0 && (
        <details className="mt-3 rounded-lg border border-cream-300 bg-cream-50 px-3 py-2 text-sm">
          <summary className="cursor-pointer text-xs font-semibold text-cocoa-500">
            {thin.length} more pollsters with fewer than {grades.min_polls_for_grade} final polls
            (no letter)
          </summary>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {thin.map((p) => (
              <span
                key={p.pollster}
                className="rounded-lg border border-cream-300 bg-white px-2 py-1 text-xs text-cocoa-600"
                title={`${p.states.join(', ')} · ${biasText(p.bias)}`}
              >
                {p.pollster}
                {p.partisan_tag && <span className="text-peach"> ({p.partisan_tag})</span>}:{' '}
                <strong>{p.mae.toFixed(1)}</strong>
                <span className="text-cocoa-400"> (n={p.n_polls})</span>
              </span>
            ))}
          </div>
        </details>
      )}
      <p className="mt-2 text-xs leading-relaxed text-cocoa-400">
        Avg miss is the mean absolute error on the Dem−Rep margin, and it sets the letter. Lean is
        the direction of the average miss: R means the pollster&rsquo;s numbers were too
        Republican. &ldquo;vs field&rdquo; is the pollster&rsquo;s miss minus the average miss of
        every final poll in the same races, so negative is better than the pack. &ldquo;Going
        in&rdquo; is the grade the model weighted the pollster by before the election. A letter
        needs at least {grades.min_polls_for_grade} final polls; the four races with an
        independent challenger are left out.
      </p>
    </Panel>
  );
}

/* ── Rubric footnote ─────────────────────────────────────────────────── */

export function GradingRubric({ card }: { card: ReportCard }) {
  const r = card.rubrics;
  return (
    <div className="mt-8 rounded-xl border border-cream-300 bg-cream-100 p-5 text-sm text-cocoa-700">
      <h3 className="font-display text-lg text-ink">How the letters are set</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        <li>
          <strong>Probabilities (Brier score).</strong> {rubricLine(r.brier, (n) => n.toFixed(3))}.
          A coin flip on every race scores 0.250.
        </li>
        <li>
          <strong>Margins and polls (average miss, points).</strong>{' '}
          {rubricLine(r.margin_points, (n) => n.toFixed(1))}.
        </li>
        <li>
          <strong>Winner calls (share missed).</strong>{' '}
          {rubricLine(r.calls_missed_share, (n) => `${Math.round(n * 100)}%`)}.
        </li>
        <li>
          <strong>Chamber call.</strong> An A needs the right party and a seat count inside the
          middle half of the simulated range; the grade drops as the real count lands further out
          in the tail, and a wrong party is a D or an F.
        </li>
      </ul>
      <p className="mt-2 text-xs text-cocoa-500">
        The thresholds are fixed, and the same ones apply to us, the markets, the raters and the
        pollsters. Every grade can be recomputed from the figure printed next to it.
      </p>
    </div>
  );
}
