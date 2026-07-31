import { getMeta } from '@/app/lib/data';

const FEED_LABELS: Record<string, string> = {
  approval: 'approval',
  generic_ballot: 'generic-ballot',
  senate: 'Senate',
};

export default function DataFreshnessBanner({ feed }: { feed: string }) {
  const meta = getMeta();
  if (!meta.stale_feeds?.includes(feed)) return null;

  const lastPollDate = meta.last_poll_dates?.[feed];
  const formatted = lastPollDate
    ? new Date(`${lastPollDate}T00:00:00`).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : 'an unknown date';

  return (
    <div
      role="status"
      className="mb-5 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950"
    >
      <strong>Data freshness warning:</strong> the newest {FEED_LABELS[feed] ?? feed} poll is
      from {formatted}. The tracker remains available using the latest data on hand while the
      source feed is refreshed.
    </div>
  );
}
