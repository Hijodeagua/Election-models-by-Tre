import Link from 'next/link';
import ApprovalComparisonChart from '@/app/components/ApprovalComparisonChart';
import LastUpdated from '@/app/components/LastUpdated';
import SenateControlSim from '@/app/components/SenateControlSim';
import SenateRaceExplorer from '@/app/components/SenateRaceExplorer';
import {
  getApproval,
  getApprovalComparison,
  getSenateControl,
  getSenateRaces,
} from '@/app/lib/data';

export default function DashboardPage() {
  const { current, num_polls } = getApproval();
  const comparison = getApprovalComparison();
  const senateRaces = getSenateRaces();
  const control = getSenateControl();

  return (
    <div className="space-y-12">
      {/* ── Section 1: Trump approval, multi-source ─────────────────── */}
      <section>
        <h2 className="text-2xl font-bold">Trump Approval — model comparison</h2>
        <p className="mt-1 text-sm text-slate-500">
          Toggle sources to compare our weighted polling average against Silver
          Bulletin, the raw VoteHub average, and 50+1. Full tracker with
          confidence bands on the{' '}
          <Link href="/approval" className="underline">
            approval page
          </Link>
          .
        </p>

        {current && (
          <div className="mt-4 grid grid-cols-3 gap-4">
            <Stat label="Approve" value={`${current.approve.toFixed(1)}%`} accent="text-dem" />
            <Stat label="Disapprove" value={`${current.disapprove.toFixed(1)}%`} accent="text-rep" />
            <Stat
              label="Net"
              value={`${current.net_approval > 0 ? '+' : ''}${current.net_approval.toFixed(1)}`}
            />
          </div>
        )}
        {current && (
          <p className="mt-2 text-xs text-slate-400">
            Our model as of {current.as_of} · {num_polls} polls in window
          </p>
        )}

        <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
          <ApprovalComparisonChart data={comparison} />
        </div>
      </section>

      {/* ── Section 2: per-race Senate forecasts ────────────────────── */}
      <section>
        <h2 className="text-2xl font-bold">Senate {senateRaces.cycle} — race by race</h2>
        <p className="mt-1 text-sm text-slate-500">
          Pick a race and toggle model variants: our base polling model, the
          NYT-vibes-adjusted version (
          <Link href="/methodology#vibes" className="underline">
            explainer
          </Link>
          ), the market-blended number, and raw Polymarket / Kalshi odds.
          Battlegrounds are starred.
        </p>
        <div className="mt-4">
          <SenateRaceExplorer races={senateRaces.races} />
        </div>
      </section>

      {/* ── Section 3: who wins the Senate ──────────────────────────── */}
      <section>
        <h2 className="text-2xl font-bold">Who wins the Senate?</h2>
        <p className="mt-1 text-sm text-slate-500">
          Aggregate forecast from {control.simulation?.n_sims.toLocaleString() ?? '1,000'}{' '}
          Monte Carlo simulations of all {senateRaces.num_races} races, with a
          correlated national-environment swing —{' '}
          <Link href="/methodology#simulation" className="underline">
            how the simulation works
          </Link>
          .
        </p>
        <div className="mt-4">
          <SenateControlSim data={control} />
        </div>
      </section>

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
