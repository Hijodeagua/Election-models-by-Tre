'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV = [
  { href: '/', label: 'Approval' },
  { href: '/generic-ballot', label: 'Generic Ballot' },
  { href: '/senate', label: 'Senate' },
  { href: '/senate-forecast', label: 'Senate Forecast' },
  { href: '/pollsters', label: 'Pollsters' },
  { href: '/methodology', label: 'Methodology' },
];

export default function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-cream-300 bg-cream-50/90 backdrop-blur">
      <div className="h-[3px] bg-peach" />
      <div className="mx-auto max-w-4xl px-4">
        <div className="flex items-center justify-between py-3">
          <Link href="/" className="flex items-center gap-3">
            {/* basePath '/election' is not auto-applied to plain img src */}
            <img
              src="/election/logo-policy-peaches.webp"
              alt="Policy & Peaches"
              className="h-12 w-12 object-contain mix-blend-multiply"
            />
            <div>
              <div className="font-display text-xl leading-none text-ink sm:text-2xl">
                Election Oracle
              </div>
              <div className="mt-1 text-[10.5px] tracking-wide text-cocoa-400">
                by Policy &amp; Peaches · <em>a work in progress</em>
              </div>
            </div>
          </Link>
          <a
            href="https://policyypeaches.substack.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="whitespace-nowrap rounded-lg bg-peach px-3.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-peach-hover"
          >
            Subscribe
          </a>
        </div>
        <nav className="-mb-px flex flex-nowrap gap-0.5 overflow-x-auto border-t border-cream-300 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {NAV.map((item) => {
            const active =
              item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`shrink-0 whitespace-nowrap border-b-2 px-3 py-2.5 text-[13px] transition-colors ${
                  active
                    ? 'border-peach font-semibold text-ink'
                    : 'border-transparent font-medium text-cocoa-500 hover:text-ink'
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
