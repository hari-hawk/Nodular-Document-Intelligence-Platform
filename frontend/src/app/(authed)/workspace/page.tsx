"use client";

import {
  Alert, Box, Button, Card, CardContent, Chip, IconButton,
  LinearProgress, Stack, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle, CheckCircle2, FileText, FileStack, Sparkles, UploadCloud, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, type BatchReport } from "@/lib/api";
import { DocumentDetail, DocumentPicker } from "@/components/document-detail";
import { KpiTile } from "@/components/kpi-tile";
import { RecentBatches } from "@/components/recent-batches";

/**
 * Workspace — the daily cockpit.
 *
 * Flow (user-tested 2026-06-05):
 *   1. KPI strip → at-a-glance read on the currently selected batch.
 *   2. Upload zone → drag-drop or browse.
 *   3. Recent batches → click any row to load.
 *   4. Selected batch:
 *        a. Document list (DocumentPicker) — click any doc to drill in.
 *        b. When a doc is selected, the DocumentDetail view replaces
 *           the picker with a back-button + the fields data grid.
 *   5. Insights & anomalies + Patterns appear as separate cards below.
 *
 * Spacing follows MUI's 8px grid via `spacing()` tokens (every padding /
 * gap / margin is a multiple of 8). Cards have consistent radius + border;
 * sections use uppercase stamps for visual rhythm.
 */
export default function WorkspacePage() {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [report, setReport] = useState<BatchReport | null>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [openDocId, setOpenDocId] = useState<string | null>(null);

  // Anchor we scroll to when a batch is loaded — without this, clicking
  // a batch deep in the recent-batches list updates the BatchOverview
  // below but the user doesn't see it because their viewport is already
  // up at the list. Smooth scroll = the missing UX feedback.
  const detailAnchorRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (report && detailAnchorRef.current) {
      // Defer one frame so the panel is in the DOM before scrolling.
      requestAnimationFrame(() => {
        detailAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }, [report?.batch_id]);

  const usageQ = useQuery({
    queryKey: ["tenant-usage"],
    queryFn: () => api.getTenantUsage(),
    retry: 0,
  });

  const upload = useMutation({
    mutationFn: (toUpload: File[]) => api.processBatch(toUpload),
    onSuccess: (r) => {
      setReport(r);
      setSelectedBatchId(r.batch_id ?? null);
      setOpenDocId(null);
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

  const docCount = report?.documents.length ?? 0;
  const insightCount = report?.insights?.length ?? 0;
  const anomalyCount = report?.anomalies?.length ?? 0;
  const cost = report?.total_cost_usd ?? 0;
  const monthlyCap = usageQ.data?.monthly_cap_usd ?? 0;
  const monthlySpent = usageQ.data?.spent_usd ?? 0;

  // The document currently drilled into (when openDocId is set).
  const openDoc = openDocId && report
    ? report.documents.find((d) => d.document_id === openDocId)
    : null;

  return (
    <Stack spacing={4}>
      {/* ─── Page heading ─── */}
      <Box>
        <Typography variant="h1">Workspace</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
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
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ mb: 3 }}>
            <Typography variant="h3">Upload documents</Typography>
            <Typography variant="body2" color="text.secondary" id="upload-hint" sx={{ mt: 0.5 }}>
              PDF, image, or text. Up to 200 pages per file (the soft cap warns at 10).
            </Typography>
          </Box>

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
              transition: "border-color .2s, background-color .2s, transform .2s",
              "&:hover": {
                borderColor: "primary.main",
                bgcolor: (t) => t.palette.mode === "dark"
                  ? "rgba(99,102,241,.08)" : "rgba(99,102,241,.08)",
              },
            }}
          >
            <Box sx={{ display: "inline-flex", p: 2, mb: 2, borderRadius: "50%", bgcolor: "primary.main", color: "primary.contrastText" }}>
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
                <Card key={i} variant="outlined" sx={{ p: 2 }}>
                  <Stack direction="row" spacing={2} alignItems="center">
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
          setOpenDocId(null);  // close any open drill-down when switching batches
        }}
      />

      {/* ─── Batch detail OR document drill-down ─── */}
      <Box ref={detailAnchorRef} sx={{ scrollMarginTop: 16 }}>
        {report ? (
          openDoc ? (
            <DocumentDetail
              document={openDoc}
              report={report}
              onBack={() => setOpenDocId(null)}
            />
          ) : (
            <BatchOverview
              report={report}
              onOpenDocument={(id) => setOpenDocId(id)}
            />
          )
        ) : (
          <Card>
            <CardContent sx={{ textAlign: "center", py: 8 }}>
              <FileText size={32} style={{ opacity: 0.3, marginBottom: 16 }} />
              <Typography variant="h4">No batch selected</Typography>
              <Typography color="text.secondary" sx={{ mt: 1 }}>
                Upload above or pick one from the list to see its results.
              </Typography>
            </CardContent>
          </Card>
        )}
      </Box>
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BatchOverview — selected batch summary + document picker
// ─────────────────────────────────────────────────────────────────────────────
function BatchOverview({
  report, onOpenDocument,
}: {
  report: BatchReport;
  onOpenDocument: (docId: string) => void;
}) {
  const docCount = report.documents.length;
  const insightCount = report.insights?.length || 0;
  const anomalyCount = report.anomalies?.length || 0;

  return (
    <Stack spacing={3}>
      <Card>
        <CardContent sx={{ p: 0 }}>
          {/* Header */}
          <Box sx={{ p: 3, borderBottom: 1, borderColor: "divider" }}>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              alignItems={{ sm: "center" }}
              justifyContent="space-between"
              spacing={2}
            >
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
          {/* Document picker — click any to drill in */}
          <Box sx={{ p: 0 }}>
            <Box sx={{ px: 3, py: 1.5, bgcolor: "action.hover", borderBottom: 1, borderColor: "divider" }}>
              <Typography
                variant="caption"
                sx={{ textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600, color: "text.secondary" }}
              >
                Documents ({docCount}) · click any to drill in
              </Typography>
            </Box>
            <DocumentPicker
              documents={report.documents}
              report={report}
              onSelect={onOpenDocument}
            />
          </Box>
        </CardContent>
      </Card>

      {/* Batch-level insights & anomalies */}
      {(insightCount > 0 || anomalyCount > 0) && (
        <Card>
          <CardContent>
            <Typography variant="h4" sx={{ mb: 2 }}>
              Insights & anomalies
              <Chip
                label={insightCount + anomalyCount}
                size="small"
                variant="outlined"
                sx={{ ml: 1 }}
              />
            </Typography>
            <Stack spacing={1.5}>
              {[
                ...(report.insights || []).map((i) => ({
                  severity: i.severity, title: i.title, body: i.body, type: i.insight_type, kind: "insight" as const,
                })),
                ...(report.anomalies || []).map((a) => ({
                  severity: a.severity, title: a.message,
                  body: a.field_path ? `field: ${a.field_path}` : "",
                  type: a.rule_id, kind: "anomaly" as const,
                })),
              ].map((f, i) => (
                <Card key={i} variant="outlined" sx={{ p: 2 }}>
                  <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                    <Chip
                      size="small"
                      label={f.severity}
                      color={f.severity === "HIGH" ? "error" : f.severity === "MEDIUM" ? "warning" : "info"}
                    />
                    <Typography variant="caption" color="text.secondary">{f.type}</Typography>
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
          </CardContent>
        </Card>
      )}
    </Stack>
  );
}

function durationSince(start: string, end: string): string {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}
