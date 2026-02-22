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
