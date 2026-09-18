"""Tests for the FRED state-economic client (Tier 1 panel).

All network is mocked with respx — the real endpoints are unreachable from CI
and the point of these tests is the parsing, caching and failure handling, not
FRED's uptime.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
import respx

from src.data.fred import (
    API_BASE,
    CSV_BASE,
    STATE_ABBRS,
    STATE_CONCEPTS,
    FredClient,
    Observation,
    change_over,
    latest_before,
    state_series_ids,
)

FREDGRAPH_CSV = """observation_date,TXUR
2024-01-01,3.9
2024-02-01,.
2024-03-01,4.1
"""

API_JSON = {
    "observations": [
        {"date": "2024-01-01", "value": "3.9"},
        {"date": "2024-02-01", "value": "."},
        {"date": "2024-03-01", "value": "4.1"},
    ]
}


def _client(tmp_path, api_key: str = "", **kwargs) -> FredClient:
    return FredClient(
        api_key=api_key, cache_dir=tmp_path / "fred", min_request_interval=0.0, **kwargs
    )


class TestKeylessTransport:
    @respx.mock
    def test_parses_csv_and_treats_period_as_missing(self, tmp_path):
        route = respx.get(CSV_BASE).mock(
            return_value=httpx.Response(200, text=FREDGRAPH_CSV)
        )
        rows = _client(tmp_path).fetch_series("TXUR")
        assert route.called
        assert rows == [
            Observation(date(2024, 1, 1), 3.9),
            Observation(date(2024, 2, 1), None),
            Observation(date(2024, 3, 1), 4.1),
        ]

    @respx.mock
    def test_html_response_is_a_failure_not_a_series(self, tmp_path):
        # An unknown ID can come back as an HTML error page with HTTP 200.
        respx.get(CSV_BASE).mock(
            return_value=httpx.Response(200, text="<!DOCTYPE html><html>nope</html>")
        )
        with pytest.raises(FileNotFoundError, match="unknown series ID"):
            _client(tmp_path).fetch_series("XXUR")


class TestApiTransport:
    @respx.mock
    def test_uses_api_when_key_present(self, tmp_path):
        route = respx.get(f"{API_BASE}/series/observations").mock(
            return_value=httpx.Response(200, json=API_JSON)
        )
        rows = _client(tmp_path, api_key="k123").fetch_series("TXUR")
        assert [o.value for o in rows] == [3.9, None, 4.1]
        assert route.calls[0].request.url.params["api_key"] == "k123"
        assert "realtime_start" not in route.calls[0].request.url.params

    @respx.mock
    def test_vintage_sends_realtime_window(self, tmp_path):
        route = respx.get(f"{API_BASE}/series/observations").mock(
            return_value=httpx.Response(200, json=API_JSON)
        )
        client = _client(tmp_path, api_key="k123", realtime=date(2022, 11, 8))
        client.fetch_series("TXUR")
        params = route.calls[0].request.url.params
        assert params["realtime_start"] == "2022-11-08"
        assert params["realtime_end"] == "2022-11-08"

    @respx.mock
    def test_api_error_names_the_series(self, tmp_path):
        respx.get(f"{API_BASE}/series/observations").mock(
            return_value=httpx.Response(
                400, text=json.dumps({"error_message": "Bad request. Series not found."})
            )
        )
        with pytest.raises(FileNotFoundError, match="Series not found"):
            _client(tmp_path, api_key="k123").fetch_series("XXUR")

    def test_vintage_without_key_is_rejected_upfront(self, tmp_path):
        # Fail before an hour-long pull, not after: the keyless endpoint cannot
        # serve vintages at all.
        with pytest.raises(ValueError, match="needs a FRED API key"):
            _client(tmp_path, realtime=date(2022, 11, 8))


class TestCaching:
    @respx.mock
    def test_second_fetch_uses_cache(self, tmp_path):
        route = respx.get(CSV_BASE).mock(
            return_value=httpx.Response(200, text=FREDGRAPH_CSV)
        )
        client = _client(tmp_path)
        first = client.fetch_series("TXUR")
        second = client.fetch_series("TXUR")
        assert route.call_count == 1
        assert first == second

    @respx.mock
    def test_force_redownloads(self, tmp_path):
        route = respx.get(CSV_BASE).mock(
            return_value=httpx.Response(200, text=FREDGRAPH_CSV)
        )
        client = _client(tmp_path)
        client.fetch_series("TXUR")
        client.fetch_series("TXUR", force=True)
        assert route.call_count == 2

    @respx.mock
    def test_vintages_cache_separately(self, tmp_path):
        respx.get(f"{API_BASE}/series/observations").mock(
            return_value=httpx.Response(200, json=API_JSON)
        )
        current = _client(tmp_path, api_key="k")
        vintage = _client(tmp_path, api_key="k", realtime=date(2022, 11, 8))
        current.fetch_series("TXUR")
        vintage.fetch_series("TXUR")
        names = sorted(p.name for p in (tmp_path / "fred").iterdir())
        assert names == ["TXUR.csv", "TXUR@2022-11-08.csv"]


class TestPanelAndProbe:
    @respx.mock
    def test_one_bad_series_does_not_end_the_pull(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("id") == "XXUR":
                return httpx.Response(404, text="not found")
            return httpx.Response(200, text=FREDGRAPH_CSV)

        respx.get(CSV_BASE).mock(side_effect=handler)
        data, failures = _client(tmp_path).fetch_panel(["TXUR", "XXUR", "OHUR"])
        assert sorted(data) == ["OHUR", "TXUR"]
        assert [f.series_id for f in failures] == ["XXUR"]

    @respx.mock
    def test_probe_reports_coverage_and_failures(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("id") == "XXUR":
                return httpx.Response(404, text="not found")
            return httpx.Response(200, text=FREDGRAPH_CSV)

        respx.get(CSV_BASE).mock(side_effect=handler)
        results = _client(tmp_path).probe(["TXUR", "XXUR"])
        assert results["TXUR"].startswith("ok (2 obs, 2024-01-01–2024-03-01")
        assert results["XXUR"].startswith("FAILED")


class TestSeriesIds:
    def test_full_panel_covers_every_state_and_concept(self):
        ids = state_series_ids()
        assert len(ids) == len(STATE_ABBRS) * len(STATE_CONCEPTS)
        assert ids[("TX", "unemployment_rate")] == "TXUR"
        assert ids[("ME", "house_price_index")] == "MESTHPI"

    def test_slicing_by_concept_and_state(self):
        ids = state_series_ids(["unemployment_rate"], ["ga", "ia"])
        assert ids == {
            ("GA", "unemployment_rate"): "GAUR",
            ("IA", "unemployment_rate"): "IAUR",
        }

    def test_unknown_concept_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown concepts"):
            state_series_ids(["vibes"])


class TestAlignment:
    SERIES = [
        Observation(date(2021, 10, 1), 5.0),
        Observation(date(2022, 9, 1), 3.6),
        Observation(date(2022, 10, 1), 3.4),
        Observation(date(2022, 12, 1), 3.2),  # after the cutoff
    ]

    def test_latest_before_ignores_the_future(self):
        obs = latest_before(self.SERIES, date(2022, 11, 8))
        assert obs is not None
        assert obs.date == date(2022, 10, 1)

    def test_latest_before_skips_missing_values(self):
        series = [Observation(date(2022, 10, 1), None), Observation(date(2022, 9, 1), 3.6)]
        obs = latest_before(series, date(2022, 11, 8))
        assert obs is not None
        assert obs.value == 3.6

    def test_change_over_pairs_with_a_year_earlier(self):
        now, prior = change_over(self.SERIES, date(2022, 11, 8), months=12)
        assert now is not None and prior is not None
        assert now.date == date(2022, 10, 1)
        assert prior.date == date(2021, 10, 1)
        assert round(now.value - prior.value, 2) == -1.6

    def test_change_over_returns_none_when_nothing_precedes(self):
        now, prior = change_over(self.SERIES, date(2019, 1, 1))
        assert now is None and prior is None


class TestOutputPaths:
    """Vintage panels must not overwrite each other — a backtest needs 2018,
    2020 and 2022 side by side."""

    def test_current_vintage_has_the_plain_name(self):
        from scripts.download_economic_data import aligned_path, panel_path

        assert panel_path(None).name == "state_economics.csv"
        assert (
            aligned_path(None, date(2026, 11, 3)).name
            == "state_economics_aligned_2026-11-03.csv"
        )

    def test_each_vintage_gets_its_own_file(self):
        from scripts.download_economic_data import panel_path

        names = {panel_path(d).name for d in (
            None, date(2018, 11, 6), date(2020, 11, 3), date(2022, 11, 8)
        )}
        assert len(names) == 4
        assert "state_economics_2022-11-08.csv" in names

    def test_aligned_path_keys_on_vintage_and_election(self):
        from scripts.download_economic_data import aligned_path

        # Same election, different vintages: revised vs as-published.
        current = aligned_path(None, date(2022, 11, 8))
        vintage = aligned_path(date(2022, 11, 8), date(2022, 11, 8))
        assert current != vintage
        assert vintage.name.endswith("_vintage2022-11-08.csv")
