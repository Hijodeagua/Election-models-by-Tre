import ApprovalChart from '@/app/components/ApprovalChart';
import ApprovalComparisonChart from '@/app/components/ApprovalComparisonChart';
import LastUpdated from '@/app/components/LastUpdated';
import { getApproval, getApprovalComparison } from '@/app/lib/data';

export default function ApprovalPage() {
  const { current, trend, num_polls } = getApproval();
  const comparison = getApprovalComparison();

  return (
    <div>
      <h2 className="text-2xl font-bold">Presidential Approval Tracker</h2>
      <p className="mt-1 text-sm text-slate-500">
        Weighted polling average of job-approval polls. This is a tracker of
        where polling stands today — not a prediction of any future outcome.
      </p>

      {current ? (
        <>
          <div className="mt-6 grid grid-cols-3 gap-4">
            <Stat label="Approve" value={`${current.approve.toFixed(1)}%`} accent="text-dem" />
            <Stat label="Disapprove" value={`${current.disapprove.toFixed(1)}%`} accent="text-rep" />
            <Stat
              label="Net"
              value={`${current.net_approval > 0 ? '+' : ''}${current.net_approval.toFixed(1)}`}
            />
          </div>
          <p className="mt-2 text-xs text-slate-400">
            As of {current.as_of} · {num_polls} polls in window
            {current.ci_approve
              ? ` · approve range ${current.ci_approve[0].toFixed(1)}–${current.ci_approve[1].toFixed(1)}%`
              : ''}
          </p>

          <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="mb-2 text-sm font-semibold text-slate-700">
              Daily trend with confidence band
            </h3>
            <ApprovalChart trend={trend} />
          </div>
        </>
      ) : (
        <EmptyState />
      )}

      {Object.keys(comparison.sources).length > 0 && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-1 text-sm font-semibold text-slate-700">
            Model comparison — toggle the sources you want
          </h3>
          <p className="mb-3 text-xs text-slate-400">
            Our weighted average alongside Silver Bulletin&apos;s model, a raw
            unweighted VoteHub poll average, and 50+1 (when available).
          </p>
          <ApprovalComparisonChart data={comparison} />
        </div>
      )}

      <LastUpdated />
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 text-center">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${accent ?? 'text-slate-900'}`}>{value}</div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
      No approval estimate yet — need at least 3 polls in the window.
    </div>
  );
}
