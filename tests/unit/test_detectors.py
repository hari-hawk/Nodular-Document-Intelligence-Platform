"""Unit tests for the deterministic detector package (Wave 2.2)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from mdi.brain.detectors import (
    detect_expirations,
    detect_pricing_anomalies,
    detect_recurring_vendors,
)
from mdi.models.schemas import Cluster, Extraction, FieldExtraction


def _cluster(vendor: str, doc_type: str = "invoice", industry: str = "general") -> Cluster:
    return Cluster(
        industry=industry, vendor=vendor, doc_type=doc_type,
        layout="free_text", language="en", confidence=0.9, rationale="",
    )


def _extraction(doc_id: uuid.UUID, **fields) -> Extraction:
    return Extraction(
        document_id=doc_id,
        fields={k: FieldExtraction(value=v, confidence=0.9) for k, v in fields.items()},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Recurring vendors
# ─────────────────────────────────────────────────────────────────────────────
class TestRecurringVendors:
    def test_singleton_vendor_not_flagged(self):
        """Min sightings = 2 by default — one document per vendor doesn't fire."""
        clusters = {
            uuid.uuid4(): _cluster("Acme Corp"),
            uuid.uuid4(): _cluster("Globex Inc."),
            uuid.uuid4(): _cluster("Initech LLC"),
        }
        assert detect_recurring_vendors(clusters) == []

    def test_two_sightings_returns_info(self):
        clusters = {
            uuid.uuid4(): _cluster("Acme Corp"),
            uuid.uuid4(): _cluster("Acme Corp"),
            uuid.uuid4(): _cluster("Globex Inc."),
        }
        findings = detect_recurring_vendors(clusters)
        assert len(findings) == 1
        # 2 of 3 = 67% → MEDIUM (above 50% concentration_warn)
        assert findings[0].severity == "MEDIUM"
        assert "Acme Corp" in findings[0].title

    def test_high_concentration_warn(self):
        """5 of 10 documents from one vendor — at the warn boundary."""
        clusters = {uuid.uuid4(): _cluster("Acme Corp") for _ in range(5)}
        clusters.update({uuid.uuid4(): _cluster(f"Other{i}") for i in range(5)})
        findings = detect_recurring_vendors(clusters)
        # Only Acme has >= 2 sightings; the rest are singletons.
        acme = [f for f in findings if "Acme" in f.title]
        assert len(acme) == 1
        assert acme[0].severity == "MEDIUM"  # exactly 50% → warn band

    def test_high_concentration_dominates(self):
        """8 of 10 = 80% → HIGH (above 75%)."""
        clusters = {uuid.uuid4(): _cluster("Acme Corp") for _ in range(8)}
        clusters.update({uuid.uuid4(): _cluster(f"Other{i}") for i in range(2)})
        findings = detect_recurring_vendors(clusters)
        acme = next(f for f in findings if "Acme" in f.title)
        assert acme.severity == "HIGH"
        assert "dominates" in acme.title.lower()

    def test_case_and_whitespace_normalisation_collapses_variants(self):
        """`AT&T` and `AT&T   ` and `at&t` count as ONE vendor."""
        clusters = {
            uuid.uuid4(): _cluster("AT&T"),
            uuid.uuid4(): _cluster("at&t"),
            uuid.uuid4(): _cluster("AT&T   "),
        }
        findings = detect_recurring_vendors(clusters)
        # All three collapse to one vendor, fires HIGH at 100%.
        assert len(findings) == 1
        assert findings[0].severity == "HIGH"

    def test_unknown_vendors_skipped(self):
        clusters = {
            uuid.uuid4(): _cluster("unknown"),
            uuid.uuid4(): _cluster("Unknown"),
            uuid.uuid4(): _cluster(""),
            uuid.uuid4(): _cluster("Acme Corp"),
        }
        findings = detect_recurring_vendors(clusters)
        # `unknown` is treated as null; Acme is a singleton → no findings.
        assert findings == []

    def test_empty_batch(self):
        assert detect_recurring_vendors({}) == []


# ─────────────────────────────────────────────────────────────────────────────
# Pricing anomalies
# ─────────────────────────────────────────────────────────────────────────────
class TestPricingAnomalies:
    def test_cluster_too_small_no_findings(self):
        """N=3 isn't enough to estimate a stable median/MAD."""
        doc_ids = [uuid.uuid4() for _ in range(3)]
        clusters = {d: _cluster("Acme Corp") for d in doc_ids}
        extractions = {
            doc_ids[0]: _extraction(doc_ids[0], total=100.0),
            doc_ids[1]: _extraction(doc_ids[1], total=110.0),
            doc_ids[2]: _extraction(doc_ids[2], total=10_000.0),  # would-be outlier
        }
        assert detect_pricing_anomalies(clusters, extractions) == []

    def test_outlier_in_normal_cluster_flagged(self):
        """5 normal invoices + 1 outlier → outlier surfaces."""
        doc_ids = [uuid.uuid4() for _ in range(6)]
        clusters = {d: _cluster("Acme Corp") for d in doc_ids}
        values = [100.0, 105.0, 95.0, 102.0, 98.0, 1_000.0]  # last is outlier
        extractions = {
            d: _extraction(d, total=v) for d, v in zip(doc_ids, values, strict=True)
        }
        findings = detect_pricing_anomalies(clusters, extractions)
        assert len(findings) == 1
        assert findings[0].affected_documents == [doc_ids[-1]]
        assert findings[0].severity == "HIGH"  # 1000 vs median ~100 is way past 3.5-sigma
        assert "above" in findings[0].title

    def test_identical_values_no_findings(self):
        """All values identical → MAD = 0 → no outlier possible."""
        doc_ids = [uuid.uuid4() for _ in range(5)]
        clusters = {d: _cluster("Acme Corp") for d in doc_ids}
        extractions = {d: _extraction(d, total=100.0) for d in doc_ids}
        assert detect_pricing_anomalies(clusters, extractions) == []

    def test_non_money_field_ignored(self):
        """`account_number` is in the extraction but NOT in _MONEY_FIELDS."""
        doc_ids = [uuid.uuid4() for _ in range(5)]
        clusters = {d: _cluster("Acme Corp") for d in doc_ids}
        extractions = {
            d: _extraction(d, account_number=f"ACC-{i:09d}")
            for i, d in enumerate(doc_ids)
        }
        assert detect_pricing_anomalies(clusters, extractions) == []

    def test_per_vendor_isolation(self):
        """An outlier-relative-to-Acme isn't an outlier in the full population."""
        acme_ids = [uuid.uuid4() for _ in range(5)]
        big_ids = [uuid.uuid4() for _ in range(5)]
        clusters = {**{d: _cluster("Acme Corp") for d in acme_ids},
                    **{d: _cluster("BigCo") for d in big_ids}}
        # Acme invoices around $100, BigCo around $10000
        extractions = {}
        for i, d in enumerate(acme_ids):
            extractions[d] = _extraction(d, total=100.0 + i)
        for i, d in enumerate(big_ids):
            extractions[d] = _extraction(d, total=10_000.0 + i * 5)
        # BigCo $10,005 is normal for BigCo; would be 100x outlier vs Acme.
        # Per-vendor bucketing means no findings here.
        assert detect_pricing_anomalies(clusters, extractions) == []


# ─────────────────────────────────────────────────────────────────────────────
# Expirations
# ─────────────────────────────────────────────────────────────────────────────
class TestExpirations:
    def test_past_date_high_severity(self):
        doc_id = uuid.uuid4()
        clusters = {doc_id: _cluster("Acme Corp")}
        extractions = {doc_id: _extraction(doc_id, due_date="2026-01-01")}
        findings = detect_expirations(
            clusters, extractions, today=date(2026, 6, 4),
        )
        assert len(findings) == 1
        assert findings[0].severity == "HIGH"
        assert "PAST" in findings[0].title

    def test_within_30_days_medium(self):
        today = date(2026, 6, 4)
        doc_id = uuid.uuid4()
        clusters = {doc_id: _cluster("Acme Corp")}
        ex = _extraction(doc_id, due_date=(today + timedelta(days=15)).isoformat())
        findings = detect_expirations({doc_id: clusters[doc_id]}, {doc_id: ex}, today=today)
        assert len(findings) == 1
        assert findings[0].severity == "MEDIUM"

    def test_90_day_heads_up_info(self):
        today = date(2026, 6, 4)
        doc_id = uuid.uuid4()
        clusters = {doc_id: _cluster("Acme Corp")}
        ex = _extraction(doc_id, due_date=(today + timedelta(days=60)).isoformat())
        findings = detect_expirations(clusters, {doc_id: ex}, today=today)
        assert findings[0].severity == "INFO"

    def test_far_future_not_flagged(self):
        """>90 days out is not actionable yet — silent."""
        today = date(2026, 6, 4)
        doc_id = uuid.uuid4()
        clusters = {doc_id: _cluster("Acme Corp")}
        ex = _extraction(doc_id, due_date=(today + timedelta(days=365)).isoformat())
        assert detect_expirations(clusters, {doc_id: ex}, today=today) == []

    def test_unparseable_date_skipped(self):
        doc_id = uuid.uuid4()
        clusters = {doc_id: _cluster("Acme Corp")}
        ex = _extraction(doc_id, due_date="sometime next quarter")
        # No crash, no finding.
        assert detect_expirations(clusters, {doc_id: ex}) == []

    def test_us_date_format_parsed(self):
        """MM/DD/YYYY — common on US invoices."""
        today = date(2026, 6, 4)
        doc_id = uuid.uuid4()
        clusters = {doc_id: _cluster("Acme Corp")}
        ex = _extraction(doc_id, due_date="06/20/2026")
        findings = detect_expirations(clusters, {doc_id: ex}, today=today)
        assert len(findings) == 1
        assert findings[0].severity == "MEDIUM"  # 16 days out

    def test_no_date_field_no_finding(self):
        doc_id = uuid.uuid4()
        clusters = {doc_id: _cluster("Acme Corp")}
        ex = _extraction(doc_id, total=100.0)
        assert detect_expirations(clusters, {doc_id: ex}) == []
