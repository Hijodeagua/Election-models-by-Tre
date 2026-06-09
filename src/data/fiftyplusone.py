"""FiftyPlusOne API client — paid polling averages from G. Elliott Morris.

Requires API key (email data@fiftyplusone.news for access).
Gated behind config: set FIFTYPLUSONE_API_KEY in .env to enable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.data.base import DataSource, Poll, PollType


class FiftyPlusOneClient(DataSource):
    """Client for the FiftyPlusOne paid API.

    Stub implementation — fill in when API access is obtained.
    """

    name = "fiftyplusone"

    def __init__(self, api_key: str = "", cache_dir: Path | None = None) -> None:
        super().__init__(cache_dir=cache_dir)
        self.api_key = api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch_polls(
        self,
        poll_type: PollType | None = None,
        subject: str | None = None,
        **kwargs: Any,
    ) -> list[Poll]:
        if not self.is_configured:
            raise RuntimeError(
                "FiftyPlusOne API key not configured. "
                "Set FIFTYPLUSONE_API_KEY in .env or email data@fiftyplusone.news."
            )
        # TODO: Implement when API spec is available
        raise NotImplementedError("FiftyPlusOne API integration pending")

    def fetch_pollsters(self) -> list[str]:
        raise NotImplementedError


class FiftyPlusOneApprovalCsvLoader:
    """Load a cached 50+1 approval-average series from CSV.

    The paid API isn't wired up yet, so the comparison chart reads a cached
    export at ``data/fallback/fiftyplusone_approval.csv`` when present:

        modeldate,approve,disapprove
        2026-01-01,41.2,55.3

    Returns an empty list when the file is absent — the website then shows
    the 50+1 series as "not available yet".
    """

    def load_series(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        import csv
        import io
        from datetime import date as _date

        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
        series: list[dict[str, Any]] = []
        for row in rows:
            try:
                series.append(
                    {
                        "as_of": _date.fromisoformat(row["modeldate"]),
                        "approve": float(row["approve"]),
                        "disapprove": float(row["disapprove"]),
                    }
                )
            except (KeyError, ValueError):
                continue
        return series
