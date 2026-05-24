"""Tests for the database engine and session management."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import SQLModel

from src.db.models import PollRecord, PollResultRecord, HistoricalResult


class TestDBEngine:
    """Test database initialization and session management."""

    def setup_method(self):
        """Create a temporary database for each test."""
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_url = f"sqlite:///{self.tmp.name}"

    def teardown_method(self):
        """Clean up temporary database."""
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _make_engine_and_session(self):
        """Create engine and session factory for the temp DB."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session, sessionmaker
        from contextlib import contextmanager

        engine = create_engine(self.db_url, connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

        SQLModel.metadata.create_all(engine)

        @contextmanager
        def get_session():
            session = SessionLocal()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        return engine, get_session

    def test_create_tables(self):
        engine, _ = self._make_engine_and_session()
        inspector = __import__("sqlalchemy").inspect(engine)
        tables = inspector.get_table_names()
        # Table names come from explicit __tablename__ on each SQLModel class
        assert "polls" in tables
        assert "poll_results" in tables
        assert "historical_results" in tables

    def test_insert_and_query_poll(self):
        from datetime import date

        _, get_session = self._make_engine_and_session()

        with get_session() as session:
            record = PollRecord(
                source_id="test-1",
                source="test",
                poll_type="approval",
                pollster="Test Pollster",
                subject="President",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 4),
                sample_size=1000,
            )
            session.add(record)
            session.flush()

            session.add(PollResultRecord(
                poll_id=record.id,
                choice="Approve",
                pct=45.0,
            ))
            session.add(PollResultRecord(
                poll_id=record.id,
                choice="Disapprove",
                pct=52.0,
            ))

        with get_session() as session:
            polls = session.query(PollRecord).all()
            assert len(polls) == 1
            assert polls[0].source_id == "test-1"

            results = session.query(PollResultRecord).filter_by(poll_id=polls[0].id).all()
            assert len(results) == 2

    def test_insert_historical_result(self):
        _, get_session = self._make_engine_and_session()

        with get_session() as session:
            session.add(HistoricalResult(
                year=2024,
                state="US",
                office="president",
                candidate="Test Candidate",
                party="D",
                votes=80000000,
                pct=51.0,
                winner=True,
            ))

        with get_session() as session:
            results = session.query(HistoricalResult).all()
            assert len(results) == 1
            assert results[0].year == 2024
            assert results[0].winner is True

    def test_session_rollback_on_error(self):
        _, get_session = self._make_engine_and_session()

        try:
            with get_session() as session:
                session.add(PollRecord(
                    source_id="rollback-test",
                    source="test",
                    poll_type="approval",
                    pollster="Test",
                    subject="Test",
                    start_date=__import__("datetime").date(2026, 1, 1),
                    end_date=__import__("datetime").date(2026, 1, 4),
                ))
                raise ValueError("Intentional error")
        except ValueError:
            pass

        with get_session() as session:
            count = session.query(PollRecord).count()
            assert count == 0

    def test_duplicate_source_id_allowed_without_unique_constraint(self):
        from datetime import date

        _, get_session = self._make_engine_and_session()

        with get_session() as session:
            for i in range(2):
                session.add(PollRecord(
                    source_id="dup-1",
                    source="test",
                    poll_type="approval",
                    pollster="Test",
                    subject="Test",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 4),
                ))

        with get_session() as session:
            count = session.query(PollRecord).filter_by(source_id="dup-1").count()
            assert count == 2
