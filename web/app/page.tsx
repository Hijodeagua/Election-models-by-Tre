import ApprovalChart from '@/app/components/ApprovalChart';
import ApprovalComparisonChart from '@/app/components/ApprovalComparisonChart';
import DataFreshnessBanner from '@/app/components/DataFreshnessBanner';
import LastUpdated from '@/app/components/LastUpdated';
import { EmptyState, MetaStrip, PageHead, Panel, StatCard } from '@/app/components/ui';
import { getApproval, getApprovalComparison } from '@/app/lib/data';

export default function ApprovalPage() {
  const { current, trend, num_polls } = getApproval();
  const comparison = getApprovalComparison();

  return (
    <div>
      <PageHead
        kicker="Presidential Approval"
        title="Is the country buying what the President is selling?"
        sub="A weighted average of public job-approval polls — weighted by pollster quality, recency, and sample size — showing where polling stands today."
      />
      <DataFreshnessBanner feed="approval" />

      {current ? (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard
              label="Approve"
              value={`${current.approve.toFixed(1)}%`}
              tone="dem"
              sub={
                current.ci_approve
                  ? `[${current.ci_approve[0].toFixed(1)} – ${current.ci_approve[1].toFixed(1)}]`
                  : undefined
              }
            />
            <StatCard
              label="Disapprove"
              value={`${current.disapprove.toFixed(1)}%`}
              tone="rep"
              sub={
                current.ci_disapprove
                  ? `[${current.ci_disapprove[0].toFixed(1)} – ${current.ci_disapprove[1].toFixed(1)}]`
                  : undefined
              }
            />
            <StatCard
              label="Net approval"
              value={`${current.net_approval > 0 ? '+' : '−'}${Math.abs(current.net_approval).toFixed(1)}`}
              tone="ink"
            />
          </div>

          <div className="mt-4">
            <MetaStrip
              items={[
                { k: 'Updated', v: current.as_of },
                { k: 'Polls in window', v: String(num_polls) },
                { k: 'Model', v: 'weighted average' },
              ]}
            />
          </div>

          <Panel title="Daily polling average · confidence band" className="mb-4">
            <ApprovalChart trend={trend} />
          </Panel>
        </>
      ) : (
        <EmptyState>
          No approval estimate yet — need at least 3 polls in the window.
        </EmptyState>
      )}

      {Object.keys(comparison.sources).length > 0 && (
        <Panel title="Model comparison — toggle the sources you want">
          <p className="mb-3 text-xs text-cocoa-400">
            Our weighted average alongside a raw unweighted VoteHub poll
            average, and 50+1 (when available).
          </p>
          <ApprovalComparisonChart data={comparison} />
        </Panel>
      )}

      <LastUpdated />
    </div>
  );
}
