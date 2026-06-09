# Election Oracle

A Python-based election modeling and forecasting system that ingests polling data from multiple sources, computes weighted polling averages, and models election outcomes.

## Features

- **Multi-source polling ingestion** — VoteHub API, RealClearPolitics scraping, with CSV fallback (no API key required)
- **Weighted polling averages** — recency decay, Silver Bulletin PPM quality ratings, sample size scaling, population-type adjustments, and partisan bias correction
- **Jackman state-space model** — hierarchical random-walk latent state with additive house-effect correction (PyMC)
- **Presidential approval tracking** — daily averages with confidence intervals
- **Generic ballot model** — congressional preference tracking with historical seat projection
- **Senate race models** — individual race polling averages, with an experimental NYT "vibes" media-sentiment overlay
- **Senate control simulation** — 1,000-run Monte Carlo nowcast with correlated national error, blended with prediction-market odds
- **Prediction-market integration** — Polymarket and Kalshi implied odds per race and for chamber control (offline CSV fallback)
- **Model comparison** — our approval average side-by-side with Silver Bulletin, raw VoteHub averages, and 50+1 (when available)
- **Web tracker** — deployable Next.js front end (`web/`) that reads static JSON exported from the Python pipeline
- **Streamlit dashboard** — local exploration UI (skeleton)

## Local Setup

### 1. Clone the repo

```bash
git clone https://github.com/Hijodeagua/Election-models-by-Tre.git
cd Election-models-by-Tre
```

### 2. Install dependencies

```bash
# Core + dev tools
pip install -e ".[dev]"

# Add PyMC for the state-space model (optional, ~500MB)
pip install -e ".[bayesian]"
```

Python 3.11+ required.

### 3. Configure (optional)

```bash
cp .env.example .env
# No API keys required for offline/CSV mode
# Add VOTEHUB_BASE_URL etc. only if you want live data fetching
```

### 4. Run the model

```bash
# Standard weighted-average output (fast, uses bundled CSV data — no internet needed)
python scripts/run_models.py --offline

# Add Jackman state-space estimates with house-effect breakdown (~2 min, requires PyMC)
python scripts/run_models.py --offline --state-space

# Force the small hand-curated CSV fallback (5 polls per model — useful for smoke testing)
python scripts/run_models.py --source csv
```

### 5. Run the test suite

```bash
pytest                  # 147 tests, ~8 seconds
pytest tests/test_models.py -v   # just the polling engine tests
```

### Data sources (offline mode)

All fallback data lives in `data/fallback/` and is committed to the repo — no downloads needed:

| File | Contents | Polls |
|---|---|---|
| `votehub_approval.csv` | VoteHub approval polls, Jan 2025 – May 2026 | 683 |
| `votehub_generic_ballot.csv` | VoteHub generic ballot polls | 344 |
| `silverb_approval.csv` | Silver Bulletin daily model estimates | daily |
| `silverb_generic_ballot.csv` | Silver Bulletin generic ballot estimates | daily |
| `approval.csv` / `generic_ballot.csv` / `senate.csv` | Hand-curated samples | 5 each |

### Expected output (weighted average, offline)

```
Election Oracle — 2026-05-24
Presidential Approval  N=683:   Approve 40.3% [38.8–41.4]  Net -15.9
Generic Ballot         N=344:   D 46.4% / R 41.1%  D+5.3  →  D 247 / R 188 seats
Senate (5 races):  AZ Gallego +4.4 · GA Collins +1.0 · MI Peters +3.0 ...
```

### Expected output (with --state-space)

```
State-space Approve: 39.5% [37.8, 40.9]  σ_α=0.23pp/day
House effects (40 pollsters with |δ|>1.5pp):
  InsiderAdvantage     +6.6pp  pro-Approve
  AP-NORC              -4.1pp  pro-Disapprove
  Quinnipiac           -4.0pp  pro-Disapprove
  ...
```

## Web Tracker (`web/`)

A deployable Next.js 14 (App Router) static site that presents the trackers —
presidential approval (with a toggleable multi-model comparison chart), generic
ballot, Senate race cards (vibes toggle + market-odds chips), a Senate-control
simulation page, and a methodology page. It reads the static JSON files in
`web/public/data/`, which are produced by the Python pipeline; it runs no
Python server itself.

```bash
# 1. Regenerate the static JSON from the offline pipeline
python scripts/export_json.py

# 2. Build / run the front end
cd web
npm install
npm run dev        # http://localhost:3000/election
npm run build      # production build (static, prerendered)
```

The site is framed explicitly as a **tracker, not a forecast** — it shows
weighted polling averages and confidence bands only, with no win probabilities.
It is served under the `/election` base path (see `web/next.config.mjs`).

### Automated refresh

`.github/workflows/refresh_data.yml` runs daily: it best-effort refreshes the
source CSVs, runs `scripts/export_json.py`, and commits the updated JSON. The
data refresh is offline-resilient — if a source is unreachable, the export falls
back to the committed CSVs in `data/fallback/`.

## Project Structure

```
election-oracle/
├── config/                  # Settings and pollster ratings
│   ├── settings.py          # Pydantic-based configuration
│   └── pollster_ratings.json
├── src/
│   ├── data/                # Data source clients
│   │   ├── base.py          # Abstract DataSource interface + Poll schema
│   │   ├── votehub.py       # VoteHub API client (free, CC BY 4.0)
│   │   ├── rcp.py           # RealClearPolitics scraper
│   │   ├── fiftyplusone.py  # FiftyPlusOne API (paid, stub)
│   │   ├── silver_bulletin.py
│   │   └── congress_gov.py
│   ├── models/              # Election models
│   │   ├── polling_average.py  # Core weighted average engine
│   │   ├── approval.py      # Presidential approval model
│   │   ├── generic_ballot.py   # Generic ballot + seat projection
│   │   ├── senate.py        # Senate race models
│   │   ├── house.py         # House race models
│   │   ├── governor.py      # Governor race models
│   │   └── presidential.py  # 2028 primary tracker
│   ├── analysis/            # Analytical utilities
│   │   ├── pollster_weights.py  # Pollster rating management
│   │   ├── trend.py         # Trend smoothing
│   │   ├── historical.py    # Historical cycle comparisons
│   │   └── fundamentals.py  # Non-polling fundamentals
│   ├── db/                  # Database layer (SQLModel ORM)
│   │   └── models.py
│   └── dashboard/           # Streamlit dashboard
│       └── app.py
├── tests/                   # Test suite
├── scripts/                 # Data refresh and backfill scripts
├── notebooks/               # Jupyter exploration notebooks
└── data/                    # Raw, processed, and historical data
```

## Polling Average Methodology

The core engine (`src/models/polling_average.py`) computes weighted averages using:

1. **Recency weighting** — exponential decay with configurable half-life (default 14 days)
2. **Pollster quality** — ratings from Silver Bulletin / custom (0–3 scale)
3. **Sample size** — sqrt scaling (larger samples get more weight)
4. **Population screen** — LV > RV > Adults weighting multipliers
5. **Partisan penalty** — polls from partisan sponsors are downweighted
6. **Bootstrap confidence intervals** — 1000 bootstrap samples for uncertainty quantification

## Data Sources

| Source | Type | Cost | Status |
|--------|------|------|--------|
| VoteHub | API | Free (CC BY 4.0) | Implemented |
| RealClearPolitics | Scraper | Free | Implemented |
| FiftyPlusOne | API | $8/mo+ | Stub (adapter ready) |
| Silver Bulletin | CSV download | Free | Implemented (model-estimate CSV loader + downloader) |
| Congress.gov | API | Free | Stub |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check .
```

## Configuration

All settings are managed via environment variables or `.env` file. See `.env.example` for available options.

Key polling average parameters are configurable in `config/settings.py`:
- `recency_half_life_days` — how fast old polls decay (default: 14)
- `lv_weight_multiplier` — extra weight for likely voter polls (default: 1.5)
- `partisan_bias_penalty` — weight penalty for partisan polls (default: 0.5)

## License

MIT
