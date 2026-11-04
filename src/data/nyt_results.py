"""AP race calls and live counts, via The New York Times election-night feed.

The NYT results pages are driven by one JSON file per office that carries the
Associated Press race calls (``race_call_status`` / ``outcome.won``), the
expected-vote-in percentage (``eevp``), precincts reporting and the running
vote totals for every candidate. For 2026 the Senate file is

    https://static01.nyt.com/elections-assets/pages/data/2026-11-03/results-senate.json

This module fetches that file and reduces each race to a :class:`RaceStatus`:
called or not, by whom, when, the winner, whether the seat flipped, how much
of the vote is in, who leads and by how much. It is the preferred results
source for election night; the Wikipedia scraper
(:mod:`src.data.wikipedia_results`) is the fallback when this feed is down.

Undocumented feed: everything here is best-effort and defensive. A changed
layout yields no statuses (and a logged warning) rather than wrong ones.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from src.data.wikipedia_senate import _UA

logger = logging.getLogger(__name__)

ELECTION_DATE = "2026-11-03"
NYT_SENATE_FEED = (
    "https://static01.nyt.com/elections-assets/pages/data/{date}/results-senate.json"
)

_PARTY_CODES = {
    "DEM": "D", "REP": "R", "IND": "I", "LIB": "L", "GRN": "G", "GRE": "G", "CON": "O",
}

# States whose postal code the feed uses when the name is missing.
_POSTAL_TO_NAME: dict[str, str] = {}


@dataclass
class CandidateCount:
    nyt_id: str
    name: str
    party: str  # D / R / I / L / G / O
    votes: int
    pct: float | None
    incumbent: bool = False


@dataclass
class RaceStatus:
    state: str  # full name, e.g. "Georgia"
    postal: str | None
    status: str  # "called" | "reporting" | "no_results" | "uncontested"
    called: bool
    called_by: list[str]
    called_at: str | None
    winner: str | None
    winner_party: str | None
    gained: bool | None  # AP's seat-flip flag
    eevp: float | None  # expected vote in, %
    precincts_reporting: int | None
    precincts_total: int | None
    total_votes: int
    leader: str | None
    leader_party: str | None
    leader_margin: float | None  # leader's share minus runner-up's, points
    dem_candidate: str | None
    rep_candidate: str | None
    dem_pct: float | None
    rep_pct: float | None
    margin: float | None  # Dem − Rep share, points
    updated_at: str | None
    rating: str | None = None
    candidates: list[CandidateCount] = field(default_factory=list)
    source: str = "ap-via-nyt"

    def to_result_dict(self) -> dict[str, Any]:
        """The ``data/results`` per-state schema (what the scorer reads)."""
        return {
            "state": self.state,
            "winner": self.winner,
            "winner_party": self.winner_party,
            "dem_candidate": self.dem_candidate,
            "rep_candidate": self.rep_candidate,
            "dem_pct": self.dem_pct,
            "rep_pct": self.rep_pct,
            "margin": self.margin,
            "total_votes": self.total_votes,
            "source": self.source,
            "note": f"called by {', '.join(self.called_by) or 'AP'} at {self.called_at}"
            if self.called
            else "",
            "called_at": self.called_at,
            "gained": self.gained,
            "eevp": self.eevp,
        }

    def to_status_dict(self) -> dict[str, Any]:
        """The compact per-race status the live forecast and the map show."""
        d = asdict(self)
        d.pop("candidates", None)
        return d


def _party_code(cand_meta: dict) -> str:
    party = cand_meta.get("party") or {}
    code = (party.get("nyt_id") or party.get("abbreviation") or "").upper().strip(". ")
    if code in _PARTY_CODES:
        return _PARTY_CODES[code]
    name = (party.get("name") or "").lower()
    if "democrat" in name:
        return "D"
    if "republican" in name:
        return "R"
    if "independent" in name or "nonpartisan" in name:
        return "I"
    return "O"


def _full_name(cand_meta: dict) -> str:
    parts = [cand_meta.get("first_name"), cand_meta.get("last_name")]
    name = " ".join(p for p in parts if p).strip()
    if cand_meta.get("suffix"):
        name = f"{name} {cand_meta['suffix']}"
    return name or str(cand_meta.get("nyt_id") or "")


def _votes_total(cand: dict) -> int:
    votes = cand.get("votes")
    if isinstance(votes, dict):
        return int(votes.get("total") or 0)
    try:
        return int(votes or 0)
    except (TypeError, ValueError):
        return 0


def parse_race(race: dict) -> RaceStatus | None:
    """Reduce one feed race to a RaceStatus (None if it is not a general)."""
    if (race.get("race_type_id") or "G") != "G":
        return None
    tru = race.get("top_reporting_unit") or {}
    state = tru.get("name") or race.get("seat") or ""
    postal = tru.get("state_postal")
    if not state and postal:
        state = _POSTAL_TO_NAME.get(postal, postal)
    if not state:
        return None
    meta: dict[str, dict] = race.get("candidate_metadata") or {}

    counts: list[CandidateCount] = []
    total = int(tru.get("total_votes") or 0)
    for c in tru.get("candidates") or []:
        cid = c.get("nyt_id")
        cm = meta.get(cid, {})
        v = _votes_total(c)
        counts.append(
            CandidateCount(
                nyt_id=str(cid),
                name=_full_name(cm) if cm else str(cid),
                party=_party_code(cm) if cm else "O",
                votes=v,
                pct=round(100.0 * v / total, 2) if total > 0 else None,
                incumbent=bool(cm.get("incumbent")),
            )
        )
    counts.sort(key=lambda c: c.votes, reverse=True)

    outcome = race.get("outcome") or {}
    won = outcome.get("won") or []
    call_status = (race.get("race_call_status") or "").lower()
    called = bool(won) and call_status not in ("too_early", "too_close", "too_close_to_call")
    winner = winner_party = None
    if called:
        wid = won[0]
        wm = meta.get(wid, {})
        winner = _full_name(wm) if wm else str(wid)
        winner_party = _party_code(wm) if wm else None
    accepted = outcome.get("winner_accepted_at") or []
    called_at = accepted[0] if accepted else None

    dem = next((c for c in counts if c.party == "D"), None)
    rep = next((c for c in counts if c.party == "R"), None)
    margin = (
        round(dem.pct - rep.pct, 2)
        if dem and rep and dem.pct is not None and rep.pct is not None
        else None
    )
    leader = counts[0] if counts and counts[0].votes > 0 else None
    lead_margin = None
    if leader and leader.pct is not None:
        runner = counts[1].pct if len(counts) > 1 and counts[1].pct is not None else 0.0
        lead_margin = round(leader.pct - runner, 2)

    eevp = tru.get("eevp")
    eevp = float(eevp) if eevp is not None else None
    if race.get("uncontested"):
        status = "uncontested"
    elif called:
        status = "called"
    elif total > 0 or (eevp or 0) > 0:
        status = "reporting"
    else:
        status = "no_results"

    return RaceStatus(
        state=state,
        postal=postal,
        status=status,
        called=called,
        called_by=list(outcome.get("called_by") or []),
        called_at=called_at,
        winner=winner,
        winner_party=winner_party,
        gained=outcome.get("gained"),
        eevp=eevp,
        precincts_reporting=tru.get("precincts_reporting"),
        precincts_total=tru.get("precincts_total"),
        total_votes=total,
        leader=leader.name if leader else None,
        leader_party=leader.party if leader else None,
        leader_margin=lead_margin,
        dem_candidate=dem.name if dem else None,
        rep_candidate=rep.name if rep else None,
        dem_pct=dem.pct if dem else None,
        rep_pct=rep.pct if rep else None,
        margin=margin,
        updated_at=race.get("updated_at") or tru.get("provider_updated_at"),
        rating=race.get("rating"),
        candidates=counts,
    )


def parse_feed(data: dict) -> dict[str, RaceStatus]:
    """All general-election Senate races in the feed, keyed by state name.

    If a state somehow carries two generals (it does not in 2026), the one
    with more votes counted wins the key and a warning is logged.
    """
    out: dict[str, RaceStatus] = {}
    for race in data.get("races") or []:
        try:
            rs = parse_race(race)
        except Exception as exc:  # noqa: BLE001 — one bad race must not sink the rest
            logger.warning("skipping unparseable race %r: %s", race.get("nyt_id"), exc)
            continue
        if rs is None:
            continue
        if rs.state in out:
            logger.warning("two Senate generals for %s in the feed; keeping the larger", rs.state)
            if out[rs.state].total_votes >= rs.total_votes:
                continue
        out[rs.state] = rs
    return out


class NytResultsSource:
    """Fetch and parse the NYT/AP Senate feed."""

    def __init__(self, date: str = ELECTION_DATE, timeout: float = 30.0) -> None:
        self.url = NYT_SENATE_FEED.format(date=date)
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NytResultsSource:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def fetch(self) -> dict[str, RaceStatus]:
        """Statuses by state, or {} on any failure (logged)."""
        try:
            resp = self._client.get(self.url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("NYT/AP feed unavailable (%s): %s", self.url, exc)
            return {}
        statuses = parse_feed(data)
        if not statuses:
            logger.warning("NYT/AP feed parsed to zero races — layout change?")
        return statuses


def summarize(statuses: dict[str, RaceStatus]) -> str:
    called = sum(1 for s in statuses.values() if s.called)
    reporting = sum(1 for s in statuses.values() if s.status == "reporting")
    return f"{called} called, {reporting} reporting, {len(statuses)} races"

