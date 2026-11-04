"""The AP-via-NYT results feed parser (fixture mirrors the live 2026 shape)."""

from __future__ import annotations

from src.data.nyt_results import parse_feed, parse_race, summarize


def _cand(nyt_id: str, first: str, last: str, party: str, incumbent: bool = False) -> dict:
    return {
        "nyt_id": nyt_id, "first_name": first, "last_name": last, "suffix": None,
        "incumbent": incumbent,
        "party": {"nyt_id": party, "name": {"DEM": "Democrat", "REP": "Republican",
                                            "IND": "Independent"}.get(party, party)},
    }


def _race(state, postal, cands, votes, *, called=None, call_status="too_early",
          gained=None, eevp=0.0, race_type="G", uncontested=False, updated="2026-11-04T02:21:02Z"):
    total = sum(votes.values())
    return {
        "nyt_id": f"{postal}-G-S-2026-11-03",
        "office": "U.S. Senate",
        "race_type_id": race_type,
        "uncontested": uncontested,
        "race_call_status": call_status,
        "rating": "likely-dem",
        "updated_at": updated,
        "candidate_metadata": {c["nyt_id"]: c for c in cands},
        "outcome": {
            "won": [called] if called else [],
            "called_by": ["ap"] if called else [],
            "winner_accepted_at": ["2026-11-04T00:56:37.784+00:00"] if called else [],
            "gained": gained,
        },
        "top_reporting_unit": {
            "name": state, "state_postal": postal, "eevp": eevp,
            "total_votes": total, "precincts_reporting": 1182, "precincts_total": 2582,
            "provider_updated_at": updated,
            "candidates": [
                {"nyt_id": cid, "votes": {"total": v}, "leader": i == 0}
                for i, (cid, v) in enumerate(votes.items())
            ],
        },
    }


GEORGIA = _race(
    "Georgia", "GA",
    [_cand("ossoff-j", "Jon", "Ossoff", "DEM", True), _cand("collins-m", "Mike", "Collins", "REP"),
     _cand("lib-x", "Lib", "Person", "LIB")],
    {"ossoff-j": 1_976_469, "collins-m": 1_333_566, "lib-x": 41_000},
    called="ossoff-j", call_status="called", gained=False, eevp=75.01,
)
TEXAS = _race(
    "Texas", "TX",
    [_cand("talarico-j", "James", "Talarico", "DEM"), _cand("paxton-k", "Ken", "Paxton", "REP")],
    {"paxton-k": 2_000_000, "talarico-j": 1_900_000},
    eevp=42.0,
)
ALASKA = _race(
    "Alaska", "AK",
    [_cand("peltola-m", "Mary", "Peltola", "DEM"),
     _cand("sullivan-d", "Dan", "Sullivan", "REP", True)],
    {"peltola-m": 0, "sullivan-d": 0}, eevp=0,
)
NEBRASKA = _race(
    "Nebraska", "NE",
    [_cand("ricketts-p", "Pete", "Ricketts", "REP", True),
     _cand("osborn-d", "Dan", "Osborn", "IND")],
    {"osborn-d": 300_000, "ricketts-p": 280_000},
    called="osborn-d", call_status="called", gained=True, eevp=88.0,
)
PRIMARY = _race("Georgia", "GA", [_cand("x", "Some", "One", "DEM")], {"x": 10}, race_type="P")


def test_called_race():
    rs = parse_race(GEORGIA)
    assert rs is not None
    assert rs.state == "Georgia" and rs.postal == "GA"
    assert rs.status == "called" and rs.called is True
    assert rs.winner == "Jon Ossoff" and rs.winner_party == "D"
    assert rs.called_by == ["ap"] and rs.called_at == "2026-11-04T00:56:37.784+00:00"
    assert rs.gained is False
    assert rs.eevp == 75.01 and rs.total_votes == 3_351_035
    assert rs.dem_candidate == "Jon Ossoff" and rs.rep_candidate == "Mike Collins"
    assert rs.dem_pct == 58.98 and rs.rep_pct == 39.8
    assert rs.margin == 19.18
    assert rs.leader == "Jon Ossoff" and rs.leader_party == "D" and rs.leader_margin == 19.18
    assert [c.party for c in rs.candidates] == ["D", "R", "L"]
    d = rs.to_result_dict()
    assert d["winner_party"] == "D" and d["source"] == "ap-via-nyt" and d["called_at"]
    assert "called by ap" in d["note"]
    s = rs.to_status_dict()
    assert "candidates" not in s and s["status"] == "called"


def test_reporting_and_no_results():
    tx = parse_race(TEXAS)
    assert tx is not None and tx.status == "reporting" and tx.called is False
    assert tx.winner is None and tx.leader == "Ken Paxton" and tx.leader_party == "R"
    assert tx.leader_margin == 2.56 and tx.margin == -2.56 and tx.eevp == 42.0
    assert tx.to_result_dict()["note"] == ""
    ak = parse_race(ALASKA)
    assert ak is not None and ak.status == "no_results" and ak.leader is None
    assert ak.dem_pct is None and ak.margin is None


def test_independent_flip_and_feed_summary():
    ne = parse_race(NEBRASKA)
    assert ne is not None and ne.winner == "Dan Osborn" and ne.winner_party == "I"
    assert ne.gained is True and ne.status == "called"
    feed = parse_feed({"races": [GEORGIA, TEXAS, ALASKA, NEBRASKA, PRIMARY]})
    assert set(feed) == {"Georgia", "Texas", "Alaska", "Nebraska"}  # primary skipped
    assert summarize(feed) == "2 called, 1 reporting, 4 races"


def test_won_without_a_call_status_is_not_a_call():
    race = dict(GEORGIA)
    race["race_call_status"] = "too_early"
    rs = parse_race(race)
    assert rs is not None and rs.called is False and rs.status == "reporting"


def test_bad_race_does_not_sink_the_feed():
    feed = parse_feed({"races": [GEORGIA, {"race_type_id": "G", "top_reporting_unit": None,
                                            "candidate_metadata": None}]})
    assert set(feed) == {"Georgia"}
