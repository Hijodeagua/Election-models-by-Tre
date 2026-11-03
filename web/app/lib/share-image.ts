// Shareable PNGs of Hijodeagua's board: the map card (stat boxes, map,
// legend) and the race table. Each is drawn as a standalone SVG string — no
// page CSS, web fonts or network — and rasterised on a canvas in the browser.
// The SVG builders are pure so tests can check them without a DOM.

import { fmtMargin, fmtProb } from '@/app/lib/format';
import { ADD_GUESSES_URL } from '@/app/lib/guesses-shared';
import {
  FILL,
  FILL_NOT_RACE,
  FILL_NO_PICK,
  LABEL_ADJUST,
  boardSummary,
  fmtNet,
  fmtSenateTotal,
  fmtWinnerMargin,
  senateTotal,
  stateFill,
} from '@/app/lib/predictions-map';
import { marginBucket, toDemMargin, type Party, type PredictionRaceView } from '@/app/lib/predictions-shared';
import { US_MAP_VIEWBOX, US_STATES, US_STATE_BORDERS } from '@/app/lib/us-states-paths';

export const SHARE_URL = 'whosyurgoat.app/election/predictions';
export const SHARE_WIDTH = 1200;

const C = {
  bg: '#faf8f5',
  panel: '#ffffff',
  line: '#e8ddd5',
  ink: '#2c1810',
  cocoa700: '#5c3d2a',
  cocoa500: '#7c5a52',
  cocoa400: '#a0736a',
  cocoa300: '#c9b3a8',
  peach: '#c1533d',
  peachWash: '#fdf0ed',
  peachBorder: '#ecc3b8',
  dem: '#2563eb',
  demWash: '#eff6ff',
  demBorder: '#dbeafe',
  rep: '#dc2626',
  repWash: '#fdeeee',
  repBorder: '#f6cccc',
  stamp: '#4e8c3f',
};
const SERIF = "Georgia, 'Times New Roman', serif";
const SANS = "-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif";
const PARTY_INK: Record<Party, string> = { D: C.dem, R: C.rep, I: C.stamp };

export function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function fmtAsOf(asOf: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(asOf);
  if (!m) return asOf;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${months[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
}

function text(
  x: number,
  y: number,
  body: string,
  o: { size: number; fill: string; weight?: number; anchor?: 'start' | 'middle' | 'end'; font?: string; spacing?: number },
): string {
  return `<text x="${x}" y="${y}" font-family="${o.font ?? SANS}" font-size="${o.size}" font-weight="${
    o.weight ?? 400
  }" fill="${o.fill}" text-anchor="${o.anchor ?? 'start'}"${
    o.spacing ? ` letter-spacing="${o.spacing}"` : ''
  }>${esc(body)}</text>`;
}

function header(title: string, asOf: string): string {
  return [
    text(48, 64, "HIJODEAGUA'S GUESSES", { size: 17, fill: C.peach, weight: 700, spacing: 2 }),
    text(48, 112, title, { size: 42, fill: C.ink, font: SERIF }),
    text(SHARE_WIDTH - 48, 64, asOf ? `as of ${fmtAsOf(asOf)}` : '', {
      size: 17,
      fill: C.cocoa400,
      anchor: 'end',
    }),
  ].join('');
}

function footer(y: number, note: string): string {
  return [
    `<line x1="48" y1="${y - 30}" x2="${SHARE_WIDTH - 48}" y2="${y - 30}" stroke="${C.line}" stroke-width="1.5"/>`,
    text(48, y, SHARE_URL, { size: 18, fill: C.peach, weight: 700 }),
    text(SHARE_WIDTH - 48, y, note, { size: 16, fill: C.cocoa400, anchor: 'end' }),
  ].join('');
}

function statCard(
  x: number,
  y: number,
  w: number,
  h: number,
  tone: 'dem' | 'rep' | 'ink' | 'peach',
  label: string,
  value: string,
  sub: string,
): string {
  const tones = {
    dem: [C.demWash, C.demBorder, C.dem],
    rep: [C.repWash, C.repBorder, C.rep],
    ink: [C.panel, C.line, C.cocoa700],
    peach: [C.peachWash, C.peachBorder, C.peach],
  } as const;
  const [bg, border, ink] = tones[tone];
  return [
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="16" fill="${bg}" stroke="${border}" stroke-width="2"/>`,
    text(x + 22, y + 36, label, { size: 17, fill: C.cocoa400 }),
    text(x + 22, y + 90, value, { size: 50, fill: ink, font: SERIF }),
    text(x + 22, y + 122, sub, { size: 15, fill: C.cocoa400 }),
  ].join('');
}

function legend(x: number, y: number): string {
  const sw = (cx: number, fill: string, hatched = false) =>
    `<rect x="${cx}" y="${y - 14}" width="18" height="18" rx="4" fill="${
      hatched ? 'url(#share-hatch)' : fill
    }" stroke="${C.line}" stroke-width="1.5"/>`;
  let cx = x;
  const parts: string[] = [];
  for (const f of [FILL.D.safe, FILL.D.likely, FILL.D.lean]) {
    parts.push(sw(cx, f));
    cx += 24;
  }
  parts.push(text(cx + 4, y, 'D', { size: 16, fill: C.dem, weight: 700 }));
  parts.push(text(cx + 20, y, 'safe · likely · lean', { size: 16, fill: C.cocoa500 }));
  cx += 178;
  for (const f of [FILL.R.lean, FILL.R.likely, FILL.R.safe]) {
    parts.push(sw(cx, f));
    cx += 24;
  }
  parts.push(text(cx + 4, y, 'R', { size: 16, fill: C.rep, weight: 700 }));
  parts.push(text(cx + 20, y, 'lean · likely · safe', { size: 16, fill: C.cocoa500 }));
  cx += 178;
  parts.push(sw(cx, FILL.I.likely));
  parts.push(text(cx + 26, y, 'I', { size: 16, fill: C.stamp, weight: 700 }));
  cx += 48;
  parts.push(sw(cx, FILL_NO_PICK, true));
  parts.push(text(cx + 26, y, 'no guess yet', { size: 16, fill: C.cocoa500 }));
  cx += 132;
  parts.push(sw(cx, FILL.D.safe));
  parts.push(sw(cx + 24, FILL.R.safe));
  parts.push(text(cx + 50, y, 'safe hold', { size: 16, fill: C.cocoa500 }));
  cx += 132;
  parts.push(sw(cx, FILL_NOT_RACE));
  parts.push(text(cx + 26, y, 'no 2026 race', { size: 16, fill: C.cocoa500 }));
  return parts.join('');
}

function mapLayer(races: PredictionRaceView[]): string {
  const byAbbr = new Map(races.map((r) => [r.abbr, r]));
  const out: string[] = [];
  for (const [abbr, s] of Object.entries(US_STATES)) {
    if (!byAbbr.has(abbr)) out.push(`<path d="${s.d}" fill="${stateFill(abbr, undefined, marginBucket, '').fill}"/>`);
  }
  out.push(`<path d="${US_STATE_BORDERS}" fill="none" stroke="#ffffff" stroke-width="1"/>`);
  for (const r of races) {
    const s = US_STATES[r.abbr];
    if (!s) continue;
    const fill = stateFill(r.abbr, r, marginBucket, 'url(#share-hatch)').fill;
    out.push(`<path d="${s.d}" fill="${fill}" stroke="#ffffff" stroke-width="1" stroke-linejoin="round"/>`);
  }
  for (const r of races) {
    const s = US_STATES[r.abbr];
    if (!s) continue;
    const adj = LABEL_ADJUST[r.abbr] ?? { dx: 0, dy: 0 };
    const x = s.cx + adj.dx;
    const y = s.cy + adj.dy;
    const onLight = r.pick == null || marginBucket(r.margin) === 'lean' || adj.leader;
    const ink = onLight ? C.ink : '#ffffff';
    if (adj.leader) {
      out.push(`<line x1="${s.cx}" y1="${s.cy}" x2="${x - 14}" y2="${y - 4}" stroke="${C.cocoa500}" stroke-width="1"/>`);
    }
    out.push(text(x, y - 2, r.abbr, { size: 13, fill: ink, weight: 700, anchor: 'middle', font: SERIF }));
    out.push(
      text(x, y + 11, r.pick == null ? '—' : fmtWinnerMargin(r.pick, r.margin), {
        size: 10.5,
        fill: ink,
        weight: 600,
        anchor: 'middle',
        font: SERIF,
      }),
    );
  }
  return out.join('');
}

// One <text> with coloured tspans so the counts carry party colour.
function senateTotalText(x: number, y: number, t: ReturnType<typeof senateTotal>, size: number): string {
  const span = (body: string, fill: string, weight = 700) =>
    `<tspan fill="${fill}" font-weight="${weight}">${esc(body)}</tspan>`;
  const bits = [span('Senate after these guesses: ', C.ink, 400), span(`${t.D} D`, C.dem), span(', ', C.ink, 400), span(`${t.R} R`, C.rep)];
  if (t.I) bits.push(span(', ', C.ink, 400), span(`${t.I} I`, C.stamp));
  if (t.uncalled) bits.push(span(`, ${t.uncalled} still to call`, C.cocoa400, 400));
  return `<text x="${x}" y="${y}" font-family="${SERIF}" font-size="${size}">${bits.join('')}</text>`;
}

const HATCH = `<defs><pattern id="share-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="${FILL_NO_PICK}"/><line x1="0" y1="0" x2="0" y2="6" stroke="#b9a99f" stroke-width="1.5"/></pattern></defs>`;

export interface ShareImage {
  svg: string;
  width: number;
  height: number;
}

export function buildMapSvg(races: PredictionRaceView[], asOf: string): ShareImage {
  const W = SHARE_WIDTH;
  const sum = boardSummary(races);
  const cardsY = 148;
  const gap = 16;
  const cardW = (W - 96 - gap * 3) / 4;
  const cardH = 140;
  const cards = [
    statCard(48, cardsY, cardW, cardH, 'dem', 'Called for Democrats', String(sum.picks.D),
      sum.flipsToD > 0 ? `${sum.flipsToD} pickup${sum.flipsToD === 1 ? '' : 's'}` : 'holds only'),
    statCard(48 + (cardW + gap), cardsY, cardW, cardH, 'rep', 'Called for Republicans', String(sum.picks.R),
      sum.flipsToR > 0 ? `${sum.flipsToR} pickup${sum.flipsToR === 1 ? '' : 's'}` : 'holds only'),
    statCard(48 + (cardW + gap) * 2, cardsY, cardW, cardH,
      sum.net > 0 ? 'dem' : sum.net < 0 ? 'rep' : 'ink', 'Net seat change', fmtNet(sum.net),
      sum.indFlips > 0 ? `${sum.indFlips} to an independent` : `across ${sum.total} races`),
    statCard(48 + (cardW + gap) * 3, cardsY, cardW, cardH, 'peach', 'Still to call', String(sum.uncalled),
      sum.uncalled === 0 ? 'every race has a guess' : 'hatched on the map'),
  ].join('');

  const total = senateTotal(races);
  const totalY = cardsY + cardH + 20;
  const totalH = 64;
  const totalStrip = [
    `<rect x="48" y="${totalY}" width="${W - 96}" height="${totalH}" rx="14" fill="${C.panel}" stroke="${C.line}" stroke-width="2"/>`,
    senateTotalText(72, totalY + 42, total, 28),
    text(W - 72, totalY + 40, 'not-up seats + safe holds + the board', { size: 15, fill: C.cocoa400, anchor: 'end' }),
  ].join('');
  const panelY = totalY + totalH + 20;
  const [, , vbW, vbH] = US_MAP_VIEWBOX.split(' ').map(Number);
  const mapW = W - 96 - 48;
  const mapH = Math.round((mapW * vbH) / vbW);
  const legendY = panelY + 44;
  const mapY = legendY + 24;
  const panelH = mapH + (mapY - panelY) + 24;
  const footY = panelY + panelH + 64;
  const H = footY + 36;

  const svg = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`,
    HATCH,
    `<rect width="${W}" height="${H}" fill="${C.bg}"/>`,
    header('2026 Senate map', asOf),
    cards,
    totalStrip,
    `<rect x="48" y="${panelY}" width="${W - 96}" height="${panelH}" rx="18" fill="${C.panel}" stroke="${C.line}" stroke-width="2"/>`,
    legend(72, legendY),
    `<svg x="72" y="${mapY}" width="${mapW}" height="${mapH}" viewBox="${US_MAP_VIEWBOX}">${mapLayer(races)}</svg>`,
    footer(footY, 'Not the model — a human guess'),
    '</svg>',
  ].join('');
  return { svg, width: W, height: H };
}

function lastName(name: string | null): string | null {
  if (!name) return null;
  const parts = name.replace(/\s+(Jr\.?|Sr\.?|II|III|IV)$/i, '').trim().split(/\s+/);
  return parts[parts.length - 1] ?? name;
}

export function matchupLine(r: PredictionRaceView): string {
  const bits: string[] = [];
  if (r.dem_candidate) bits.push(`${lastName(r.dem_candidate)} (D)`);
  if (r.rep_candidate) bits.push(`${lastName(r.rep_candidate)} (R)`);
  if (r.ind_candidate) bits.push(`${lastName(r.ind_candidate)} (I)`);
  return bits.join(' v. ');
}

export function buildTableSvg(races: PredictionRaceView[], asOf: string): ShareImage {
  const W = SHARE_WIDTH;
  const sum = boardSummary(races);
  const rowH = 46;
  const headY = 236;
  const firstRowY = headY + 22;
  const tableBottom = firstRowY + rowH * races.length;
  const footY = tableBottom + 76;
  const H = footY + 36;
  const col = { state: 72, held: 300, matchup: 372, guess: 860, model: 1020, delta: W - 72 };

  const rows: string[] = [];
  races.forEach((r, i) => {
    const y = firstRowY + rowH * i;
    if (i % 2 === 1) rows.push(`<rect x="48" y="${y}" width="${W - 96}" height="${rowH}" fill="${C.bg}"/>`);
    const base = y + 30;
    rows.push(text(col.state, base, r.state, { size: 19, fill: C.cocoa700, weight: 600 }));
    rows.push(text(col.held, base, r.held_by, { size: 18, fill: PARTY_INK[r.held_by], weight: 700 }));
    rows.push(text(col.matchup, base, matchupLine(r), { size: 16, fill: C.cocoa500 }));
    rows.push(
      text(col.guess, base, r.pick ? fmtWinnerMargin(r.pick, r.margin) : '—', {
        size: 19,
        fill: r.pick ? PARTY_INK[r.pick] : C.cocoa300,
        weight: 700,
        anchor: 'end',
      }),
    );
    const med = r.model?.median_margin ?? null;
    const prob = r.model?.dem_win_prob ?? null;
    // Where the independent is the simulation's non-Republican side (NE, MT),
    // its "D" share and positive margins belong to the independent.
    const side = r.ind_candidate && r.model?.dem_candidate === r.ind_candidate ? 'I' : 'D';
    const modelTxt = med == null ? '—' : side === 'I' && med > 0 ? fmtMargin(med).replace(/^D/, 'I') : fmtMargin(med);
    rows.push(
      text(col.model, base, modelTxt, {
        size: 18,
        fill: med == null ? C.cocoa300 : med > 0 ? PARTY_INK[side] : med < 0 ? C.rep : C.cocoa700,
        weight: 600,
        anchor: 'end',
      }),
    );
    if (prob != null) {
      rows.push(text(col.model + 8, base, `${fmtProb(prob)} ${side}`, { size: 13, fill: C.cocoa400 }));
    }
    const mine = toDemMargin(r.pick, r.margin);
    const delta = mine != null && med != null ? mine - med : null;
    rows.push(
      text(col.delta, base, delta == null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(1)}`, {
        size: 18,
        fill: delta == null ? C.cocoa300 : Math.abs(delta) < 0.05 ? C.cocoa700 : delta > 0 ? C.dem : C.rep,
        anchor: 'end',
      }),
    );
  });

  const summary = `${sum.picks.D} D · ${sum.picks.R} R${sum.picks.I ? ` · ${sum.picks.I} I` : ''} · net ${fmtNet(
    sum.net,
  )}${sum.uncalled ? ` · ${sum.uncalled} still to call` : ''}`;

  const svg = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`,
    `<rect width="${W}" height="${H}" fill="${C.bg}"/>`,
    header('2026 Senate guesses', asOf),
    senateTotalText(48, 154, senateTotal(races), 26),
    text(48, 188, `Board: ${summary}`, { size: 18, fill: C.cocoa500 }),
    `<rect x="48" y="${headY - 24}" width="${W - 96}" height="${tableBottom - headY + 32}" rx="16" fill="${C.panel}" stroke="${C.line}" stroke-width="2"/>`,
    text(col.state, headY + 6, 'STATE', { size: 13, fill: C.cocoa400, weight: 700, spacing: 1 }),
    text(col.held, headY + 6, 'HELD', { size: 13, fill: C.cocoa400, weight: 700, spacing: 1 }),
    text(col.matchup, headY + 6, 'MATCHUP', { size: 13, fill: C.cocoa400, weight: 700, spacing: 1 }),
    text(col.guess, headY + 6, 'GUESS', { size: 13, fill: C.cocoa400, weight: 700, spacing: 1, anchor: 'end' }),
    text(col.model, headY + 6, 'MODEL', { size: 13, fill: C.cocoa400, weight: 700, spacing: 1, anchor: 'end' }),
    text(col.delta, headY + 6, 'Δ VS MODEL', { size: 13, fill: C.cocoa400, weight: 700, spacing: 1, anchor: 'end' }),
    rows.join(''),
    footer(footY, 'Model = simulation median margin · Δ = guess minus model'),
    '</svg>',
  ].join('');
  return { svg, width: W, height: H };
}

// Plain-text version for group chats.
export function buildShareText(races: PredictionRaceView[], asOf: string): string {
  const sum = boardSummary(races);
  const lines = [
    `Hijodeagua's 2026 Senate guesses${asOf ? ` (as of ${fmtAsOf(asOf)})` : ''}`,
    fmtSenateTotal(senateTotal(races)),
    `Board: ${sum.picks.D} D · ${sum.picks.R} R${sum.picks.I ? ` · ${sum.picks.I} I` : ''} · net ${fmtNet(sum.net)}`,
    '',
    ...races.map((r) => `${r.abbr}  ${r.pick ? fmtWinnerMargin(r.pick, r.margin) : '—'}`),
    '',
    `https://${SHARE_URL}`,
    `Add your own guesses: ${ADD_GUESSES_URL}`,
  ];
  return lines.join('\n');
}

// Browser only: rasterise an SVG string to a PNG blob at `scale`x.
export async function svgToPng(img: ShareImage, scale = 2): Promise<Blob> {
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(img.svg)}`;
  const el = new Image();
  el.decoding = 'async';
  await new Promise<void>((resolve, reject) => {
    el.onload = () => resolve();
    el.onerror = () => reject(new Error('could not render the image'));
    el.src = url;
  });
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas unavailable');
  ctx.drawImage(el, 0, 0, canvas.width, canvas.height);
  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('could not encode PNG'))), 'image/png'),
  );
}
