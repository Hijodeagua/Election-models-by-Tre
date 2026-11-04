"""Wikipedia Senate *results* scraper — the post-election counterpart of
:mod:`wikipedia_senate` (which reads the polling tables).

After polls close, each race article (``2026 United States Senate election in
Georgia``) gains a "Results" / "General election" section whose table comes
from the Election box templates: Party | Candidate | Votes | % | ±%. This
module fetches the article through the MediaWiki API, finds that table and
returns the two-party shares, the winner and the Dem − Rep margin.

Best-effort by design: anything odd (no table yet, zero votes, a layout
change) yields ``None`` for that state rather than a wrong number, and the
scorer only counts states with a parsed result. Hand corrections go in
``data/results/senate_2026_manual.json`` (same schema), which overrides.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from lxml import html as lxml_html

from src.data.names import names_match
from src.data.wikipedia_senate import _UA, WIKIPEDIA_API, article_title_for_state

logger = logging.getLogger(__name__)

# A results table has to carry at least this many votes to count as real;
# pre-election articles sometimes hold an empty election box.
MIN_TOTAL_VOTES = 10_000

# Any heading above a table (its whole chain: h4 → h3 → h2) containing one of
# these marks a table that is NOT the general election. Race articles put the
# primary results under "Democratic primary → Results", so the nearest heading
# alone ("Results") is not enough to tell them apart.
NON_GENERAL_HEADING_TOKENS = (
    "primary", "primaries", "convention", "caucus", "nomination", "blanket",
    "top-four", "top four", "jungle", "poll", "endorsement", "fundrais",
    "prediction", "debate", "forum",
)

# Infobox values that mean "winner not yet known".
_INFOBOX_PENDING = {
    "", "tbd", "tba", "pending", "to be determined", "undetermined", "n/a", "—", "-",
}
_PARTY_WORDS = re.compile(
    r"\b(democratic|democrat|republican|independent|libertarian|green|party|dfl|npa)\b",
    re.IGNORECASE,
)

_PARTY_CODES = (
    ("democratic", "D"),
    ("republican", "R"),
    ("independent", "I"),
    ("libertarian", "L"),
    ("green", "G"),
)


@dataclass
class RaceResult:
    state: str
    winner: str | None
    winner_party: str | None
    dem_candidate: str | None
    rep_candidate: str | None
    dem_pct: float | None
    rep_pct: float | None
    margin: float | None  # Dem − Rep, percentage points
    total_votes: int
    source: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(text: str) -> str:
    s = re.sub(r"\[[^\]]*\]", "", text or "")
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _party_code(text: str) -> str | None:
    t = text.lower()
    for needle, code in _PARTY_CODES:
        if needle in t:
            return code
    return "O" if t else None


def _to_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _to_pct(text: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", (text or "").replace(",", ""))
    return float(m.group()) if m else None


_HEADING_TAGS = ("h2", "h3", "h4", "h5")


def _preceding_headings(table):
    """Yield (level, text) for every heading before ``table``, nearest first."""
    node = table
    while node is not None:
        prev = node.getprevious()
        while prev is not None:
            tag = prev.tag if isinstance(prev.tag, str) else ""
            if tag in _HEADING_TAGS:
                yield int(tag[1]), _clean(prev.text_content()).lower()
            elif tag == "div":
                # Headings are often wrapped in a <div class="mw-heading">.
                for h in reversed(prev.xpath(".//h2|.//h3|.//h4|.//h5")):
                    yield int(h.tag[1]), _clean(h.text_content()).lower()
            prev = prev.getprevious()
        node = node.getparent()


def _heading_chain(table) -> list[str]:
    """The section chain a table sits in, nearest first: e.g.
    ["results", "democratic primary", "background"]. Each entry is the nearest
    preceding heading of a strictly higher level than the one before it."""
    chain: list[str] = []
    level = 99
    for lvl, text in _preceding_headings(table):
        if lvl < level:
            chain.append(text)
            level = lvl
            if lvl <= 2:
                break
    return chain


def _heading_before(table) -> str:
    """Text of the nearest preceding heading, lower-cased ('' if none)."""
    chain = _heading_chain(table)
    return chain[0] if chain else ""


def infobox_winner(doc) -> str | None:
    """The winner named in the article infobox, if it has an "after
    election" / "elected" cell.

    Returns the name when filled, ``""`` when the cell exists but is still
    TBD (the race is not called), and ``None`` when no such cell exists.
    """
    for box in doc.xpath("//table[contains(@class,'infobox')]"):
        rows = box.xpath(".//tr")
        for i, tr in enumerate(rows):
            ths = tr.xpath("./th")
            for j, th in enumerate(ths):
                label = _clean(th.text_content()).lower()
                if "before" in label:
                    continue
                keys = ("after election", "elected", "senator-elect", "winner")
                if not any(k in label for k in keys):
                    continue
                # Two-column infobox: labels on one row, values on the next.
                value_cells = tr.xpath("./td")
                if not value_cells and i + 1 < len(rows):
                    value_cells = rows[i + 1].xpath("./td")
                if not value_cells:
                    return ""
                cell = value_cells[j] if j < len(value_cells) else value_cells[-1]
                # itertext keeps a gap between "Name" and "Party" split by <br>.
                text = _PARTY_WORDS.sub(" ", _clean(" ".join(cell.itertext())))
                text = re.sub(r"\s+", " ", text).strip(" ,;:")
                return "" if text.lower() in _INFOBOX_PENDING else text
    return None


def _table_rows(table) -> list[list[str]]:
    """Rows as text cells, expanding colspan so header and body columns line
    up (election boxes put a 2-wide "Party" header over a swatch + name)."""
    rows = []
    for tr in table.xpath(".//tr"):
        cells: list[str] = []
        for c in tr.xpath("./th|./td"):
            try:
                span = max(1, int(c.get("colspan", "1")))
            except ValueError:
                span = 1
            cells.extend([_clean(c.text_content())] * span)
        if cells:
            rows.append(cells)
    return rows


def parse_results_tables(page_html: str, state: str) -> RaceResult | None:
    """Find the general-election results table in an article and summarise it."""
    if not page_html:
        return None
    doc = lxml_html.fromstring(page_html)
    called = infobox_winner(doc)
    if called == "":
        # The infobox has an "elected" cell that is still blank: results may
        # be trickling into a table, but nobody has called the race.
        logger.info("  %s: infobox winner still TBD — not called", state)
        return None
    candidates: list[tuple[int, RaceResult]] = []
    for table in doc.xpath("//table"):
        if "infobox" in (table.get("class") or ""):
            continue
        rows = _table_rows(table)
        if len(rows) < 2:
            continue
        header = [h.lower() for h in rows[0]]
        if not any("candidate" in h for h in header) or not any("votes" in h for h in header):
            continue
        chain = _heading_chain(table)
        if any(k in h for h in chain for k in NON_GENERAL_HEADING_TOKENS):
            continue
        parsed = _parse_election_box(rows, state)
        if parsed is None:
            continue
        heading = chain[0] if chain else ""
        # Prefer tables under a results-style heading; score 2 for an explicit
        # general-election/results heading, 1 otherwise.
        score = 2 if ("general" in heading or "result" in heading) else 1
        candidates.append((score, parsed))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1].total_votes), reverse=True)
    best = candidates[0][1]
    if called and not names_match(best.winner, called):
        logger.warning(
            "  %s: results table winner %r disagrees with infobox winner %r — skipping",
            state, best.winner, called,
        )
        return None
    if called:
        best.note = (best.note + " infobox-confirmed").strip()
    return best


def _parse_election_box(rows: list[list[str]], state: str) -> RaceResult | None:
    header = [h.lower() for h in rows[0]]

    def col(pred) -> int | None:
        for i, h in enumerate(header):
            if pred(h):
                return i
        return None

    i_party = col(lambda h: "party" in h)
    i_cand = col(lambda h: "candidate" in h)
    i_votes = col(lambda h: "votes" in h)
    i_pct = col(lambda h: h.strip() in ("%", "percent", "percentage", "share") or h.endswith("%"))
    if i_cand is None or i_votes is None:
        return None

    entries: list[tuple[str, str | None, int, float | None]] = []
    for cells in rows[1:]:
        if len(cells) <= max(i_cand, i_votes):
            continue
        name = cells[i_cand]
        votes = _to_int(cells[i_votes])
        if not name or votes is None:
            continue
        low = name.lower()
        if low.startswith(("total", "turnout", "majority", "registered", "rejected", "invalid")):
            continue
        # Election-box rows carry the party swatch as an empty first cell, so
        # the party text is in the cell before the candidate when present.
        party_text = cells[i_party] if i_party is not None and i_party < len(cells) else ""
        if not party_text and i_cand >= 1:
            party_text = cells[i_cand - 1]
        pct = _to_pct(cells[i_pct]) if i_pct is not None and i_pct < len(cells) else None
        entries.append((name, _party_code(party_text), votes, pct))

    if not entries:
        return None
    total = sum(v for _, _, v, _ in entries)
    if total < MIN_TOTAL_VOTES:
        return None
    # Fill missing percentages from the vote counts.
    entries = [
        (n, p, v, pct if pct is not None else round(100.0 * v / total, 2))
        for n, p, v, pct in entries
    ]
    entries.sort(key=lambda e: e[2], reverse=True)
    # A general election has candidates from more than one party. A table with
    # a single party (or one candidate at 100%) is a primary, whatever its
    # heading says.
    parties = {p for _, p, _, _ in entries if p in ("D", "R", "I")}
    if len(parties) < 2 or entries[0][3] is not None and entries[0][3] >= 100.0:
        return None
    winner_name, winner_party, _, _ = entries[0]
    dem = next((e for e in entries if e[1] == "D"), None)
    rep = next((e for e in entries if e[1] == "R"), None)
    dem_pct = dem[3] if dem else None
    rep_pct = rep[3] if rep else None
    margin = round(dem_pct - rep_pct, 2) if dem_pct is not None and rep_pct is not None else None
    return RaceResult(
        state=state,
        winner=winner_name,
        winner_party=winner_party,
        dem_candidate=dem[0] if dem else None,
        rep_candidate=rep[0] if rep else None,
        dem_pct=dem_pct,
        rep_pct=rep_pct,
        margin=margin,
        total_votes=total,
        source="wikipedia",
    )


class WikipediaResultsSource:
    """Fetch a race article and parse its results table."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WikipediaResultsSource:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def fetch_html(self, title: str) -> str:
        resp = self._client.get(
            WIKIPEDIA_API,
            params={
                "action": "parse", "page": title, "prop": "text",
                "formatversion": "2", "format": "json", "redirects": "1",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload:
            raise RuntimeError(payload["error"].get("info", "Wikipedia API error"))
        return payload.get("parse", {}).get("text", "")

    def fetch_result(self, state: str, article: str | None = None) -> RaceResult | None:
        title = article or article_title_for_state(state)
        try:
            page_html = self.fetch_html(title)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("  %s: results fetch failed (%s)", state, exc)
            return None
        try:
            return parse_results_tables(page_html, state)
        except Exception as exc:  # noqa: BLE001
            logger.warning("  %s: results parse failed (%s)", state, exc)
            return None
