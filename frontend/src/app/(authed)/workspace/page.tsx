"use client";

import {
  Alert, Box, Button, Card, CardContent, Chip, Divider,
  IconButton, LinearProgress, Stack, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle, CheckCircle2, ChevronDown, ChevronRight,
  FileText, FileStack, Sparkles, UploadCloud, X,
} from "lucide-react";
import { useState } from "react";

import { api, type BatchReport } from "@/lib/api";
import { FieldRow, fieldValueAsString } from "@/components/field-row";
import { KpiTile } from "@/components/kpi-tile";
import { RecentBatches } from "@/components/recent-batches";

/**
 * Workspace — the daily-use cockpit.
 *
 * Polish pass (MUI):
 *   - KPI hero strip with 4 stat tiles (Docs · Insights · Anomalies · Cost)
 *     so analysts get an at-a-glance read on the current batch without
 *     scrolling.
 *   - Gradient-bordered upload zone with a Material drop-target feel.
 *   - Recent batches gets surfaced UNDER the upload so the "I just
 *     uploaded — now what" flow stays top-to-bottom.
 *   - Each batch detail section uses MUI's expansion-pattern via
 *     <Section>: chevron + tone-aware Chip count + smooth expand.
 *
 * Accessibility:
 *   - File picker is a real <input type="file"> wrapped in <label>,
 *     so screen-reader users hit it via "Browse" link text.
 *   - Drop zone has aria-describedby pointing at the file-type hint.
 *   - Section headers are <button> with aria-expanded so SR users
 *     understand the collapsible region.
 */
export default function WorkspacePage() {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [report, setReport] = useState<BatchReport | null>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);

  // Tenant-scoped current usage (for the Cost-this-month KPI).
  const usageQ = useQuery({
    queryKey: ["tenant-usage"],
    queryFn: () => api.getTenantUsage(),
    retry: 0,  // 401s when admin-only signed in are fine, leave silently
  });

  const upload = useMutation({
    mutationFn: (toUpload: File[]) => api.processBatch(toUpload),
    onSuccess: (r) => {
      setReport(r);
      setSelectedBatchId(r.batch_id ?? null);
      setFiles([]);
      queryClient.invalidateQueries({ queryKey: ["recent-batches"] });
    },
  });

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length) setFiles((prev) => [...prev, ...dropped]);
  };

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files || []);
    if (picked.length) setFiles((prev) => [...prev, ...picked]);
  };

  const removeFile = (i: number) =>
    setFiles((prev) => prev.filter((_, idx) => idx !== i));

  // KPI inputs — pull from the current report when present, fall back to "—".
  const docCount = report?.documents.length ?? 0;
  const insightCount = report?.insights?.length ?? 0;
  const anomalyCount = report?.anomalies?.length ?? 0;
  const cost = report?.total_cost_usd ?? 0;
  const monthlyCap = usageQ.data?.monthly_cap_usd ?? 0;
  const monthlySpent = usageQ.data?.spent_usd ?? 0;

  return (
    <Stack spacing={4}>
      {/* ─── Hero / page heading ─── */}
      <Box>
        <Typography variant="h1" sx={{ fontWeight: 700 }}>Workspace</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          Upload documents, watch them get extracted, review what came out.
        </Typography>
      </Box>

      {/* ─── KPI strip ─── */}
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", md: "repeat(4, 1fr)" },
        }}
      >
        <KpiTile
          label="Documents in batch"
          value={report ? docCount : "—"}
          caption={report ? `${docCount} processed` : "Upload to begin"}
          icon={<FileStack size={18} />}
        />
        <KpiTile
          label="Insights"
          value={report ? insightCount : "—"}
          caption={insightCount ? "needs review" : "none yet"}
          tone={insightCount ? "info" : "default"}
          icon={<Sparkles size={18} />}
        />
        <KpiTile
          label="Anomalies"
          value={report ? anomalyCount : "—"}
          caption={anomalyCount ? "flagged" : "all clear"}
          tone={anomalyCount ? "danger" : "success"}
          icon={anomalyCount ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
        />
        <KpiTile
          label="Spend this month"
          value={monthlyCap ? `$${monthlySpent.toFixed(2)}` : `$${cost.toFixed(4)}`}
          caption={monthlyCap ? `of $${monthlyCap.toFixed(0)} cap` : "this batch"}
          tone="default"
        />
      </Box>

      {/* ─── Upload zone ─── */}
      <Card>
        <CardContent sx={{ p: { xs: 2, md: 3 } }}>
          <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 2 }}>
            <Box>
              <Typography variant="h3">Upload documents</Typography>
              <Typography variant="body2" color="text.secondary" id="upload-hint">
                PDF, image, or text. Up to 200 pages per file (the soft cap warns at 10).
              </Typography>
            </Box>
          </Stack>

          <Box
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            aria-describedby="upload-hint"
            sx={{
              borderRadius: 3,
              border: "2px dashed",
              borderColor: "divider",
              bgcolor: (t) => t.palette.mode === "dark"
                ? "rgba(99,102,241,.04)" : "rgba(99,102,241,.04)",
              p: { xs: 4, md: 6 },
              textAlign: "center",
              transition: "border-color .2s, background-color .2s",
              "&:hover": {
                borderColor: "primary.main",
                bgcolor: (t) => t.palette.mode === "dark"
                  ? "rgba(99,102,241,.08)" : "rgba(99,102,241,.08)",
              },
            }}
          >
            <Box sx={{ display: "inline-flex", p: 2, mb: 1.5, borderRadius: "50%", bgcolor: "primary.main", color: "primary.contrastText" }}>
              <UploadCloud size={28} />
            </Box>
            <Typography sx={{ fontWeight: 600, mb: 0.5 }}>
              Drag files here, or{" "}
              <Box
                component="label"
                sx={{ color: "primary.main", cursor: "pointer", textDecoration: "underline" }}
              >
                browse
                <input
                  type="file"
                  multiple
                  hidden
                  onChange={onPick}
                  accept=".pdf,.png,.jpg,.jpeg,.tiff,.txt"
                  aria-label="Pick files to upload"
                />
              </Box>
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Multiple files OK. They&apos;re processed concurrently.
            </Typography>
          </Box>

          {files.length > 0 && (
            <Stack spacing={1.5} sx={{ mt: 3 }}>
              {files.map((f, i) => (
                <Card key={i} variant="outlined" sx={{ p: 1.5 }}>
                  <Stack direction="row" spacing={1.5} alignItems="center">
                    <FileText size={18} style={{ flexShrink: 0, opacity: 0.6 }} />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography variant="body2" sx={{ fontWeight: 500 }} noWrap>
                        {f.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {(f.size / 1024).toFixed(1)} KB · {f.type || "unknown"}
                      </Typography>
                    </Box>
                    <IconButton size="small" onClick={() => removeFile(i)} aria-label={`Remove ${f.name}`}>
                      <X size={16} />
                    </IconButton>
                  </Stack>
                </Card>
              ))}
              <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ pt: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  {files.length} file{files.length === 1 ? "" : "s"} queued
                </Typography>
                <Button
                  variant="contained"
                  size="large"
                  onClick={() => upload.mutate(files)}
                  disabled={upload.isPending}
                >
                  {upload.isPending ? "Processing…" : "Process"}
                </Button>
              </Stack>
              {upload.isPending && <LinearProgress />}
            </Stack>
          )}

          {upload.isError && (
            <Alert severity="error" icon={<AlertCircle size={18} />} sx={{ mt: 2 }}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>Processing failed</Typography>
              <Typography variant="body2">{(upload.error as Error)?.message}</Typography>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* ─── Recent batches ─── */}
      <RecentBatches
        selectedId={selectedBatchId}
        onSelect={(r, summary) => {
          setReport(r);
          setSelectedBatchId(summary.id);
        }}
      />

      {/* ─── Batch detail (stacked sections) ─── */}
      {report ? (
        <BatchDetail report={report} />
      ) : (
        <Card>
          <CardContent sx={{ textAlign: "center", py: 6 }}>
            <FileText size={32} style={{ opacity: 0.3, marginBottom: 12 }} />
            <Typography variant="h4">No batch selected</Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              Upload above or pick one from the list to see its results.
            </Typography>
          </CardContent>
        </Card>
      )}
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BatchDetail — collapsible Results / Insights / Corrections
// ─────────────────────────────────────────────────────────────────────────────
type Section = "results" | "insights" | "corrections" | null;

function BatchDetail({ report }: { report: BatchReport }) {
  const [openSection, setOpenSection] = useState<Section>("results");
  const docCount = report.documents.length;
  const insightCount = report.insights?.length || 0;
  const anomalyCount = report.anomalies?.length || 0;

  return (
    <Card>
      <CardContent sx={{ p: 0 }}>
        {/* Header */}
        <Box sx={{ p: 3, borderBottom: 1, borderColor: "divider" }}>
          <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} justifyContent="space-between" spacing={2}>
            <Box>
              <Typography variant="h3">Selected batch</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {docCount} document{docCount === 1 ? "" : "s"} processed in{" "}
                {durationSince(report.started_at, report.finished_at)} ·{" "}
                cost ${report.total_cost_usd.toFixed(4)}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Chip
                size="small"
                color={anomalyCount ? "error" : "default"}
                variant={anomalyCount ? "filled" : "outlined"}
                label={`${anomalyCount} anomal${anomalyCount === 1 ? "y" : "ies"}`}
              />
              <Chip
                size="small"
                color={insightCount ? "info" : "default"}
                variant={insightCount ? "filled" : "outlined"}
                label={`${insightCount} insight${insightCount === 1 ? "" : "s"}`}
              />
            </Stack>
          </Stack>
        </Box>

        <ExpandSection
          label="Results — what was extracted"
          isOpen={openSection === "results"}
          onToggle={() => setOpenSection(openSection === "results" ? null : "results")}
          badge={`${docCount} docs`}
        >
          <ResultsSection report={report} />
        </ExpandSection>
        <ExpandSection
          label="Insights & anomalies"
          isOpen={openSection === "insights"}
          onToggle={() => setOpenSection(openSection === "insights" ? null : "insights")}
          badge={`${insightCount + anomalyCount}`}
        >
          <InsightsSection report={report} />
        </ExpandSection>
        <ExpandSection
          label="Review & corrections"
          isOpen={openSection === "corrections"}
          onToggle={() => setOpenSection(openSection === "corrections" ? null : "corrections")}
        >
          <CorrectionsSection report={report} />
        </ExpandSection>
      </CardContent>
    </Card>
  );
}

function ExpandSection({
  label, isOpen, onToggle, badge, children,
}: {
  label: string;
  isOpen: boolean;
  onToggle: () => void;
  badge?: string | number;
  children: React.ReactNode;
}) {
  return (
    <Box sx={{ borderTop: 1, borderColor: "divider", "&:first-of-type": { borderTop: 0 } }}>
      <Box
        component="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        sx={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          px: 3, py: 2,
          textAlign: "left",
          border: 0,
          background: "transparent",
          cursor: "pointer",
          color: "text.primary",
          fontSize: "0.9375rem",
          fontWeight: 500,
          "&:hover": { bgcolor: "action.hover" },
        }}
      >
        {isOpen ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        <Typography sx={{ flex: 1, fontWeight: 500 }}>{label}</Typography>
        {badge !== undefined && (
          <Chip size="small" label={badge} variant="outlined" />
        )}
      </Box>
      {isOpen && <Box sx={{ px: 3, pb: 3 }}>{children}</Box>}
    </Box>
  );
}

function ResultsSection({ report }: { report: BatchReport }) {
  if (report.documents.length === 0) {
    return <Typography variant="body2" color="text.secondary">No documents in this batch.</Typography>;
  }
  return (
    <Stack spacing={2}>
      {report.documents.map((doc) => {
        const cluster = report.clusters[doc.document_id];
        const fields = report.extractions[doc.document_id]?.fields || {};
        const entries = Object.entries(fields);
        return (
          <Card key={doc.document_id} variant="outlined" sx={{ p: 2 }}>
            <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 1.5 }}>
              <Typography variant="body1" sx={{ fontWeight: 600 }}>{doc.filename}</Typography>
              {cluster && (
                <Typography variant="caption" color="text.secondary">
                  {cluster.industry} · {cluster.vendor} · {cluster.doc_type} · conf {(cluster.confidence * 100).toFixed(0)}%
                </Typography>
              )}
            </Stack>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, columnGap: 3, rowGap: 0.5 }}>
              {entries.map(([k, v]) => (
                <FieldRow
                  key={k}
                  fieldName={k}
                  displayValue={formatFieldValue(v.value)}
                  editValue={fieldValueAsString(v.value)}
                  industry={cluster?.industry || "unknown"}
                  vendor={cluster?.vendor || "unknown"}
                  docType={cluster?.doc_type || "unknown"}
                />
              ))}
              {entries.length === 0 && (
                <Typography variant="caption" color="text.secondary">No fields extracted.</Typography>
              )}
            </Box>
          </Card>
        );
      })}
    </Stack>
  );
}

function InsightsSection({ report }: { report: BatchReport }) {
  const all = [
    ...(report.insights || []).map((i) => ({ ...i, kind: "insight" as const })),
    ...(report.anomalies || []).map((a) => ({
      kind: "anomaly" as const,
      insight_type: a.rule_id,
      severity: a.severity,
      title: a.message,
      body: a.field_path ? `field: ${a.field_path}` : "",
    })),
  ];
  if (all.length === 0) {
    return (
      <Stack alignItems="center" sx={{ py: 4 }}>
        <CheckCircle2 size={24} style={{ opacity: 0.5 }} />
        <Typography variant="body2" sx={{ mt: 1, fontWeight: 500 }}>Nothing flagged</Typography>
        <Typography variant="caption" color="text.secondary">No insights and no anomalies on this batch.</Typography>
      </Stack>
    );
  }
  return (
    <Stack spacing={1.5}>
      {all.map((f, i) => (
        <Card key={i} variant="outlined" sx={{ p: 2 }}>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
            <Chip
              size="small"
              label={f.severity}
              color={f.severity === "HIGH" ? "error" : f.severity === "MEDIUM" ? "warning" : "info"}
            />
            <Typography variant="caption" color="text.secondary">{f.insight_type}</Typography>
          </Stack>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>{f.title}</Typography>
          {f.body && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: "pre-wrap" }}>
              {f.body}
            </Typography>
          )}
        </Card>
      ))}
    </Stack>
  );
}

function CorrectionsSection({ report }: { report: BatchReport }) {
  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        Hover any field in the Results section above to reveal a pencil icon. Corrections embed into the
        brain immediately and bias future similar documents.
      </Typography>
      {report.pattern_matches && report.pattern_matches.length > 0 && (
        <Card variant="outlined" sx={{ p: 2 }}>
          <Typography variant="caption" sx={{ fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Pattern matches
          </Typography>
          <Stack spacing={0.5} sx={{ mt: 1.5 }}>
            {report.pattern_matches.slice(0, 10).map((m, i) => (
              <Stack key={i} direction="row" spacing={2} sx={{ fontFamily: "monospace", fontSize: "0.75rem" }}>
                <Typography variant="caption" color="text.secondary">#{m.rank}</Typography>
                <Typography variant="caption" sx={{ fontFamily: "monospace" }}>{m.pattern_id.slice(0, 8)}</Typography>
                <Typography variant="caption" color="text.secondary">
                  similarity {(m.similarity * 100).toFixed(0)}%
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Card>
      )}
      <Divider />
      <Typography variant="caption" color="text.secondary">
        Inline-edit affordance · queue of recent analyst corrections coming in Wave 3.x polish.
      </Typography>
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function formatFieldValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) return `[${v.length} items]`;
  if (typeof v === "object") return JSON.stringify(v).slice(0, 80);
  return String(v);
}

function durationSince(start: string, end: string): string {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}
