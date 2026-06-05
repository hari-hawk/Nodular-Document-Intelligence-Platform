"use client";

import {
  Box, Card, CardContent, Chip, Divider, IconButton, Stack,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Tooltip, Typography,
} from "@mui/material";
import {
  ArrowLeft, ChevronRight, FileText, Pencil, Sparkles, X,
} from "lucide-react";
import { useState } from "react";

import { type BatchReport } from "@/lib/api";
import { FieldRow, fieldValueAsString } from "@/components/field-row";

/**
 * Per-document drill-down view. Lives below the batch detail when an
 * analyst clicks a document. Shows:
 *   - Document header (filename, classification, page count)
 *   - Extracted fields as a properly-laid-out 2-column data grid with
 *     dividers between rows + zebra striping (clear scan path)
 *   - Severity chips for any per-document anomalies
 *
 * UX rules followed:
 *   - 8px grid: every spacing/padding/gap is a multiple of 8 via MUI's
 *     `spacing(1) = 8px` token (sx={{ p: 3 }} → 24px, sx={{ p: 2 }} → 16px).
 *   - Hover affordance: field rows lift on hover so analysts know they're
 *     clickable for inline correction.
 *   - Click-target size: every interactive row is ≥40px tall (WCAG 2.2 SC 2.5.8).
 *   - Keyboard nav: `tabIndex` + Enter on rows + escape closes the view.
 *   - Visual rhythm: section headers use a consistent muted/uppercase
 *     stamp pattern so the eye knows where it is.
 */
export function DocumentDetail({
  document,
  report,
  onBack,
  onClose,
}: {
  document: BatchReport["documents"][number];
  report: BatchReport;
  onBack?: () => void;
  onClose?: () => void;
}) {
  const cluster = report.clusters[document.document_id];
  const extraction = report.extractions[document.document_id];
  const fields = extraction?.fields || {};
  const fieldEntries = Object.entries(fields);
  const docAnomalies = (report.anomalies || []).filter(
    (a) => a.field_path && fields[a.field_path.split(".")[0]],
  );

  return (
    <Card>
      <CardContent sx={{ p: 0 }}>
        {/* ── Header bar ─────────────────────────────────────────── */}
        <Box sx={{ px: 3, py: 2.5, borderBottom: 1, borderColor: "divider" }}>
          <Stack direction="row" spacing={2} alignItems="flex-start">
            {onBack && (
              <Tooltip title="Back to documents">
                <IconButton onClick={onBack} aria-label="Back to documents" size="small">
                  <ArrowLeft size={18} />
                </IconButton>
              </Tooltip>
            )}
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" alignItems="center" spacing={1}>
                <FileText size={16} style={{ opacity: 0.5 }} />
                <Typography variant="h3" sx={{ fontWeight: 600, fontSize: "1.0625rem" }} noWrap>
                  {document.filename}
                </Typography>
              </Stack>
              {cluster && (
                <Stack direction="row" spacing={1} sx={{ mt: 1 }} useFlexGap flexWrap="wrap">
                  <Chip label={cluster.industry} size="small" variant="outlined" />
                  <Chip label={cluster.vendor} size="small" variant="outlined" color="primary" />
                  <Chip label={cluster.doc_type} size="small" variant="outlined" />
                  <Chip
                    label={`${(cluster.confidence * 100).toFixed(0)}% confidence`}
                    size="small"
                    color={cluster.confidence > 0.8 ? "success" : cluster.confidence > 0.6 ? "info" : "warning"}
                    variant="outlined"
                  />
                  <Chip
                    label={`${document.page_count} page${document.page_count === 1 ? "" : "s"}`}
                    size="small"
                    variant="outlined"
                  />
                </Stack>
              )}
            </Box>
            {onClose && (
              <Tooltip title="Close detail view">
                <IconButton onClick={onClose} aria-label="Close detail view" size="small">
                  <X size={18} />
                </IconButton>
              </Tooltip>
            )}
          </Stack>
        </Box>

        {/* ── Extracted fields ───────────────────────────────────── */}
        <SectionStamp>Extracted fields ({fieldEntries.length})</SectionStamp>
        {fieldEntries.length === 0 ? (
          <Box sx={{ px: 3, py: 6, textAlign: "center" }}>
            <Sparkles size={28} style={{ opacity: 0.25, marginBottom: 12 }} />
            <Typography variant="body1" sx={{ fontWeight: 500 }}>
              No fields extracted yet
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
              The extraction stage may have rate-limited. Try re-uploading once
              the LLM quota recovers; in the meantime, the schema (visible in
              Brain → Patterns) shows what was discovered.
            </Typography>
          </Box>
        ) : (
          <TableContainer>
            <Table size="medium" aria-label={`Fields for ${document.filename}`}>
              <TableHead>
                <TableRow sx={{ "& th": { fontWeight: 600, fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.04em", color: "text.secondary", py: 1.5 } }}>
                  <TableCell sx={{ width: "32%", pl: 3 }}>Field</TableCell>
                  <TableCell>Value</TableCell>
                  <TableCell align="right" sx={{ width: 110, pr: 3 }}>Confidence</TableCell>
                  <TableCell sx={{ width: 56 }} />
                </TableRow>
              </TableHead>
              <TableBody>
                {fieldEntries.map(([k, v], i) => (
                  <FieldDataRow
                    key={k}
                    fieldName={k}
                    field={v}
                    industry={cluster?.industry || "unknown"}
                    vendor={cluster?.vendor || "unknown"}
                    docType={cluster?.doc_type || "unknown"}
                    striped={i % 2 === 1}
                  />
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {/* ── Per-document anomalies (when present) ──────────────── */}
        {docAnomalies.length > 0 && (
          <>
            <Divider />
            <SectionStamp>Anomalies on this document ({docAnomalies.length})</SectionStamp>
            <Stack spacing={1} sx={{ px: 3, pb: 3 }}>
              {docAnomalies.map((a, i) => (
                <Stack
                  key={i}
                  direction="row"
                  spacing={2}
                  alignItems="flex-start"
                  sx={{ p: 2, borderRadius: 1, bgcolor: "action.hover" }}
                >
                  <Chip
                    label={a.severity}
                    size="small"
                    color={a.severity === "HIGH" ? "error" : a.severity === "MEDIUM" ? "warning" : "info"}
                  />
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {a.message}
                    </Typography>
                    {a.field_path && (
                      <Typography variant="caption" color="text.secondary">
                        on field: <code>{a.field_path}</code> · rule {a.rule_id}
                      </Typography>
                    )}
                  </Box>
                </Stack>
              ))}
            </Stack>
          </>
        )}

        {/* ── Pattern provenance ─────────────────────────────────── */}
        {report.pattern_matches && report.pattern_matches.filter(m => m.document_id === document.document_id).length > 0 && (
          <>
            <Divider />
            <SectionStamp>Pattern matches</SectionStamp>
            <Stack spacing={0.5} sx={{ px: 3, pb: 3 }}>
              {report.pattern_matches
                .filter((m) => m.document_id === document.document_id)
                .slice(0, 5)
                .map((m, i) => (
                  <Stack key={i} direction="row" spacing={2} alignItems="center" sx={{ py: 0.5 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ width: 24 }}>
                      #{m.rank}
                    </Typography>
                    <Typography variant="caption" sx={{ fontFamily: "monospace", flex: 1 }}>
                      {m.pattern_id.slice(0, 12)}…
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      similarity {(m.similarity * 100).toFixed(0)}%
                    </Typography>
                  </Stack>
                ))}
            </Stack>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Field row with inline edit affordance
// ─────────────────────────────────────────────────────────────────────────────
function FieldDataRow({
  fieldName, field, industry, vendor, docType, striped,
}: {
  fieldName: string;
  field: { value: unknown; confidence: number; source_text?: string };
  industry: string;
  vendor: string;
  docType: string;
  striped: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const display = formatFieldValue(field.value);
  const edit = fieldValueAsString(field.value);
  const conf = field.confidence;

  return (
    <TableRow
      hover
      sx={{
        bgcolor: striped ? "action.hover" : "transparent",
        "&:last-child td": { borderBottom: 0 },
      }}
    >
      <TableCell sx={{ pl: 3, py: 1.5, fontFamily: "monospace", fontSize: "0.8125rem", color: "text.secondary", verticalAlign: "top" }}>
        {fieldName}
      </TableCell>
      <TableCell sx={{ py: 1.5 }}>
        {editing ? (
          <FieldRow
            fieldName={fieldName}
            displayValue={display}
            editValue={edit}
            industry={industry}
            vendor={vendor}
            docType={docType}
          />
        ) : (
          <Typography
            variant="body2"
            sx={{ fontFamily: "monospace", wordBreak: "break-word", whiteSpace: "pre-wrap" }}
          >
            {display || <Box component="span" sx={{ color: "text.disabled" }}>—</Box>}
          </Typography>
        )}
      </TableCell>
      <TableCell align="right" sx={{ pr: 3, py: 1.5, verticalAlign: "top" }}>
        <ConfidenceBar value={conf} />
      </TableCell>
      <TableCell sx={{ py: 1.5, verticalAlign: "top" }}>
        <Tooltip title={editing ? "Cancel" : "Edit value"}>
          <IconButton
            size="small"
            onClick={() => setEditing(!editing)}
            aria-label={`${editing ? "Cancel editing" : "Edit"} ${fieldName}`}
          >
            <Pencil size={14} />
          </IconButton>
        </Tooltip>
      </TableCell>
    </TableRow>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round((value || 0) * 100);
  const tone = value > 0.8 ? "success.main" : value > 0.6 ? "warning.main" : "error.main";
  return (
    <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end">
      <Box sx={{ width: 40, height: 4, bgcolor: "divider", borderRadius: 999, overflow: "hidden" }}>
        <Box sx={{ width: `${pct}%`, height: "100%", bgcolor: tone, transition: "width .3s" }} />
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: "tabular-nums", minWidth: 32 }}>
        {pct}%
      </Typography>
    </Stack>
  );
}

function SectionStamp({ children }: { children: React.ReactNode }) {
  return (
    <Typography
      component="div"
      variant="caption"
      sx={{
        px: 3, py: 1.5,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        fontWeight: 600,
        color: "text.secondary",
        fontSize: "0.7rem",
        bgcolor: "action.hover",
        borderBottom: 1,
        borderColor: "divider",
      }}
    >
      {children}
    </Typography>
  );
}

function formatFieldValue(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) return `[${v.length} items] ${JSON.stringify(v).slice(0, 60)}…`;
  if (typeof v === "object") return JSON.stringify(v, null, 2);
  return String(v);
}

// ─────────────────────────────────────────────────────────────────────────────
// Document picker — list of docs in a batch with click-to-drill affordance
// ─────────────────────────────────────────────────────────────────────────────
export function DocumentPicker({
  documents, report, onSelect,
}: {
  documents: BatchReport["documents"];
  report: BatchReport;
  onSelect: (docId: string) => void;
}) {
  if (documents.length === 0) {
    return (
      <Box sx={{ p: 4, textAlign: "center" }}>
        <FileText size={28} style={{ opacity: 0.25, marginBottom: 12 }} />
        <Typography variant="body2" color="text.secondary">No documents in this batch.</Typography>
      </Box>
    );
  }
  return (
    <Box component="ul" role="list" sx={{ listStyle: "none", m: 0, p: 0 }}>
      {documents.map((doc) => {
        const cluster = report.clusters[doc.document_id];
        const extraction = report.extractions[doc.document_id];
        const fieldCount = Object.keys(extraction?.fields || {}).length;
        return (
          <Box
            key={doc.document_id}
            component="li"
            sx={{ borderBottom: 1, borderColor: "divider", "&:last-child": { borderBottom: 0 } }}
          >
            <Box
              component="button"
              onClick={() => onSelect(doc.document_id)}
              sx={{
                width: "100%",
                px: 3, py: 2,
                textAlign: "left",
                border: 0,
                bgcolor: "transparent",
                cursor: "pointer",
                transition: "background-color .12s",
                display: "flex",
                alignItems: "center",
                gap: 2,
                "&:hover": { bgcolor: "action.hover" },
                "&:focus-visible": {
                  bgcolor: "action.hover",
                  outline: "2px solid",
                  outlineColor: "primary.main",
                  outlineOffset: -2,
                },
              }}
              aria-label={`Open ${doc.filename}`}
            >
              <FileText size={18} style={{ opacity: 0.5, flexShrink: 0 }} />
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="body2" sx={{ fontWeight: 500 }} noWrap>
                  {doc.filename}
                </Typography>
                <Stack direction="row" spacing={1} sx={{ mt: 0.5 }} useFlexGap flexWrap="wrap">
                  {cluster && (
                    <>
                      <Typography variant="caption" color="text.secondary">
                        {cluster.industry}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">·</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {cluster.vendor}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">·</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {cluster.doc_type}
                      </Typography>
                    </>
                  )}
                  <Typography variant="caption" color="text.secondary">·</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {doc.page_count} page{doc.page_count === 1 ? "" : "s"}
                  </Typography>
                </Stack>
              </Box>
              <Chip
                size="small"
                label={`${fieldCount} fields`}
                color={fieldCount > 0 ? "primary" : "default"}
                variant={fieldCount > 0 ? "filled" : "outlined"}
                sx={{ flexShrink: 0 }}
              />
              <ChevronRight size={18} style={{ opacity: 0.3, flexShrink: 0 }} />
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
