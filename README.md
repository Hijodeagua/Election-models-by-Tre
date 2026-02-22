# Election Oracle

A Python-based election modeling and forecasting system that ingests polling data from multiple sources, computes weighted polling averages, and models election outcomes.

## Features

- **Multi-source polling ingestion** — VoteHub API, RealClearPolitics scraping, with adapters for FiftyPlusOne and Silver Bulletin
- **Weighted polling averages** — recency decay, pollster quality ratings, sample size scaling, likely voter adjustments, and partisan bias correction
- **Presidential approval tracking** — daily averages with confidence intervals and trend analysis
- **Generic ballot model** — congressional preference tracking with historical seat projection
- **Senate/House/Governor race models** — individual race polling and race ratings integration
- **2028 presidential primary tracker** — early primary and favorability polling
- **Interactive dashboard** — Streamlit-based visualization

## Quick Start

```bash
# Clone and install
git clone https://github.com/Hijodeagua/Election-models-by-Tre.git
cd Election-models-by-Tre
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your API keys (VoteHub is free, no key needed)

# Run data refresh
python -m scripts.refresh_data

# Launch dashboard
streamlit run src/dashboard/app.py
```

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
| Silver Bulletin | Scraper | Free (ratings) | Stub |
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
