import { describe, expect, it } from 'vitest';
import { boardSummary, fmtNet } from '@/app/lib/predictions-map';
import type { PredictionRaceView } from '@/app/lib/predictions-shared';
import { buildMapSvg, buildShareText, buildTableSvg, esc, fmtAsOf, matchupLine } from '@/app/lib/share-image';

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
