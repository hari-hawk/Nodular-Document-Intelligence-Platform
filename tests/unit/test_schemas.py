"""Pydantic schemas — strict mode + key invariants."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mdi.models.schemas import (
    BatchReport,
    Cluster,
    FieldDef,
    Schema,
    StrictModel,
)


def test_strict_mode_rejects_extra_fields():
    class M(StrictModel):
        x: int

    with pytest.raises(ValidationError):
        M(x=1, y=2)  # type: ignore[call-arg]


def test_cluster_confidence_bounded():
    Cluster(industry="x", vendor="y", doc_type="z", confidence=0.5)
    with pytest.raises(ValidationError):
        Cluster(industry="x", vendor="y", doc_type="z", confidence=1.5)


def test_schema_round_trips():
    s = Schema(fields=[FieldDef(name="vendor", type="string", required=True)])
    s2 = Schema.model_validate_json(s.model_dump_json())
    assert s2 == s


def test_batch_report_finished_after_started():
    started = datetime.now(timezone.utc)
    BatchReport(
        tenant_id=uuid4(),
        started_at=started,
        finished_at=started + timedelta(seconds=1),
    )
    with pytest.raises(ValidationError):
        BatchReport(
            tenant_id=uuid4(),
            started_at=started,
            finished_at=started - timedelta(seconds=1),
        )
