import type { Metadata } from 'next';
import Link from 'next/link';
import { DM_Serif_Display, Source_Serif_4 } from 'next/font/google';
import SiteHeader from '@/app/components/SiteHeader';
import './globals.css';

const display = DM_Serif_Display({
  weight: '400',
  style: ['normal', 'italic'],
  subsets: ['latin'],
  variable: '--font-display',
});

const serifBody = Source_Serif_4({
  weight: ['400', '500', '600'],
  subsets: ['latin'],
  variable: '--font-serif-body',
});

export const metadata: Metadata = {
  title: 'Election Oracle — Policy y Peaches',
  description:
    'A polling-average tracker for presidential approval, the generic ballot, and Senate races. More to come, but to learn more read here: https://policyypeaches.substack.com/',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${display.variable} ${serifBody.variable}`}>
      <body className="flex min-h-screen flex-col">
        <SiteHeader />
        <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">{children}</main>
        <footer className="mt-10 border-t border-cream-300 bg-cream-100">
          <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-6">
            <div className="flex items-center gap-2.5">
              <img
                src="/election/logo-policy-peaches.webp"
                alt=""
                className="h-8 w-8 object-contain mix-blend-multiply"
              />
              <span className="text-[11.5px] text-cocoa-500">
                © 2026 Policy &amp; Peaches · Updated daily from public polling
              </span>
            </div>
            <div className="flex gap-4 text-[11.5px]">
              <Link href="/methodology" className="text-peach hover:text-peach-hover">
                Methodology
              </Link>
              <a
                href="https://policyypeaches.substack.com/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-peach hover:text-peach-hover"
              >
                Newsletter
              </a>
              <a
                href="https://github.com/Hijodeagua/Election-models-by-Tre"
                target="_blank"
                rel="noopener noreferrer"
                className="text-peach hover:text-peach-hover"
              >
                GitHub
              </a>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
