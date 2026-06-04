"""Inner Voice — pure-Python verdicts."""
from __future__ import annotations

from uuid import uuid4

from mdi.brain import inner_voice
from mdi.models.schemas import Anomaly, Extraction, FieldExtraction


def _ex(conf: float, n: int = 3) -> list[Extraction]:
    return [
        Extraction(
            document_id=uuid4(),
            fields={f"f{i}": FieldExtraction(value="x", confidence=conf) for i in range(n)},
        )
        for _ in range(3)
    ]


def test_strong_verdict():
    r = inner_voice.reflect(
        pattern_id=None,
        extractions=_ex(0.9),
        anomalies=[],
        correction_agreement_counts=[3, 4, 5],
    )
    assert r.verdict == "strong"


def test_weak_when_anomalies_dominate():
    extractions = _ex(0.5, n=2)
    anomalies = [
        Anomaly(rule_id="r", severity="HIGH", message="bad") for _ in range(5)
    ]
    r = inner_voice.reflect(pattern_id=None, extractions=extractions, anomalies=anomalies)
    assert r.verdict == "weak"


def test_watch_when_stabilising():
    r = inner_voice.reflect(pattern_id=None, extractions=_ex(0.75), anomalies=[])
    assert r.verdict == "watch"
