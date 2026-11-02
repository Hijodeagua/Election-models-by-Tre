'use client';

// Share Hijodeagua's board as an image (map card or table) or as text. The
// PNG is rendered as soon as the dialog opens, so the Share button can call
// navigator.share straight from the tap (iOS requires that).

import { useEffect, useMemo, useRef, useState } from 'react';
import type { PredictionRaceView } from '@/app/lib/predictions-shared';
import { buildMapSvg, buildShareText, buildTableSvg, svgToPng } from '@/app/lib/share-image';

type Kind = 'map' | 'table';

interface Rendered {
  kind: Kind;
  blob: Blob;
  url: string;
}

export default function ShareDialog({
  races,
  asOf,
  onClose,
}: {
  races: PredictionRaceView[];
  asOf: string;
  onClose: () => void;
}) {
  const [kind, setKind] = useState<Kind>('map');
  const [rendered, setRendered] = useState<Rendered | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const image = useMemo(
    () => (kind === 'map' ? buildMapSvg(races, asOf) : buildTableSvg(races, asOf)),
    [kind, races, asOf],
  );
  const filename = `hijodeagua-senate-guesses-${kind}.png`;

  useEffect(() => {
    let cancelled = false;
    let url: string | null = null;
    setRendered(null);
    setError(null);
    setStatus(null);
    svgToPng(image)
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setRendered({ kind, blob, url });
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'could not render the image');
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [image, kind]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const file = rendered ? new File([rendered.blob], filename, { type: 'image/png' }) : null;
  const canShareFile =
    typeof navigator !== 'undefined' &&
    !!file &&
    typeof navigator.canShare === 'function' &&
    navigator.canShare({ files: [file] });
  const canCopyImage =
    typeof window !== 'undefined' && 'ClipboardItem' in window && !!navigator.clipboard?.write;

  async function share() {
    if (!file) return;
    try {
      await navigator.share({ files: [file], title: "Hijodeagua's Senate guesses" });
      setStatus('Shared');
    } catch (e) {
      if ((e as DOMException)?.name !== 'AbortError') setStatus('Sharing failed — try Download');
    }
  }

  async function copyImage() {
    if (!rendered) return;
    try {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': rendered.blob })]);
      setStatus('Image copied — paste it anywhere');
    } catch {
      setStatus('Copy blocked by the browser — try Download');
    }
  }

  function download() {
    if (!rendered) return;
    const a = document.createElement('a');
    a.href = rendered.url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setStatus('Downloaded');
  }

  async function copyText() {
    try {
      await navigator.clipboard.writeText(buildShareText(races, asOf));
      setStatus('Text copied');
    } catch {
      setStatus('Copy blocked by the browser');
    }
  }

  const btn =
    'rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50';
  const primary = `${btn} border-peach bg-peach text-white hover:bg-peach-hover`;
  const secondary = `${btn} border-cream-300 bg-white text-cocoa-700 hover:border-peach hover:text-peach`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-0 sm:items-center sm:p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-title"
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl border border-cream-300 bg-cream-50 p-4 shadow-xl sm:rounded-2xl sm:p-5"
      >
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 id="share-title" className="font-display text-xl text-ink">
            Share these guesses
          </h3>
          <button ref={closeRef} type="button" onClick={onClose} className={secondary} aria-label="Close">
            Close
          </button>
        </div>

        <div className="mb-3 inline-flex rounded-lg border border-cream-300 bg-white p-0.5" role="group" aria-label="Image style">
          {(['map', 'table'] as Kind[]).map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={kind === k}
              onClick={() => setKind(k)}
              className={`rounded-md px-3 py-1 text-xs font-semibold ${
                kind === k ? 'bg-peach text-white' : 'text-cocoa-700 hover:text-peach'
              }`}
            >
              {k === 'map' ? 'Map' : 'Table'}
            </button>
          ))}
        </div>

        <div className="overflow-hidden rounded-xl border border-cream-300 bg-white">
          {rendered && rendered.kind === kind ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={rendered.url}
              alt={kind === 'map' ? "Map of Hijodeagua's Senate guesses" : "Table of Hijodeagua's Senate guesses"}
              className="block h-auto w-full"
            />
          ) : (
            <div className="flex aspect-[4/3] items-center justify-center text-sm text-cocoa-400">
              {error ? `Could not build the image (${error}).` : 'Building image…'}
            </div>
          )}
        </div>
        <p className="mt-1.5 text-[11px] text-cocoa-400">
          On a phone you can also press and hold the image to save it.
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {canShareFile && (
            <button type="button" onClick={share} disabled={!rendered} className={primary}>
              Share…
            </button>
          )}
          {canCopyImage && (
            <button type="button" onClick={copyImage} disabled={!rendered} className={canShareFile ? secondary : primary}>
              Copy image
            </button>
          )}
          <button type="button" onClick={download} disabled={!rendered} className={secondary}>
            Download PNG
          </button>
          <button type="button" onClick={copyText} className={secondary}>
            Copy as text
          </button>
          {status && (
            <span role="status" className="text-xs font-semibold text-stamp">
              {status}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
