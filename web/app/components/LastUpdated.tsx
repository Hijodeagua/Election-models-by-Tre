import { getMeta } from '@/app/lib/data';

// "Last updated" stamp shown on every page, driven by meta.json.
export default function LastUpdated() {
  const meta = getMeta();
  const stamp = meta.last_updated
    ? new Date(meta.last_updated).toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : 'unknown';

  return (
    <div className="mt-10 border-t border-slate-200 pt-4 text-xs text-slate-500">
      <p>Last updated: {stamp}</p>
      <p className="mt-1 font-medium uppercase tracking-wide text-slate-400">
        {meta.label}
      </p>
    </div>
  );
}
