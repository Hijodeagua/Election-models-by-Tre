import LastUpdated from '@/app/components/LastUpdated';

export default function MethodologyPage() {
  return (
    <div className="prose prose-slate max-w-none">
      <h2 className="text-2xl font-bold">Methodology</h2>

      <h3 className="mt-6 text-lg font-semibold">What this is</h3>
      <p className="mt-2 text-sm text-slate-600">
        This site is an election <strong>forecast in active development</strong>.
        Its foundation is a set of weighted polling averages — polls are
        weighted by a hybrid pollster-quality score and recency, as of the date
        stamped on each page. On top of that foundation, the Senate Forecast
        page runs a probabilistic simulation of chamber control and compares
        the result against prediction-market prices. The shaded bands on the
        tracker charts are confidence intervals around the polling average.
      </p>

      <h3 className="mt-6 text-lg font-semibold">Where it stands</h3>
      <p className="mt-2 text-sm text-slate-600">
        The probabilities published here come from a Monte Carlo simulation
        that has <strong>not yet been backtested</strong> across past election
        cycles, so treat them as an early-stage model output rather than a
        settled prediction. As calibration work completes, the uncertainty
        parameters and market-blend weights will be tuned against historical
        results and this page will be updated to reflect that.
      </p>
      <p className="mt-2 text-sm text-slate-600">
        The generic-ballot &ldquo;estimated seats&rdquo; figure is an{' '}
        <strong>illustrative</strong> translation from a static historical
        slope. It is a directional indicator only, not a seat projection.
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
          <strong>Senate</strong> — per-race weighted polling averages, with
          win probabilities and the control simulation on the Senate Forecast
          page.
        </li>
      </ul>

      <h3 className="mt-6 text-lg font-semibold">Comparison &amp; nowcast layers</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
        <li>
          <strong>Model comparison (homepage)</strong> — our approval average
          shown alongside Silver Bulletin&rsquo;s published model, an unweighted
          VoteHub poll average, and 50+1 when available. Each line is that
          source&rsquo;s own output; we don&rsquo;t blend them.
        </li>
        <li>
          <strong>NYT vibes adjustment (Senate)</strong> — an experimental,
          bounded (±3 pt) overlay on the base race average derived from
          sentiment-scored New York Times coverage. Full explainer on the
          Senate page. Off by default.
        </li>
        <li>
          <strong>Senate control simulation</strong> — 1,000 Monte Carlo
          simulations of the key races with correlated national polling error,
          optionally blending Polymarket/Kalshi implied odds at a tunable
          weight. Today it answers &ldquo;if the election were held now&rdquo;;
          as backtesting across past cycles completes, it will mature into a
          full election-day forecast.
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
