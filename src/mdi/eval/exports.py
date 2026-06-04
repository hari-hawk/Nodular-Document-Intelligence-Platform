"""Multi-format exports for a BatchReport.

Per direction: any uploaded document's extraction should be exportable as
PDF, Email-ready HTML, Excel, CSV, or raw JSON. Excel + CSV live in the
Streamlit UI directly (pandas does the work). PDF + Email + JSON live here.

Inputs are always the BatchReport dict (as returned by the orchestrator) so
the same functions serve the Streamlit UI, the FastAPI endpoints, and any
future programmatic consumers.
"""
from __future__ import annotations

import html
import io
import json
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def to_json_bytes(report: dict[str, Any], *, pretty: bool = True) -> bytes:
    return json.dumps(report, indent=2 if pretty else None, default=str).encode("utf-8")


# ---------------------------------------------------------------------------
# PDF — executive summary + per-doc detail
# ---------------------------------------------------------------------------
def to_pdf_bytes(report: dict[str, Any], *, mode: str = "executive") -> bytes:
    """Render a BatchReport as PDF.

    mode='executive' — 1-page summary (KPIs, top insights, narrator).
    mode='detailed'  — adds a per-document detail page.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.7 * inch, bottomMargin=0.6 * inch,
        title="MDI Batch Report",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=colors.HexColor("#6366F1"))
    sub = ParagraphStyle("sub", parent=styles["BodyText"], textColor=colors.grey, fontSize=9)
    body = styles["BodyText"]
    flow: list[Any] = []

    flow.append(Paragraph("MDI · Batch Report", h1))
    started = report.get("started_at", "")
    finished = report.get("finished_at", "")
    tenant = str(report.get("tenant_id", ""))[:8]
    flow.append(Paragraph(
        f"Tenant {tenant} · started {started} · finished {finished}", sub,
    ))
    flow.append(Spacer(1, 0.18 * inch))

    # KPIs
    n_docs = len(report.get("documents") or [])
    n_anom = len(report.get("anomalies") or [])
    n_insight = len(report.get("insights") or [])
    n_briefings = len(report.get("briefings") or [])
    cost = report.get("total_cost_usd", 0.0) or 0.0
    kpi_data = [
        ["Documents", "Anomalies", "Insights", "Briefings", "Cost (USD)"],
        [str(n_docs), str(n_anom), str(n_insight), str(n_briefings), f"${cost:.5f}"],
    ]
    kpi_t = Table(kpi_data, colWidths=[1.2 * inch] * 5)
    kpi_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F3F4F6")),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.lightgrey),
    ]))
    flow.append(kpi_t)
    flow.append(Spacer(1, 0.2 * inch))

    # Narrator
    summary = report.get("narrator_summary") or "(no summary)"
    flow.append(Paragraph("Executive summary", styles["Heading3"]))
    flow.append(Paragraph(html.escape(summary), body))
    flow.append(Spacer(1, 0.15 * inch))

    # Insights
    insights = report.get("insights") or []
    if insights:
        flow.append(Paragraph("Top insights", styles["Heading3"]))
        rows = [["Severity", "Title", "Body"]]
        for i in insights[:8]:
            rows.append([
                i.get("severity", ""),
                Paragraph(html.escape(i.get("title", "")), body),
                Paragraph(html.escape((i.get("body") or "")[:300]), body),
            ])
        t = Table(rows, colWidths=[0.8 * inch, 2.4 * inch, 3.4 * inch], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTSIZE",   (0, 0), (-1, -1), 8),
            ("VALIGN",     (0, 0), (-1, -1), "TOP"),
            ("GRID",       (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 0.15 * inch))

    # Per-doc detail in detailed mode
    if mode == "detailed":
        flow.append(PageBreak())
        flow.append(Paragraph("Per-document detail", h1))
        flow.append(Spacer(1, 0.1 * inch))
        clusters = report.get("clusters") or {}
        extractions = report.get("extractions") or {}
        for d in report.get("documents") or []:
            did = d.get("document_id", "")
            cl = clusters.get(did, {})
            ex = (extractions.get(did) or {}).get("fields") or {}
            flow.append(Paragraph(html.escape(d.get("filename", "")), styles["Heading4"]))
            meta = f"{cl.get('industry','?')} · {cl.get('vendor','?')} · {cl.get('doc_type','?')}"
            flow.append(Paragraph(meta, sub))
            field_rows = [["Field", "Value", "Conf"]]
            for k, v in list(ex.items())[:30]:
                field_rows.append([
                    k,
                    Paragraph(html.escape(str(v.get("value") if isinstance(v, dict) else v))[:200], body),
                    f"{(v.get('confidence') if isinstance(v, dict) else 0):.2f}",
                ])
            ft = Table(field_rows, colWidths=[1.8 * inch, 4.2 * inch, 0.7 * inch], repeatRows=1)
            ft.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTSIZE",   (0, 0), (-1, -1), 7),
                ("VALIGN",     (0, 0), (-1, -1), "TOP"),
                ("GRID",       (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]))
            flow.append(ft)
            flow.append(Spacer(1, 0.15 * inch))

    doc.build(flow)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Email — inline-CSS HTML for paste-into-Gmail, plus .eml file
# ---------------------------------------------------------------------------
def to_email_html(report: dict[str, Any]) -> str:
    """Inline-CSS HTML suitable for pasting into a Gmail compose window."""
    started = report.get("started_at", "")
    n_docs = len(report.get("documents") or [])
    cost = report.get("total_cost_usd", 0.0) or 0.0
    summary = html.escape(report.get("narrator_summary") or "")
    rows: list[str] = []
    clusters = report.get("clusters") or {}
    extractions = report.get("extractions") or {}
    for d in report.get("documents") or []:
        did = d.get("document_id", "")
        cl = clusters.get(did, {})
        ex_fields = (extractions.get(did) or {}).get("fields") or {}
        # Pick a few stable fields for the email row.
        vendor = (cl.get("vendor") or
                  (ex_fields.get("vendor", {}) or ex_fields.get("vendor_name", {}) or {}).get("value", ""))
        total = (ex_fields.get("total", {}) or ex_fields.get("total_amount", {}) or
                 ex_fields.get("total_due", {}) or {}).get("value", "")
        currency = (ex_fields.get("currency", {}) or {}).get("value", "")
        rows.append(f"""
          <tr style="border-bottom:1px solid #E5E7EB;">
            <td style="padding:6px 10px; font-family:sans-serif; font-size:13px;">{html.escape(d.get('filename',''))}</td>
            <td style="padding:6px 10px; font-family:sans-serif; font-size:13px;">{html.escape(cl.get('industry',''))}</td>
            <td style="padding:6px 10px; font-family:sans-serif; font-size:13px;">{html.escape(str(vendor))}</td>
            <td style="padding:6px 10px; font-family:sans-serif; font-size:13px;">{html.escape(cl.get('doc_type',''))}</td>
            <td style="padding:6px 10px; font-family:sans-serif; font-size:13px; text-align:right;">{html.escape(str(total))} {html.escape(str(currency))}</td>
          </tr>""")

    return f"""<!doctype html>
<html><body style="margin:0; padding:0; background:#F9FAFB; font-family: -apple-system, Segoe UI, Roboto, sans-serif;">
  <div style="max-width:720px; margin:0 auto; background:#FFFFFF; padding:24px;">
    <h1 style="font-size:22px; margin:0 0 4px 0; color:#111827;">MDI · Batch Report</h1>
    <p style="color:#6B7280; font-size:13px; margin:0 0 16px 0;">
      Processed {n_docs} document(s) at {started} · spend ${cost:.5f}
    </p>

    <div style="background:#F3F4F6; border-left:3px solid #6366F1; padding:12px 14px; margin:12px 0; color:#111827; font-size:14px;">
      <strong style="color:#6366F1;">Executive summary</strong><br/>
      {summary or "(no summary)"}
    </div>

    <table style="width:100%; border-collapse:collapse; margin-top:14px;">
      <thead>
        <tr style="background:#1F2937; color:#FFFFFF;">
          <th style="text-align:left; padding:8px 10px; font-family:sans-serif; font-size:12px;">File</th>
          <th style="text-align:left; padding:8px 10px; font-family:sans-serif; font-size:12px;">Industry</th>
          <th style="text-align:left; padding:8px 10px; font-family:sans-serif; font-size:12px;">Vendor</th>
          <th style="text-align:left; padding:8px 10px; font-family:sans-serif; font-size:12px;">Doc type</th>
          <th style="text-align:right; padding:8px 10px; font-family:sans-serif; font-size:12px;">Total</th>
        </tr>
      </thead>
      <tbody>{''.join(rows) or '<tr><td colspan=5 style="padding:14px; color:#9CA3AF; font-style:italic;">(no documents)</td></tr>'}</tbody>
    </table>

    <p style="margin-top:24px; color:#9CA3AF; font-size:11px;">
      Generated by MDI · Modular Data Intelligence
    </p>
  </div>
</body></html>"""


def to_eml_bytes(report: dict[str, Any], *, subject: str | None = None,
                 to_addr: str = "you@example.com",
                 from_addr: str = "mdi@localhost") -> bytes:
    """Build an RFC822 .eml file (HTML body + optional Excel attachment)."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    n_docs = len(report.get("documents") or [])
    msg["Subject"] = subject or f"MDI batch · {n_docs} document(s) processed"
    msg["Date"] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content("This is the plain-text fallback; open in an HTML-capable client.")
    msg.add_alternative(to_email_html(report), subtype="html")
    return msg.as_bytes()


# ---------------------------------------------------------------------------
# Convenience union
# ---------------------------------------------------------------------------
def export(report: dict[str, Any], fmt: str, **kwargs: Any) -> bytes:
    fmt = fmt.lower()
    if fmt == "json":
        return to_json_bytes(report, **kwargs)
    if fmt == "pdf":
        return to_pdf_bytes(report, **kwargs)
    if fmt == "email_html":
        return to_email_html(report).encode("utf-8")
    if fmt == "eml":
        return to_eml_bytes(report, **kwargs)
    raise ValueError(f"unknown export format: {fmt!r}")
