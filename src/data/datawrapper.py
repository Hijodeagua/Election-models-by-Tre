"""Datawrapper API client for publishing charts to Substack.

Workflow:
    1. Create charts manually at app.datawrapper.de
    2. Copy chart IDs into .env (e.g. DW_CHART_APPROVAL_ID=aBcDe)
    3. Call client.update_and_publish(chart_id, csv_data) to push data + publish

API docs: https://developer.datawrapper.de/docs

Required env var:
    DATAWRAPPER_API_TOKEN — get from https://app.datawrapper.de/account/api-tokens
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_DW_API = "https://api.datawrapper.de/v3"


@dataclass
class ChartIds:
    """Datawrapper chart IDs — set via env vars or pass directly."""

    approval_trend: str = ""
    generic_ballot_trend: str = ""
    senate_snapshot: str = ""
    house_effects: str = ""

    @classmethod
    def from_settings(cls) -> ChartIds:
        return cls(
            approval_trend=getattr(settings, "dw_chart_approval_id", ""),
            generic_ballot_trend=getattr(settings, "dw_chart_gb_id", ""),
            senate_snapshot=getattr(settings, "dw_chart_senate_id", ""),
            house_effects=getattr(settings, "dw_chart_house_effects_id", ""),
        )


class DatawrapperClient:
    """Push data and publish Datawrapper charts."""

    def __init__(self, api_token: str | None = None, timeout: float = 30.0) -> None:
        token = api_token or getattr(settings, "datawrapper_api_token", "")
        if not token:
            raise ValueError(
                "Datawrapper API token not set. "
                "Add DATAWRAPPER_API_TOKEN to your .env file. "
                "Get one at https://app.datawrapper.de/account/api-tokens"
            )
        self._client = httpx.Client(
            base_url=_DW_API,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DatawrapperClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Public API ───────────────────────────────────────────────────

    def update_and_publish(self, chart_id: str, csv_data: str) -> bool:
        """Upload CSV data to a chart and trigger publish. Returns True on success."""
        if not chart_id:
            logger.warning("No chart ID provided — skipping")
            return False
        ok = self._put_data(chart_id, csv_data)
        if ok:
            ok = self._publish(chart_id)
        return ok

    def get_chart_info(self, chart_id: str) -> dict:
        """Fetch chart metadata (useful for debugging)."""
        resp = self._client.get(f"/charts/{chart_id}")
        resp.raise_for_status()
        return resp.json()

    # ── Chart-specific CSV builders ──────────────────────────────────

    @staticmethod
    def approval_trend_csv(snapshots: list) -> str:
        """Build CSV from a list of ApprovalSnapshot objects (approval_trend output)."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "approve", "disapprove", "net", "approve_lo", "approve_hi"])
        for s in snapshots:
            lo = s.ci_approve[0] if s.ci_approve else ""
            hi = s.ci_approve[1] if s.ci_approve else ""
            w.writerow([s.as_of, round(s.approve, 2), round(s.disapprove, 2),
                        round(s.net_approval, 2), lo, hi])
        return buf.getvalue()

    @staticmethod
    def generic_ballot_csv(snapshots: list) -> str:
        """Build CSV from a list of GenericBallotSnapshot objects."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "dem", "rep", "margin", "dem_lo", "dem_hi"])
        for s in snapshots:
            lo = s.ci_dem[0] if s.ci_dem else ""
            hi = s.ci_dem[1] if s.ci_dem else ""
            w.writerow([s.as_of, round(s.dem_pct, 2), round(s.rep_pct, 2),
                        round(s.margin, 2), lo, hi])
        return buf.getvalue()

    @staticmethod
    def senate_snapshot_csv(races: list) -> str:
        """Build CSV from SenateRaceResult objects."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["state", "dem_candidate", "dem_pct", "rep_candidate", "rep_pct",
                    "margin", "n_polls", "as_of"])
        for race in sorted(races, key=lambda r: r.state):
            if race.num_polls == 0:
                continue
            cands = sorted(race.candidates.items(), key=lambda x: x[1], reverse=True)
            dem = cands[0] if cands else ("", 0)
            rep = cands[1] if len(cands) > 1 else ("", 0)
            w.writerow([race.state, dem[0], round(dem[1], 1), rep[0], round(rep[1], 1),
                        round(race.margin or 0, 1), race.num_polls, race.as_of])
        return buf.getvalue()

    @staticmethod
    def house_effects_csv(ss_result) -> str:
        """Build CSV from a StateSpaceResult for the house-effects chart."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["pollster", "delta_mean", "delta_lo", "delta_hi", "direction"])
        fx = ss_result.house_effects_sorted(threshold=0.5)
        for name, mean, lo, hi in fx:
            direction = "pro-Approve" if mean > 0 else "pro-Disapprove"
            w.writerow([name, round(mean, 2), round(lo, 2), round(hi, 2), direction])
        return buf.getvalue()

    # ── Private ──────────────────────────────────────────────────────

    def _put_data(self, chart_id: str, csv_data: str) -> bool:
        try:
            resp = self._client.put(
                f"/charts/{chart_id}/data",
                content=csv_data.encode(),
                headers={"Content-Type": "text/csv"},
            )
            resp.raise_for_status()
            logger.info("Updated data for chart %s", chart_id)
            return True
        except Exception as exc:
            logger.error("Failed to update chart %s: %s", chart_id, exc)
            return False

    def _publish(self, chart_id: str) -> bool:
        try:
            resp = self._client.post(f"/charts/{chart_id}/publish")
            resp.raise_for_status()
            logger.info("Published chart %s", chart_id)
            return True
        except Exception as exc:
            logger.error("Failed to publish chart %s: %s", chart_id, exc)
            return False
