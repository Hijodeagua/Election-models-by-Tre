"""Under-the-hood forecast report — a single self-contained HTML file.

Independent of the Next.js site: this is the place to look at one run of both
chamber models and gut-check it. Three pages (tabs) in one file:

  1. Overview  — headline numbers, every feature each model uses with its
                 coefficient and measured importance, and two US maps (Senate
                 P(D) by state; House expected seat change by state).
  2. House     — seat distribution, seats-votes curve, national environment,
                 closest districts with all input values, per-state rollup,
                 open seats, redistricting, importance table.
  3. Senate    — race table with every fundamentals input, polls, house-effect
                 correction, market, P(D), leverage and tipping-point share;
                 seat distribution; error-correlation matrix; knob sensitivity.

It re-runs both simulators at larger scale than the site (defaults: 500,000
Senate / 200,000 House simulations) using exactly the production inputs
(web/public/data/*.json + config/*.json), and writes
reports/forecast_report_<date>.html plus reports/latest.html and a JSON
summary of the run.

Usage:
    python scripts/build_report.py [--senate-sims 500000] [--house-sims 200000]
"""

from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_json import _senate_similarity  # noqa: E402
from src.models.house_forecast import (  # noqa: E402
    HouseForecastSimulator,
    load_districts,
    load_house_config,
    load_state_presidential,
)
from src.models.senate_simulation import (  # noqa: E402
    RaceInput,
    SenateControlSimulator,
    load_cycle_config,
)

DATA_DIR = PROJECT_ROOT / "web" / "public" / "data"
REPORT_DIR = PROJECT_ROOT / "reports"
GEOJSON = PROJECT_ROOT / "data" / "geo" / "us_states.geojson"

STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY", "District of Columbia": "DC",
}

# Diverging palette for P(D): Rep red → neutral gray → Dem blue (validated:
# #dc2626 / #2563eb pass CVD and normal-vision separation; gray is the midpoint).
DEM, REP, NEUTRAL = "#2563eb", "#dc2626", "#c9c4bd"


# ── helpers ───────────────────────────────────────────────────────────────────

def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _hex_to_rgb(a), _hex_to_rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ra, rb, strict=True))


def prob_color(p: float | None) -> str:
    """Diverging: 0 → red, 0.5 → gray, 1 → blue."""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "#efebe6"
    p = min(1.0, max(0.0, p))
    return _mix(REP, NEUTRAL, p / 0.5) if p < 0.5 else _mix(NEUTRAL, DEM, (p - 0.5) / 0.5)


def delta_color(v: float, scale: float) -> str:
    """Diverging around 0 for seat changes."""
    t = max(-1.0, min(1.0, v / scale))
    return _mix(NEUTRAL, DEM, t) if t >= 0 else _mix(NEUTRAL, REP, -t)


def m(v: float | None, d: int = 1) -> str:
    """Dem−Rep margin label."""
    if v is None:
        return "—"
    if abs(v) < 0.05:
        return "Even"
    return f"{'D' if v > 0 else 'R'}+{abs(v):.{d}f}"


def pct(v: float | None, d: int = 0) -> str:
    return "—" if v is None else f"{v * 100:.{d}f}%"


def sgn(v: float | None, d: int = 1) -> str:
    return "—" if v is None else f"{v:+.{d}f}"


def esc(s: object) -> str:
    return html.escape(str(s))


# ── projection (Albers USA: lower 48 + AK/HI insets) ─────────────────────────

def _albers(lon: float, lat: float, phi1: float, phi2: float, phi0: float, lam0: float):
    lon, lat = math.radians(lon), math.radians(lat)
    p1, p2, p0, l0 = map(math.radians, (phi1, phi2, phi0, lam0))
    n = (math.sin(p1) + math.sin(p2)) / 2.0
    c = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
    rho0 = math.sqrt(c - 2 * n * math.sin(p0)) / n
    theta = n * (lon - l0)
    rho = math.sqrt(max(c - 2 * n * math.sin(lat), 0.0)) / n
    return rho * math.sin(theta), rho0 - rho * math.cos(theta)


def _project_feature(coords, proj) -> list[list[tuple[float, float]]]:
    rings = []
    for ring in coords:
        rings.append([proj(lon, lat) for lon, lat in ring])
    return rings


def build_state_paths() -> dict[str, str]:
    """{abbr: svg path d} in a 960×600 viewBox, AK/HI inset bottom-left."""
    if not GEOJSON.exists():
        return {}
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    lower = lambda lon, lat: _albers(lon, lat, 29.5, 45.5, 23.0, -96.0)  # noqa: E731
    ak = lambda lon, lat: _albers(lon, lat, 55.0, 65.0, 50.0, -154.0)  # noqa: E731
    hi = lambda lon, lat: _albers(lon, lat, 8.0, 18.0, 13.0, -157.0)  # noqa: E731

    raw: dict[str, list[list[tuple[float, float]]]] = {}
    for f in gj["features"]:
        abbr = STATE_ABBR.get(f["properties"].get("name", ""))
        if not abbr or abbr == "DC":
            continue
        proj = ak if abbr == "AK" else hi if abbr == "HI" else lower
        geom = f["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        rings: list[list[tuple[float, float]]] = []
        for poly in polys:
            rings.extend(_project_feature(poly, proj))
        raw[abbr] = rings

    def _bounds(keys):
        xs = [x for k in keys for r in raw[k] for x, _ in r]
        ys = [y for k in keys for r in raw[k] for _, y in r]
        return min(xs), max(xs), min(ys), max(ys)

    lower48 = [k for k in raw if k not in ("AK", "HI")]
    x0, x1, y0, y1 = _bounds(lower48)
    scale = min(900.0 / (x1 - x0), 470.0 / (y1 - y0))

    def _fit(keys, sc, ox, oy, flip_box):
        bx0, bx1, by0, by1 = flip_box
        out = {}
        for k in keys:
            d = []
            for ring in raw[k]:
                pts = [
                    (ox + (x - bx0) * sc, oy + (by1 - y) * sc) for x, y in ring
                ]
                d.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
            out[k] = " ".join(d)
        return out

    paths = _fit(lower48, scale, 30.0, 16.0, (x0, x1, y0, y1))
    if "AK" in raw:
        ax0, ax1, ay0, ay1 = _bounds(["AK"])
        s_ak = min(200.0 / (ax1 - ax0), 130.0 / (ay1 - ay0))
        paths.update(_fit(["AK"], s_ak, 40.0, 505.0, (ax0, ax1, ay0, ay1)))
    if "HI" in raw:
        hx0, hx1, hy0, hy1 = _bounds(["HI"])
        s_hi = min(110.0 / (hx1 - hx0), 60.0 / (hy1 - hy0))
        paths.update(_fit(["HI"], s_hi, 270.0, 560.0, (hx0, hx1, hy0, hy1)))
    return paths


def svg_map(
    paths: dict[str, str],
    fill: dict[str, str],
    labels: dict[str, str],
    title: str,
    legend: list[tuple[str, str]],
    tooltips: dict[str, str] | None = None,
) -> str:
    parts = [
        f'<svg viewBox="0 0 960 660" role="img" aria-label="{esc(title)}" class="map">'
    ]
    for abbr, d in paths.items():
        tip = esc((tooltips or {}).get(abbr, abbr))
        parts.append(
            f'<path d="{d}" fill="{fill.get(abbr, "#efebe6")}" stroke="#ffffff" '
            f'stroke-width="1.2" class="st" data-abbr="{abbr}"><title>{tip}</title></path>'
        )
    # label at centroid-ish (bbox centre) for states that have a label
    for abbr, text in labels.items():
        d = paths.get(abbr)
        if not d:
            continue
        pts = [tuple(map(float, p.split(","))) for seg in d.replace("Z", "").split("M") if seg
               for p in seg.strip().split(" L") if p]
        if not pts:
            continue
        # use largest ring bbox centre
        xs, ys = zip(*pts, strict=True)
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        parts.append(
            f'<text x="{cx:.0f}" y="{cy:.0f}" text-anchor="middle" class="maplbl">{esc(text)}</text>'
        )
    lx, ly = 640, 630
    for i, (color, label) in enumerate(legend):
        parts.append(
            f'<rect x="{lx + i * 105}" y="{ly}" width="18" height="12" rx="2" fill="{color}" stroke="#bbb" stroke-width="0.5"/>'
            f'<text x="{lx + 22 + i * 105}" y="{ly + 10}" class="maplgd">{esc(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ── charts (inline SVG) ──────────────────────────────────────────────────────

def svg_histogram(dist: dict[str, int], threshold: int, total: int, width=720, height=220,
                  bin_width: int = 1, x_label: str = "Democratic seats") -> str:
    keys = sorted(int(k) for k in dist)
    lo, hi = keys[0], keys[-1]
    lo = (lo // bin_width) * bin_width
    bins = {}
    for s in range(lo, hi + 1, bin_width):
        bins[s] = sum(dist.get(str(k), 0) for k in range(s, s + bin_width))
    mx = max(bins.values()) or 1
    n = len(bins)
    pad_l, pad_b, pad_t = 36, 30, 16
    bw = (width - pad_l - 10) / n
    out = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="Seat distribution">']
    for i, (s, c) in enumerate(bins.items()):
        h = (height - pad_b - pad_t) * c / mx
        x = pad_l + i * bw
        y = height - pad_b - h
        color = DEM if s + bin_width - 1 >= threshold else REP
        rng_lbl = f"{s}" if bin_width == 1 else f"{s}–{s + bin_width - 1}"
        out.append(
            f'<rect x="{x + 1:.1f}" y="{y:.1f}" width="{max(bw - 2, 1):.1f}" height="{h:.1f}" '
            f'fill="{color}" rx="2"><title>{rng_lbl} D seats: {c:,} sims ({c / total:.1%})</title></rect>'
        )
        if n <= 40 or i % max(1, n // 20) == 0:
            out.append(
                f'<text x="{x + bw / 2:.1f}" y="{height - pad_b + 14}" text-anchor="middle" class="tick">{s}</text>'
            )
    # threshold line
    tx = pad_l + ((threshold - lo) // bin_width + 0.0) * bw
    out.append(
        f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="{pad_t - 6}" y2="{height - pad_b}" stroke="var(--ink)" stroke-dasharray="4 3"/>'
        f'<text x="{tx + 4:.1f}" y="{pad_t + 4}" class="tick">majority {threshold}</text>'
    )
    out.append(f'<text x="{width / 2}" y="{height - 4}" text-anchor="middle" class="tick">{esc(x_label)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_curve(points: list[dict], threshold: int, today_x: float, today_y: float,
              width=720, height=240) -> str:
    xs = [p["margin"] for p in points]
    ys = [p["dem_seats"] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys + [threshold]) - 5, max(ys + [threshold]) + 5
    pl, pr, pt, pb = 44, 16, 14, 34
    sx = lambda x: pl + (x - x0) / (x1 - x0) * (width - pl - pr)  # noqa: E731
    sy = lambda y: pt + (y1 - y) / (y1 - y0) * (height - pt - pb)  # noqa: E731
    d = " ".join(f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(zip(xs, ys, strict=True)))
    out = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="Seats-votes curve">']
    for y in range(int(y0 // 10 * 10), int(y1) + 1, 10):
        out.append(f'<line x1="{pl}" x2="{width - pr}" y1="{sy(y):.1f}" y2="{sy(y):.1f}" class="grid"/>'
                   f'<text x="{pl - 6}" y="{sy(y) + 4:.1f}" text-anchor="end" class="tick">{y}</text>')
    out.append(f'<line x1="{pl}" x2="{width - pr}" y1="{sy(threshold):.1f}" y2="{sy(threshold):.1f}" stroke="var(--ink)" stroke-dasharray="4 3"/>'
               f'<text x="{pl + 4}" y="{sy(threshold) - 4:.1f}" class="tick">majority {threshold}</text>')
    out.append(f'<path d="{d}" fill="none" stroke="{DEM}" stroke-width="2"/>')
    for x, y in zip(xs, ys, strict=True):
        out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" fill="{DEM}" stroke="var(--surface)" stroke-width="2">'
                   f'<title>National {m(x)}: {y:.0f} expected D seats</title></circle>')
        out.append(f'<text x="{sx(x):.1f}" y="{height - pb + 16}" text-anchor="middle" class="tick">{m(x, 0)}</text>')
    out.append(f'<circle cx="{sx(today_x):.1f}" cy="{sy(today_y):.1f}" r="6" fill="#c1533d" stroke="var(--surface)" stroke-width="2">'
               f'<title>Today: {m(today_x)} → {today_y:.1f} seats</title></circle>'
               f'<text x="{sx(today_x) + 9:.1f}" y="{sy(today_y) - 8:.1f}" class="tick">today</text>')
    out.append(f'<text x="{width / 2}" y="{height - 4}" text-anchor="middle" class="tick">national two-party margin</text></svg>')
    return "".join(out)


def svg_bars(rows: list[tuple[str, float, str]], width=560, max_val: float | None = None) -> str:
    """Horizontal importance bars: (label, value, note)."""
    if not rows:
        return ""
    mx = max_val or max(v for _, v, _ in rows) or 1.0
    rh, pad_l = 24, 250
    height = rh * len(rows) + 8
    out = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="Feature importance">']
    for i, (label, v, note) in enumerate(rows):
        y = 4 + i * rh
        w = (width - pad_l - 70) * v / mx
        out.append(f'<text x="{pad_l - 8}" y="{y + 16}" text-anchor="end" class="lbl">{esc(label)}</text>'
                   f'<rect x="{pad_l}" y="{y + 4}" width="{w:.1f}" height="{rh - 8}" rx="3" fill="{DEM}" fill-opacity="0.85">'
                   f'<title>{esc(label)}: {v:.3f} — {esc(note)}</title></rect>'
                   f'<text x="{pad_l + w + 6:.1f}" y="{y + 16}" class="lbl">{v:.3f}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_corr(names: list[str], corr: list[list[float]]) -> str:
    n = len(names)
    cell, pad = 46, 110
    size = pad + cell * n + 10
    out = [f'<svg viewBox="0 0 {size} {size}" class="chart" role="img" aria-label="Error correlation">']
    for i, a in enumerate(names):
        out.append(f'<text x="{pad - 6}" y="{pad + i * cell + cell / 2 + 4}" text-anchor="end" class="lbl">{esc(a)}</text>')
        out.append(f'<text x="{pad + i * cell + cell / 2}" y="{pad - 8}" text-anchor="middle" class="lbl" transform="rotate(-35 {pad + i * cell + cell / 2},{pad - 8})">{esc(a)}</text>')
        for j in range(n):
            v = corr[i][j]
            t = (v - 0.2) / 0.8  # 0.2..1 → light..dark single hue
            color = _mix("#eef3fc", DEM, max(0.0, min(1.0, t)))
            out.append(f'<rect x="{pad + j * cell + 1}" y="{pad + i * cell + 1}" width="{cell - 2}" height="{cell - 2}" fill="{color}" rx="3">'
                       f'<title>{esc(a)} × {esc(names[j])}: ρ = {v:.2f}</title></rect>'
                       f'<text x="{pad + j * cell + cell / 2}" y="{pad + i * cell + cell / 2 + 4}" text-anchor="middle" class="cell" fill="{"#fff" if t > 0.55 else "var(--ink)"}">{v:.2f}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_margin_hist(hist: list[dict], width=200, height=44) -> str:
    if not hist:
        return ""
    mx = max(h["pct"] for h in hist) or 1
    bw = width / len(hist)
    out = [f'<svg viewBox="0 0 {width} {height}" class="spark">']
    for i, h in enumerate(hist):
        hh = (height - 4) * h["pct"] / mx
        out.append(f'<rect x="{i * bw:.1f}" y="{height - hh:.1f}" width="{max(bw - 1, 0.5):.1f}" height="{hh:.1f}" fill="{DEM if h["mid"] > 0 else REP}"><title>{m(h["mid"])}: {h["pct"]:.1%}</title></rect>')
    zero = next((i for i, h in enumerate(hist) if h["mid"] > 0), len(hist) // 2)
    out.append(f'<line x1="{zero * bw:.1f}" x2="{zero * bw:.1f}" y1="0" y2="{height}" stroke="var(--ink)" stroke-width="1"/></svg>')
    return "".join(out)


# ── simulations ───────────────────────────────────────────────────────────────

def run_senate(sf: dict, cycle: dict, n_sims: int, seed: int) -> dict:
    sim = SenateControlSimulator(
        dem_safe_seats=sf["dem_safe_seats"],
        rep_safe_seats=sf["rep_safe_seats"],
        dem_majority_threshold=sf["dem_majority_threshold"],
        national_sigma=sf["national_sigma"],
        race_sigma=sf["race_sigma"],
        market_weight=sf["market_weight"],
        bias=sf.get("bias", 0.0),
        tail_dof=sf.get("tail_dof"),
    )
    by_state = {e["state"]: e for e in cycle["competitive_races"]}
    entries = [by_state[r["state"]] for r in sf["races"]]
    inputs = [
        RaceInput(
            state=r["state"], race=r["race"], dem_candidate=r["dem_candidate"],
            rep_candidate=r["rep_candidate"], margin=r["margin"], num_polls=r["num_polls"],
            market_dem_prob=r.get("market_dem_prob", {}), fundamentals=r.get("fundamentals", {}),
        )
        for r in sf["races"]
    ]
    corr_cfg = cycle.get("correlation", {}) or {}
    k = _senate_similarity(entries, corr_cfg)
    share = float(corr_cfg.get("similarity_share", 0.0))
    fc = sim.simulate(inputs, num_simulations=n_sims, seed=seed, similarity=k, similarity_share=share)
    wins = sim.last_dem_wins  # (n_sims, n_races) for races with a margin
    seats = sf["dem_safe_seats"] + wins.sum(axis=1)
    ctrl = seats >= sf["dem_majority_threshold"]
    # leverage + tipping point (need effective margins: rank by simulated margin isn't
    # stored, so approximate tipping as the race whose win flips control most often)
    lev, tip = [], []
    need = sf["dem_majority_threshold"] - sf["dem_safe_seats"]
    for j in range(wins.shape[1]):
        pw = ctrl[wins[:, j]].mean() if wins[:, j].any() else float("nan")
        pl = ctrl[~wins[:, j]].mean() if (~wins[:, j]).any() else float("nan")
        lev.append(float(pw - pl))
        # race j is decisive when Dems win exactly `need` races including j
        others = wins.sum(axis=1) - wins[:, j]
        tip.append(float(((others == need - 1) & wins[:, j]).mean()))
    return {"forecast": fc, "leverage": lev, "tipping": tip, "sim": sim,
            "ctrl_var": float(seats.var()), "seats": seats}


def run_house(hf: dict, cfg: dict, n_sims: int, seed: int, overrides: dict | None = None):
    cfg = json.loads(json.dumps(cfg))
    for path, val in (overrides or {}).items():
        node = cfg
        keys = path.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = val
    lean = cfg.get("district_lean", {})
    corr = cfg.get("correlation", {}) or {}
    ncfg = cfg.get("national_environment", {})
    sf_cfg = cfg.get("state_fundamentals", {}) or {}
    state_pres = load_state_presidential()
    nat = next(iter(state_pres.values()), {}) if state_pres else {}
    national_trend = float(nat.get("national_2024", 0.0)) - float(nat.get("national_2020", 0.0))
    econ_by_state = {d["state"]: d.get("econ_adjust", 0.0) for d in hf.get("districts", [])}
    districts = load_districts(
        open_seats=lean.get("open_seats", {}).get("districts", []),
        state_pres=state_pres,
        state_adjust={st: (v, {}) for st, v in econ_by_state.items()},
    )
    polling_sigma = float(ncfg.get("generic_ballot_sigma", 2.5))
    drift = float(hf.get("campaign_drift_sigma", 0.0)) if cfg.get("campaign_drift_per_sqrt_day") else 0.0
    if "campaign_drift_per_sqrt_day" in (overrides or {}):
        drift = float(overrides["campaign_drift_per_sqrt_day"]) * math.sqrt(hf.get("days_to_election", 0))
    sim = HouseForecastSimulator(
        baseline_margin=float(cfg["baseline"]["two_party_margin"]),
        national_sigma=float(math.hypot(polling_sigma, drift)),
        district_sigma=float(cfg["district_error"]["district_sigma"]),
        tail_dof=ncfg.get("national_tail_dof", 5),
        dem_majority_threshold=int(cfg["dem_majority_threshold"]),
        total_seats=int(cfg["total_seats"]),
        redistricting=cfg.get("redistricting", {}).get("states", []),
        lean_weight_2024=float(lean.get("weight_2024", 1.0)),
        lean_weight_2022=float(lean.get("weight_2022", 0.0)),
        incumbency_advantage=float(lean.get("incumbency_advantage", 0.0)),
        similarity_share=float(corr.get("similarity_share", 0.0)),
        similarity_weights=corr.get("weights"),
        lean_scale=float(corr.get("lean_scale", 10.0)),
        regions=corr.get("regions"),
        state_trend_weight=float(sf_cfg.get("state_trend_weight", 0.0)),
        national_trend=national_trend,
    )
    expected = hf["expected_national_margin"]
    if "national_environment.generic_ballot_bias" in (overrides or {}):
        expected = (hf["raw_national_margin"] + overrides["national_environment.generic_ballot_bias"]
                    + hf.get("economy", {}).get("national", {}).get("inflation_effect", 0.0))
    if "expected_national_margin" in (overrides or {}):
        expected = overrides["expected_national_margin"]
    fc = sim.simulate(districts, expected, num_simulations=n_sims, seed=seed,
                      curve_margins=cfg.get("seats_votes_curve_margins"))
    return fc, sim, districts


def house_importance(hf: dict, cfg: dict, n_sims: int, seed: int, base_p: float, base_seats: float):
    grid = [
        ("National margin (generic ballot level)", "expected_national_margin",
         [hf["expected_national_margin"] - 2, hf["expected_national_margin"] + 2]),
        ("Generic-ballot bias", "national_environment.generic_ballot_bias", [0.0, -2.0]),
        ("Generic-ballot σ", "national_environment.generic_ballot_sigma", [1.5, 3.5]),
        ("Campaign drift /√day", "campaign_drift_per_sqrt_day", [0.0, 0.6]),
        ("Redistricting (none)", "redistricting.states", [[]]),
        ("District σ", "district_error.district_sigma", [4.5, 8.5]),
        ("Similarity share", "correlation.similarity_share", [0.0, 0.7]),
        ("Incumbency advantage (open seats)", "district_lean.incumbency_advantage", [0.0, 5.0]),
        ("2022 lean weight", "district_lean.weight_2022", [0.0, 0.5]),
        ("State trend weight (2020→2024)", "state_fundamentals.state_trend_weight", [0.0, 0.5]),
        ("National tails (Gaussian)", "national_environment.national_tail_dof", [None]),
    ]
    rows = []
    for label, key, vals in grid:
        res = []
        for v in vals:
            fc, _, _ = run_house(hf, cfg, n_sims, seed, {key: v})
            res.append((v, fc.dem_majority_prob, fc.mean_dem_seats))
        spread = max(abs(p - base_p) for _, p, _ in res) * (2 if len(res) == 1 else 1)
        pspread = max(p for _, p, _ in res) - min(p for _, p, _ in res) if len(res) > 1 else abs(res[0][1] - base_p)
        rows.append({"feature": label, "key": key, "grid": res, "spread": round(pspread, 4),
                     "seat_spread": round(max(s for *_, s in res) - min(s for *_, s in res), 2)
                     if len(res) > 1 else round(abs(res[0][2] - base_seats), 2)})
        _ = spread
    rows.sort(key=lambda r: -r["spread"])
    return rows


# ── HTML ──────────────────────────────────────────────────────────────────────

CSS = """
:root{--surface:#fcfcfb;--panel:#ffffff;--ink:#1d1a17;--ink2:#5c564f;--muted:#8a8580;--line:#e6e1da;--dem:#2563eb;--rep:#dc2626;--accent:#c1533d;--wash:#f4f0eb}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--surface:#151413;--panel:#1f1d1b;--ink:#f3efe9;--ink2:#c7c1b8;--muted:#8f887f;--line:#33302c;--wash:#262321}}
*{box-sizing:border-box}body{margin:0;background:var(--surface);color:var(--ink);font:14px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
header{padding:18px 24px 0;border-bottom:1px solid var(--line)}h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:26px 0 10px}h3{font-size:14px;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink2)}
.sub{color:var(--ink2);margin:0 0 12px}.tabs{display:flex;gap:4px}.tabs button{background:none;border:0;border-bottom:3px solid transparent;padding:10px 14px;font-weight:600;color:var(--ink2);cursor:pointer;font-size:14px}.tabs button.on{color:var(--ink);border-color:var(--accent)}
main{max-width:1180px;margin:0 auto;padding:18px 24px 60px}.page{display:none}.page.on{display:block}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.tile .k{font-size:11.5px;color:var(--muted)}.tile .v{font-size:30px;font-weight:700;line-height:1.1;margin-top:2px}.tile .s{font-size:11.5px;color:var(--ink2);margin-top:4px}.dem{color:var(--dem)}.rep{color:var(--rep)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-top:14px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:900px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:12.5px}th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:1px solid var(--line);padding:6px 6px;white-space:nowrap}td{padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}tr:hover td{background:var(--wash)}
.chart,.map{width:100%;height:auto;display:block}.tick{font-size:11px;fill:var(--muted)}.lbl{font-size:12px;fill:var(--ink2)}.cell{font-size:10.5px}.grid{stroke:var(--line)}.maplbl{font-size:11px;font-weight:700;fill:#1d1a17;paint-order:stroke;stroke:#ffffff;stroke-width:3px}.maplgd{font-size:11px;fill:var(--ink2)}
.st:hover{stroke:var(--ink);stroke-width:1.6}.spark{width:120px;height:26px;display:block}
.note{font-size:12px;color:var(--ink2)}.flag{display:inline-block;background:var(--wash);border:1px solid var(--line);border-radius:999px;padding:1px 8px;font-size:11px;margin:2px 4px 2px 0}
.warn{border-left:3px solid #eda100;padding-left:10px}.kv{display:grid;grid-template-columns:max-content 1fr;gap:3px 14px;font-size:12.5px}.kv b{color:var(--ink2);font-weight:600}
code{font-size:12px;background:var(--wash);padding:1px 5px;border-radius:4px}
"""

JS = """
document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>{
 document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
 document.querySelectorAll('.page').forEach(p=>p.classList.toggle('on',p.id===b.dataset.page));
 history.replaceState(null,'','#'+b.dataset.page);}));
const h=location.hash.slice(1);if(h){const b=document.querySelector(`.tabs button[data-page="${h}"]`);if(b)b.click();}
"""


def tile(k: str, v: str, s: str = "", cls: str = "") -> str:
    return f'<div class="tile"><div class="k">{esc(k)}</div><div class="v {cls}">{esc(v)}</div><div class="s">{esc(s)}</div></div>'


def table(headers: list[tuple[str, bool]], rows: list[list[str]], note: str = "") -> str:
    th = "".join(f'<th class="{"n" if num else ""}">{h}</th>' for h, num in headers)
    body = "".join(
        "<tr>" + "".join(f'<td class="{"n" if headers[i][1] else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    n = f'<p class="note">{note}</p>' if note else ""
    return f'<div style="overflow-x:auto"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>{n}'


def build(args) -> Path:
    today = date.today()
    sf, hf, meta = _load("senate_forecast.json"), _load("house_forecast.json"), _load("meta.json")
    senate_races = _load("senate.json")["races"]
    hist_by_state = {r["state"]: (r.get("forecast") or {}).get("margin_hist", []) for r in senate_races}
    cycle, hcfg = load_cycle_config(), load_house_config()
    sens = json.loads((PROJECT_ROOT / "config" / "sensitivity_analysis.json").read_text())
    calib = json.loads((PROJECT_ROOT / "config" / "forecast_calibration.json").read_text())

    print(f"Senate: {args.senate_sims:,} simulations …")
    sen = run_senate(sf, cycle, args.senate_sims, args.seed)
    sfc = sen["forecast"]
    print(f"  P(D control)={sfc.dem_control_prob:.4f} mean={sfc.mean_dem_seats:.2f}")
    print(f"House: {args.house_sims:,} simulations …")
    hfc, hsim, districts = run_house(hf, hcfg, args.house_sims, args.seed)
    print(f"  P(D majority)={hfc.dem_majority_prob:.4f} mean={hfc.mean_dem_seats:.2f}")
    print("House importance (one-at-a-time) …")
    himp = house_importance(hf, hcfg, args.importance_sims, args.seed, hfc.dem_majority_prob, hfc.mean_dem_seats)

    # ── derived: per-state house rollup
    by_state: dict[str, dict] = {}
    for d in hfc.districts:
        s = by_state.setdefault(d.state, {"d24": 0, "r24": 0, "exp": 0.0, "n": 0, "open": 0})
        s["n"] += 1
        s["exp"] += d.dem_win_prob
        s["d24" if d.winner_2024 == "D" else "r24"] += 1
        s["open"] += int(d.open_seat)
    redraw = {r["state"]: r for r in hfc.redistricting_states}
    for st, s in by_state.items():
        s["shift"] = redraw.get(st, {}).get("dem_seat_shift", 0.0)
        s["change"] = s["exp"] + s["shift"] - s["d24"]

    paths = build_state_paths()
    sen_fill = {}
    sen_lbl = {}
    sen_tip = {}
    abbr_by_state = {e["state"]: e["abbr"] for e in cycle["competitive_races"]}
    for r in sfc.races:
        ab = abbr_by_state[r.state]
        p = r.dem_win_prob_sim if r.dem_win_prob_sim is not None else r.dem_win_prob_blended
        sen_fill[ab] = prob_color(p)
        sen_lbl[ab] = f"{ab} {pct(p)}"
        sen_tip[ab] = f"{r.state}: {r.dem_candidate} (D) v {r.rep_candidate} (R) — P(D) {pct(p)}, margin {m(r.margin)}"
        _ = sen_tip
    house_fill, house_lbl, house_tip = {}, {}, {}
    for st, s in by_state.items():
        house_fill[st] = delta_color(s["change"], 3.0)
        if abs(s["change"]) >= 0.8 or s["shift"]:
            house_lbl[st] = f"{st} {s['change']:+.1f}"
        house_tip[st] = (f"{st}: 2024 D {s['d24']}/R {s['r24']} → expected D {s['exp'] + s['shift']:.1f} "
                         f"({s['change']:+.1f}){' incl. redistricting ' + sgn(s['shift'], 0) if s['shift'] else ''}; "
                         f"{s['open']} open seat(s)")

    # ── Senate importance (from the committed sweep) + fundamentals coefficients
    sens_rows = sorted(sens["knobs"], key=lambda k: -k["spread_across_grid"])
    coefs = sf.get("fundamentals_coefficients", {})
    ne = sf.get("national_environment", {})
    bc = sf.get("bias_calibration", {})
    econ_snap = sf.get("economy", {}) or {}

    # ── pages
    stale = meta.get("stale_feeds", [])
    gut = []
    if stale:
        gut.append(f"Stale feeds: {', '.join(stale)} (newest poll {', '.join(f'{k} {v}' for k, v in meta.get('last_poll_dates', {}).items())}).")
    gut.append("Hand-entered, unverified: Senate incumbency/record features, House open-seat list, redistricting seat shifts (config files flag each).")
    gut.append("Hand-set coefficients: incumbency, experience, 2022 weight, generic-ballot bias/σ, district σ, similarity shares.")
    gut.append(f"Prediction markets: weight {sf['market_weight']} in the Senate blend (polls + fundamentals only).")
    missing = [k for k, v in (("gas prices", econ_snap.get("states_with_gas")), ("state unemployment", econ_snap.get("states_with_unemployment"))) if not v]
    if missing:
        gut.append("Economic series not yet fetched: " + ", ".join(missing) + " (run scripts/refresh_data.py --source economic with EIA_API_KEY set); those terms contribute 0 until then. CPI is live.")
    gut.append(f"House-effect correction applied to {sum(v['polls_adjusted'] for v in sf.get('house_effects', {}).values())} of {sum(v['polls_total'] for v in sf.get('house_effects', {}).values())} Senate polls (pollsters with a 2018–24 record).")

    econ_c = coefs.get("economy", {})
    sched = lambda d: ", ".join(f"{k}: {v:+g}" for k, v in (d or {}).items())  # noqa: E731
    senate_features = [
        ("Race polling average (weighted by pollster grade + recency, corrected by each pollster's calibrated house effect)", "weight 1−k/(k+n), k=%s" % coefs.get("blend_k"), "polls"),
        ("2024 presidential margin", f"full weight ({coefs.get('pres_2024_weight')})", "lean"),
        ("2020 presidential margin", f"{coefs.get('pres_2020_shift_weight')} of how 2020 differed from 2024", "lean"),
        ("Last Senate race in the state", f"{coefs.get('last_senate_shift_weight')} of how it differed from 2024", "lean"),
        ("Generic ballot", f"{ne.get('generic_margin')} → weight {cycle['national_environment']['generic_weight']} of national swing", "environment"),
        ("Net presidential approval", f"{ne.get('approval_net')} × {cycle['national_environment']['approval_to_margin_coef']} → weight {cycle['national_environment']['approval_weight']} of national swing", "environment"),
        ("Incumbency (binary)", f"±{coefs.get('incumbency_advantage')} pts (×{coefs.get('appointed_incumbent_factor')} appointed)", "candidate"),
        ("Years in office — incumbent (categorical)", sched(coefs.get("incumbent_tenure_schedule")), "candidate"),
        ("Years in office — challengers (categorical)", sched(coefs.get("office_years_schedule")), "candidate"),
        ("Candidate experience (statewide W–L)", f"{coefs.get('experience_per_statewide_win')}/win, {coefs.get('experience_per_statewide_loss')}/loss, cap ±{coefs.get('experience_cap')}", "candidate"),
        ("Inflation (CPI year-over-year)", f"CPI {econ_snap.get('cpi_yoy', '—')}% ({econ_snap.get('as_of', '')}); ({'CPI'} − {econ_c.get('inflation_baseline')}) × {econ_c.get('inflation_coef')} on the president's party", "economy"),
        ("State gas price vs national", f"{econ_c.get('gas_deviation_coef')} per $1 above national — {'available' if econ_snap.get('states_with_gas') else 'pending EIA fetch (EIA_API_KEY)'}", "economy"),
        ("State unemployment vs national", f"{econ_c.get('unemployment_deviation_coef')} per point above national — {'available' if econ_snap.get('states_with_unemployment') else 'pending BLS fetch'}", "economy"),
        ("Systematic poll bias", f"{bc.get('cycle_type')} cycles: {bc.get('raw_bias')} × {bc.get('weight')} = {bc.get('applied')}", "error model"),
        ("National error σ", f"{sf.get('polling_national_sigma')} ⊕ drift {sf.get('campaign_drift_sigma')} = {sf['national_sigma']}", "error model"),
        ("Race error σ / similarity share", f"{sf['race_sigma']} / {sf.get('similarity_share')} (region {sf.get('correlation', {}).get('region_weight')}, lean scale {sf.get('correlation', {}).get('lean_scale')})", "error model"),
        ("Tails", f"Student-t({sf.get('tail_dof')})", "error model"),
    ]
    h_econ = hf.get("economy", {}).get("coefficients", {})
    h_snap = hf.get("economy", {}).get("snapshot", {})
    house_features = [
        ("2024 two-party margin (district)", f"weight {hfc.lean_weight_2024}", "lean"),
        ("2022 two-party margin (district)", f"weight {hfc.lean_weight_2022}", "lean"),
        ("Incumbent flag", f"2024 winner on the ballot: {hfc.total_seats - hfc.num_open_seats} seats; open: {hfc.num_open_seats} (−{hfc.incumbency_advantage} pts to the departing party)", "candidate"),
        ("State 2024 presidential margin", "exported per district; drives the state trend term", "state"),
        ("State 2020 presidential margin", f"state trend = {hfc.state_trend_weight} × [(state '24 − '20) − national ({hfc.national_trend:+.1f})]", "state"),
        ("Inflation (CPI year-over-year)", f"CPI {h_snap.get('cpi_yoy', '—')}%; ({'CPI'} − {h_econ.get('inflation_baseline')}) × {h_econ.get('inflation_coef')} on the national margin", "economy"),
        ("State gas price / unemployment vs national", f"{h_econ.get('gas_deviation_coef')} per $1, {h_econ.get('unemployment_deviation_coef')} per point — {'available' if h_snap.get('states_with_gas') else 'pending EIA/BLS fetch'}", "economy"),
        ("Generic ballot (two-party)", f"{m(hf.get('generic_ballot_two_party'))}, weight {hcfg['national_environment']['generic_weight']}", "environment"),
        ("Approval-implied margin", f"{m(hf.get('approval_implied_margin'))}, weight {hcfg['national_environment']['approval_weight']}", "environment"),
        ("Generic-ballot bias", f"{hf['generic_ballot_bias']} pts", "error model"),
        ("National error σ", f"{hf['polling_sigma']} ⊕ drift {hf['campaign_drift_sigma']:.2f} = {hf['national_sigma']:.2f}", "error model"),
        ("District error σ / similarity share", f"{hf['district_sigma']} / {hfc.similarity_share} (weights {hfc.similarity_weights}, lean scale {hfc.lean_scale})", "error model"),
        ("Redistricting (net seat shift)", f"{sgn(hfc.redistricting_shift_mean, 0)} seats over {len(hfc.redistricting_states)} states", "structure"),
        ("Tails", f"Student-t({hf.get('tail_dof')})", "error model"),
    ]

    def features_table(rows):
        return table([("Feature", False), ("Value / coefficient used", False), ("Group", False)],
                     [[esc(a), esc(b), f'<span class="flag">{esc(c)}</span>'] for a, b, c in rows])

    sen_imp_bars = svg_bars([(k["knob"], k["spread_across_grid"], k["description"]) for k in sens_rows])
    house_imp_bars = svg_bars([(r["feature"], r["spread"], f"grid {r['grid']}") for r in himp])

    overview = f"""
<div class="tiles">
{tile("P(Democratic Senate control)", pct(sfc.dem_control_prob), f"mean {sfc.mean_dem_seats:.2f} D seats · need {sf['dem_majority_threshold']}", "dem" if sfc.dem_control_prob >= .5 else "rep")}
{tile("P(Democratic House majority)", pct(hfc.dem_majority_prob), f"mean {hfc.mean_dem_seats:.1f} seats · 80% {hfc.seats_p10:.0f}–{hfc.seats_p90:.0f}", "dem" if hfc.dem_majority_prob >= .5 else "rep")}
{tile("National environment", m(hf['expected_national_margin']), f"GB two-party {m(hf.get('generic_ballot_two_party'))} · net approval {ne.get('approval_net')} · CPI {econ_snap.get('cpi_yoy', '—')}%")}
</div>
<div class="grid2">
 <div class="panel"><h3>Senate — P(D) by race</h3>{svg_map(paths, sen_fill, sen_lbl, "Senate P(D)", [(prob_color(0.1), "R favoured"), (prob_color(0.5), "toss-up"), (prob_color(0.9), "D favoured")], sen_tip)}
 <p class="note">Nine simulated races; grey states have no modelled 2026 race (safe or unpolled). Hover for candidates and margin.</p></div>
 <div class="panel"><h3>House — expected D seat change vs 2024, by state</h3>{svg_map(paths, house_fill, house_lbl, "House seat change", [(delta_color(-3, 3), "R gains"), (NEUTRAL, "no change"), (delta_color(3, 3), "D gains")], house_tip)}
 <p class="note">Sum of district win probabilities minus 2024 D seats, plus the configured redistricting shift (TX −5, CA +5, MO/NC/OH −1, UT +1). Labelled where |change| ≥ 0.8.</p></div>
</div>
<div class="grid2">
 <div class="panel"><h3>Senate model — features and values used</h3>{features_table(senate_features)}
  <h3>Importance — Δ P(control) across each knob's grid</h3>{sen_imp_bars}<p class="note">From config/sensitivity_analysis.json (re-run {sens.get('generated', '')[:10]}); baseline {pct(sens['baseline']['dem_control_prob'])}.</p></div>
 <div class="panel"><h3>House model — features and values used</h3>{features_table(house_features)}
  <h3>Importance — Δ P(majority) across each knob's grid</h3>{house_imp_bars}<p class="note">One-at-a-time, {args.importance_sims:,} sims per point, computed in this run.</p></div>
</div>
<div class="panel warn"><h3>Gut-check flags</h3><ul class="note">{''.join(f'<li>{esc(g)}</li>' for g in gut)}</ul>
<div class="kv"><b>Pipeline run</b><span>{esc(meta.get('last_updated', ''))}</span><b>Polls</b><span>{esc(meta.get('poll_counts'))}</span><b>Calibration</b><span>{calib['n_races']} Senate races {calib['cycles']}, σ_nat {calib['national_sigma']}, σ_race {calib['race_sigma']}, pooled bias {calib['bias']}; Brier {calib['brier_score']}</span><b>Report built</b><span>{datetime.now().isoformat(timespec='seconds')}</span></div></div>
"""

    # ── House page
    comp = sorted([d for d in hfc.districts if 0.1 <= d.dem_win_prob <= 0.9], key=lambda d: abs(d.dem_win_prob - 0.5))
    comp_rows = [[
        f"{esc(d.label)}{' ↻' if d.state in redraw else ''}", m(d.margin_2024) + f" ({d.winner_2024})", m(d.margin_2022) if d.margin_2022 is not None else "—",
        m(d.lean), (f"open ({sgn(d.incumbency_adjust)})" if d.open_seat else f"{d.incumbent_party} ✓"),
        f"{m(d.state_pres_2024)} / {m(d.state_pres_2020)}", sgn(d.state_trend_adjust, 2), sgn(d.econ_adjust, 2),
        m(d.expected_margin),
        f"{m(d.margin_p10)}…{m(d.margin_p90)}", f'<span class="{"dem" if d.dem_win_prob >= .5 else "rep"}"><b>{pct(d.dem_win_prob)}</b></span>'
    ] for d in comp]
    state_rows = [[esc(st), str(s["n"]), str(s["d24"]), f"{s['exp']:.1f}", sgn(s["shift"], 0) if s["shift"] else "—", f'<b class="{"dem" if s["change"] >= 0 else "rep"}">{s["change"]:+.1f}</b>', str(s["open"]), "↻" if st in redraw else ""]
                  for st, s in sorted(by_state.items(), key=lambda kv: -abs(kv[1]["change"]))]
    open_rows = [[esc(d.label), esc(d.open_seat_reason), m(d.lean), m(d.expected_margin), pct(d.dem_win_prob)] for d in sorted(hfc.districts, key=lambda d: d.label) if d.open_seat]
    himp_rows = [[esc(r["feature"]), esc(r["key"]), esc(", ".join(f"{v if not isinstance(v, list) else 'none'} → {pct(p, 1)} ({s:.1f})" for v, p, s in r["grid"])), f"{r['spread']:.3f}", f"{r['seat_spread']:.1f}"] for r in himp]
    rd_rows = [[esc(r["state"]), sgn(r["dem_seat_shift"], 0), str(r.get("sd")), esc(r.get("note", ""))] for r in hfc.redistricting_states]
    house_page = f"""
<div class="tiles">
{tile("P(D majority)", pct(hfc.dem_majority_prob), f"{args.house_sims:,} simulations", "dem" if hfc.dem_majority_prob >= .5 else "rep")}
{tile("Mean / median D seats", f"{hfc.mean_dem_seats:.1f} / {hfc.median_dem_seats:.0f}", f"80% range {hfc.seats_p10:.0f}–{hfc.seats_p90:.0f}; 2024: 215 D / 220 R")}
{tile("Expected flips", f"{sum(d.dem_win_prob for d in hfc.districts if d.winner_2024 == 'R'):.1f} / {sum(1 - d.dem_win_prob for d in hfc.districts if d.winner_2024 == 'D'):.1f}", "R→D / D→R, before redistricting shift")}
{tile("Tipping-point margin", m(hfc.tipping_point_margin), "national two-party margin where expected seats = 218")}
{tile("Swing applied", m(hfc.national_swing), f"expected {m(hfc.expected_national_margin)} vs 2024 {m(hfc.baseline_margin)}")}
</div>
<div class="grid2">
 <div class="panel"><h3>Seat distribution</h3>{svg_histogram(dict((str(k), v) for k, v in hfc.seat_distribution.items()), hfc.dem_majority_threshold, hfc.num_simulations, bin_width=2)}</div>
 <div class="panel"><h3>Seats–votes curve of the current map</h3>{svg_curve(hfc.seats_by_margin, hfc.dem_majority_threshold, hfc.expected_national_margin, hfc.mean_dem_seats)}</div>
</div>
<div class="panel"><h3>National environment inputs</h3><div class="kv">
<b>Generic ballot (raw / two-party)</b><span>{m(hf.get('generic_ballot_raw_margin'))} / {m(hf.get('generic_ballot_two_party'))} (weight {hcfg['national_environment']['generic_weight']})</span>
<b>Net approval → implied margin</b><span>{hf.get('approval_net')} × {hcfg['national_environment']['approval_to_margin_coef']} = {m(hf.get('approval_implied_margin'))} (weight {hcfg['national_environment']['approval_weight']})</span>
<b>Blend, bias, inflation</b><span>{m(hf.get('raw_national_margin'))} + ({hf['generic_ballot_bias']}) + ({hf.get('economy', {}).get('national', {}).get('inflation_effect', 0):+.2f} inflation) = <b>{m(hf['expected_national_margin'])}</b></span>
<b>State terms</b><span>trend {hfc.state_trend_weight} × [(state '24 − '20) − national {hfc.national_trend:+.1f}]; state gas/unemployment deviations × ({h_econ.get('gas_deviation_coef')}, {h_econ.get('unemployment_deviation_coef')}) — {'live' if h_snap.get('states_with_gas') else 'pending fetch (0 for now)'}</span>
<b>National error</b><span>σ = {hf['polling_sigma']} (historical generic-ballot miss) ⊕ {hf['campaign_drift_sigma']:.2f} drift ({hf['days_to_election']} days) = {hf['national_sigma']:.2f}, t({hf.get('tail_dof')})</span>
<b>District error</b><span>σ = {hf['district_sigma']} per district; {hfc.similarity_share:.0%} of it shared via same-state/region/lean similarity (weights {hfc.similarity_weights}, lean scale {hfc.lean_scale})</span>
<b>District lean</b><span>{hfc.lean_weight_2024}×2024 + {hfc.lean_weight_2022}×2022 two-party margin; open seats −{hfc.incumbency_advantage} for the departing party ({hfc.num_open_seats} flagged)</span>
</div></div>
<div class="panel"><h3>Closest {len(comp)} districts (P(D) 10–90%) — every input value</h3>
{table([("District", False), ("2024", True), ("2022", True), ("Lean", True), ("Incumbent", True), ("State pres '24 / '20", True), ("State trend", True), ("Economy", True), ("Expected", True), ("80% range", True), ("P(D)", True)], comp_rows, "Expected = lean + incumbency adjustment + state trend + state economy + national swing. ↻ = state redrawn since 2024: the district row is on the old lines; the state's net effect enters through the redistricting shift.")}</div>
<div class="grid2">
 <div class="panel"><h3>Per-state rollup</h3>{table([("State", False), ("Seats", True), ("D 2024", True), ("Expected D", True), ("Redistrict", True), ("Change", True), ("Open", True), ("", False)], state_rows)}</div>
 <div><div class="panel"><h3>Open seats used ({len(open_rows)})</h3>{table([("District", False), ("Reason", False), ("Lean", True), ("Expected", True), ("P(D)", True)], open_rows, "Hand-entered Oct 2026 — verify.")}</div>
 <div class="panel"><h3>Redistricting shifts</h3>{table([("State", False), ("D seats", True), ("sd", True), ("Note", False)], rd_rows)}</div></div>
</div>
<div class="panel"><h3>Feature importance — one-at-a-time ({args.importance_sims:,} sims per point)</h3>{table([("Feature", False), ("Config key", False), ("Grid → P(majority) (mean seats)", False), ("Δ P", True), ("Δ seats", True)], himp_rows)}</div>
"""

    # ── Senate page
    names = [r.state for r in sfc.races]
    srows, orows = [], []
    he = sf.get("house_effects", {})
    for i, r in enumerate(sfc.races):
        f = r.fundamentals or {}
        hrow = he.get(r.state) or {}
        orows.append([
            f"<b>{esc(r.state)}</b>", f"<b>{m(r.margin)}</b>", svg_margin_hist(hist_by_state.get(r.state, [])),
            pct(r.dem_win_prob_polls),
            f'<span class="{"dem" if (r.dem_win_prob_sim or 0) >= .5 else "rep"}"><b>{pct(r.dem_win_prob_sim)}</b></span>',
            f"{m(r.median_margin)} ({m(r.margin_p10)}…{m(r.margin_p90)})",
            f"{sen['leverage'][i]:.2f}", pct(sen["tipping"][i]),
        ])
        ls = f.get("last_senate") or {}
        ec = f.get("economy") or {}
        srows.append([
            f"<b>{esc(r.state)}</b><br><span class='note'>{esc(r.dem_candidate)} v {esc(r.rep_candidate)}</span>",
            f"{m(f.get('pres_2024'))} / {m(f.get('pres_2020'))}",
            (f"{m(ls.get('margin'))} ({ls.get('year')})<br><span class='note'>{esc(ls.get('race', ''))}</span>") if ls else "—",
            f"{m(f.get('lean'))}<br><span class='note'>{sgn(f.get('pres_2020_shift_effect'), 2)} '20, {sgn(f.get('last_senate_shift_effect'), 2)} last</span>",
            sgn(f.get("national_swing")),
            (f"{f.get('incumbent_party')} · {f.get('incumbent_years')}y{' appt.' if f.get('incumbent_appointed') else ''}<br>{sgn(f.get('incumbency_effect'))} + tenure {sgn(f.get('tenure_effect'), 2)}" if f.get("incumbent_party") else "open"),
            f"{f.get('dem_office_years', 0)} / {f.get('rep_office_years', 0)}<br>{sgn(f.get('office_years_effect'), 2)}",
            f"{f.get('dem_statewide_wins', 0)}–{f.get('dem_statewide_losses', 0)} / {f.get('rep_statewide_wins', 0)}–{f.get('rep_statewide_losses', 0)}<br>{sgn(f.get('experience_effect'), 2)}",
            f"{sgn(f.get('economy_effect'), 2)}<br><span class='note'>{', '.join(ec.get('available', [])) or 'none'}</span>",
            f"<b>{m(f.get('prior'))}</b>",
            (f"{m(f.get('poll_margin'))} ({f.get('num_polls')})" + (f"<br><span class='note'>raw {m(f.get('poll_margin') - hrow.get('adjustment', 0) if f.get('poll_margin') is not None and hrow.get('adjustment') is not None else None)}, HE {sgn(hrow.get('adjustment'))} on {hrow.get('polls_adjusted')}/{hrow.get('polls_total')}</span>" if hrow else "")) if f.get("poll_margin") is not None else "—",
            pct(f.get("fundamentals_weight")), f"<b>{m(r.margin)}</b>",
        ])
    sens_rows_html = [[esc(k["knob"]), esc(k["description"]), esc("; ".join(f"{g['value']} → {pct(g['dem_control_prob'])}" for g in k["grid"])), f"{k['spread_across_grid']:.3f}"] for k in sens_rows]
    he_table = _house_effect_rows(calib, cycle)
    senate_page = f"""
<div class="tiles">
{tile("P(D control)", pct(sfc.dem_control_prob), f"{args.senate_sims:,} simulations; need {sf['dem_majority_threshold']} (VP is R)", "dem" if sfc.dem_control_prob >= .5 else "rep")}
{tile("Mean / median D seats", f"{sfc.mean_dem_seats:.2f} / {sfc.median_dem_seats:.0f}", f"{sf['dem_safe_seats']} safe D + {len(sfc.races)} simulated races")}
{tile("Economy", f"CPI {econ_snap.get('cpi_yoy', '—')}%", f"as of {econ_snap.get('as_of', '—')}; gas/unemployment {'live' if econ_snap.get('states_with_gas') else 'pending'}")}
{tile("Error model", f"σ {sf['national_sigma']} / {sf['race_sigma']}", f"national ⊕ drift / race; bias {sf.get('bias')}; t({sf.get('tail_dof')}); similarity {sf.get('similarity_share')}")}
{tile("National swing", sgn(ne.get('national_swing')), f"approval {ne.get('approval_net')} → {sgn(ne.get('approval_implied_margin'))}; GB {sgn(ne.get('generic_margin'))}; vs 2024 House {ne.get('house_baseline_2024')}")}
</div>
<div class="panel"><h3>Inputs — every race, every value used</h3>
{table([("Race", False), ("Pres '24 / '20", True), ("Last Senate race", True), ("Lean", True), ("Swing", True), ("Incumbent (yrs)", True), ("Office yrs D / R", True), ("Record D / R", True), ("Economy", True), ("Prior", True), ("Polls (n)", True), ("Prior wt", True), ("Final margin", True)], srows,
"Lean = 2024 presidential margin + %s × (2020 − 2024) + %s × (last Senate − 2024). Prior = lean + swing + incumbency + tenure + office years + record + economy. Final = (1−w)·polls + w·prior, w = k/(k+n). HE = house-effect correction from the pollster-grade analysis (relative mean error, shrunk, capped ±%s), applied to each matched poll before averaging; 'raw' is the uncorrected average." % (coefs.get('pres_2020_shift_weight'), coefs.get('last_senate_shift_weight'), cycle.get('polls', {}).get('house_effect_cap')))}</div>
<div class="panel"><h3>Outcomes — {args.senate_sims:,} correlated simulations</h3>
{table([("Race", False), ("Final margin", True), ("Simulated margin", False), ("P(D) analytic", True), ("P(D) sim", True), ("Median (80% range)", True), ("Leverage", True), ("Tipping", True)], orows,
"Leverage = P(control | D wins race) − P(control | D loses race). Tipping = share of simulations in which this race is exactly the 51st Democratic seat.")}</div>
<div class="grid2">
 <div class="panel"><h3>Seat distribution</h3>{svg_histogram(dict((str(k), v) for k, v in sfc.seat_distribution.items()), sf['dem_majority_threshold'], sfc.num_simulations)}</div>
 <div class="panel"><h3>Implied correlation of total error between races</h3>{svg_corr([abbr_by_state[n] for n in names], sfc.error_correlation)}
 <p class="note">National σ shared by all races plus {sf.get('similarity_share', 0):.0%} of race variance shared through region ({sf.get('correlation', {}).get('region_weight')}) and 2024-lean proximity (scale {sf.get('correlation', {}).get('lean_scale')} pts). Ohio–Iowa–Michigan and Maine–New Hampshire move together more than Georgia–Maine.</p></div>
</div>
<div class="panel"><h3>Pollster house effects applied (from config/forecast_calibration.json)</h3>{he_table}</div>
<div class="panel"><h3>Knob sensitivity — Δ P(D control) across each grid (config/sensitivity_analysis.json)</h3>{table([("Knob", False), ("What it is", False), ("Grid → P(control)", False), ("Spread", True)], sens_rows_html)}</div>
<div class="panel"><h3>Error-model provenance</h3><div class="kv">
<b>Calibration</b><span>{calib['n_races']} Senate races, cycles {calib['cycles']}, final-{calib['lookback_days']}-day polls vs results; per-cycle mean error {calib['cycle_mean_error']}</span>
<b>Bias used</b><span>{bc.get('cycle_type')} cycles {bc.get('years')} ({bc.get('n_races')} races): {bc.get('raw_bias')} × weight {bc.get('weight')} = <b>{bc.get('applied')}</b> pts on every margin</span>
<b>Sigmas</b><span>national {sf.get('polling_national_sigma')} ⊕ drift {sf.get('campaign_drift_sigma')} ({sf.get('days_to_election')} days × {cycle['forecast'].get('campaign_drift_per_sqrt_day')}/√day) = {sf['national_sigma']}; race {sf['race_sigma']}</span>
<b>Tails</b><span>t({sf.get('tail_dof')}) — backtest Brier {calib['tail_comparison']['t5']['brier']} vs Gaussian {calib['tail_comparison']['gaussian']['brier']}</span>
<b>Market blend</b><span>weight {sf['market_weight']} — polls + fundamentals only</span>
<b>Economy</b><span>CPI {econ_snap.get('cpi_yoy', '—')}% ({econ_snap.get('as_of', '—')}, {esc(econ_snap.get('sources', {}).get('cpi_yoy', ''))}); gas prices and state unemployment {'live' if econ_snap.get('states_with_gas') else 'pending the keyed EIA / BLS fetch'}; coefficients {esc(coefs.get('economy'))}</span>
</div></div>
"""

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Forecast run {today.isoformat()}</title><style>{CSS}</style></head><body>
<header><h1>Election Oracle — under the hood · {today.isoformat()}</h1>
<p class="sub">One run of both chamber models with every input exposed. Senate {args.senate_sims:,} and House {args.house_sims:,} correlated simulations; Policy &amp; Peaches internal gut-check, not the public site.</p>
<nav class="tabs"><button class="on" data-page="overview">Overview</button><button data-page="house">House</button><button data-page="senate">Senate</button></nav></header>
<main>
<section id="overview" class="page on">{overview}</section>
<section id="house" class="page">{house_page}</section>
<section id="senate" class="page">{senate_page}</section>
</main><script>{JS}</script></body></html>"""

    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"forecast_report_{today.isoformat()}.html"
    out.write_text(page, encoding="utf-8")
    shutil.copy(out, REPORT_DIR / "latest.html")
    summary = {
        "as_of": today.isoformat(), "built": datetime.now().isoformat(timespec="seconds"),
        "senate": {"num_simulations": args.senate_sims, "dem_control_prob": sfc.dem_control_prob,
                   "mean_dem_seats": sfc.mean_dem_seats, "seat_distribution": sfc.seat_distribution,
                   "races": [{"state": r.state, "margin": r.margin, "p_polls": r.dem_win_prob_polls,
                              "p_sim": r.dem_win_prob_sim,
                              "leverage": round(sen["leverage"][i], 4), "tipping": round(sen["tipping"][i], 4),
                              "fundamentals": r.fundamentals} for i, r in enumerate(sfc.races)],
                   "error_correlation": sfc.error_correlation, "knob_importance": [
                       {"knob": k["knob"], "spread": k["spread_across_grid"]} for k in sens_rows]},
        "house": {"num_simulations": args.house_sims, "dem_majority_prob": hfc.dem_majority_prob,
                  "mean_dem_seats": hfc.mean_dem_seats, "seats_p10": hfc.seats_p10, "seats_p90": hfc.seats_p90,
                  "tipping_point_margin": hfc.tipping_point_margin, "importance": himp,
                  "by_state": by_state, "num_competitive": len(comp)},
    }
    (REPORT_DIR / f"run_{today.isoformat()}.json").write_text(json.dumps(summary, indent=1, default=float))
    shutil.copy(REPORT_DIR / f"run_{today.isoformat()}.json", REPORT_DIR / "latest.json")
    print(f"Wrote {out.relative_to(PROJECT_ROOT)} (+ latest.html, run json)")
    return out


def _house_effect_rows(calib: dict, cycle: dict) -> str:
    from scripts.export_json import _house_effect_table

    pc = cycle.get("polls", {})
    tbl = _house_effect_table(calib, pc.get("house_effect_shrink_k", 10.0), pc.get("house_effect_cap", 2.5))
    rows = sorted(tbl.values(), key=lambda r: r["effect"])
    return table(
        [("Pollster", False), ("n (2018–24)", True), ("Mean error", True), ("Relative", True), ("Applied", True)],
        [[esc(r["pollster"]), str(r["n_polls"]), sgn(r["mean_error"], 2), sgn(r["relative_error"], 2), f"<b>{sgn(r['effect'], 2)}</b>"] for r in rows],
        f"Mean error = actual − poll (Dem−Rep), pooled mean {calib['bias']}; relative = mean − pooled; applied = relative × n/(n+{pc.get('house_effect_shrink_k')}), capped ±{pc.get('house_effect_cap')}. Positive = pollster understated Democrats → its polls shifted toward D.",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the under-the-hood forecast report.")
    ap.add_argument("--senate-sims", type=int, default=500_000)
    ap.add_argument("--house-sims", type=int, default=200_000)
    ap.add_argument("--importance-sims", type=int, default=30_000)
    ap.add_argument("--seed", type=int, default=20261103)
    build(ap.parse_args())


if __name__ == "__main__":
    main()
