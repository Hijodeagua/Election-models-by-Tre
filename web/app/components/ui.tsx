// Policy & Peaches shared primitives — ported from design-system/layout.jsx.

import type { ReactNode } from 'react';

export function PageHead({
  kicker,
  title,
  sub,
}: {
  kicker?: string;
  title: string;
  sub?: ReactNode;
}) {
  return (
    <div className="mb-5">
      {kicker && (
        <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-peach">
          {kicker}
        </div>
      )}
      <h2 className="font-display text-3xl leading-[1.08] tracking-tight text-ink sm:text-4xl">
        {title}
      </h2>
      {sub && (
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-cocoa-500">{sub}</p>
      )}
    </div>
  );
}

export function Panel({
  title,
  children,
  className = '',
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-cream-300 bg-white p-4 sm:p-5 ${className}`}>
      {title && (
        <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-cocoa-400">
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

const STAT_TONES = {
  dem: 'border-dem-border bg-dem-wash text-dem',
  rep: 'border-rep-border bg-rep-wash text-rep',
  ink: 'border-cream-300 bg-white text-cocoa-700',
  peach: 'border-peach-border bg-peach-wash text-peach',
} as const;

export function StatCard({
  label,
  value,
  tone = 'ink',
  sub,
}: {
  label: string;
  value: string;
  tone?: keyof typeof STAT_TONES;
  sub?: string;
}) {
  const toneCls = STAT_TONES[tone];
  return (
    <div className={`rounded-xl border px-4 py-4 ${toneCls.split(' ').slice(0, 2).join(' ')}`}>
      <div className="mb-1 text-[11.5px] text-cocoa-400">{label}</div>
      <div className={`font-display text-3xl leading-none sm:text-4xl ${toneCls.split(' ')[2]}`}>
        {value}
      </div>
      {sub && <div className="mt-1.5 text-[11px] text-cocoa-400">{sub}</div>}
    </div>
  );
}

export function MetaStrip({ items }: { items: { k: string; v: string }[] }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg bg-cream-200 px-3.5 py-2">
      {items.map((it) => (
        <span key={it.k} className="text-[11.5px] text-cocoa-500">
          {it.k} <strong className="text-cocoa-700">{it.v}</strong>
        </span>
      ))}
    </div>
  );
}

const PILL_TONES = {
  neutral: 'border-cream-300 bg-cream-50 text-cocoa-500',
  peach: 'border-peach-border bg-peach-wash text-peach',
  dem: 'border-dem-border bg-dem-wash text-dem',
  green: 'border-[#cfe2c6] bg-stamp-wash text-stamp',
} as const;

export function Pill({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: keyof typeof PILL_TONES;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${PILL_TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="mt-6 rounded-xl border border-dashed border-cocoa-300 bg-white p-8 text-center text-sm text-cocoa-500">
      {children}
    </div>
  );
}
