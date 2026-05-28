import LastUpdated from '@/app/components/LastUpdated';
import { getSenate } from '@/app/lib/data';

export default function SenatePage() {
  const { races } = getSenate();

  return (
    <div>
      <h2 className="text-2xl font-bold">Senate Race Trackers</h2>
      <p className="mt-1 text-sm text-slate-500">
        Per-race weighted polling averages. Each row shows the leading
        candidates and the polling margin. No win probabilities — these are
        polling averages only.
      </p>

      {races.length > 0 ? (
        <div className="mt-6 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Candidate averages</th>
                <th className="px-4 py-3 text-right">Margin</th>
                <th className="px-4 py-3 text-right">Polls</th>
              </tr>
            </thead>
            <tbody>
              {races.map((race) => {
                const ranked = Object.entries(race.candidates).sort((a, b) => b[1] - a[1]);
                return (
                  <tr key={race.state} className="border-b border-slate-100 last:border-0">
                    <td className="px-4 py-3 font-medium">{race.state}</td>
                    <td className="px-4 py-3">
                      {ranked.slice(0, 3).map(([name, pct]) => (
                        <span key={name} className="mr-3 whitespace-nowrap">
                          {name}: <strong>{pct.toFixed(1)}%</strong>
                        </span>
                      ))}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {race.margin != null
                        ? `${race.margin > 0 ? '+' : ''}${race.margin.toFixed(1)}`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-500">{race.num_polls}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          No Senate races with polling data yet.
        </div>
      )}

      <LastUpdated />
    </div>
  );
}
