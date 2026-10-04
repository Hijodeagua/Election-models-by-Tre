"""Tests for the economic fundamentals layer (src/data/economic.py,
src/analysis/fundamentals.py)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.analysis.fundamentals import economic_components, schedule_lookup
from src.data.economic import (
    EconomicRow,
    EconomicSnapshot,
    load_economic_csv,
    snapshot_from_rows,
    write_economic_csv,
)

FALLBACK = Path(__file__).resolve().parent.parent / "data" / "fallback"


def _snap(**kw) -> EconomicSnapshot:
    base = dict(
        as_of=date(2026, 8, 1), cpi_yoy=3.4, gas_price_us=3.10, unemployment_us=4.2,
        gas_price_by_state={"TX": 2.80, "CA": 4.60}, unemployment_by_state={"TX": 4.0, "CA": 5.4},
    )
    base.update(kw)
    return EconomicSnapshot(**base)


CFG = {"inflation_baseline": 2.5, "inflation_coef": -0.3, "gas_deviation_coef": -1.0,
       "unemployment_deviation_coef": -0.3}


class TestEconomicComponents:
    def test_inflation_hurts_president_party_flipped_to_dem_rep(self):
        out = economic_components(_snap(), CFG, "R", None)
        assert out["inflation_effect"] == pytest.approx(0.27)  # (3.4-2.5)*-0.3 → +0.27 for Dems
        dem_pres = economic_components(_snap(), CFG, "D", None)
        assert dem_pres["inflation_effect"] == pytest.approx(-0.27)

    def test_state_deviations(self):
        tx = economic_components(_snap(), CFG, "R", "TX")
        assert tx["gas_deviation"] == pytest.approx(-0.30)
        assert tx["gas_effect"] == pytest.approx(-0.30)  # cheaper gas helps the R president in TX
        assert tx["unemployment_effect"] == pytest.approx(-0.06)
        assert set(tx["available"]) == {"inflation", "gas", "unemployment"}
        assert tx["total"] == pytest.approx(0.27 - 0.30 - 0.06, abs=0.002)

    def test_missing_data_contributes_zero(self):
        out = economic_components(_snap(gas_price_us=None), CFG, "R", "TX")
        assert out["gas_effect"] == 0.0 and "gas" not in out["available"]
        assert economic_components(None, CFG, "R", "TX")["total"] == 0.0
        assert economic_components(_snap(), CFG, "R", "ZZ")["gas_effect"] == 0.0


class TestScheduleLookup:
    SCHED = {"_comment": "x", "0": 0.0, "1-6": 0.25, "7-15": 0.75, "16+": 1.0}

    def test_categories(self):
        assert schedule_lookup(self.SCHED, 0) == ("0", 0.0)
        assert schedule_lookup(self.SCHED, 3.8) == ("1-6", 0.25)
        assert schedule_lookup(self.SCHED, 15.9) == ("7-15", 0.75)
        assert schedule_lookup(self.SCHED, 48) == ("16+", 1.0)
        assert schedule_lookup(self.SCHED, None) == ("none", 0.0)


class TestCsv:
    def test_committed_snapshot_has_cpi(self):
        snap = snapshot_from_rows(load_economic_csv(FALLBACK / "economic.csv"))
        assert snap.cpi_yoy is not None and 0 < snap.cpi_yoy < 15
        assert snap.as_of is not None

    def test_round_trip_and_latest_wins(self, tmp_path):
        rows = [
            EconomicRow(date(2026, 7, 1), "gas_price", "US", 3.0, "usd/gal", "EIA"),
            EconomicRow(date(2026, 8, 1), "gas_price", "US", 3.2, "usd/gal", "EIA"),
            EconomicRow(date(2026, 8, 1), "gas_price", "TX", 2.9, "usd/gal", "EIA"),
            EconomicRow(date(2026, 8, 1), "cpi_yoy", "US", 3.4, "pct", "x"),
        ]
        write_economic_csv(rows, tmp_path / "economic.csv")
        snap = snapshot_from_rows(load_economic_csv(tmp_path / "economic.csv"))
        assert snap.gas_price_us == 3.2 and snap.gas_deviation("TX") == pytest.approx(-0.3)
        assert snap.cpi_yoy == 3.4
