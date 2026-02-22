"""Congress.gov API client — member info, voting records, bill data.

Useful for congressional race context. Requires API key from api.congress.gov.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.data.base import DataSource, Poll, PollType


class CongressGovClient(DataSource):
    """Client for the Congress.gov API.

    Provides member information and voting records, not polling data.
    Stub — expand as needed for race context enrichment.
    """

    name = "congress_gov"

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
        raise NotImplementedError("Congress.gov does not provide polling data")

    def fetch_pollsters(self) -> list[str]:
        raise NotImplementedError("Congress.gov does not track pollsters")

    def fetch_members(self, congress: int = 119, chamber: str = "senate") -> list[dict[str, Any]]:
        """Fetch current members of Congress.

        Args:
            congress: Congress number (119 = 2025-2027).
            chamber: 'senate' or 'house'.

        Returns:
            List of member records.
        """
        if not self.is_configured:
            raise RuntimeError("Congress.gov API key not configured.")
        # TODO: Implement with httpx
        raise NotImplementedError
