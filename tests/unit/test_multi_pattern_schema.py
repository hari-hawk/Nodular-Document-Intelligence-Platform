"""Unit tests for Wave 2.1 multi-pattern schema surface.

The DB-touching `lookup_patterns_multi()` requires a real Postgres with
pgvector — that's integration test territory. This file locks in the
schema-level changes:
  - BatchReport.pattern_matches accepts the expected shape
  - Defaults to empty list (backwards compat — old reports load cleanly)
  - JSON-round-trips so the field survives DB persistence
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from mdi.models.schemas import BatchReport


def test_batch_report_defaults_pattern_matches_to_empty_list():
    """Existing serialised reports (from before Wave 2.1) don't have a
    pattern_matches field; they must still parse without errors and
    receive an empty list."""
    now = datetime.now(UTC)
    report = BatchReport(
        tenant_id=uuid.uuid4(),
        started_at=now,
        finished_at=now,
    )
    assert report.pattern_matches == []


def test_pattern_matches_accepts_canonical_shape():
    """The orchestrator emits dicts with these keys; locking the shape
    so the frontend Patterns page can rely on it."""
    now = datetime.now(UTC)
    doc_id = str(uuid.uuid4())
    pat_id = str(uuid.uuid4())
    report = BatchReport(
        tenant_id=uuid.uuid4(),
        started_at=now,
        finished_at=now,
        pattern_matches=[
            {"document_id": doc_id, "pattern_id": pat_id,
             "similarity": 0.91, "rank": 0},
            {"document_id": doc_id, "pattern_id": str(uuid.uuid4()),
             "similarity": 0.78, "rank": 1},
        ],
    )
    assert len(report.pattern_matches) == 2
    assert report.pattern_matches[0]["rank"] == 0
    assert report.pattern_matches[0]["similarity"] == 0.91


def test_pattern_matches_survives_json_round_trip():
    """The report gets persisted as JSONB; pattern_matches must come back
    out the other side intact."""
    now = datetime.now(UTC)
    original = BatchReport(
        tenant_id=uuid.uuid4(),
        started_at=now,
        finished_at=now,
        pattern_matches=[
            {"document_id": "doc-1", "pattern_id": "pat-1",
             "similarity": 0.95, "rank": 0},
        ],
    )
    dumped = original.model_dump(mode="json")
    rehydrated = BatchReport.model_validate(dumped)
    assert rehydrated.pattern_matches == original.pattern_matches


def test_pattern_matches_doesnt_break_existing_fields():
    """Sanity — adding pattern_matches doesn't bump anything else in
    BatchReport's shape contract."""
    now = datetime.now(UTC)
    report = BatchReport(
        tenant_id=uuid.uuid4(),
        started_at=now,
        finished_at=now,
        narrator_summary="hello",
        total_cost_usd=1.23,
    )
    assert report.narrator_summary == "hello"
    assert report.total_cost_usd == 1.23
    assert report.pattern_matches == []
