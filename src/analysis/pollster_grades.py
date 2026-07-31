"""Empirical pollster grades built from this project's own backtest.

This replaces the imported Silver Bulletin error table (``src/data/pollster_ratings``)
with a rating fitted here, from raw polls matched to certified results.

The metric is *par error*: how far a poll landed from the result, minus how far
the rest of the field landed from the result on the same race. Grading against
par rather than against raw error is the whole point — a pollster who works
Georgia Senate races is not worse than one who works California, they are
working a harder problem. Par is computed leave-one-out so a pollster who
dominates a race is never scored against itself.

Two numbers come out of each pollster's record:

``par_error``  mean (|poll error| − |par error|), recency-weighted. Negative is
               better than the field. This drives the grade and the weight.
``lean``       mean signed error, Democratic margin minus actual. Positive means
               the house reads friendlier to Democrats than the result. This is
               reported but deliberately does NOT drive the grade — a house with
               a large, *stable* lean is correctable, and penalising it twice
               (once in the grade, once in the bias term) double-counts.

Both are shrunk toward the pool with an empirical-Bayes weight n/(n+K), so a
pollster with four polls cannot top the table on noise.

Fit with ``scripts/build_pollster_grades.py``; consumed via
``config/pollster_grades.json``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# General elections only. Primaries are a different forecasting problem and
# their errors are an order of magnitude larger; mixing them in would grade
# pollsters on which races they happen to cover.
GENERAL_TYPES = frozenset({"Pres-G", "Sen-G", "Gov-G", "House-G"})

# A race needs this many polls before leave-one-out par is meaningful.
MIN_POLLS_PER_RACE = 3

# Empirical-Bayes shrinkage constant, in polls. A pollster with K polls is
# pulled halfway to the pool mean. Tuned on two holdout splits (train ≤2016
# scored on 2018-2022, train ≤2018 scored on 2020-2022); 10 is the value that
# is at or near the optimum on both.
SHRINK_K = 10.0

# Recency half-life in cycles, or None for no decay.
#
# None is not an oversight. Decaying old cycles was tested against both holdout
# splits at every shrinkage constant and lost every time — monotonically, and
# by more the harder the decay:
#
#     half-life   train ≤2016   train ≤2018     (mean abs error, k=10)
#     2 cycles       4.6234        4.9014
#     4 cycles       4.5727        4.7604
#     8 cycles       4.5523        4.7190
#     none           4.5342        4.6588
#
# Lowering SHRINK_K does not rescue decay, so this is not an effective-sample-
# size artefact: old polls genuinely carry information about a house's lean.
# That is the opposite of how recency works when *averaging* polls, and the two
# should not be confused — an old poll is bad evidence about today's race and
# good evidence about a pollster's methodology.
#
# Caveat: only testable through 2022, which is where the archive ends. Re-tune
# once a 2024 corpus is available, since a regime shift in methodology is
# exactly the thing that would make decay start paying.
RECENCY_HALF_LIFE_CYCLES: float | None = None

# Minimum recency-weighted polls before a pollster is graded at all.
MIN_POLLS_TO_GRADE = 8.0

# Letter cuts as percentiles of the graded pool, best first. Grading on the
# distribution rather than on fixed error thresholds keeps the letters stable
# as polling accuracy drifts between cycles.
GRADE_PERCENTILES: tuple[tuple[float, str], ...] = (
    (0.05, "A+"), (0.15, "A"), (0.30, "A-"),
    (0.45, "B+"), (0.60, "B"), (0.72, "B-"),
    (0.82, "C+"), (0.90, "C"), (0.96, "C-"),
    (1.00, "D"),
)


@dataclass(frozen=True)
class RawPoll:
    """One poll from the archive, matched to its certified result."""

    pollster: str
    cycle: int
    race_id: str
    race_type: str
    location: str
    time_to_election: int
    sample_size: int | None
    methodology: str
    partisan: str | None
    dem_margin_poll: float
    dem_margin_actual: float

    @property
    def signed_error(self) -> float:
        """Poll minus result, in Democratic margin. Positive = overstated Dems."""
        return self.dem_margin_poll - self.dem_margin_actual

    @property
    def abs_error(self) -> float:
        return abs(self.signed_error)


@dataclass
class PollsterRecord:
    """A pollster's graded track record."""

    pollster: str
    n_polls: int
    n_races: int
    n_weighted: float
    cycles: list[int]
    last_cycle: int
    raw_abs_error: float
    par_error: float
    par_error_shrunk: float
    lean: float
    lean_shrunk: float
    quality: float = 0.0
    grade: str = ""
    percentile: float = 0.0
    methodology: str = ""
    partisan_share: float = 0.0

    def to_dict(self) -> dict:
        return {
            "pollster": self.pollster,
            "grade": self.grade,
            "quality": round(self.quality, 3),
            "par_error": round(self.par_error, 3),
            "par_error_shrunk": round(self.par_error_shrunk, 3),
            "raw_abs_error": round(self.raw_abs_error, 3),
            "lean": round(self.lean, 3),
            "lean_shrunk": round(self.lean_shrunk, 3),
            "n_polls": self.n_polls,
            "n_races": self.n_races,
            "n_weighted": round(self.n_weighted, 1),
            "cycles": self.cycles,
            "last_cycle": self.last_cycle,
            "percentile": round(self.percentile, 4),
            "methodology": self.methodology,
            "partisan_share": round(self.partisan_share, 3),
        }


def normalize_poll_row(row: dict) -> RawPoll | None:
    """Turn one ``raw_polls.csv`` row into a RawPoll, or None if unusable.

    Drops anything that is not a straight Democrat-versus-Republican general,
    since a signed Democratic error is undefined otherwise.
    """
    if row.get("type_simple") not in GENERAL_TYPES:
        return None
    p1, p2 = row.get("cand1_party"), row.get("cand2_party")
    try:
        margin_poll = float(row["margin_poll"])
        margin_actual = float(row["margin_actual"])
    except (TypeError, ValueError, KeyError):
        return None
    if p1 == "DEM" and p2 == "REP":
        dem_poll, dem_actual = margin_poll, margin_actual
    elif p1 == "REP" and p2 == "DEM":
        dem_poll, dem_actual = -margin_poll, -margin_actual
    else:
        return None
    if not math.isfinite(dem_poll) or not math.isfinite(dem_actual):
        return None
    try:
        sample = int(float(row["samplesize"]))
    except (TypeError, ValueError, KeyError):
        sample = None
    try:
        ttoe = int(float(row["time_to_election"]))
    except (TypeError, ValueError, KeyError):
        return None
    partisan = (row.get("partisan") or "").strip() or None
    return RawPoll(
        pollster=(row.get("pollster") or "").strip(),
        cycle=int(row["cycle"]),
        race_id=str(row["race_id"]),
        race_type=row["type_simple"],
        location=row.get("location", ""),
        time_to_election=ttoe,
        sample_size=sample,
        methodology=(row.get("methodology") or "").strip(),
        partisan=partisan if partisan not in {"NA", "nan"} else None,
        dem_margin_poll=dem_poll,
        dem_margin_actual=dem_actual,
    )


def _time_adjustment(polls: list[RawPoll]) -> dict[int, float]:
    """Mean absolute error by time-to-election bucket, over the whole corpus.

    Leave-one-out par already absorbs race difficulty, but not the fact that a
    race's polls are spread over two months. Without this a pollster who fields
    early is penalised for fielding early.
    """
    buckets: dict[int, list[float]] = {}
    for p in polls:
        buckets.setdefault(min(p.time_to_election // 7, 8), []).append(p.abs_error)
    overall = sum(p.abs_error for p in polls) / len(polls)
    return {
        b: (sum(v) / len(v)) - overall
        for b, v in buckets.items()
        if len(v) >= 30
    }


def _recency_weight(cycle: int, latest_cycle: int) -> float:
    if RECENCY_HALF_LIFE_CYCLES is None:
        return 1.0
    cycles_back = max(0, (latest_cycle - cycle)) / 2.0  # cycles, not years
    return 0.5 ** (cycles_back / RECENCY_HALF_LIFE_CYCLES)


def build_records(
    polls: Iterable[RawPoll],
    *,
    shrink_k: float = SHRINK_K,
    min_weighted: float = MIN_POLLS_TO_GRADE,
) -> list[PollsterRecord]:
    """Score every pollster against leave-one-out par and grade the field."""
    polls = [p for p in polls if p.pollster]
    if not polls:
        return []
    latest = max(p.cycle for p in polls)

    by_race: dict[str, list[RawPoll]] = {}
    for p in polls:
        by_race.setdefault(p.race_id, []).append(p)

    tadj = _time_adjustment(polls)

    # Leave-one-out par: the field's error on this race, excluding this poll.
    scored: list[tuple[RawPoll, float, float]] = []  # poll, vs_par, weight
    for race_polls in by_race.values():
        if len(race_polls) < MIN_POLLS_PER_RACE:
            continue
        total = sum(p.abs_error for p in race_polls)
        n = len(race_polls)
        for p in race_polls:
            par = (total - p.abs_error) / (n - 1)
            # Both sides get the same time correction so it cancels for polls
            # fielded at the same moment, and only bites when they differ.
            adj = tadj.get(min(p.time_to_election // 7, 8), 0.0)
            par_adj = par + adj - (
                sum(tadj.get(min(q.time_to_election // 7, 8), 0.0) for q in race_polls if q is not p)
                / (n - 1)
            )
            scored.append((p, p.abs_error - par_adj, _recency_weight(p.cycle, latest)))

    # Every race may have been too thin to score against a field.
    if not scored:
        return []

    by_pollster: dict[str, list[tuple[RawPoll, float, float]]] = {}
    for item in scored:
        by_pollster.setdefault(item[0].pollster, []).append(item)

    # Pool mean of vs-par is ~0 by construction; shrink toward it explicitly.
    pool_w = sum(w for _, _, w in scored)
    pool_par = sum(v * w for _, v, w in scored) / pool_w
    pool_lean = sum(p.signed_error * w for p, _, w in scored) / pool_w

    records: list[PollsterRecord] = []
    for name, items in by_pollster.items():
        wsum = sum(w for _, _, w in items)
        if wsum < min_weighted:
            continue
        par = sum(v * w for _, v, w in items) / wsum
        lean = sum(p.signed_error * w for p, _, w in items) / wsum
        raw_abs = sum(p.abs_error * w for p, _, w in items) / wsum
        k = shrink_k
        par_s = (wsum * par + k * pool_par) / (wsum + k)
        lean_s = (wsum * lean + k * pool_lean) / (wsum + k)
        cycles = sorted({p.cycle for p, _, _ in items})
        methods = [p.methodology for p, _, _ in items if p.methodology]
        records.append(PollsterRecord(
            pollster=name,
            n_polls=len(items),
            n_races=len({p.race_id for p, _, _ in items}),
            n_weighted=wsum,
            cycles=cycles,
            last_cycle=cycles[-1],
            raw_abs_error=raw_abs,
            par_error=par,
            par_error_shrunk=par_s,
            lean=lean,
            lean_shrunk=lean_s,
            methodology=max(set(methods), key=methods.count) if methods else "",
            partisan_share=sum(1 for p, _, _ in items if p.partisan) / len(items),
        ))

    _assign_grades(records)
    return sorted(records, key=lambda r: r.par_error_shrunk)


def _assign_grades(records: list[PollsterRecord]) -> None:
    """Percentile cuts on shrunk par error, best first."""
    ordered = sorted(records, key=lambda r: r.par_error_shrunk)
    n = len(ordered)
    for i, rec in enumerate(ordered):
        pctile = (i + 0.5) / n
        rec.percentile = pctile
        for cut, letter in GRADE_PERCENTILES:
            if pctile <= cut:
                rec.grade = letter
                break
        else:
            rec.grade = GRADE_PERCENTILES[-1][1]
        rec.quality = quality_from_par(rec.par_error_shrunk)


def quality_from_par(par_error: float) -> float:
    """Map par error (points, negative is better) onto the engine's 0–3 scale.

    The engine multiplies poll weight by ``(quality/3) ** exponent``, so this
    only needs to be monotone decreasing in error and land the realistic range
    near the middle of the scale. 1.5 is par; each point of error better than
    par is worth 0.3 of quality, matching the slope the engine was tuned
    against so the change of rating source does not silently rescale weights.
    """
    return max(0.0, min(3.0, 1.5 - par_error * 0.3))


def unknown_default(records: list[PollsterRecord]) -> float:
    """Quality for a pollster with no track record: 25th percentile of the pool.

    A house nobody has scored is more likely to be mediocre than average —
    the graded pool is survivorship-filtered toward shops that lasted.
    """
    qs = sorted(r.quality for r in records)
    return round(qs[len(qs) // 4], 3) if qs else 1.408


def load_grades(path: Path | None = None) -> dict:
    path = path or Path(__file__).resolve().parents[2] / "config" / "pollster_grades.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ── name resolution ──────────────────────────────────────────────────────────
#
# The archive and the live feeds spell the same shop differently, and the live
# feeds also tag state polls with a sponsor party. Matching on a stripped key
# rather than the literal string is what lifted grade coverage of the 2026 poll
# volume from 22% to 76%.

_NOISE = re.compile(
    r"\b(the|inc|llc|co|company|group|polling|research|university|college|institute"
    r"|school|of|public|opinion|center|centre|strategies|associates|partners)\b"
)
_PARTY_TAG = re.compile(r"\s*\((d|r|i)\)", re.I)

# Same organisation, different masthead. Left side is what a feed may emit.
NAME_ALIASES: dict[str, str] = {
    # CNN's field work is SSRS; AP-NORC has only four archive polls and does not
    # clear the grading threshold, so it stays unrated rather than borrowing one.
    "cnn/ssrs": "SSRS",
    "cnn": "SSRS",
    "harrisx": "Harris Insights & Analytics",
    "harris poll": "Harris Insights & Analytics",
    "harrisx/harris": "Harris Insights & Analytics",
    "harrisx/harris poll": "Harris Insights & Analytics",
    "new york times/siena university": "The New York Times/Siena College",
    "new york times/siena college": "The New York Times/Siena College",
    "nyt/siena": "The New York Times/Siena College",
    "umass lowell": "University of Massachusetts Lowell",
    "reuters/ipsos": "Ipsos",
    "ppp": "Public Policy Polling",
    "fox news": "Beacon Research/Shaw & Co. Research",
    "marquette law school": "Marquette University Law School",
    "monmouth university": "Monmouth University Polling Institute",
    "john zogby strategies": "Zogby Analytics",
    "abc news/washington post": "ABC News/The Washington Post",
    "nbc news/marist": "Marist College",
    "cbs news/yougov": "YouGov",
    "the economist": "YouGov",
}


def normalize_name(name: str) -> str:
    """Collapse a pollster name to a match key: no party tag, no filler words."""
    s = _PARTY_TAG.sub("", (name or "").lower())
    s = s.replace("&", "and").replace("/ ", "/")
    s = _NOISE.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


class GradeBook:
    """Look up a pollster's fitted grade by whatever name a feed used."""

    def __init__(self, payload: dict | None = None) -> None:
        payload = payload if payload is not None else load_grades()
        self.meta: dict = payload.get("_meta", {})
        self.records: dict[str, dict] = {
            r["pollster"]: r for r in payload.get("grades", [])
        }
        self.unknown_quality: float = self.meta.get("unknown_default", 1.408)
        self._pool_lean: float | None = None
        # Region-scoped leans, e.g. {"battleground_2026": {"states": [...],
        # "leans": {pollster: lean}}}. Fitting the lean on the states you are
        # actually forecasting beats both a national lean and a per-state one —
        # see docs in relative_lean().
        self.regions: dict = payload.get("regions", {})
        self._index: dict[str, str] = {}
        for name in self.records:
            self._index.setdefault(normalize_name(name), name)
        for alias, target in NAME_ALIASES.items():
            if target in self.records:
                self._index.setdefault(normalize_name(alias), target)

    def resolve(self, name: str) -> str | None:
        """Canonical graded name for ``name``, or None if it has no record."""
        key = normalize_name(name)
        if key in self._index:
            return self._index[key]
        alias = NAME_ALIASES.get(_PARTY_TAG.sub("", (name or "").lower()).strip())
        return alias if alias in self.records else None

    def get(self, name: str) -> dict | None:
        canon = self.resolve(name)
        return self.records.get(canon) if canon else None

    def quality(self, name: str) -> float:
        rec = self.get(name)
        return rec["quality"] if rec else self.unknown_quality

    def grade(self, name: str) -> str | None:
        rec = self.get(name)
        return rec["grade"] if rec else None

    @property
    def pool_lean(self) -> float:
        """Volume-weighted mean fitted lean of the graded pool.

        The whole field overstates Democrats by about this much. Downstream
        models already carry a calibrated bias term fitted against that same
        systematic error, so house-effect corrections must be centred on this
        value or the shift gets applied twice.
        """
        if self._pool_lean is None:
            recs = list(self.records.values())
            w = sum(r["n_weighted"] for r in recs) or 1.0
            self._pool_lean = sum(r["lean_shrunk"] * r["n_weighted"] for r in recs) / w
        return self._pool_lean

    def lean(self, name: str) -> float:
        """Fitted house effect in Democratic margin; 0.0 for an unrated house."""
        rec = self.get(name)
        return rec["lean_shrunk"] if rec else 0.0

    def relative_lean(self, name: str, region: str | None = None) -> float:
        """House effect net of the field's systematic lean.

        This is the number to subtract from a poll when the model downstream
        also applies a calibrated bias term. An unrated house is treated as
        average, which is the honest default: we know nothing about it.

        Pass ``region`` to use a lean fitted on that region's races instead of
        the national one. A firm's lean is not a constant — it moves by five to
        seven points between states — and on held-out battleground races a
        region-scoped lean beats the national figure on both validation splits:

            correction                 fit ≤2016   fit ≤2018   (mean abs error)
            none                          3.8308      4.0410
            national lean                 3.6260      3.7063
            region-pooled lean            3.5279      3.4113
            per-state lean                3.5551      3.4641

        Per-state is worse than region-pooled: those cells run three to twenty
        polls and the noise costs more than the specificity buys. Pool the
        region, do not slice it further. Quality/grade still comes from the full
        national fit, where coverage is much better.
        """
        if region:
            leans = (self.regions.get(region) or {}).get("leans") or {}
            canon = self.resolve(name)
            if canon and canon in leans:
                return leans[canon] - self.pool_lean
        rec = self.get(name)
        return (rec["lean_shrunk"] - self.pool_lean) if rec else 0.0

    def region_states(self, region: str) -> list[str]:
        """States a fitted region covers, empty if the region is unknown."""
        return list((self.regions.get(region) or {}).get("states") or [])

    def __contains__(self, name: str) -> bool:
        return self.resolve(name) is not None

    def __len__(self) -> int:
        return len(self.records)
