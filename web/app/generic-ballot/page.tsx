import LastUpdated from '@/app/components/LastUpdated';
import DataFreshnessBanner from '@/app/components/DataFreshnessBanner';
import MarginChart from '@/app/components/MarginChart';
import { EmptyState, MetaStrip, PageHead, Panel, StatCard } from '@/app/components/ui';
import { getGenericBallot } from '@/app/lib/data';

export default function GenericBallotPage() {
  const { current, trend, num_polls } = getGenericBallot();

  const lead = current ? (current.margin >= 0 ? 'D' : 'R') : '';

  return (
    <div>
      <PageHead
        kicker="Generic Congressional Ballot"
        title="Which party do voters want running Congress?"
        sub={
          <>
            &ldquo;If the election were held today, would you vote for the
            Democrat or the Republican in your district?&rdquo; — averaged
            across public polls. Margin is the Democratic minus Republican
            share.
          </>
        }
      />
      <DataFreshnessBanner feed="generic_ballot" />

      {current ? (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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
                { k: 'Updated', v: current.as_of },
                { k: 'Polls in window', v: String(num_polls) },
              ]}
            />
          </div>

          {current.estimated_dem_seats != null && (
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
