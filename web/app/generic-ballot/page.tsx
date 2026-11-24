import LastUpdated from '@/app/components/LastUpdated';
import DataFreshnessBanner from '@/app/components/DataFreshnessBanner';
import MarginChart from '@/app/components/MarginChart';
import { EmptyState, MetaStrip, PageHead, Panel, StatCard } from '@/app/components/ui';
import { GradeBadge } from '@/app/components/Grades';
import { getGenericBallot, getGradedScorecard, type GenericBallotGrade } from '@/app/lib/data';

export default function GenericBallotPage() {
  const live = getGenericBallot();
  const { num_polls } = live;
  // After the election: the last pre-election average against the House vote,
  // and the trend stops on election day.
  const grade = getGradedScorecard()?.generic_ballot;
  const graded = grade?.available && grade.forecast ? grade : null;
  const cutoff = graded?.forecast?.as_of ?? null;
  const trend = cutoff ? live.trend.filter((t) => t.as_of <= cutoff) : live.trend;
  const current = cutoff ? (trend[trend.length - 1] ?? live.current) : live.current;

  const lead = current ? (current.margin >= 0 ? 'D' : 'R') : '';

  return (
    <div>
      <PageHead
        kicker={graded ? 'Generic Congressional Ballot · Graded' : 'Generic Congressional Ballot'}
        title={
          graded
            ? 'Did the generic ballot see the House coming?'
            : 'Which party do voters want running Congress?'
        }
        sub={
          <>
            &ldquo;If the election were held today, would you vote for the
            Democrat or the Republican in your district?&rdquo; — averaged
            across public polls. Margin is the Democratic minus Republican
            share.
          </>
        }
      />
      {graded ? <GenericBallotGradePanel grade={graded} /> : <DataFreshnessBanner feed="generic_ballot" />}

      {current ? (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {graded && (
              <h3 className="col-span-full -mb-1 mt-2 text-[11px] font-bold uppercase tracking-[0.1em] text-cocoa-400">
                The final average
              </h3>
            )}
            <StatCard label="Democrats" value={`${current.dem_pct.toFixed(1)}%`} tone="dem" />
            <StatCard label="Republicans" value={`${current.rep_pct.toFixed(1)}%`} tone="rep" />
            <StatCard
              label={`${lead === 'D' ? 'Democratic' : 'Republican'} edge`}
              value={`${lead}+${Math.abs(current.margin).toFixed(1)}`}
              tone="peach"
            />
          </div>

          <div className="mt-4">
            <MetaStrip
              items={[
                { k: graded ? 'Final average' : 'Updated', v: current.as_of },
                { k: 'Polls in window', v: String(num_polls) },
              ]}
            />
          </div>

          {!graded && current.estimated_dem_seats != null && (
            <p className="mb-4 rounded-lg border border-peach-border bg-peach-wash px-3.5 py-2.5 text-xs leading-relaxed text-cocoa-700">
              Rough seat translation from the national margin: D{' '}
              {current.estimated_dem_seats} / R {current.estimated_rep_seats}
              {current.estimated_dem_seats_lo != null &&
                current.estimated_dem_seats_hi != null && (
                  <> (80% range: D {current.estimated_dem_seats_lo}–{current.estimated_dem_seats_hi})</>
                )}
              .
            </p>
          )}

          <Panel title="D−R margin over time">
            <MarginChart trend={trend} />
          </Panel>
        </>
      ) : (
        <EmptyState>
          No generic-ballot estimate yet — need at least 3 polls in the window.
        </EmptyState>
      )}

      <LastUpdated />
    </div>
  );
}

function GenericBallotGradePanel({ grade }: { grade: GenericBallotGrade }) {
  const fc = grade.forecast!;
  const res = grade.result;
  const m = (v: number | null | undefined) =>
    v == null ? '—' : `${v >= 0 ? 'D' : 'R'}+${Math.abs(v).toFixed(1)}`;
  const day = (iso: string | null | undefined) =>
    iso
      ? new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : '';

  if (!res) {
    return (
      <Panel title="Graded against the House result" className="mb-5">
        <p className="text-sm text-cocoa-700">
          The final average was {m(fc.margin)}, translated to {fc.dem_seats} Democratic seats. The
          national House result has not been entered yet, so there is nothing to grade it against.
        </p>
      </Panel>
    );
  }

  const provisional = res.status !== 'final';
  return (
    <Panel
      title={`Graded against the House result${provisional ? ' — provisional' : ''}`}
      className="mb-5"
    >
      <div className="flex flex-wrap items-center gap-3">
        <GradeBadge grade={grade.grades.overall} size="lg" empty="—" />
        <p className="min-w-0 flex-1 text-sm leading-relaxed text-cocoa-700">
          {res.winner_right ? 'Right party, ' : 'Wrong party, and '}
          {res.margin_error != null && res.seats_error != null ? (
            <>
              {Math.abs(res.margin_error) < 2 ? 'right size' : 'wrong size'}: the final average
              undersold {res.margin_error > 0 ? 'Democrats' : 'Republicans'} by{' '}
              <strong>{Math.abs(res.margin_error).toFixed(1)} points</strong> and{' '}
              <strong>{Math.abs(res.seats_error)} seats</strong>.
            </>
          ) : (
            'with the full result still to come.'
          )}
        </p>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
              <th className="py-2 pr-3"></th>
              <th className="py-2 pr-3 text-right">Final average ({day(fc.as_of)})</th>
              <th className="py-2 pr-3 text-right">Result</th>
              <th className="py-2 pr-3 text-right">Miss</th>
              <th className="py-2 text-right">Grade</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-cream-100">
              <td className="py-2.5 pr-3 font-medium text-cocoa-700">National margin</td>
              <td className="py-2.5 pr-3 text-right text-cocoa-700">{m(fc.margin)}</td>
              <td className="py-2.5 pr-3 text-right text-cocoa-700">
                {provisional && res.national_margin != null ? 'about ' : ''}
                {m(res.national_margin)}
              </td>
              <td className="py-2.5 pr-3 text-right text-cocoa-700">
                {res.margin_error != null
                  ? `${res.margin_error > 0 ? 'D' : 'R'} +${Math.abs(res.margin_error).toFixed(1)}`
                  : '—'}
              </td>
              <td className="py-2.5 text-right">
                <GradeBadge grade={grade.grades.margin} empty="—" />
              </td>
            </tr>
            <tr>
              <td className="py-2.5 pr-3 font-medium text-cocoa-700">Democratic House seats</td>
              <td className="py-2.5 pr-3 text-right text-cocoa-700">
                {fc.dem_seats ?? '—'}
                {fc.dem_seats_lo != null && fc.dem_seats_hi != null && (
                  <div className="text-[11px] text-cocoa-400">
                    80% range {fc.dem_seats_lo}–{fc.dem_seats_hi}
                  </div>
                )}
              </td>
              <td className="py-2.5 pr-3 text-right text-cocoa-700">
                {res.dem_seats ?? '—'}
                {res.uncalled_seats ? (
                  <div className="text-[11px] text-cocoa-400">{res.uncalled_seats} uncalled</div>
                ) : null}
              </td>
              <td className="py-2.5 pr-3 text-right text-cocoa-700">
                {res.seats_error != null
                  ? `${res.seats_error > 0 ? 'D' : 'R'} +${Math.abs(res.seats_error)}`
                  : '—'}
                {res.seats_in_range != null && (
                  <div className={`text-[11px] ${res.seats_in_range ? 'text-stamp' : 'text-peach'}`}>
                    {res.seats_in_range ? 'inside' : 'outside'} the range
                  </div>
                )}
              </td>
              <td className="py-2.5 text-right">
                <GradeBadge grade={grade.grades.seats} empty="—" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-cocoa-400">
        {provisional && (
          <>
            Provisional as of {day(res.as_of)}: {res.margin_note ?? 'the count is not final.'} The
            grade will be redone on the Clerk of the House&rsquo;s official statistics.{' '}
          </>
        )}
        The margin is graded on the same scale as the Senate margins; seats go on that scale at two
        seats to the point.
        {res.sources.length > 0 && (
          <>
            {' '}Sources:{' '}
            {res.sources.map((s, i) => (
              <span key={s.url}>
                {i > 0 && ', '}
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-peach underline">
                  {s.label}
                </a>
              </span>
            ))}
            .
          </>
        )}
      </p>
    </Panel>
  );
}
