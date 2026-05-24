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
    approval_pro: str = ""
    generic_ballot_trend: str = ""
    senate_snapshot: str = ""
    house_effects: str = ""

    @classmethod
    def from_settings(cls) -> ChartIds:
        return cls(
            approval_trend=getattr(settings, "dw_chart_approval_id", ""),
            approval_pro=getattr(settings, "dw_chart_approval_pro_id", ""),
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

    def update_and_publish(self, chart_id: str, csv_data: str, metadata: dict | None = None) -> bool:
        """Upload CSV data, optionally apply metadata, then publish. Returns True on success."""
        if not chart_id:
            logger.warning("No chart ID provided — skipping")
            return False
        ok = self._put_data(chart_id, csv_data)
        if ok and metadata:
            self._patch_metadata(chart_id, metadata)
        if ok:
            ok = self._publish(chart_id)
        return ok

    def get_chart_info(self, chart_id: str) -> dict:
        """Fetch chart metadata (useful for debugging)."""
        resp = self._client.get(f"/charts/{chart_id}")
        resp.raise_for_status()
        return resp.json()

    # ── Chart metadata presets ───────────────────────────────────────

    @staticmethod
    def approval_metadata() -> dict:
        approve_color = "#c0392b"     # red
        disapprove_color = "#2166ac"  # blue
        return {
            "title": "Do Americans <span style='color:#c0392b'>approve</span> or <span style='color:#2166ac'>disapprove</span> of Donald Trump?",
            "metadata": {
                "describe": {
                    "intro": "A polling average of Trump's approval rating, accounting for each poll's quality, recency, sample size, and partisan lean.",
                    "byline": "Policy & Peaches",
                    "source-name": "VoteHub / Silver Bulletin",
                },
                "annotate": {
                    "notes": "Shaded regions show 95% confidence intervals around the polling average.",
                },
                "visualize": {
                    "custom-colors": {
                        "approve": approve_color,
                        "disapprove": disapprove_color,
                        "approve_lo": approve_color,
                        "approve_hi": approve_color,
                        "disapprove_lo": disapprove_color,
                        "disapprove_hi": disapprove_color,
                    },
                    "ranges": [
                        {"from": "approve_lo", "to": "approve_hi", "color": approve_color, "opacity": 0.18},
                        {"from": "disapprove_lo", "to": "disapprove_hi", "color": disapprove_color, "opacity": 0.18},
                    ],
                    "line-widths": {
                        "approve": 2.5, "disapprove": 2.5,
                        "approve_lo": 0, "approve_hi": 0,
                        "disapprove_lo": 0, "disapprove_hi": 0,
                    },
                    "custom-labels": {
                        "approve": "Approve",
                        "disapprove": "Disapprove",
                        "approve_lo": "",
                        "approve_hi": "",
                        "disapprove_lo": "",
                        "disapprove_hi": "",
                    },
                },
                "axes": {"x": "date", "y": "approve,disapprove,approve_lo,approve_hi,disapprove_lo,disapprove_hi"},
            },
        }

    @staticmethod
    def approval_pro_metadata() -> dict:
        return {
            "title": "Presidential Approval — Professional Reference",
            "metadata": {
                "describe": {
                    "intro": "Average of established polling models (Silver Bulletin, +RCP when available) for cross-check",
                    "byline": "Policy & Peaches",
                    "source-name": "Silver Bulletin model",
                },
                "visualize": {
                    "custom-colors": {
                        "approve": "#c0392b",
                        "disapprove": "#2166ac",
                        "net": "#999999",
                    },
                    "line-widths": {"approve": 2.5, "disapprove": 2.5, "net": 1.5},
                    "custom-labels": {
                        "approve": "Approve",
                        "disapprove": "Disapprove",
                        "net": "Net approval",
                    },
                },
                "axes": {"x": "date", "y": "approve,disapprove,net"},
            },
        }

    @staticmethod
    def generic_ballot_metadata() -> dict:
        return {
            "title": "Generic Congressional Ballot",
            "metadata": {
                "describe": {
                    "intro": "90-day polling average · which party's candidate would you vote for in Congress?",
                    "byline": "Policy & Peaches",
                    "source-name": "VoteHub / Silver Bulletin",
                },
                "visualize": {
                    "custom-colors": {
                        "dem": "#2166ac",
                        "rep": "#d6604d",
                        "margin": "#999999",
                        "dem_lo": "#2166ac",
                        "dem_hi": "#2166ac",
                    },
                    "range": {"dem_lo": "dem_hi"},
                    "range-opacity": 0.15,
                    "line-widths": {"dem": 2.5, "rep": 2.5, "margin": 1.5,
                                    "dem_lo": 0, "dem_hi": 0},
                    "custom-labels": {
                        "dem": "Democrat",
                        "rep": "Republican",
                        "margin": "Dem margin",
                        "dem_lo": "",
                        "dem_hi": "",
                    },
                },
                "axes": {"x": "date", "y": "dem,rep,margin,dem_lo,dem_hi"},
            },
        }

    @staticmethod
    def senate_metadata() -> dict:
        return {
            "title": "Senate Race Polling Averages",
            "metadata": {
                "describe": {
                    "intro": "Current polling averages for competitive 2026 Senate races",
                    "byline": "Policy & Peaches",
                    "source-name": "VoteHub",
                },
            },
        }

    # ── Chart-specific CSV builders ──────────────────────────────────

    @staticmethod
    def approval_trend_csv(snapshots: list) -> str:
        """Build CSV from a list of ApprovalSnapshot objects (approval_trend output)."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "approve", "disapprove",
                    "approve_lo", "approve_hi", "disapprove_lo", "disapprove_hi"])
        for s in snapshots:
            a_lo = s.ci_approve[0] if s.ci_approve else ""
            a_hi = s.ci_approve[1] if s.ci_approve else ""
            d_lo = s.ci_disapprove[0] if s.ci_disapprove else ""
            d_hi = s.ci_disapprove[1] if s.ci_disapprove else ""
            w.writerow([s.as_of, round(s.approve, 2), round(s.disapprove, 2),
                        a_lo, a_hi, d_lo, d_hi])
        return buf.getvalue()

    @staticmethod
    def approval_pro_consensus_csv(
        silverb_csv_path,
        rcp_csv_path=None,
        start_date=None,
    ) -> str:
        """Average available professional model outputs by date.

        Currently averages Silver Bulletin (always) with RCP if its CSV exists.
        Reads SB's daily smoothed model output directly.
        """
        from collections import defaultdict
        from datetime import datetime as _dt

        per_day: dict = defaultdict(list)

        def _parse_sb_date(s: str):
            for fmt in ("%m/%d/%y", "%Y-%m-%d"):
                try:
                    return _dt.strptime(s, fmt).date()
                except ValueError:
                    continue
            return None

        with open(silverb_csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = _parse_sb_date(row.get("modeldate", ""))
                if not d:
                    continue
                if start_date and d < start_date:
                    continue
                try:
                    per_day[d].append(("sb", float(row["approve"]), float(row["disapprove"])))
                except (KeyError, ValueError):
                    continue

        if rcp_csv_path and rcp_csv_path.exists():
            with open(rcp_csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pass  # placeholder — RCP schema differs; wire when format known

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "approve", "disapprove", "net", "n_models"])
        for d in sorted(per_day):
            entries = per_day[d]
            approve = sum(e[1] for e in entries) / len(entries)
            disapprove = sum(e[2] for e in entries) / len(entries)
            w.writerow([d, round(approve, 2), round(disapprove, 2),
                        round(approve - disapprove, 2), len(entries)])
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

    def _patch_metadata(self, chart_id: str, metadata: dict) -> bool:
        try:
            resp = self._client.patch(
                f"/charts/{chart_id}",
                json=metadata,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Failed to patch metadata for chart %s: %s", chart_id, exc)
            return False

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
