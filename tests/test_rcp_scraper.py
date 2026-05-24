"""Tests for the RCP scraper with mocked HTML."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.data.base import PollType, Population
from src.data.rcp import RCPClient


MOCK_APPROVAL_HTML = """
<html>
<body>
<table>
  <tr>
    <th>Poll</th>
    <th>Date</th>
    <th>Sample</th>
    <th>Approve</th>
    <th>Disapprove</th>
    <th>Spread</th>
  </tr>
  <tr>
    <td>RCP Average</td>
    <td>1/15 - 2/15</td>
    <td>--</td>
    <td>43.5</td>
    <td>53.2</td>
    <td>-9.7</td>
  </tr>
  <tr>
    <td>Marist College</td>
    <td>2/10 - 2/13</td>
    <td>1100 LV</td>
    <td>44</td>
    <td>53</td>
    <td>-9</td>
  </tr>
  <tr>
    <td>Quinnipiac</td>
    <td>2/5 - 2/9</td>
    <td>1500 RV</td>
    <td>42</td>
    <td>55</td>
    <td>-13</td>
  </tr>
  <tr>
    <td>Emerson College</td>
    <td>2/1 - 2/4</td>
    <td>1000 A</td>
    <td>45</td>
    <td>51</td>
    <td>-6</td>
  </tr>
</table>
</body>
</html>
"""

MOCK_GB_HTML = """
<html>
<body>
<table>
  <tr>
    <th>Poll</th>
    <th>Date</th>
    <th>Sample</th>
    <th>Democrat</th>
    <th>Republican</th>
    <th>Spread</th>
  </tr>
  <tr>
    <td>RCP Average</td>
    <td>1/20 - 2/15</td>
    <td>--</td>
    <td>46.5</td>
    <td>45.0</td>
    <td>+1.5</td>
  </tr>
  <tr>
    <td>ABC/Ipsos</td>
    <td>2/8 - 2/12</td>
    <td>1200 LV</td>
    <td>48</td>
    <td>44</td>
    <td>+4</td>
  </tr>
  <tr>
    <td>Fox News</td>
    <td>2/1 - 2/5</td>
    <td>900 RV</td>
    <td>45</td>
    <td>46</td>
    <td>-1</td>
  </tr>
</table>
</body>
</html>
"""

MOCK_EMPTY_HTML = """
<html><body><p>No data available</p></body></html>
"""


class TestRCPParsing:
    def _make_client(self) -> RCPClient:
        return RCPClient()

    def test_parse_approval_table(self):
        client = self._make_client()
        url = "https://www.realclearpolling.com/polls/approval/president/donald-trump"
        polls = client._parse_polling_table(MOCK_APPROVAL_HTML, url)

        # Should skip "RCP Average" row
        assert len(polls) == 3

        # Check first real poll
        marist = polls[0]
        assert marist.pollster == "Marist College"
        assert marist.poll_type == PollType.APPROVAL
        assert marist.sample_size == 1100
        assert marist.population == Population.LIKELY_VOTERS
        assert len(marist.answers) >= 2

        approve_answer = next(a for a in marist.answers if "approve" in a.choice.lower())
        assert approve_answer.pct == 44.0

    def test_parse_generic_ballot_table(self):
        client = self._make_client()
        url = "https://www.realclearpolling.com/polls/generic-ballot/national"
        polls = client._parse_polling_table(MOCK_GB_HTML, url)

        # Should skip "RCP Average" row
        assert len(polls) == 2

        abc = polls[0]
        assert abc.pollster == "ABC/Ipsos"
        assert abc.poll_type == PollType.GENERIC_BALLOT
        assert abc.sample_size == 1200
        assert abc.population == Population.LIKELY_VOTERS

    def test_parse_empty_html(self):
        client = self._make_client()
        polls = client._parse_polling_table(MOCK_EMPTY_HTML, "https://example.com")
        assert polls == []

    def test_rcp_average_row_skipped(self):
        client = self._make_client()
        url = "https://www.realclearpolling.com/polls/approval/president/donald-trump"
        polls = client._parse_polling_table(MOCK_APPROVAL_HTML, url)
        pollster_names = [p.pollster for p in polls]
        assert "RCP Average" not in pollster_names

    def test_subject_from_url_trump(self):
        assert RCPClient._subject_from_url(
            "https://www.realclearpolling.com/polls/approval/president/donald-trump"
        ) == "Donald Trump"

    def test_subject_from_url_generic_ballot(self):
        assert RCPClient._subject_from_url(
            "https://www.realclearpolling.com/polls/generic-ballot/national"
        ) == "Generic Ballot"

    def test_subject_from_url_unknown(self):
        assert RCPClient._subject_from_url("https://example.com/other") == "Unknown"


class TestRCPDateParsing:
    def test_normal_date_range(self):
        start, end = RCPClient._parse_date_range("2/10 - 2/13")
        assert start.month == 2
        assert start.day == 10
        assert end.month == 2
        assert end.day == 13

    def test_year_rollover(self):
        start, end = RCPClient._parse_date_range("12/28 - 1/2")
        assert start.month == 12
        assert end.month == 1
        assert start.year == end.year - 1

    def test_invalid_date_fallback(self):
        start, end = RCPClient._parse_date_range("garbage")
        assert start == date.today()
        assert end == date.today()

    def test_empty_date(self):
        start, end = RCPClient._parse_date_range("")
        assert start == date.today()


class TestRCPSampleParsing:
    def test_lv_sample(self):
        size, pop = RCPClient._parse_sample("1100 LV")
        assert size == 1100
        assert pop == Population.LIKELY_VOTERS

    def test_rv_sample(self):
        size, pop = RCPClient._parse_sample("1500 RV")
        assert size == 1500
        assert pop == Population.REGISTERED_VOTERS

    def test_adults_sample(self):
        size, pop = RCPClient._parse_sample("1000 A")
        assert size == 1000
        assert pop == Population.ADULTS

    def test_empty_sample(self):
        size, pop = RCPClient._parse_sample("")
        assert size is None
        assert pop is None

    def test_no_population(self):
        size, pop = RCPClient._parse_sample("800")
        assert size == 800
        assert pop is None


class TestRCPFetchWithMock:
    @patch.object(RCPClient, "_fetch_page", return_value=MOCK_APPROVAL_HTML)
    def test_fetch_approval_polls(self, mock_fetch):
        client = RCPClient()
        polls = client.fetch_polls(poll_type=PollType.APPROVAL)
        assert len(polls) == 3
        assert all(p.poll_type == PollType.APPROVAL for p in polls)
        mock_fetch.assert_called_once()

    @patch.object(RCPClient, "_fetch_page", return_value=MOCK_GB_HTML)
    def test_fetch_gb_polls(self, mock_fetch):
        client = RCPClient()
        polls = client.fetch_polls(poll_type=PollType.GENERIC_BALLOT)
        assert len(polls) == 2
        assert all(p.poll_type == PollType.GENERIC_BALLOT for p in polls)

    def test_fetch_unknown_type_raises(self):
        client = RCPClient()
        with pytest.raises(ValueError, match="No known RCP URL"):
            client.fetch_polls(poll_type=PollType.PRIMARY)

    @patch.object(RCPClient, "_fetch_page", return_value=MOCK_APPROVAL_HTML)
    def test_cache_write_and_read(self, mock_fetch, tmp_path: Path):
        client = RCPClient(cache_dir=tmp_path)
        # First call fetches and caches
        polls1 = client.fetch_polls(poll_type=PollType.APPROVAL)
        assert len(polls1) == 3
        assert mock_fetch.call_count == 1

        # Second call should read from cache
        polls2 = client.fetch_polls(poll_type=PollType.APPROVAL)
        assert len(polls2) == 3
        assert mock_fetch.call_count == 1  # Not called again
