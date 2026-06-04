"""Conscience — sandboxed rule execution + invent-disabled-by-default."""
from __future__ import annotations

import pytest
from uuid import uuid4

from mdi.brain import conscience
from mdi.brain.hippocampus import baseline_rules_from_schema
from mdi.models.schemas import (
    Extraction,
    FieldDef,
    FieldExtraction,
    Rule,
    RuleSet,
    Schema,
)


def test_validate_passes_when_rules_hold():
    schema = Schema(
        fields=[FieldDef(name="total", type="currency", required=True)],
    )
    rs = baseline_rules_from_schema(schema)
    extraction = Extraction(
        document_id=uuid4(),
        fields={"total": FieldExtraction(value=100.0, confidence=1.0)},
    )
    result = conscience.validate(extraction, rs)
    assert result.anomalies == []


def test_validate_flags_required_missing():
    schema = Schema(fields=[FieldDef(name="total", type="currency", required=True)])
    rs = baseline_rules_from_schema(schema)
    extraction = Extraction(document_id=uuid4(), fields={})
    result = conscience.validate(extraction, rs)
    assert any(a.severity == "HIGH" for a in result.anomalies)


def test_validate_flags_negative_currency():
    rs = RuleSet(rules=[
        Rule(rule_id="nonneg", expression="(fields.get('total') or 0) >= 0",
             severity="MEDIUM", message="negative")
    ])
    extraction = Extraction(
        document_id=uuid4(),
        fields={"total": FieldExtraction(value=-5.0, confidence=1.0)},
    )
    result = conscience.validate(extraction, rs)
    assert len(result.anomalies) == 1


def test_sandbox_blocks_dangerous_expression():
    rs = RuleSet(rules=[
        Rule(rule_id="bad", expression="__import__('os').system('echo pwned')",
             severity="HIGH", message="should not run")
    ])
    extraction = Extraction(document_id=uuid4(), fields={})
    result = conscience.validate(extraction, rs)
    # Sandbox rejects → anomaly with rule errored.
    assert len(result.anomalies) == 1
    assert "rule errored" in result.anomalies[0].message


@pytest.mark.asyncio
async def test_invent_disabled_by_default(installed_fake_gateway):
    schema = Schema(fields=[FieldDef(name="total", type="currency", required=True)])
    rs = await conscience.invent(schema)
    assert rs.rules == []  # ENABLE_INVENTED_RULES=false default
