"""Eyes — open-vocabulary classification (Stage 2)."""
from __future__ import annotations

import json
import re

from mdi.kernel.llm_gateway import GatewayLike, get_gateway
from mdi.kernel.observability import get_logger
from mdi.models.schemas import Cluster, IngestedDocument

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are the perception organ of an open-vocabulary document intelligence system.
Classify the document by inspecting its content. Detect:
  - industry (free-form, lower_snake_case, e.g. telecom, healthcare_claims, cloud_finance)
  - vendor (the issuer / counterparty as it appears on the document)
  - doc_type (free-form, lower_snake_case: invoice, purchase_order, contract, statement, receipt,
              claim_837, remit_835, prior_auth, lab_report, bol, supplier_invoice, etc.)
  - layout (one of: tabular, form, free_text, scanned, mixed)
  - language (ISO 639-1)
  - confidence (0..1) and a one-line rationale.

Return ONLY a JSON object with those keys. No markdown, no commentary.
"""


def _heuristic_cluster(doc: IngestedDocument) -> Cluster:
    """Used when no LLM is wired (FakeGateway returns nothing classifiable)."""
    text = (doc.text or "").lower()
    doc_type = "unknown"
    if "invoice" in text:
        doc_type = "invoice"
    elif "purchase order" in text or "p.o." in text:
        doc_type = "purchase_order"
    elif "contract" in text or "agreement" in text:
        doc_type = "contract"
    elif "statement" in text:
        doc_type = "statement"
    elif "receipt" in text:
        doc_type = "receipt"

    industry = "general_business"
    if any(k in text for k in ["icd-10", "cpt", "ndc", "patient"]):
        industry = "healthcare_claims"
    elif any(k in text for k in ["aws", "azure", "gcp", "ec2"]):
        industry = "cloud_finance"
    elif any(k in text for k in ["mrc", "broadband", "sip", "carrier"]):
        industry = "telecom_billing"

    vendor_match = re.search(r"\b(?:from|vendor|issuer)\s*[:\-]\s*([^\n]+)", text)
    vendor = (vendor_match.group(1).strip()[:64] if vendor_match else "unknown").title()

    return Cluster(
        industry=industry,
        vendor=vendor or "unknown",
        doc_type=doc_type,
        layout="scanned" if doc.needs_vision else "free_text",
        language="en",
        confidence=0.4,
        rationale="heuristic fallback (no LLM response or empty document)",
    )


async def classify(
    doc: IngestedDocument,
    *,
    gateway: GatewayLike | None = None,
) -> Cluster:
    gw = gateway or get_gateway()

    body = (doc.text or "")[:8000]
    if not body and not doc.images:
        return _heuristic_cluster(doc)

    prompt = f"FILENAME: {doc.filename}\n\nCONTENT:\n{body}\n"
    try:
        resp = await gw.generate(
            organ="eyes",
            tier="perception",
            system=SYSTEM_PROMPT,
            prompt=prompt,
            images=doc.images or None,
            json_mode=True,
            max_output_tokens=512,
            temperature=0.0,
        )
    except Exception as e:
        logger.warning("eyes.gateway_error", error=str(e))
        return _heuristic_cluster(doc)

    try:
        data = json.loads(resp.text)
        return Cluster(
            industry=str(data.get("industry", "general_business")).lower(),
            vendor=str(data.get("vendor", "unknown")),
            doc_type=str(data.get("doc_type", "unknown")).lower(),
            layout=data.get("layout", "free_text"),
            language=data.get("language", "en"),
            confidence=float(data.get("confidence", 0.5)),
            rationale=str(data.get("rationale", "")),
        )
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("eyes.parse_error", error=str(e), text=resp.text[:200])
        return _heuristic_cluster(doc)
