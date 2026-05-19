# Election Oracle — Project Plan

A standalone reference document so a fresh Claude session can pick up where the
last one left off. This captures the full project state, decisions made,
methodology, and what's left to build.

---

## 1. Project Overview

**Election Oracle** is a Python-based election modeling and forecasting system
that ingests polling data from multiple sources, computes weighted polling
averages, models election outcomes, and produces media-sentiment-based "vibes"
metrics for candidates. Charts are designed to be published to a Substack
newsletter (Policy & Peaches) via Datawrapper embeds.

**Project owner:** Tre (data scientist, MPH in Epidemiology and Biostatistics)
**GitHub repo:** `Hijodeagua/Election-models-by-Tre`
**Current branch:** `claude/init-election-oracle-Pe1bx`
**Test status:** 105 tests passing across 5 test files

---

## 2. Repository Structure

```
election-oracle/
├── README.md
├── PROJECT_PLAN.md              # This file
├── pyproject.toml               # Dependencies and build config
├── .env.example                 # Template for secrets
├── .gitignore
│
├── config/
│   ├── settings.py              # Pydantic settings (reads .env)
│   └── pollster_ratings.json    # Pollster quality ratings (0–3 scale)
│
├── src/
│   ├── data/                    # Data source clients
│   │   ├── base.py              # Abstract DataSource + Poll/PollAnswer schema
│   │   ├── votehub.py           # VoteHub API client (free, CC BY 4.0)
│   │   ├── rcp.py               # RealClearPolitics scraper
│   │   ├── fiftyplusone.py      # FiftyPlusOne API client (paid, stub)
│   │   ├── silver_bulletin.py   # Silver Bulletin scraper (stub)
│   │   ├── congress_gov.py      # Congress.gov API (stub)
│   │   └── forecasters.py       # Race ratings (Cook/Sabato/538/RCP)
│   │
│   ├── models/                  # Election models
│   │   ├── polling_average.py   # Weighted average engine (CORE)
│   │   ├── approval.py          # Presidential approval tracker
│   │   ├── generic_ballot.py    # Generic ballot + seat projection
│   │   ├── senate.py            # Senate race models
│   │   ├── house.py             # House race models (stub)
│   │   ├── governor.py          # Governor race models (stub)
│   │   ├── presidential.py      # 2028 primary tracker (stub)
│   │   └── candidate_quality.py # WAR-style quality model
│   │
│   ├── media/                   # Media sentiment analysis
│   │   ├── nyt.py               # NYT Archive + Search API client
│   │   ├── mentions.py          # Candidate mention extraction
│   │   ├── sentiment.py         # Transformer + keyword scorers
│   │   └── vibes.py             # Three vibes metrics
│   │
│   ├── analysis/                # Analytical utilities
│   │   ├── pollster_weights.py  # Pollster rating manager
│   │   ├── trend.py             # Trend smoothing
│   │   ├── historical.py        # Historical cycle comparisons
│   │   └── fundamentals.py      # Non-polling fundamentals
│   │
│   ├── db/
│   │   └── models.py            # SQLModel ORM (9 tables)
│   │
│   └── dashboard/
│       └── app.py               # Streamlit dashboard skeleton
│
├── tests/                       # 105 passing tests
│   ├── test_data_sources.py
│   ├── test_models.py
│   ├── test_analysis.py
│   ├── test_media.py
│   └── test_forecasters.py
│
├── scripts/
│   ├── refresh_data.py          # Scheduled data pull
│   └── backfill.py              # Historical backfill (stub)
│
├── notebooks/                   # Empty — ready for exploration
│
└── data/
    ├── raw/                     # API response cache
    ├── processed/               # Cleaned datasets
    └── historical/              # Past election results
```

---

## 3. What's Been Built

### Data Layer
- **VoteHub API client** — Full client with retry logic (tenacity), per-query disk caching, retrieves polls/pollsters/subjects/poll-types, normalizes to `Poll` dataclass
- **RealClearPolitics scraper** — BeautifulSoup-based, handles RCP/realclearpolling.com table formats with date range parsing
- **Stubs for FiftyPlusOne, Silver Bulletin, Congress.gov** — Adapter-ready, gated behind config (`is_configured` property)
- **Forecaster ratings** — 7-point normalized rating scale (Solid D → Solid R), consensus aggregation, 538 historical CSV loader

### Polling Average Engine (`src/models/polling_average.py`)
Core weighted average with:
1. Recency exponential decay (configurable half-life, default 14 days)
2. Pollster quality weighting (0–3 scale from `pollster_ratings.json`)
3. Sample size sqrt scaling
4. Population multipliers (LV=1.5x, RV=1.0x, Adults=0.6x)
5. Partisan sponsor penalty (0.5x)
6. Bootstrap confidence intervals (1000 samples)
7. Auto-detection of answer choices

### Election Models
- **Presidential approval** — Daily snapshots with trend analysis
- **Generic ballot** — Translation to House seats (~5.5 seats per margin point)
- **Senate** — Per-state polling aggregation
- **Candidate quality / WAR** — Fundamentals-only baseline → expected vote share → residual = candidate quality. Inputs: partisan lean, generic ballot, incumbency, presidential approval × same-party, midterm penalty. Includes backtesting with RMSE/MAE.
- **House, Governor, Presidential Primary** — Stubs awaiting data

### Media Sentiment Pipeline (`src/media/`)
- **NYT client** — Archive API (every article by month) + Article Search API. Built-in rate limiting (10 req/min), per-month caching, political filter
- **Mention extraction** — Candidate name + alias matching, sentence-level windowing with neighboring context, deduplication
- **Sentiment scoring** — Two backends:
  - `TransformerScorer`: cardiffnlp/twitter-roberta-base-sentiment-latest (requires `[ml]` extra: `transformers` + `torch`)
  - `KeywordScorer`: zero-dependency fallback with curated political-news patterns
- **Three vibes metrics:**
  1. **Pos/neg %** — Simple count of positive vs negative scored mentions
  2. **Five buckets** — Overwhelmingly positive (>70%) / More positive (>55%) / Neutral-mixed / More negative (>55%) / Overwhelmingly negative (>70%)
  3. **Scandal flags** — 18 trigger patterns (indictment, ethics violation, sexual misconduct, federal investigation, etc.) with 0–1 severity scoring and mention-count aggregation

### Database (SQLModel)
9 tables: polls, poll_results, pollster_ratings, polling_averages, races, candidates, race_ratings, historical_results. Default to SQLite for dev, Postgres-ready.

### Analysis Utilities
- Pollster weight manager (case-insensitive lookup, persistence)
- Moving average trend smoothing
- Historical midterm benchmarks (2006–2022)
- Fundamentals-based structural lean estimation

---

## 4. Key Methodology Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Primary polling source | VoteHub (free, CC BY 4.0) | 538 shut down March 2025; VoteHub is the most accessible replacement |
| Sentiment backend | Transformer first, keyword fallback | Lexicon methods (VADER) fail on political framing like "denied", "dogged by", "faces questions over" |
| Sentiment model | cardiffnlp/twitter-roberta-base-sentiment-latest | News-trained, free, runs locally |
| Vibe buckets | Five buckets at 70/55/55/70 thresholds | Matches conventional polling/forecasting language |
| Scandal patterns | 18 curated regex triggers with severity weights | Indictment=1.0, scandal=0.85, affair=0.6, etc. |
| Forecaster scale | 7-point Solid D → Solid R | Standard across Cook/Sabato/Inside Elections |
| Win prob mapping | Solid=0.97, Likely=0.85, Lean=0.65, Tossup=0.50 | Industry-standard implied probabilities |
| Generic-D/R baseline | OLS-style linear model with fundamentals | Split Ticket / G. Elliott Morris approach |
| WAR definition | Actual vote share − expected vote share | Isolates candidate-specific signal from structure |
| Recency half-life | 14 days for approval polls | Aligns with 538-era conventions |
| Publishing platform | Datawrapper → Substack embed | Matches Silver Bulletin's workflow; Substack whitelists Datawrapper |

---

## 5. What's Left to Build

### Immediate Next Steps
1. **Datawrapper publishing module** (`src/publishing/datawrapper.py`)
   - Push model output to Datawrapper via their REST API
   - Auto-update charts on data refresh
   - Generate embed URLs for Substack posts
   - Requires: `DATAWRAPPER_API_TOKEN` in `.env`

2. **Run pipeline against live data** (once API keys are in place)
   - Test VoteHub + RCP ingestion end-to-end
   - Verify NYT mention extraction on real 2022/2024 articles
   - Sanity-check vibes metrics against known cases

3. **Vibes backtest notebook** (`notebooks/04_vibes_backtest.ipynb`)
   - Pull NYT coverage for 2016/18/20/22 Senate + Governor races
   - Compute vibes metrics per candidate
   - Run three regression specs:
     - `win ~ vibes_metric`
     - `win ~ vibes_metric + fundamentals`
     - `win ~ vibes_metric + fundamentals + forecaster_consensus`
   - Report R², AUC, marginal effects

### Medium-term
4. **Fundamentals data ingestion** — FRED API for GDP, inflation, unemployment, wage growth
5. **Streamlit dashboard** — Build out the three placeholder tabs (approval, generic ballot, senate)
6. **Historical results backfill** — Populate `data/historical/` with past election outcomes
7. **House district-level model** — Generic-ballot extrapolation + district polling where available
8. **Coefficient refinement** — Replace `DEFAULT_COEFFICIENTS` in `candidate_quality.py` with values fit from real backtest

### Eventually
9. **2028 primary tracker** — Once primary polling ramps up
10. **Race ratings tracker** — Scrape Cook/Sabato/Inside Elections weekly
11. **Substack publishing automation** — Auto-generate chart-heavy draft posts on a schedule

---

## 6. Configuration

### Required API keys (set in `.env`)
- `NYT_API_KEY` — Free at developer.nytimes.com (4000 req/day, 10 req/min)
- `DATAWRAPPER_API_TOKEN` — Free at app.datawrapper.de/account/api-tokens
- `CONGRESS_GOV_API_KEY` — Optional, free at api.congress.gov
- `FIFTYPLUSONE_API_KEY` — Optional, paid ($8/mo+)

### Tunable parameters (in `config/settings.py`)
- `recency_half_life_days = 14.0`
- `min_sample_size = 100`
- `lv_weight_multiplier = 1.5`
- `rv_weight_multiplier = 1.0`
- `adults_weight_multiplier = 0.6`
- `partisan_bias_penalty = 0.5`

### Install
```bash
pip install -e ".[dev]"           # Base + dev tools
pip install -e ".[dev,ml]"        # Add transformers/torch for sentiment
pip install -e ".[dev,bayesian]"  # Add PyMC for Bayesian models (future)
```

---

## 7. Quick-Start for a Fresh Session

```bash
# 1. Get on the branch
git fetch origin claude/init-election-oracle-Pe1bx
git checkout claude/init-election-oracle-Pe1bx

# 2. Install
pip install -e ".[dev]"

# 3. Verify tests pass (should see 105 passed)
python -m pytest tests/ -v

# 4. Check what's there
ls src/         # data/ media/ models/ analysis/ db/ dashboard/
ls tests/       # 5 test files
cat PROJECT_PLAN.md  # This file
```

---

## 8. Open Questions / Decisions Pending

- **Datawrapper free vs paid?** Free tier works for testing but includes Datawrapper branding. Paid ($599/yr) for custom branding when ready to ship.
- **Default branch on GitHub** — Currently only `claude/init-election-oracle-Pe1bx` exists. May need to promote to `main` for clean PR workflow.
- **Fundamentals data source** — FRED is the obvious choice for economic indicators, but need to decide which series specifically (GDP growth Q2 vs Q3, headline CPI vs core, etc.)
- **Vibes time windows** — Should backtest use the final 4 weeks before election, the final 12 weeks, or post-primary through election day? Tradeoff between signal strength and sample size.
- **Sentiment for primary races** — Same model as general election, or does primary coverage need its own tuning?

---

## 9. Related Reference

### Data sources (priority order)
1. VoteHub API (free, CC BY 4.0) — base URL `https://votehub.com/polls/api`
2. RealClearPolitics scraping (free)
3. NYT Archive + Search API (free, requires key)
4. Datawrapper publishing API (free tier)
5. FiftyPlusOne (paid) — adapter ready
6. Silver Bulletin (paid for full, free pollster ratings)
7. FRED (free) — for fundamentals (not yet integrated)

### External landscape
- 538 shut down March 2025; NYT picked up the tracker
- G. Elliott Morris (ex-538) launched Strength In Numbers + FiftyPlusOne
- Nate Silver runs Silver Bulletin independently
- Split Ticket popularized the WAR concept for candidate quality
- Substack supports Datawrapper, Flourish, Infogram, Tableau Public embeds

---

## 10. Branch / Commit History

| Commit | Description |
|---|---|
| `fd1ec8f` | Initialize election-oracle repo with full project structure |
| `093ee9f` | Add media sentiment pipeline, forecaster ratings, and candidate quality model |
| `66ea2ad` | Add Datawrapper API token config slot |

All work is on branch `claude/init-election-oracle-Pe1bx`, pushed to origin.
