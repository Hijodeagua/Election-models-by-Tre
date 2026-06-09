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

      <h3 className="mt-6 text-lg font-semibold">Trackers vs. forecasts</h3>
      <p className="mt-2 text-sm text-slate-600">
        The approval, generic-ballot and per-race Senate pages are{' '}
        <strong>trackers</strong> — no win-probability language. The dashboard
        additionally shows an <strong>experimental Senate forecast</strong>:
        per-race win probabilities and a chamber-control simulation. It has not
        been backtested across multiple cycles yet, so treat those
        probabilities as a structured reading of polls, ratings and markets —
        not a calibrated prediction.
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

      <h3 className="mt-6 text-lg font-semibold">Senate win probabilities</h3>
      <p className="mt-2 text-sm text-slate-600">
        For each 2026 race we convert the polled Dem-minus-Rep margin into a
        win probability using a normal error model with σ = 5 points — roughly
        the historical accuracy of Senate polling averages. Races without
        usable polling fall back to a structural rating prior (solid ≈ 97%,
        likely ≈ 85%, lean ≈ 65%, tossup = 50%). Where Polymarket or Kalshi
        have an open market on the race, the final number is a blend:{' '}
        <code>(1 − w) × model + w × market</code> with w = 0.25. The blend is
        applied <em>before</em> simulation, so market prices inform the
        forecast itself, not just the comparison chart.
      </p>

      <h3 id="vibes" className="mt-6 scroll-mt-6 text-lg font-semibold">
        The NYT &ldquo;vibes&rdquo; component
      </h3>
      <p className="mt-2 text-sm text-slate-600">
        The vibes layer measures how a candidate is being covered in the New
        York Times and nudges that race&rsquo;s polling margin accordingly. The
        pipeline pulls every NYT article mentioning a candidate, scores each
        mention&rsquo;s sentiment, and reduces the result to three metrics:
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
        <li>
          <strong>Tone split</strong> — the share of mentions that are
          positive, negative, or neutral.
        </li>
        <li>
          <strong>Five-bucket rating</strong> — from overwhelmingly negative
          (−2) to overwhelmingly positive (+2), based on the tone split.
        </li>
        <li>
          <strong>Scandal flags</strong> — pattern matching for indictments,
          investigations, resignations and the like, combined into a 0–1
          severity score.
        </li>
      </ul>
      <p className="mt-2 text-sm text-slate-600">
        Each candidate&rsquo;s adjustment is{' '}
        <code>bucket × 0.5 − scandal_severity × 1.5</code> points of margin,
        capped at ±1.5; the race adjustment is the Dem candidate&rsquo;s value
        minus the Rep candidate&rsquo;s, capped at ±2.5 points. The caps are
        deliberate: media tone is a seasoning on top of polling, never the
        dish. When no coverage data exists for a race the adjustment is exactly
        zero — vibes are never imputed.
      </p>

      <h3 id="simulation" className="mt-6 scroll-mt-6 text-lg font-semibold">
        The Senate control simulation
      </h3>
      <p className="mt-2 text-sm text-slate-600">
        &ldquo;Who wins the Senate&rdquo; is answered by running{' '}
        <strong>1,000 Monte Carlo simulations</strong> of all 35 races (the 33
        Class 2 seats plus the Florida and Ohio specials). Each race&rsquo;s
        blended win probability is converted back to an implied margin, then
        every simulation draws one shared national-environment swing (σ = 3
        points, applied to all races at once) plus an independent per-race
        error (σ = 4 points). The shared swing is what makes outcomes
        correlated — polling misses tend to break the same direction
        everywhere, which is why control probabilities are wider than
        multiplying independent races would suggest. Seats not up this cycle
        are held fixed (34 D, 31 R), and Democrats need 51 seats for control
        since the Vice President is Republican. The histogram shows the full
        distribution of seat outcomes; the tipping-point list counts how often
        each state was the seat that decided control.
      </p>

      <h3 className="mt-6 text-lg font-semibold">Comparison sources</h3>
      <p className="mt-2 text-sm text-slate-600">
        The dashboard overlays our numbers with Silver Bulletin model
        estimates, raw VoteHub polling averages, 50+1 (where data is
        available), and Polymarket / Kalshi prices. Each series is shown
        exactly as published by its source; when a source has no data yet, its
        toggle is disabled rather than filled with placeholders.
      </p>

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
