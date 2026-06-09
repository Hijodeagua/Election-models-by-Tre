import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'Election Tracker — whosyurgoat',
  description:
    'A polling-average tracker for presidential approval, the generic ballot, and Senate races. Not a forecast.',
};

const NAV = [
  { href: '/', label: 'Approval' },
  { href: '/generic-ballot', label: 'Generic Ballot' },
  { href: '/senate', label: 'Senate' },
  { href: '/senate-forecast', label: 'Senate Forecast' },
  { href: '/methodology', label: 'Methodology' },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-4xl flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-lg font-bold">Election Tracker</h1>
              <p className="text-xs uppercase tracking-wide text-slate-400">
                Polling averages · not a forecast
              </p>
            </div>
            <nav className="flex flex-wrap gap-3 text-sm">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded px-2 py-1 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-4xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
