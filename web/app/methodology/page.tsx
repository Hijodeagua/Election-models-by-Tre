import LastUpdated from '@/app/components/LastUpdated';
import { PageHead } from '@/app/components/ui';

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 mt-7 font-display text-xl text-ink">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-4 font-serifbody text-base leading-relaxed text-cocoa-700">{children}</p>
  );
}

export default function MethodologyPage() {
  return (
    <div className="max-w-2xl">
      <PageHead
        kicker="Methodology"
        title="How the Oracle actually works"
        sub="No black boxes. Here is every step between a raw poll and the numbers on this site."
      />

      <div className="mb-6 rounded-xl border border-peach-border bg-peach-wash px-4 py-3.5">
        <p className="font-display text-lg leading-snug text-peach">
          A forecast in active development — calibration and backtesting are
          still in progress, so treat every probability as an early-stage model
          output.
        </p>
      </div>

      <H>What this is</H>
      <P>
        This site is an election <strong>forecast in active development</strong>.
        Its foundation is a set of weighted polling averages — polls are
        weighted by a hybrid pollster-quality score and recency, as of the date
        stamped on each page. On top of that foundation, the Senate Forecast
        page runs a probabilistic simulation of chamber control and compares
        the result against prediction-market prices. The shaded bands on the
        tracker charts are confidence intervals around the polling average.
      </P>

      <H>Where it stands</H>
      <P>
        The probabilities published here come from a Monte Carlo simulation
        that has <strong>not yet been backtested</strong> across past election
        cycles, so treat them as an early-stage model output rather than a
        settled prediction. As calibration work completes, the uncertainty
        parameters and market-blend weights will be tuned against historical
        results and this page will be updated to reflect that.
      </P>
      <P>
        The generic-ballot &ldquo;estimated seats&rdquo; figure is an{' '}
        <strong>illustrative</strong> translation from a static historical
        slope. It is a directional indicator only, not a seat projection.
      </P>

      <H>The three trackers</H>
      <ul className="mb-4 list-disc space-y-1.5 pl-5 font-serifbody text-base leading-relaxed text-cocoa-700">
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

      <H>Comparison &amp; nowcast layers</H>
      <ul className="mb-4 list-disc space-y-1.5 pl-5 font-serifbody text-base leading-relaxed text-cocoa-700">
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

      <H>Data &amp; refresh</H>
      <P>
        Polling data is refreshed daily by a scheduled job that runs the model
        pipeline and publishes static JSON. The heavier hierarchical
        state-space estimates are intentionally excluded from the published
        data for performance reasons.
      </P>

      <div className="mt-7 border-t border-cream-300 pt-4 text-xs leading-relaxed text-cocoa-400">
        Data sources: VoteHub, Silver Bulletin, Polymarket, Kalshi, state
        pollster releases. Code &amp; full poll log on{' '}
        <a
          href="https://github.com/Hijodeagua/Election-models-by-Tre"
          target="_blank"
          rel="noopener noreferrer"
          className="text-peach underline"
        >
          GitHub
        </a>
        .
      </div>

      <LastUpdated />
    </div>
  );
}
