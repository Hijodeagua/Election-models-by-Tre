<!-- @dsCard group="Election Tracker" viewport="1040x860" name="Election Tracker — Interactive Site" -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Election Oracle — Policy &amp; Peaches</title>
  <link rel="stylesheet" href="../../styles.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/react@18.3.1/umd/react.development.js" integrity="sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L" crossorigin="anonymous"></script>
  <script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" integrity="sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm" crossorigin="anonymous"></script>
  <script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" integrity="sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y" crossorigin="anonymous"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { background: #faf8f5; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    ::selection { background: #fbe0d9; }
  </style>
</head>
<body>
  <div id="root"></div>

  <!-- NOTE: this file is assembled from theme.jsx + layout.jsx + screens.jsx (the
       factored source). Modules are inlined here because the preview sandbox gates
       external XHR sub-resource fetches. Edit the .jsx sources, then re-bundle. -->

  <script type="text/babel">
// ===== theme.jsx =====
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

  </script>

  <script type="text/babel">
// ===== layout.jsx =====
// Election Oracle UI Kit — layout shell: header, footer, shared primitives
const { EO_T: TT, EO_LOGO: LOGO_SRC } = window;

const NAV = [
  { id: 'approval', label: 'Approval' },
  { id: 'ballot', label: 'Generic Ballot' },
  { id: 'senate', label: 'Senate' },
  { id: 'forecast', label: 'Senate Forecast' },
  { id: 'methodology', label: 'Methodology' },
];

// Sticky full-width banner header that condenses on scroll
function Header({ active, onNav, scrolled }) {
  return (
    <header style={{ position: 'sticky', top: 0, zIndex: 50, background: 'rgba(250,248,245,0.88)', backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)', borderBottom: `1px solid ${TT.border}`, boxShadow: scrolled ? '0 6px 20px -16px rgba(44,24,16,0.5)' : 'none', transition: 'box-shadow 200ms ease' }}>
      <div style={{ height: 3, background: TT.peach }}></div>
      <div style={{ maxWidth: 1040, margin: '0 auto', padding: '0 24px' }}>
        {/* Brand row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: scrolled ? 56 : 78, transition: 'height 200ms ease' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 13 }}>
            <img src={LOGO_SRC} alt="Policy & Peaches" style={{ height: scrolled ? 38 : 52, width: scrolled ? 38 : 52, objectFit: 'contain', transition: 'all 200ms ease', mixBlendMode: 'multiply' }} />
            <div>
              <div style={{ fontFamily: TT.serif, fontSize: scrolled ? 19 : 23, color: TT.ink, lineHeight: 1, transition: 'font-size 200ms ease' }}>Election&nbsp;Oracle</div>
              {!scrolled && <div style={{ fontSize: 10.5, color: TT.cocoa400, marginTop: 3, letterSpacing: '0.02em' }}>by Policy &amp; Peaches · <em>a tracker, not a crystal ball</em></div>}
            </div>
          </div>
          <a href="#" onClick={e => e.preventDefault()} style={{ fontSize: 12.5, fontWeight: 600, color: '#fff', background: TT.peach, padding: '8px 15px', borderRadius: 7, textDecoration: 'none', fontFamily: TT.sans, whiteSpace: 'nowrap' }}>Subscribe</a>
        </div>
        {/* Nav row */}
        <nav style={{ display: 'flex', gap: 2, borderTop: `1px solid ${TT.border}`, paddingTop: 0 }}>
          {NAV.map(n => {
            const on = active === n.id;
            return (
              <button key={n.id} onClick={() => onNav(n.id)}
                style={{ background: 'transparent', border: 'none', borderBottom: on ? `2px solid ${TT.peach}` : '2px solid transparent', color: on ? TT.ink : TT.cocoa500, padding: '11px 13px', marginBottom: -1, fontSize: 13, fontWeight: on ? 600 : 500, cursor: 'pointer', fontFamily: TT.sans, transition: 'color 120ms ease' }}
                onMouseEnter={e => { if (!on) e.currentTarget.style.color = TT.ink; }}
                onMouseLeave={e => { if (!on) e.currentTarget.style.color = TT.cocoa500; }}>
                {n.label}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer style={{ borderTop: `1px solid ${TT.border}`, marginTop: 40, background: TT.panel }}>
      <div style={{ maxWidth: 1040, margin: '0 auto', padding: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <img src={LOGO_SRC} alt="" style={{ height: 30, width: 30, objectFit: 'contain', mixBlendMode: 'multiply' }} />
          <span style={{ fontSize: 11.5, color: TT.cocoa500, fontFamily: TT.sans }}>© 2026 Policy &amp; Peaches · Updated daily from public polling</span>
        </div>
        <div style={{ display: 'flex', gap: 16, fontSize: 11.5, fontFamily: TT.sans }}>
          {['Methodology', 'Data sources', 'Newsletter', 'About'].map(l => (
            <a key={l} href="#" onClick={e => e.preventDefault()} style={{ color: TT.peach, textDecoration: 'none' }}>{l}</a>
          ))}
        </div>
      </div>
    </footer>
  );
}

// ── shared primitives ────────────────────────────────────────────────────────
function PageHead({ kicker, title, sub }) {
  return (
    <div style={{ marginBottom: 18 }}>
      {kicker && <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.12em', color: TT.peach, fontWeight: 700, fontFamily: TT.sans, marginBottom: 7 }}>{kicker}</div>}
      <h1 style={{ fontFamily: TT.serif, fontSize: 34, color: TT.ink, lineHeight: 1.08, margin: 0, letterSpacing: '-0.01em' }}>{title}</h1>
      {sub && <p style={{ fontSize: 14, color: TT.cocoa500, marginTop: 8, fontFamily: TT.sans, maxWidth: 640, lineHeight: 1.5 }}>{sub}</p>}
    </div>
  );
}

function Panel({ title, legend, children, style }) {
  return (
    <div style={{ background: TT.surface, border: `1px solid ${TT.border}`, borderRadius: 12, padding: 18, ...style }}>
      {(title || legend) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          {title && <div style={{ fontSize: 11, fontWeight: 700, color: TT.cocoa400, textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: TT.sans }}>{title}</div>}
          {legend && <div style={{ display: 'flex', gap: 14 }}>{legend.map(l => (
            <span key={l.label} style={{ fontSize: 11, color: l.color, display: 'flex', alignItems: 'center', gap: 5, fontFamily: TT.sans }}>
              <span style={{ display: 'inline-block', width: 16, height: 3, background: l.color, borderRadius: 2 }}></span>{l.label}
            </span>
          ))}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

function StatCard({ label, value, tone = 'ink', sub }) {
  const map = {
    dem: { c: TT.dem, bg: TT.demWash, b: TT.demBorder },
    rep: { c: TT.rep, bg: TT.repWash, b: TT.repBorder },
    ink: { c: TT.cocoa700, bg: TT.surface, b: TT.border },
    peach: { c: TT.peach, bg: TT.peachWash, b: TT.peachBorder },
  }[tone];
  return (
    <div style={{ background: map.bg, border: `1px solid ${map.b}`, borderRadius: 12, padding: '16px 18px' }}>
      <div style={{ fontSize: 11.5, color: TT.cocoa400, fontFamily: TT.sans, marginBottom: 6, letterSpacing: '0.02em' }}>{label}</div>
      <div style={{ fontFamily: TT.serif, fontSize: 36, color: map.c, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: TT.cocoa400, fontFamily: TT.sans, marginTop: 6 }}>{sub}</div>}
    </div>
  );
}

function MetaStrip({ items }) {
  return (
    <div style={{ background: TT.sunken, borderRadius: 8, padding: '8px 14px', display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
      {items.map((it, i) => (
        <span key={i} style={{ fontSize: 11.5, color: TT.cocoa500, fontFamily: TT.sans }}>{it.k} <strong style={{ color: TT.cocoa700 }}>{it.v}</strong></span>
      ))}
    </div>
  );
}

function Pill({ children, tone = 'neutral', onClick, active }) {
  const tones = {
    neutral: { bg: '#f9f7f5', c: TT.cocoa500, b: TT.border },
    peach: { bg: TT.peachWash, c: TT.peach, b: TT.peachBorder },
    dem: { bg: TT.demWash, c: TT.dem, b: TT.demBorder },
    green: { bg: TT.greenWash, c: TT.green, b: '#cfe2c6' },
  };
  const s = active ? tones.peach : tones[tone];
  return (
    <button onClick={onClick} disabled={!onClick}
      style={{ background: s.bg, color: s.c, border: `1px solid ${s.b}`, borderRadius: 9999, padding: '3px 11px', fontSize: 11, fontWeight: 600, fontFamily: TT.sans, cursor: onClick ? 'pointer' : 'default' }}>
      {children}
    </button>
  );
}

Object.assign(window, { EO_NAV: NAV, Header, Footer, PageHead, Panel, StatCard, MetaStrip, Pill });

  </script>

  <script type="text/babel">
// ===== screens.jsx =====
// Election Oracle UI Kit — the five tracker screens
const {
  EO_T: S, PageHead, Panel, StatCard, MetaStrip, Pill,
  ApprovalChart, BallotChart, SeatBar, ForecastHistogram, ProbSplit, Sparkline,
} = window;

const grid3 = { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 };

// ── 1 · APPROVAL ─────────────────────────────────────────────────────────────
function ApprovalScreen() {
  return (
    <div>
      <PageHead kicker="Presidential Approval" title="Is the country buying what the President is selling?"
        sub="A weighted average of every public job-approval poll, smoothed with a state-space model that down-weights cheap online surveys and corrects for house effects." />
      <div style={grid3}>
        <StatCard label="Approve" value="40.3%" tone="dem" sub="[38.8 – 41.4]" />
        <StatCard label="Disapprove" value="52.1%" tone="rep" sub="[50.5 – 53.6]" />
        <StatCard label="Net approval" value="−11.8" tone="ink" sub="lowest since inauguration" />
      </div>
      <MetaStrip items={[{ k: 'Updated', v: 'May 24, 2026' }, { k: 'Polls in window', v: '683' }, { k: 'Model', v: 'state-space avg' }]} />
      <Panel title="Daily polling average · confidence band"
        legend={[{ label: 'Approve', color: S.dem }, { label: 'Disapprove', color: S.rep }]} style={{ marginBottom: 14 }}>
        <ApprovalChart />
      </Panel>
      <Panel title="The one-line read">
        <p style={{ fontFamily: S.serif, fontSize: 19, color: S.ink, lineHeight: 1.4, margin: 0 }}>
          Approval has drifted down about five points over the past year and has been flat-to-soft since winter — <span style={{ color: S.peach }}>underwater by double digits</span>, but not collapsing.
        </p>
      </Panel>
    </div>
  );
}

// ── 2 · GENERIC BALLOT ───────────────────────────────────────────────────────
function BallotScreen() {
  return (
    <div>
      <PageHead kicker="Generic Congressional Ballot" title="Which party do voters want running Congress?"
        sub="“If the election were held today, would you vote for the Democrat or the Republican in your district?” — averaged and translated into a rough seat estimate." />
      <div style={grid3}>
        <StatCard label="Democrats" value="46.4%" tone="dem" />
        <StatCard label="Republicans" value="41.1%" tone="rep" />
        <StatCard label="Democratic edge" value="D+5.3" tone="peach" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 14 }}>
        <Panel title="Generic ballot margin over time" style={{ marginBottom: 0 }}>
          <BallotChart />
        </Panel>
        <Panel title="Illustrative House seat split" style={{ marginBottom: 0 }}>
          <div style={{ display: 'flex', gap: 18, marginBottom: 18 }}>
            <div><div style={{ fontFamily: S.serif, fontSize: 38, color: S.dem, lineHeight: 1 }}>247</div><div style={{ fontSize: 11, color: S.cocoa500, fontFamily: S.sans }}>Democratic</div></div>
            <div><div style={{ fontFamily: S.serif, fontSize: 38, color: S.rep, lineHeight: 1 }}>188</div><div style={{ fontSize: 11, color: S.cocoa500, fontFamily: S.sans }}>Republican</div></div>
          </div>
          <SeatBar dem={247} rep={188} />
          <p style={{ fontSize: 11, color: S.cocoa400, fontFamily: S.sans, marginTop: 12, lineHeight: 1.5 }}>
            A national-swing estimate, <em>not</em> a district-by-district forecast. Real seats hinge on incumbency and maps.
          </p>
        </Panel>
      </div>
    </div>
  );
}

// ── 3 · SENATE ───────────────────────────────────────────────────────────────
function SenateRaceRow({ race }) {
  const [vibes, setVibes] = React.useState(false);
  const m = vibes && race.vibes ? race.margin + race.vibesShift : race.margin;
  const lead = m > 0 ? 'D' : 'R';
  const leadColor = m > 0 ? S.dem : S.rep;
  return (
    <div style={{ background: S.surface, border: `1px solid ${S.border}`, borderRadius: 12, padding: 16, display: 'flex', alignItems: 'center', gap: 16 }}>
      <div style={{ minWidth: 86 }}>
        <div style={{ fontFamily: S.serif, fontSize: 19, color: S.ink, lineHeight: 1 }}>{race.state}</div>
        <div style={{ fontSize: 10.5, color: S.cocoa400, fontFamily: S.sans, marginTop: 3 }}>{race.numPolls} polls</div>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, color: S.cocoa700, fontFamily: S.sans }}>
          {race.cands[0].n} <strong style={{ color: S.dem }}>{race.cands[0].p}%</strong>
          <span style={{ color: S.cocoa300, margin: '0 8px' }}>·</span>
          {race.cands[1].n} <strong style={{ color: S.rep }}>{race.cands[1].p}%</strong>
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
          {race.vibes && <Pill onClick={() => setVibes(!vibes)} active={vibes} tone="neutral">NYT vibes {vibes ? 'on' : 'off'}</Pill>}
          <Pill tone="neutral">Polymarket {lead} {race.market}%</Pill>
        </div>
      </div>
      <Sparkline data={race.spark} color={leadColor} />
      <div style={{ textAlign: 'right', minWidth: 70 }}>
        <div style={{ fontFamily: S.serif, fontSize: 24, color: leadColor, lineHeight: 1 }}>{lead}+{Math.abs(m).toFixed(1)}</div>
        <div style={{ fontSize: 10, color: S.cocoa400, fontFamily: S.sans, marginTop: 3 }}>{vibes && race.vibes ? 'with vibes' : 'base model'}</div>
      </div>
    </div>
  );
}

function SenateScreen() {
  const races = [
    { state: 'Arizona', cands: [{ n: 'Gallego', p: 48.2 }, { n: 'Lake', p: 44.8 }], margin: 3.4, vibesShift: 1.2, vibes: true, numPolls: 8, market: 61, spark: [1.1, 1.8, 2.4, 2.9, 3.1, 3.4] },
    { state: 'Georgia', cands: [{ n: 'Warnock', p: 47.1 }, { n: 'Kemp', p: 46.1 }], margin: 1.0, vibesShift: 0.8, vibes: true, numPolls: 12, market: 54, spark: [2.0, 1.6, 1.2, 0.9, 1.1, 1.0] },
    { state: 'Michigan', cands: [{ n: 'Peters', p: 49.5 }, { n: 'Rogers', p: 46.5 }], margin: 3.0, vibesShift: 0, vibes: false, numPolls: 10, market: 67, spark: [2.2, 2.6, 2.8, 3.1, 2.9, 3.0] },
    { state: 'Pennsylvania', cands: [{ n: 'McCormick', p: 47.9 }, { n: 'Deluzio', p: 46.4 }], margin: -1.5, vibesShift: 0.9, vibes: true, numPolls: 14, market: 44, spark: [-0.4, -0.8, -1.0, -1.3, -1.4, -1.5] },
    { state: 'Nevada', cands: [{ n: 'Rosen', p: 48.0 }, { n: 'Brown', p: 46.2 }], margin: 1.8, vibesShift: 0, vibes: false, numPolls: 7, market: 58, spark: [1.2, 1.5, 1.7, 1.6, 1.9, 1.8] },
    { state: 'Ohio', cands: [{ n: 'Brown', p: 47.4 }, { n: 'Moreno', p: 47.0 }], margin: 0.4, vibesShift: 1.1, vibes: true, numPolls: 9, market: 49, spark: [-0.6, -0.2, 0.1, 0.3, 0.5, 0.4] },
  ];
  return (
    <div>
      <PageHead kicker="Senate Battlegrounds" title="The six races that decide the chamber"
        sub="Polling averages for the closest seats, with an optional “NYT vibes” fundamentals nudge and the latest prediction-market price for context." />
      <MetaStrip items={[{ k: 'Toss-ups', v: '6 of 34' }, { k: 'Most polled', v: 'Pennsylvania' }, { k: 'Tightest', v: 'Ohio (D+0.4)' }]} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {races.map(r => <SenateRaceRow key={r.state} race={r} />)}
      </div>
      <p style={{ fontSize: 11.5, color: S.cocoa400, fontFamily: S.sans, marginTop: 14, lineHeight: 1.5 }}>
        “NYT vibes” blends a light fundamentals adjustment (incumbency, state lean) into the raw average — toggle it to see how much the narrative is doing the work.
      </p>
    </div>
  );
}

// ── 4 · SENATE FORECAST ──────────────────────────────────────────────────────
function ForecastScreen() {
  return (
    <div>
      <PageHead kicker="Senate Forecast" title="Who controls the Senate after November?"
        sub="Ten thousand simulated elections, seeding each race with its polling average, correlated polling error, and a prediction-market prior." />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        <StatCard label="Democrats hold control" value="78%" tone="dem" sub="up 4 pts this week" />
        <StatCard label="Most likely outcome" value="D 52 · R 48" tone="ink" sub="modal simulated chamber" />
      </div>
      <Panel title="Chamber control probability" style={{ marginBottom: 14 }}>
        <ProbSplit demPct={78} />
      </Panel>
      <Panel title="Distribution of simulated outcomes" style={{ marginBottom: 14 }}>
        <ForecastHistogram />
      </Panel>
      <Panel title="Tipping-point races · ranked by leverage">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {[
            { s: 'Ohio', m: 'D+0.4', p: 49, w: 22 },
            { s: 'Pennsylvania', m: 'R+1.5', p: 44, w: 19 },
            { s: 'Georgia', m: 'D+1.0', p: 54, w: 17 },
            { s: 'Nevada', m: 'D+1.8', p: 58, w: 14 },
            { s: 'Arizona', m: 'D+3.4', p: 61, w: 11 },
          ].map((r, i) => (
            <div key={r.s} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '9px 0', borderTop: i ? `1px solid ${S.border}` : 'none' }}>
              <span style={{ fontSize: 13, color: S.cocoa700, fontFamily: S.sans, minWidth: 110, fontWeight: 500 }}>{r.s}</span>
              <span style={{ fontSize: 12.5, color: S.cocoa500, fontFamily: S.sans, minWidth: 50 }}>{r.m}</span>
              <div style={{ flex: 1, height: 8, background: S.sunken, borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${r.w * 4}%`, height: '100%', background: S.peach, borderRadius: 4 }}></div>
              </div>
              <span style={{ fontSize: 11.5, color: S.cocoa400, fontFamily: S.sans, minWidth: 78, textAlign: 'right' }}>{r.w}% tipping</span>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

// ── 5 · METHODOLOGY ──────────────────────────────────────────────────────────
function MethodologyScreen() {
  const P = ({ children }) => <p style={{ fontSize: 16, lineHeight: 1.7, color: S.cocoa700, fontFamily: S.serifBody || "'Source Serif 4', Georgia, serif", margin: '0 0 18px' }}>{children}</p>;
  const H = ({ children }) => <h3 style={{ fontFamily: S.serif, fontSize: 22, color: S.ink, margin: '28px 0 10px' }}>{children}</h3>;
  return (
    <div style={{ maxWidth: 660 }}>
      <PageHead kicker="Methodology" title="How the Oracle actually works"
        sub="No black boxes. Here is every step between a raw poll and the numbers on this site." />
      <div style={{ background: S.peachWash, border: `1px solid ${S.peachBorder}`, borderRadius: 12, padding: '14px 18px', marginBottom: 24 }}>
        <p style={{ fontFamily: S.serif, fontSize: 17, color: S.peach, margin: 0, lineHeight: 1.4 }}>
          This is a <em>tracker</em>, not a crystal ball. We tell you where opinion is — not who will win your group chat's bet.
        </p>
      </div>
      <H>1 · Collecting the polls</H>
      <P>We ingest every public poll that releases a topline and crosstabs, logging the pollster, sample, mode, and field dates. Partisan-sponsored releases are kept but flagged so the model can discount them.</P>
      <H>2 · Weighting</H>
      <P>Each poll's influence scales with sample size, recency, and a pollster-quality score. Cheap online panels with thin track records get down-weighted; gold-standard live-caller surveys carry more.</P>
      <H>3 · The state-space average</H>
      <P>Rather than a blunt rolling mean, we fit a state-space model that treats true opinion as a slow-moving latent series and each poll as a noisy reading of it. That's what produces the smooth line and its confidence band.</P>
      <H>4 · House effects &amp; “vibes”</H>
      <P>We estimate each pollster's persistent lean and correct for it. On Senate races you can layer in a light fundamentals nudge — incumbency and state partisanship — that we cheekily call “NYT vibes.” It's optional, and we show you exactly how much it moves the number.</P>
      <H>5 · Markets as a sanity check</H>
      <P>Prediction-market prices (Polymarket, Kalshi) sit alongside the model as a gut-check — never baked silently into the average. When the model and the market disagree, that gap is usually the interesting part.</P>
      <div style={{ borderTop: `1px solid ${S.border}`, marginTop: 28, paddingTop: 16, fontSize: 12.5, color: S.cocoa400, fontFamily: S.sans, lineHeight: 1.6 }}>
        Data sources: FiveThirtyEight archive, VoteHub, Silver Bulletin, state pollster releases, Polymarket, Kalshi. Code &amp; full poll log on GitHub. Last model run: May 24, 2026, 6:00 ET.
      </div>
    </div>
  );
}

Object.assign(window, { ApprovalScreen, BallotScreen, SenateScreen, ForecastScreen, MethodologyScreen });

  </script>

  <script type="text/babel">
// ===== app shell =====
const { Header, Footer, ApprovalScreen, BallotScreen, SenateScreen, ForecastScreen, MethodologyScreen } = window;
const SCREENS = { approval: ApprovalScreen, ballot: BallotScreen, senate: SenateScreen, forecast: ForecastScreen, methodology: MethodologyScreen };

function App() {
  const [active, setActive] = React.useState('approval');
  const [scrolled, setScrolled] = React.useState(false);
  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 18);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  const go = (id) => { setActive(id); window.scrollTo({ top: 0, behavior: 'smooth' }); };
  const Screen = SCREENS[active];
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header active={active} onNav={go} scrolled={scrolled} />
      <main style={{ flex: 1, maxWidth: 1040, width: '100%', margin: '0 auto', padding: '28px 24px 8px' }}>
        <Screen />
      </main>
      <Footer />
    </div>
  );
}
ReactDOM.createRoot(document.getElementById('root')).render(<App />);
  </script>
</body>
</html>
