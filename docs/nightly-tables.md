---
title: Nightly table automation
---

# Nightly table automation

## Current pipeline

The automation wraps the existing refresh and publish flow:

1. `scripts/refresh_data.py` refreshes source CSVs in `data/fallback/`.
2. `scripts/publish.py` builds Datawrapper-ready CSV payloads for approval, professional approval, generic ballot, Senate, and optional house-effects outputs.
3. `src/data/datawrapper.py` uploads CSV data to existing Datawrapper charts and publishes them.
4. Published Datawrapper charts remain available for Substack embeds.

## GitHub Actions schedule

`.github/workflows/nightly-tables.yml` runs nightly at `08:17 UTC` and can also be started manually with `workflow_dispatch`.

Pull requests run a safe verification mode:

```bash
python scripts/nightly_tables.py --dry-run --skip-refresh
```

Scheduled runs execute:

```bash
python scripts/nightly_tables.py
```

Manual dispatch can run all charts or one chart, with or without dry-run.

## Local verification

Install dependencies first:

```bash
pip install -e ".[dev]"
```

Verify using committed fallback data without external writes or publishing:

```bash
python scripts/nightly_tables.py --dry-run --skip-refresh
```

Verify live data fetching without writing refreshed files or publishing:

```bash
python scripts/nightly_tables.py --dry-run
```

Run a real local publish only after configuring `.env` with the Datawrapper token and chart IDs:

```bash
python scripts/nightly_tables.py
```

## Required repository secrets

Configure these in GitHub repository settings before enabling real scheduled publishing:

| Secret | Purpose |
|---|---|
| `DATAWRAPPER_API_TOKEN` | Datawrapper API bearer token used to update and publish charts. |
| `DW_CHART_APPROVAL_ID` | Existing Datawrapper chart ID for the approval trend. |
| `DW_CHART_GB_ID` | Existing Datawrapper chart ID for the generic ballot trend. |
| `DW_CHART_SENATE_ID` | Existing Datawrapper chart ID for the Senate snapshot. |

## Optional repository secrets

| Secret | Purpose |
|---|---|
| `DW_CHART_APPROVAL_PRO_ID` | Existing Datawrapper chart ID for the professional approval reference output. |
| `DW_CHART_HOUSE_EFFECTS_ID` | Existing Datawrapper chart ID for the optional house-effects output. |

## Remaining external requirements

The automation cannot create or approve external Datawrapper charts. Chart IDs must point to charts created in the Datawrapper UI, and the token must have permission to update and publish those charts.

`house_effects` still requires invoking `scripts/publish.py --state-space`; the default nightly workflow does not run the state-space model because it is slower and has optional Bayesian dependencies.
