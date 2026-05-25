"""LLM-based prediction extraction from NYT Senate race articles.

For each article, classifies whether it contains a directional prediction
(who will win the race) and extracts the predicted winner, confidence level,
and the journalist who wrote it.

Uses Claude Haiku via the Anthropic API — roughly $0.25 per 2,000 articles.
Results are cached to data/vibes/predictions.json; re-runs skip cached articles.

Set ANTHROPIC_API_KEY in .env before running.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic

from src.models.vibes import ArticleSignal

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_PATH = Path("data/vibes/predictions.json")
_MODEL = "claude-haiku-4-5-20251001"
_RATE_LIMIT_SLEEP_SEC = 0.5   # Haiku is fast; small sleep avoids burst limits
_MAX_TEXT_CHARS = 800          # headline + snippet/lead, truncated to keep tokens low

# Valid enum values — normalize unexpected model output to defaults
_VALID_ARTICLE_TYPES = {
    "horse_race", "poll_coverage", "candidate_profile", "endorsement",
    "scandal", "debate", "fundraising", "policy", "other",
}
_VALID_SUBJECTS = {"Democrat", "Republican", "both", "race_general"}
_VALID_HOOKS = {
    "new_poll", "endorsement", "gaffe", "debate",
    "ad_buy", "campaign_event", "early_voting", "other",
}
_VALID_SENTIMENTS = {"positive", "negative", "neutral"}
_VALID_WINNERS = {"D", "R", "tossup", "none"}
_VALID_CONFIDENCE = {"clear", "moderate", "slight", "none"}


@dataclass
class PredictionRecord:
    """Extracted prediction and metadata from a single NYT article."""

    article_id: str
    race: str
    state: str
    year: int
    byline: str                # "By NICHOLAS FANDOS" or ""
    publication_date: str      # ISO date string

    # Prediction fields
    has_prediction: bool       # Does the article contain a directional prediction?
    predicted_winner: str      # "D" | "R" | "tossup" | "none"
    confidence: str            # "clear" | "moderate" | "slight" | "none"
    key_phrase: str            # Short quote supporting the prediction

    # Article classification
    article_type: str          # "horse_race" | "poll_coverage" | "candidate_profile" |
                               # "endorsement" | "scandal" | "debate" | "fundraising" |
                               # "policy" | "other"
    primary_subject: str       # "Democrat" | "Republican" | "both" | "race_general"
    news_hook: str             # "new_poll" | "endorsement" | "gaffe" | "debate" |
                               # "ad_buy" | "campaign_event" | "early_voting" | "other"

    # Candidate-aware sentiment — independent scales, NOT opposites.
    # An article can be positive for both (tight tossup, both doing well),
    # negative for both (ugly race), or any other combination.
    # Analyze as a (dem_sentiment, rep_sentiment) pair — the 3×3 matrix matters.
    # Do NOT reduce to a single dem-rep diff score; that collapses (pos,pos) and
    # (neutral,neutral) into the same value, losing the tossup signal.
    dem_sentiment: str         # "positive" | "negative" | "neutral"
    rep_sentiment: str         # "positive" | "negative" | "neutral"

    # Human-readable summary
    summary: str               # 2-sentence plain-English summary

    model: str                 # LLM model used


_SYSTEM_PROMPT = """\
You analyze US Senate race news articles and return structured metadata in one JSON object.
Respond ONLY with JSON — no prose, no markdown fences.

Required fields:

PREDICTION (is there a forward-looking judgment about who will win?)
  has_prediction   : true if the article forecasts a winner, false if it only reports facts/polls
  predicted_winner : "D", "R", "tossup", or null (null when has_prediction is false)
  confidence       : "clear" (likely/expected/favored), "moderate" (slight edge/leans),
                     "slight" (marginal/could go either way), or null
  key_phrase       : 15-word max quote that encodes the prediction, or ""

CLASSIFICATION
  article_type   : one of: horse_race | poll_coverage | candidate_profile |
                   endorsement | scandal | debate | fundraising | policy | other
  primary_subject: who the article is primarily about: Democrat | Republican | both | race_general
  news_hook      : what triggered this article: new_poll | endorsement | gaffe | debate |
                   ad_buy | campaign_event | early_voting | other

CANDIDATE-AWARE SENTIMENT (judge separately for each party's candidate)
  dem_sentiment  : positive | negative | neutral
  rep_sentiment  : positive | negative | neutral

SUMMARY
  summary        : exactly 2 sentences summarizing what the article says about this race

Example output:
{
  "has_prediction": true,
  "predicted_winner": "D",
  "confidence": "moderate",
  "key_phrase": "holds a narrow but durable lead",
  "article_type": "horse_race",
  "primary_subject": "both",
  "news_hook": "new_poll",
  "dem_sentiment": "positive",
  "rep_sentiment": "neutral",
  "summary": "A new Marquette poll shows the Democratic candidate leading by 4 points.
Analysts say the margin reflects strength with suburban voters."
}
"""


def _build_user_message(signal: ArticleSignal) -> str:
    text = signal.lead_paragraph or signal.snippet or ""
    body = f"{signal.headline}\n{text}".strip()
    if len(body) > _MAX_TEXT_CHARS:
        body = body[:_MAX_TEXT_CHARS] + "…"
    return f"Race: {signal.race}\n\n{body}"


class PredictionExtractor:
    """Extract directional predictions from ArticleSignals using Claude Haiku.

    Parameters
    ----------
    api_key:
        Anthropic API key. Defaults to ANTHROPIC_API_KEY env var.
    cache_path:
        Path to the JSON file where extracted predictions are persisted.
    """

    def __init__(
        self,
        api_key: str | None = None,
        cache_path: Path = _DEFAULT_CACHE_PATH,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self._client = anthropic.Anthropic(api_key=key)
        self.cache_path = cache_path
        self._cache: dict[str, dict] = self._load_cache()

    # ── Public interface ───────────────────────────────────────────────────────

    def extract_all(
        self,
        signals: list[ArticleSignal],
        *,
        skip_cached: bool = True,
        save_every: int = 50,
    ) -> list[PredictionRecord]:
        """Run extraction over a list of ArticleSignals.

        Skips articles already in cache if skip_cached=True.
        Saves to disk every `save_every` new extractions.
        """
        to_process = [
            s for s in signals
            if not skip_cached or s.article_id not in self._cache
        ] if skip_cached else signals

        logger.info(
            "Extracting predictions: %d articles (%d cached, %d to process)",
            len(signals), len(signals) - len(to_process), len(to_process),
        )

        for i, signal in enumerate(to_process, 1):
            try:
                record = self._classify(signal)
                self._cache[signal.article_id] = asdict(record)
            except Exception as exc:
                logger.warning("Failed to classify %s: %s", signal.article_id, exc)

            if i % save_every == 0:
                self._save_cache()
                logger.info("  saved checkpoint at %d/%d", i, len(to_process))

            time.sleep(_RATE_LIMIT_SLEEP_SEC)

        self._save_cache()
        return [PredictionRecord(**v) for v in self._cache.values()]

    def load_cached(self) -> list[PredictionRecord]:
        """Return all cached predictions without making any API calls."""
        return [PredictionRecord(**v) for v in self._cache.values()]

    # ── Classification ─────────────────────────────────────────────────────────

    def _classify(self, signal: ArticleSignal) -> PredictionRecord:
        user_msg = _build_user_message(signal)
        response = self._client.messages.create(
            model=_MODEL,
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            import re
            clean = re.sub(r"```[a-z]*\n?", "", raw).strip()
            parsed = json.loads(clean)

        def _norm(val: object, valid: set[str], default: str) -> str:
            s = str(val).strip() if val else ""
            return s if s in valid else default

        has_pred = bool(parsed.get("has_prediction", False))
        return PredictionRecord(
            article_id=signal.article_id,
            race=signal.race,
            state=signal.state,
            year=signal.year,
            byline=signal.byline,
            publication_date=signal.publication_date.isoformat(),
            has_prediction=has_pred,
            predicted_winner=_norm(parsed.get("predicted_winner"), _VALID_WINNERS, "none"),
            confidence=_norm(parsed.get("confidence"), _VALID_CONFIDENCE, "none"),
            key_phrase=parsed.get("key_phrase") or "",
            article_type=_norm(parsed.get("article_type"), _VALID_ARTICLE_TYPES, "other"),
            primary_subject=_norm(parsed.get("primary_subject"), _VALID_SUBJECTS, "race_general"),
            news_hook=_norm(parsed.get("news_hook"), _VALID_HOOKS, "other"),
            dem_sentiment=_norm(parsed.get("dem_sentiment"), _VALID_SENTIMENTS, "neutral"),
            rep_sentiment=_norm(parsed.get("rep_sentiment"), _VALID_SENTIMENTS, "neutral"),
            summary=parsed.get("summary") or "",
            model=_MODEL,
        )

    # ── Cache helpers ──────────────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict]:
        if self.cache_path.exists():
            try:
                return {r["article_id"]: r for r in json.loads(self.cache_path.read_text())}
            except Exception:
                return {}
        return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(list(self._cache.values()), indent=2))
