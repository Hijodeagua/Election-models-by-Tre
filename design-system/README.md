// Election Oracle UI Kit — shared theme constants + SVG charts
// Warm "Policy & Peaches" editorial direction (cream paper, peach accent,
// DM Serif Display headlines) with crisp editorial polling charts.

const T = {
  bg: '#faf8f5',
  surface: '#ffffff',
  sunken: '#f0ebe5',
  panel: '#f5f0ea',
  border: '#e8ddd5',
  ink: '#2c1810',
  cocoa700: '#5c3d2a',
  cocoa500: '#7c5a52',
  cocoa400: '#a0736a',
  cocoa300: '#c9b3a8',
  peach: '#c1533d',
  peachHover: '#a8442f',
  peachWash: '#fdf0ed',
  peachBorder: '#ecc3b8',
  green: '#4e8c3f',
  greenWash: '#eef5ea',
  dem: '#2563eb',
  demWash: '#eff6ff',
  demBorder: '#dbeafe',
  rep: '#dc2626',
  repWash: '#fdeeee',
  repBorder: '#f6cccc',
  serif: "'DM Serif Display', Georgia, serif",
  sans: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
};

const LOGO = '../../assets/logo-policy-peaches.webp';

// ── helpers ──────────────────────────────────────────────────────────────────
function smoothPath(pts) {
  if (pts.length < 2) return '';
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[i + 1];
    const cx = (x0 + x1) / 2;
    d += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`;
  }
  return d;
}

// ── Approval trend: approve vs disapprove with CI band ───────────────────────
function ApprovalChart({ height = 230 }) {
  const W = 720, H = 230, padL = 34, padR = 52, padB = 22, padT = 8;
  const lo = 35, hi = 56;
  const y = v => padT + (hi - v) / (hi - lo) * (H - padT - padB);
  const xs = n => padL + (n / 14) * (W - padL - padR);
  const approve = [45.8, 45.2, 44.1, 43.4, 42.8, 41.9, 41.1, 40.5, 40.8, 41.3, 40.9, 40.4, 40.2, 40.6, 40.3];
  const disapp = [47.9, 48.4, 49.1, 49.8, 50.2, 50.9, 51.4, 51.8, 51.5, 51.1, 51.6, 52.0, 52.3, 51.9, 52.1];
  const aPts = approve.map((v, i) => [xs(i), y(v)]);
  const dPts = disapp.map((v, i) => [xs(i), y(v)]);
  const band = 1.1;
  const bTop = approve.map((v, i) => [xs(i), y(v + band)]);
  const bBot = approve.map((v, i) => [xs(i), y(v - band)]).reverse();
  const bandD = `${smoothPath(bTop)} L${bBot[0][0]},${bBot[0][1]} ${smoothPath(bBot).slice(1)} Z`;
  const grid = [40, 45, 50, 55];
  const ticks = [["Jan '25", 0], ['Apr', 2.3], ['Jul', 4.7], ['Oct', 7], ["Jan '26", 9.3], ['Apr', 11.7], ['May', 14]];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height, display: 'block' }}>
      {grid.map(v => (
        <g key={v}>
          <line x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke={T.border} strokeWidth="1" strokeDasharray="3,4" />
          <text x={padL - 7} y={y(v) + 3.5} textAnchor="end" fontSize="10" fill={T.cocoa400} fontFamily={T.sans}>{v}</text>
        </g>
      ))}
      <path d={bandD} fill="rgba(37,99,235,0.10)" />
      <path d={smoothPath(dPts)} fill="none" stroke={T.rep} strokeWidth="2.5" strokeLinecap="round" />
      <path d={smoothPath(aPts)} fill="none" stroke={T.dem} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx={aPts[14][0]} cy={aPts[14][1]} r="4.5" fill={T.dem} stroke="#fff" strokeWidth="1.5" />
      <circle cx={dPts[14][0]} cy={dPts[14][1]} r="4.5" fill={T.rep} stroke="#fff" strokeWidth="1.5" />
      <text x={aPts[14][0] + 9} y={aPts[14][1] + 4} fontSize="12" fill={T.dem} fontWeight="700" fontFamily={T.sans}>40.3</text>
      <text x={dPts[14][0] + 9} y={dPts[14][1] + 4} fontSize="12" fill={T.rep} fontWeight="700" fontFamily={T.sans}>52.1</text>
      {ticks.map(([label, n], i) => (
        <text key={i} x={xs(n)} y={H - 5} fontSize="10" fill={T.cocoa400} textAnchor="middle" fontFamily={T.sans}>{label}</text>
      ))}
    </svg>
  );
}

// ── Generic ballot margin over time (shaded lead area) ───────────────────────
function BallotChart({ height = 200 }) {
  const W = 720, H = 200, padL = 30, padR = 40, padB = 22, padT = 10;
  const lo = -2, hi = 9;
  const y = v => padT + (hi - v) / (hi - lo) * (H - padT - padB);
  const xs = n => padL + (n / 12) * (W - padL - padR);
  const margin = [2.1, 2.8, 3.3, 3.9, 4.4, 4.9, 5.6, 6.1, 5.7, 5.2, 5.0, 5.1, 5.3];
  const pts = margin.map((v, i) => [xs(i), y(v)]);
  const area = `${smoothPath(pts)} L${xs(12)},${y(0)} L${xs(0)},${y(0)} Z`;
  const grid = [0, 3, 6, 9];
  const ticks = [["'25 Q1", 0], ['Q2', 2.5], ['Q3', 5], ['Q4', 7.5], ["'26 Q1", 10], ['now', 12]];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height, display: 'block' }}>
      {grid.map(v => (
        <g key={v}>
          <line x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke={v === 0 ? T.cocoa300 : T.border} strokeWidth={v === 0 ? 1.3 : 1} strokeDasharray={v === 0 ? 'none' : '3,4'} />
          <text x={padL - 6} y={y(v) + 3.5} textAnchor="end" fontSize="10" fill={T.cocoa400} fontFamily={T.sans}>{v > 0 ? `D+${v}` : v}</text>
        </g>
      ))}
      <path d={area} fill="rgba(37,99,235,0.09)" />
      <path d={smoothPath(pts)} fill="none" stroke={T.dem} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx={pts[12][0]} cy={pts[12][1]} r="4.5" fill={T.dem} stroke="#fff" strokeWidth="1.5" />
      <text x={pts[12][0] - 6} y={pts[12][1] - 10} fontSize="12" fill={T.dem} fontWeight="700" textAnchor="end" fontFamily={T.sans}>D+5.3</text>
      {ticks.map(([label, n], i) => (
        <text key={i} x={xs(n)} y={H - 5} fontSize="10" fill={T.cocoa400} textAnchor="middle" fontFamily={T.sans}>{label}</text>
      ))}
    </svg>
  );
}

// ── Horizontal seat bar (D | tossup | R) with 218 majority marker ────────────
function SeatBar({ dem = 247, rep = 188, total = 435, majority = 218 }) {
  const tossup = total - dem - rep;
  const pct = n => (n / total) * 100;
  return (
    <div>
      <div style={{ display: 'flex', height: 30, borderRadius: 6, overflow: 'hidden', position: 'relative', border: `1px solid ${T.border}` }}>
        <div style={{ width: `${pct(dem)}%`, background: T.dem, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 12, fontWeight: 700, fontFamily: T.sans }}>{dem}</div>
        {tossup > 0 && <div style={{ width: `${pct(tossup)}%`, background: T.sunken }}></div>}
        <div style={{ width: `${pct(rep)}%`, background: T.rep, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 12, fontWeight: 700, fontFamily: T.sans }}>{rep}</div>
        <div style={{ position: 'absolute', left: `${pct(majority)}%`, top: -4, bottom: -4, width: 2, background: T.ink }}></div>
      </div>
      <div style={{ position: 'relative', height: 16, marginTop: 2 }}>
        <span style={{ position: 'absolute', left: `${pct(majority)}%`, transform: 'translateX(-50%)', fontSize: 9.5, color: T.cocoa500, fontFamily: T.sans }}>218 to control</span>
      </div>
    </div>
  );
}

// ── Forecast histogram of simulated seat outcomes ────────────────────────────
function ForecastHistogram({ height = 150 }) {
  // distribution of simulated Dem Senate seats, centered ~52
  const bars = [
    { s: 48, p: 2 }, { s: 49, p: 5 }, { s: 50, p: 10 }, { s: 51, p: 17 },
    { s: 52, p: 24 }, { s: 53, p: 20 }, { s: 54, p: 12 }, { s: 55, p: 6 }, { s: 56, p: 4 },
  ];
  const max = Math.max(...bars.map(b => b.p));
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height, padding: '0 4px' }}>
        {bars.map(b => {
          const control = b.s >= 51;
          return (
            <div key={b.s} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{ width: '100%', height: (b.p / max) * (height - 22), background: control ? T.dem : T.cocoa300, borderRadius: '4px 4px 0 0', opacity: b.s === 52 ? 1 : 0.82 }}></div>
              <span style={{ fontSize: 9.5, color: T.cocoa400, fontFamily: T.sans }}>{b.s}</span>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 10.5, color: T.cocoa500, fontFamily: T.sans, marginTop: 6, textAlign: 'center' }}>
        Simulated Democratic Senate seats · <strong style={{ color: T.dem }}>51+ = control</strong> in 78% of runs
      </div>
    </div>
  );
}

// ── Probability split bar ────────────────────────────────────────────────────
function ProbSplit({ demPct = 78, label = 'Chamber control' }) {
  const repPct = 100 - demPct;
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontFamily: T.sans, marginBottom: 6 }}>
        <span style={{ color: T.dem, fontWeight: 700 }}>Democrats {demPct}%</span>
        <span style={{ color: T.cocoa400 }}>{label}</span>
        <span style={{ color: T.rep, fontWeight: 700 }}>Republicans {repPct}%</span>
      </div>
      <div style={{ display: 'flex', height: 14, borderRadius: 7, overflow: 'hidden' }}>
        <div style={{ width: `${demPct}%`, background: T.dem }}></div>
        <div style={{ width: `${repPct}%`, background: T.rep }}></div>
      </div>
    </div>
  );
}

// ── Tiny sparkline for senate race cards ─────────────────────────────────────
function Sparkline({ data, color, width = 96, height = 30 }) {
  const min = Math.min(...data), max = Math.max(...data);
  const rng = max - min || 1;
  const pts = data.map((v, i) => [(i / (data.length - 1)) * width, height - 3 - ((v - min) / rng) * (height - 6)]);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width, height }}>
      <path d={smoothPath(pts)} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.5" fill={color} />
    </svg>
  );
}

Object.assign(window, {
  EO_T: T, EO_LOGO: LOGO,
  ApprovalChart, BallotChart, SeatBar, ForecastHistogram, ProbSplit, Sparkline,
});
