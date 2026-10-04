# data/fallback — committed offline snapshots

These files keep every pipeline runnable with **zero network access and zero
API keys** (local dev, CI, tests). The daily `refresh_data` GitHub Actions
cron overwrites the live-source files; the rest are seeds or hand-curated
fixtures.

| File | What it is | Refreshed by |
|------|------------|--------------|
| `votehub_approval.csv` | Raw VoteHub approval polls (primary source) | cron (`--source votehub`) |
| `votehub_generic_ballot.csv` | Raw VoteHub generic-ballot polls | cron (`--source votehub`) |
| `votehub_senate.csv` | Raw VoteHub Senate head-to-head polls (absent until first fetch) | cron (`--source votehub`) |
| `silverb_approval.csv` / `silverb_generic_ballot.csv` | Silver Bulletin daily model estimates | cron (`--source silverb`) |
| `market_odds.csv` | Polymarket + Kalshi implied probabilities for key Senate races and chamber control. Rows with `is_seed=true` are hand-entered placeholders, **not** real market prices — they exist so the simulation runs offline and are replaced on the first successful market fetch. Races with no row (e.g. Texas/Maine after the Oct 2026 fix that dropped state-legislature markets) run polls-only until the next fetch finds the right market. | cron (`--source markets`) |
| `nyt_vibes.csv` | Cached output of the NYT media-sentiment ("vibes") pipeline. The committed file is a **neutral placeholder** (zero adjustment for every candidate) until the pipeline runs with `NYT_API_KEY` set. | vibes pipeline (manual; needs key) |
| `fiftyplusone_approval.csv` | Optional cached 50+1 approval series (`modeldate,approve,disapprove`, ISO dates). Not committed — the site shows the 50+1 toggle as "no data yet" until it exists. | manual (paid API) |
| `house_districts_2024.csv` | One row per congressional district: 2024 two-party Dem−Rep margin, winner, and whether the margin was imputed (uncontested seat → 2022 margin or a safe placeholder). Input to the House forecast. | `scripts/build_house_districts.py` (manual; downloads the 538 results archive) |
| `approval.csv`, `generic_ballot.csv`, `senate.csv` | Tiny hand-curated poll sets used as a last-resort fallback and for smoke tests | never (fixtures) |

Pipelines prefer the large live-source exports and only fall back to the
hand-curated fixtures when those are missing (see `_load_polls` in
`scripts/export_json.py`).
