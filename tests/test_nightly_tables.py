from __future__ import annotations

from scripts import nightly_tables


def test_missing_publish_env_reports_required_variables(monkeypatch):
    for name in nightly_tables._REQUIRED_PUBLISH_ENV:
        monkeypatch.delenv(name, raising=False)

    assert nightly_tables._missing_publish_env() == nightly_tables._REQUIRED_PUBLISH_ENV


def test_missing_publish_env_accepts_required_variables(monkeypatch):
    for name in nightly_tables._REQUIRED_PUBLISH_ENV:
        monkeypatch.setenv(name, "configured")

    assert nightly_tables._missing_publish_env() == []
