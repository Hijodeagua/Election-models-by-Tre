import LastUpdated from '@/app/components/LastUpdated';
import MarginChart from '@/app/components/MarginChart';
import { getGenericBallot } from '@/app/lib/data';

export default function GenericBallotPage() {
  const { current, trend, num_polls } = getGenericBallot();

  const lead = current ? (current.margin >= 0 ? 'D' : 'R') : '';

  return (
    <div>
      <h2 className="text-2xl font-bold">Generic Ballot Tracker</h2>
      <p className="mt-1 text-sm text-slate-500">
        Weighted polling average of the national generic congressional ballot.
        Margin is the Democratic minus Republican share. Tracker only — not a
        seat forecast.
      </p>

      {current ? (
        <>
          <div className="mt-6 grid grid-cols-3 gap-4">
            <Stat label="Democrat" value={`${current.dem_pct.toFixed(1)}%`} accent="text-dem" />
            <Stat label="Republican" value={`${current.rep_pct.toFixed(1)}%`} accent="text-rep" />
            <Stat
              label="Margin"
              value={`${lead}+${Math.abs(current.margin).toFixed(1)}`}
            />
          </div>
          <p className="mt-2 text-xs text-slate-400">
            As of {current.as_of} · {num_polls} polls in window
          </p>

          {current.estimated_dem_seats != null && (
            <p className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Illustrative seat translation: D {current.estimated_dem_seats} / R{' '}
              {current.estimated_rep_seats}. This is a rough directional indicator
              from a static historical slope — <strong>not a probability</strong>.
            </p>
          )}

          <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="mb-2 text-sm font-semibold text-slate-700">
              D−R margin trend
            </h3>
            <MarginChart trend={trend} />
          </div>
        </>
      ) : (
        <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          No generic-ballot estimate yet — need at least 3 polls in the window.
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
