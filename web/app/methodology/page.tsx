import LastUpdated from '@/app/components/LastUpdated';
import { PageHead } from '@/app/components/ui';
import { getMeta } from '@/app/lib/data';

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 mt-7 font-display text-xl text-ink">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-4 font-serifbody text-base leading-relaxed text-cocoa-700">{children}</p>
  );
}

const POLL_LABELS: Record<string, string> = {
  approval: 'Presidential approval',
  generic_ballot: 'Generic ballot',
  senate: 'Senate races',
};

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return 'no polls yet';
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export default function MethodologyPage() {
  const meta = getMeta();
  const lastUpdated = meta.last_updated
    ? new Date(meta.last_updated).toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : 'unknown';
  const pollDates = meta.last_poll_dates ?? {};
  const pollCounts = meta.poll_counts ?? {};
  const staleFeeds: string[] = meta.stale_feeds ?? [];
  const feeds = Object.keys(POLL_LABELS);

  return (
    <div className="max-w-2xl">
      <PageHead
        kicker="Methodology"
        title="How the Oracle actually works"
        sub="No black boxes. Here is every step between a raw poll and the numbers on this site."
      />

      <H>What this is</H>
      <P>
        A work in progress from the team at Policy y Peaches. Its foundation is a
        set of weighted polling averages — polls are weighted by a hybrid
        pollster-quality score and recency, as of the date stamped on each page.
        On top of that foundation, the Senate Forecast page runs a probabilistic
        simulation of chamber control and compares the result against
        prediction-market prices. The shaded bands on the charts are confidence
        intervals around the polling average.
      </P>

      <H>The three trackers</H>
      <ul className="mb-4 list-disc space-y-1.5 pl-5 font-serifbody text-base leading-relaxed text-cocoa-700">
        <li>
          <strong>Presidential approval</strong> — weighted average of
          job-approval polls, with a daily trend and CI band.
        </li>
        <li>
          <strong>Generic ballot</strong> — weighted average of the national
          D-vs-R congressional preference, reported as a margin. The
          &ldquo;estimated seats&rdquo; figure is a directional translation from a
          historical slope.
        </li>
        <li>
          <strong>Senate</strong> — per-race weighted polling averages. Click any
          race card to chart how our win probability for that race has moved over
          time. Chamber-wide win probabilities live on the Senate Forecast page.
        </li>
      </ul>

      <H>Comparison &amp; nowcast layers</H>
      <ul className="mb-4 list-disc space-y-1.5 pl-5 font-serifbody text-base leading-relaxed text-cocoa-700">
        <li>
          <strong>Model comparison (homepage)</strong> — our approval average
          shown alongside an unweighted VoteHub poll average, and 50+1 when
          available. Each line is that source&rsquo;s own output; we
          don&rsquo;t blend them.
        </li>
        <li>
          <strong>NYT vibes adjustment (Senate)</strong> — an experimental,
          bounded (±3 pt) overlay on the base race average derived from
          sentiment-scored New York Times coverage. Full explainer on the
          Senate page. Off by default.
        </li>
        <li>
          <strong>Senate control simulation</strong> — 50,000 Monte Carlo
          simulations of the key races with correlated national polling error,
          optionally blending Polymarket/Kalshi implied odds at a tunable weight.
          It shows where the chamber stands today given current polling and market
          prices.
        </li>
      </ul>

      <H>Data &amp; refresh</H>
      <P>
        Polling data is refreshed by a scheduled job that runs the model pipeline
        twice a day and publishes static JSON — including the hierarchical
        state-space estimates (house-effect-corrected approval and generic
        ballot). If a primary feed stops delivering new polls for more than 72
        hours, the pipeline tops it up from Wikipedia&rsquo;s national polling
        tables and flags the feed below.
      </P>

      <div className="mb-4 overflow-hidden rounded-xl border border-cream-300 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-cream-300 text-left text-xs uppercase tracking-wide text-cocoa-400">
              <th className="px-4 py-3">Feed</th>
              <th className="px-4 py-3 text-right">Polls in average</th>
              <th className="px-4 py-3 text-right">Most recent poll</th>
            </tr>
          </thead>
          <tbody>
            {feeds.map((key) => (
              <tr key={key} className="border-b border-cream-100 last:border-0">
                <td className="px-4 py-3 font-medium text-cocoa-700">{POLL_LABELS[key]}</td>
                <td className="px-4 py-3 text-right text-cocoa-500">
                  {pollCounts[key] != null ? pollCounts[key].toLocaleString() : '—'}
                </td>
                <td className="px-4 py-3 text-right text-cocoa-700">
                  {fmtDate(pollDates[key])}
                  {staleFeeds.includes(key) && (
                    <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
                      stale
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-4 text-xs leading-relaxed text-cocoa-500">
        Pipeline last run <strong className="text-cocoa-700">{lastUpdated}</strong>.
        &ldquo;Most recent poll&rdquo; is the newest survey in each feed — if those
        dates start drifting behind today, the upstream polling sources need a
        refresh. <em>Reminder to the team: keep the source CSVs current.</em>
      </p>

      <div className="mt-7 border-t border-cream-300 pt-4 text-xs leading-relaxed text-cocoa-400">
        A work in progress from the team at Policy y Peaches —{' '}
        <a
          href="https://policyypeaches.substack.com/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-peach underline"
        >
          learn more here
        </a>
        . Data sources: VoteHub, Polymarket, Kalshi, state
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
