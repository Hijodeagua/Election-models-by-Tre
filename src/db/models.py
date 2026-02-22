"""SQLModel ORM definitions for the election oracle database."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


# ── Core polling tables ───────────────────────────────────────────────


class PollRecord(SQLModel, table=True):
    """Individual poll record from any data source."""

    __tablename__ = "polls"

    id: int | None = Field(default=None, primary_key=True)
    source_id: str = Field(index=True, description="Source-specific poll ID (e.g. votehub-123)")
    source: str = Field(index=True, description="Data source name (votehub, rcp, etc.)")
    poll_type: str = Field(index=True)
    pollster: str = Field(index=True)
    subject: str = Field(index=True)
    start_date: date
    end_date: date
    sample_size: int | None = None
    population: str | None = None  # lv, rv, a
    partisan: bool = False
    internal: bool = False
    sponsors: str | None = None  # JSON array
    url: str | None = None
    raw_json: str | None = None  # Full raw response for debugging
    created_at: datetime = Field(default_factory=datetime.utcnow)

    results: list[PollResultRecord] = Relationship(back_populates="poll")


class PollResultRecord(SQLModel, table=True):
    """Individual answer choice within a poll."""

    __tablename__ = "poll_results"

    id: int | None = Field(default=None, primary_key=True)
    poll_id: int = Field(foreign_key="polls.id", index=True)
    choice: str
    pct: float

    poll: PollRecord | None = Relationship(back_populates="results")


# ── Pollster metadata ────────────────────────────────────────────────


class PollsterRating(SQLModel, table=True):
    """Quality/accuracy rating for a polling firm."""

    __tablename__ = "pollster_ratings"

    id: int | None = Field(default=None, primary_key=True)
    pollster: str = Field(index=True, unique=True)
    rating: float = Field(description="0–3 scale (3 = highest quality)")
    source: str = Field(description="Where the rating came from")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Computed averages ────────────────────────────────────────────────


class PollingAverage(SQLModel, table=True):
    """Daily snapshot of a computed weighted polling average."""

    __tablename__ = "polling_averages"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    poll_type: str = Field(index=True)
    as_of: date = Field(index=True)
    choice: str
    average_pct: float
    ci_low: float | None = None
    ci_high: float | None = None
    num_polls: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Election race tables ─────────────────────────────────────────────


class Race(SQLModel, table=True):
    """An election contest."""

    __tablename__ = "races"

    id: int | None = Field(default=None, primary_key=True)
    year: int = Field(index=True)
    state: str = Field(index=True)
    district: str | None = None  # For House races
    office: str = Field(description="president, senate, house, governor")
    special: bool = False

    candidates: list[Candidate] = Relationship(back_populates="race")
    ratings: list[RaceRating] = Relationship(back_populates="race")


class Candidate(SQLModel, table=True):
    """A candidate in a race."""

    __tablename__ = "candidates"

    id: int | None = Field(default=None, primary_key=True)
    race_id: int = Field(foreign_key="races.id", index=True)
    name: str
    party: str
    incumbent: bool = False

    race: Race | None = Relationship(back_populates="candidates")


class RaceRating(SQLModel, table=True):
    """Cook/Sabato/Inside Elections race rating over time."""

    __tablename__ = "race_ratings"

    id: int | None = Field(default=None, primary_key=True)
    race_id: int = Field(foreign_key="races.id", index=True)
    source: str = Field(description="cook, sabato, inside_elections")
    rating: str = Field(description="solid_d, likely_d, lean_d, tossup, lean_r, likely_r, solid_r")
    as_of: date
    created_at: datetime = Field(default_factory=datetime.utcnow)

    race: Race | None = Relationship(back_populates="ratings")


# ── Historical results ───────────────────────────────────────────────


class HistoricalResult(SQLModel, table=True):
    """Past election outcomes for backtesting models."""

    __tablename__ = "historical_results"

    id: int | None = Field(default=None, primary_key=True)
    year: int = Field(index=True)
    state: str = Field(index=True)
    district: str | None = None
    office: str
    candidate: str
    party: str
    votes: int
    pct: float
    winner: bool = False
