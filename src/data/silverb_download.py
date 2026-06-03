"""Download Silver Bulletin daily model estimate CSVs.

Silver Bulletin publishes approval and generic ballot model outputs as
downloadable CSVs via their Substack. URLs are configurable via environment
variables so they can be updated without code changes if SB moves the files.

If a download fails the existing file in data/fallback/ is left untouched,
so the model continues to run on the last-known-good data.

Env vars (optional — defaults shown):
    SILVERB_APPROVAL_CSV_URL
    SILVERB_GB_CSV_URL
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

# Silver Bulletin publishes their model CSVs at these URLs.
# If they change, update via env vars without touching code.
_DEFAULT_APPROVAL_URL = (
    "https://static.natesilver.net/approval.csv"
)
_DEFAULT_GB_URL = (
    "https://static.natesilver.net/generic-ballot.csv"
)


class SilverBulletinDownloader:
    """Downloads Silver Bulletin daily model CSVs and writes them to disk."""

    def __init__(
        self,
        fallback_dir: Path | None = None,
        timeout: float = 30.0,
        approval_url: str | None = None,
        gb_url: str | None = None,
    ) -> None:
        self.fallback_dir = fallback_dir or (
            Path(__file__).resolve().parent.parent.parent / "data" / "fallback"
        )
        self.fallback_dir.mkdir(parents=True, exist_ok=True)
        self.approval_url = approval_url or getattr(
            settings, "silverb_approval_csv_url", _DEFAULT_APPROVAL_URL
        )
        self.gb_url = gb_url or getattr(
            settings, "silverb_gb_csv_url", _DEFAULT_GB_URL
        )
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "election-oracle/0.1"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SilverBulletinDownloader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def refresh_approval(self) -> bool:
        """Download fresh approval CSV. Returns True on success."""
        return self._download(self.approval_url, self.fallback_dir / "silverb_approval.csv")

    def refresh_generic_ballot(self) -> bool:
        """Download fresh generic ballot CSV. Returns True on success."""
        return self._download(self.gb_url, self.fallback_dir / "silverb_generic_ballot.csv")

    def refresh_all(self) -> dict[str, bool]:
        return {
            "approval": self.refresh_approval(),
            "generic_ballot": self.refresh_generic_ballot(),
        }

    def _download(self, url: str, dest: Path) -> bool:
        try:
            logger.info("Downloading %s → %s", url, dest.name)
            resp = self._client.get(url)
            resp.raise_for_status()

            # Basic sanity check: must look like a CSV with at least 2 lines
            text = resp.text.strip()
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if len(lines) < 2 or "," not in lines[0]:
                logger.warning(
                    "Downloaded content from %s doesn't look like a valid CSV "
                    "(%d lines, first: %r) — keeping existing file",
                    url, len(lines), lines[0][:80] if lines else "",
                )
                return False

            dest.write_text(text + "\n", encoding="utf-8")
            logger.info("Saved %d rows to %s", len(lines) - 1, dest.name)
            return True

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "HTTP %d fetching %s — keeping existing file",
                exc.response.status_code, url,
            )
        except Exception as exc:
            logger.warning("Failed to download %s: %s — keeping existing file", url, exc)
        return False
