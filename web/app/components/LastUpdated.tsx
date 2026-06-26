import { getMeta } from '@/app/lib/data';

// Per-page footer: a plain "work in progress" note with a link to the
// newsletter, plus the last-updated stamp. Replaces the old stack of
// "this is not a forecast" disclaimers.
export default function LastUpdated() {
  const meta = getMeta();
  const stamp = meta.last_updated
    ? new Date(meta.last_updated).toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : 'unknown';

  return (
    <div className="mt-10 border-t border-cream-300 pt-4 text-xs text-cocoa-500">
      <p>
        A work in progress from the team at Policy y Peaches.{' '}
        <a
          href="https://policyypeaches.substack.com/"
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-peach underline"
        >
          Learn more here
        </a>
        .
      </p>
      <p className="mt-1.5 text-cocoa-400">Last updated: {stamp}</p>
    </div>
  );
}
