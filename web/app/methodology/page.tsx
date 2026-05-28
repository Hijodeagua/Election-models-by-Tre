import LastUpdated from '@/app/components/LastUpdated';

export default function MethodologyPage() {
  return (
    <div className="prose prose-slate max-w-none">
      <h2 className="text-2xl font-bold">Methodology</h2>

      <h3 className="mt-6 text-lg font-semibold">What this is</h3>
      <p className="mt-2 text-sm text-slate-600">
        This site is a <strong>tracker</strong>. Every number shown is a
        weighted average of recent public polls, as of the date stamped on each
        page. We weight polls by a hybrid pollster-quality score and recency.
        The shaded bands are confidence intervals around the polling average —
        they describe uncertainty in the <em>average</em>, not in any election
        outcome.
      </p>

      <h3 className="mt-6 text-lg font-semibold">What this is not</h3>
      <p className="mt-2 text-sm text-slate-600">
        This is <strong>not a forecast</strong>. It does not output a
        probability that any candidate or party will win. A forecast requires a
        probabilistic outcome model with simulation and calibration that has
        been backtested across multiple election cycles — work that is not yet
        complete here. Until that exists, we deliberately avoid all
        win-probability language.
      </p>
      <p className="mt-2 text-sm text-slate-600">
        The generic-ballot &ldquo;estimated seats&rdquo; figure is an{' '}
        <strong>illustrative</strong> translation from a static historical
        slope. It is a directional indicator only and must not be read as a
        probability or a seat projection.
      </p>

      <h3 className="mt-6 text-lg font-semibold">The three trackers</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
        <li>
          <strong>Presidential approval</strong> — weighted average of
          job-approval polls, with a daily trend and CI band.
        </li>
        <li>
          <strong>Generic ballot</strong> — weighted average of the national
          D-vs-R congressional preference, reported as a margin.
        </li>
        <li>
          <strong>Senate</strong> — per-race weighted polling averages. No win
          probabilities.
        </li>
      </ul>

      <h3 className="mt-6 text-lg font-semibold">Data &amp; refresh</h3>
      <p className="mt-2 text-sm text-slate-600">
        Polling data is refreshed daily by a scheduled job that runs the model
        pipeline and publishes static JSON. The heavier hierarchical
        state-space estimates are intentionally excluded from the published
        data for performance reasons.
      </p>

      <LastUpdated />
    </div>
  );
}
