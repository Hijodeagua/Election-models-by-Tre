from __future__ import annotations

from scripts import nightly_tables


def test_missing_publish_env_reports_token_and_chart_id(monkeypatch):
    monkeypatch.delenv("DATAWRAPPER_API_TOKEN", raising=False)
    monkeypatch.delenv("DW_CHART_APPROVAL_ID", raising=False)

    missing = nightly_tables._missing_publish_env("approval")
    assert "DATAWRAPPER_API_TOKEN" in missing
    assert "DW_CHART_APPROVAL_ID" in missing


def test_missing_publish_env_only_checks_selected_chart(monkeypatch):
    monkeypatch.setenv("DATAWRAPPER_API_TOKEN", "tok")
    monkeypatch.setenv("DW_CHART_APPROVAL_ID", "c1")
    monkeypatch.delenv("DW_CHART_GB_ID", raising=False)
    monkeypatch.delenv("DW_CHART_SENATE_ID", raising=False)

    # Publishing just approval should not require GB or senate IDs
    assert nightly_tables._missing_publish_env("approval") == []


def test_missing_publish_env_all_checks_required_charts(monkeypatch):
    monkeypatch.setenv("DATAWRAPPER_API_TOKEN", "tok")
    monkeypatch.delenv("DW_CHART_APPROVAL_ID", raising=False)
    monkeypatch.delenv("DW_CHART_GB_ID", raising=False)
    monkeypatch.delenv("DW_CHART_SENATE_ID", raising=False)

    missing = nightly_tables._missing_publish_env("all")
    assert "DW_CHART_APPROVAL_ID" in missing
    assert "DW_CHART_GB_ID" in missing
    assert "DW_CHART_SENATE_ID" in missing


def test_missing_publish_env_accepts_all_configured(monkeypatch):
    monkeypatch.setenv("DATAWRAPPER_API_TOKEN", "tok")
    for chart, var in nightly_tables._CHART_ENV_MAP.items():
        monkeypatch.setenv(var, "configured")

    assert nightly_tables._missing_publish_env("all") == []
