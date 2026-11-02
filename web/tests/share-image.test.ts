import { describe, expect, it } from 'vitest';
import type { PredictionRaceView } from '@/app/lib/predictions-shared';
import { buildMapSvg, buildShareText, buildTableSvg, esc, fmtAsOf, matchupLine } from '@/app/lib/share-image';
import { readFileSync } from 'node:fs';
import {
  FILL,
  FILL_NOT_RACE,
  NOT_UP,
  SAFE_HOLDS,
  boardSummary,
  fmtNet,
  fmtSenateTotal,
  senateTotal,
  stateFill,
} from '@/app/lib/predictions-map';
import { marginBucket } from '@/app/lib/predictions-shared';

function race(p: Partial<PredictionRaceView> & { abbr: string; state: string }): PredictionRaceView {
  return {
    held_by: 'R',
    incumbent: null,
    open: false,
    dem_candidate: 'Dee Dem',
    rep_candidate: 'Rhea Rep',
    ind_candidate: null,
    pick: null,
    margin: null,
    note: '',
    model: { dem_candidate: 'Dee Dem', rep_candidate: 'Rhea Rep', poll_margin: 1, median_margin: 2.04, dem_win_prob: 0.61 },
    features: null,
    ...p,
  };
}

const RACES = [
  race({ abbr: 'ME', state: 'Maine', pick: 'R', margin: 2 }),
  race({ abbr: 'NC', state: 'North Carolina', pick: 'D', margin: 6.5 }),
  race({ abbr: 'NH', state: 'New Hampshire', held_by: 'D', pick: 'D', margin: 4 }),
  race({ abbr: 'NE', state: 'Nebraska', dem_candidate: null, ind_candidate: 'Dan Osborn', pick: 'I', margin: 1 }),
  race({ abbr: 'AK', state: 'Alaska', model: null }),
];

describe('boardSummary', () => {
  it('counts calls, pickups, independents and uncalled races', () => {
    const s = boardSummary(RACES);
    expect(s.picks).toEqual({ D: 2, R: 1, I: 1 });
    expect(s.flipsToD).toBe(1); // NC; NH is a hold
    expect(s.flipsToR).toBe(0);
    expect(s.indFlips).toBe(1);
    expect(s.uncalled).toBe(1);
    expect(s.net).toBe(1);
    expect(s.total).toBe(5);
  });

  it('formats net change', () => {
    expect(fmtNet(0)).toBe('±0');
    expect(fmtNet(6)).toBe('D+6');
    expect(fmtNet(-2)).toBe('R+2');
  });
});

describe('share images', () => {
  it('escapes markup and formats dates', () => {
    expect(esc(`A & B <c> "d"`)).toBe('A &amp; B &lt;c&gt; &quot;d&quot;');
    expect(fmtAsOf('2026-11-02')).toBe('Nov 2, 2026');
    expect(fmtAsOf('')).toBe('');
  });

  it('builds a map card with the stat boxes, every race label and the link', () => {
    const { svg, width, height } = buildMapSvg(RACES, '2026-11-02');
    expect(width).toBe(1200);
    expect(height).toBeGreaterThan(900);
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true);
    expect(svg.endsWith('</svg>')).toBe(true);
    for (const t of ['Called for Democrats', 'Called for Republicans', 'Net seat change', 'Still to call']) {
      expect(svg).toContain(t);
    }
    expect(svg).toContain('>D+1<'); // net change value
    expect(svg).toContain('1 to an independent');
    for (const r of RACES) expect(svg).toContain(`>${r.abbr}<`);
    expect(svg).toContain('>R+2.0<');
    expect(svg).toContain('url(#share-hatch)'); // Alaska has no guess
    expect(svg).toContain('whosyurgoat.app/election/predictions');
    expect(svg).toContain('as of Nov 2, 2026');
    expect(svg).not.toMatch(/&(?!amp;|lt;|gt;|quot;)/); // no raw ampersands
  });

  it('builds a table with one row per race, the model and the delta', () => {
    const { svg, height } = buildTableSvg(RACES, '2026-11-02');
    expect(height).toBeGreaterThan(400);
    for (const r of RACES) expect(svg).toContain(`>${r.state}<`);
    expect(svg).toContain('>D+6.5<');
    expect(svg).toContain('>D+2.0<'); // model median
    expect(svg).toContain('61% D');
    expect(svg).toContain('>+4.5<'); // NC: 6.5 − 2.04, rounded
    expect(svg).toContain('2 D · 1 R · 1 I · net D+1 · 1 still to call');
    expect(svg).not.toMatch(/&(?!amp;|lt;|gt;|quot;)/);
  });

  it('labels the model with I where the independent is the non-Republican side', () => {
    const ne = race({
      abbr: 'NE', state: 'Nebraska', dem_candidate: null, ind_candidate: 'Dan Osborn', pick: 'R', margin: 3,
      model: { dem_candidate: 'Dan Osborn', rep_candidate: 'Pete Ricketts', poll_margin: null, median_margin: 1.2, dem_win_prob: 0.55 },
    });
    const { svg } = buildTableSvg([ne], '2026-11-02');
    expect(svg).toContain('>I+1.2<');
    expect(svg).toContain('55% I');
    expect(svg).not.toContain('55% D');
  });

  it('shortens matchups to last names', () => {
    expect(matchupLine(RACES[0])).toBe('Dem (D) v. Rep (R)');
    expect(matchupLine(RACES[3])).toBe('Rep (R) v. Osborn (I)');
    expect(matchupLine(race({ abbr: 'X', state: 'X', dem_candidate: 'Bob Smith Jr.' }))).toBe('Smith (D) v. Rep (R)');
  });

  it('builds a text version for group chats', () => {
    const t = buildShareText(RACES, '2026-11-02');
    expect(t.split('\n')[0]).toBe("Hijodeagua's 2026 Senate guesses (as of Nov 2, 2026)");
    expect(t).toContain('ME  R+2.0');
    expect(t).toContain('AK  —');
    expect(t.trim().endsWith('https://whosyurgoat.app/election/predictions')).toBe(true);
  });
});


const config = JSON.parse(readFileSync(new URL('../../config/senate_2026.json', import.meta.url), 'utf-8')) as {
  dem_safe_seats: number;
  rep_safe_seats: number;
  competitive_races: { abbr: string; held_by: string }[];
};
const board = JSON.parse(readFileSync(new URL('../content/predictions.json', import.meta.url), 'utf-8')) as {
  races: { abbr: string; held_by: 'D' | 'R' | 'I' }[];
};

// The board as in Hijodeagua's screenshot: 10 D, 7 R.
const SCREENSHOT: Record<string, 'D' | 'R'> = {
  MN: 'D', MI: 'D', OH: 'D', KS: 'D', TX: 'D', NC: 'D', SC: 'D', GA: 'D', NH: 'D', AK: 'D',
  MT: 'R', NE: 'R', IA: 'R', MS: 'R', LA: 'R', FL: 'R', ME: 'R',
};

describe('safe holds and the Senate total', () => {
  it('matches the cycle config: the 18 races off the board, their parties, and the not-up seats', () => {
    const boardAbbrs = new Set(board.races.map((r) => r.abbr));
    const offBoard = config.competitive_races.filter((r) => !boardAbbrs.has(r.abbr));
    expect(Object.keys(SAFE_HOLDS).sort()).toEqual(offBoard.map((r) => r.abbr).sort());
    for (const r of offBoard) expect(SAFE_HOLDS[r.abbr]).toBe(r.held_by);
    expect(NOT_UP).toEqual({ D: config.dem_safe_seats, R: config.rep_safe_seats });
    expect(NOT_UP.D + NOT_UP.R + config.competitive_races.length).toBe(100);
    expect(board.races).toHaveLength(17);
  });

  it('colours safe holds as safe and only no-race states as "no race"', () => {
    expect(stateFill('CO', undefined, marginBucket, 'h')).toEqual({ kind: 'safe', fill: FILL.D.safe });
    expect(stateFill('VA', undefined, marginBucket, 'h').fill).toBe(FILL.D.safe);
    expect(stateFill('AL', undefined, marginBucket, 'h')).toEqual({ kind: 'safe', fill: FILL.R.safe });
    expect(stateFill('WY', undefined, marginBucket, 'h').fill).toBe(FILL.R.safe);
    for (const none of ['CA', 'NY', 'AZ', 'PA', 'WI', 'ND', 'UT']) {
      expect(stateFill(none, undefined, marginBucket, 'h')).toEqual({ kind: 'none', fill: FILL_NOT_RACE });
    }
    expect(stateFill('ME', { pick: 'R', margin: 2 }, marginBucket, 'h').fill).toBe(FILL.R.lean);
    expect(stateFill('ME', { pick: null, margin: null }, marginBucket, 'h').fill).toBe('h');
  });

  it('reads 53 D, 47 R for the screenshot board', () => {
    const races = board.races.map((r) => ({ held_by: r.held_by, pick: SCREENSHOT[r.abbr] }));
    expect(senateTotal(races)).toEqual({ D: 53, R: 47, I: 0, uncalled: 0 });
    expect(fmtSenateTotal(senateTotal(races))).toBe('Senate after these guesses: 53 D, 47 R');
  });

  it('counts independents separately and flags uncalled races', () => {
    const t = senateTotal([
      { held_by: 'R', pick: 'I' },
      { held_by: 'R', pick: 'D' },
      { held_by: 'R', pick: null },
    ]);
    expect(t).toEqual({ D: 44, R: 40, I: 1, uncalled: 1 });
    expect(fmtSenateTotal(t)).toBe('Senate after these guesses: 44 D, 40 R, 1 I, 1 still to call');
  });

  it('puts the safe holds, the legend and the total in the share images and text', () => {
    const races = RACES;
    const map = buildMapSvg(races, '2026-11-02').svg;
    expect(map).toContain(`fill="${FILL.D.safe}"`);
    expect(map).toContain(`fill="${FILL.R.safe}"`);
    expect(map).toContain('safe hold');
    expect(map).toContain('no 2026 race');
    expect(map).toContain('Senate after these guesses: ');
    expect(map).toMatch(/>45 D<\/tspan>/); // 34 + 9 + NC, NH
    expect(map).toMatch(/>41 R<\/tspan>/); // 31 + 9 + ME
    const table = buildTableSvg(races, '2026-11-02').svg;
    expect(table).toContain('Senate after these guesses: ');
    expect(buildShareText(races, '2026-11-02').split('\n')[1]).toBe(
      'Senate after these guesses: 45 D, 41 R, 1 I, 1 still to call',
    );
  });
});
