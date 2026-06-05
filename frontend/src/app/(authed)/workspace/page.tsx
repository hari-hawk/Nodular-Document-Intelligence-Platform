"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle, ChevronDown, ChevronRight, FileText, UploadCloud } from "lucide-react";
import { useState } from "react";

import { api, BatchReport } from "@/lib/api";
import { cn } from "@/lib/cn";
import { FieldRow, fieldValueAsString } from "@/components/field-row";
import { RecentBatches } from "@/components/recent-batches";
import {
  Badge, Button, Card, CardBody, CardDescription, CardHeader, CardTitle,
  EmptyState, Spinner,
} from "@/components/ui";

/**
 * Workspace — the daily-use cockpit. Single page, three stacked sections:
 *
 *   1. Upload zone (drag-drop or file picker)
 *   2. Selected batch — appears after upload completes, with three
 *      collapsible inner sections: Results / Insights / Corrections
 *
 * No tabs at the page level: scrolling top-to-bottom matches the
 * natural workflow ("I uploaded — now what came out — now what do I do
 * about it"). Tabs would force a context switch for a single linear
 * task.
 *
 * Recent-batches history would also live here long-term (between
 * upload and results) but listing /report needs a separate endpoint
 * that doesn't exist yet — when it does, drop it in between the
 * Upload card and the Selected-batch detail without restructuring.
 */
export default function WorkspacePage() {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [report, setReport] = useState<BatchReport | null>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (toUpload: File[]) => api.processBatch(toUpload),
    onSuccess: (r) => {
      setReport(r);
      // The upload just produced a new batch; refresh the list so the
      // user sees it appear at the top without a manual reload. The
      // batch_id comes back inside the report (set by the orchestrator).
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

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Workspace</h1>
        <p className="text-sm text-[rgb(var(--fg-muted))] mt-1">
          Upload documents, watch them get extracted, review what came out.
        </p>
      </header>

      {/* ───────────── Upload section ───────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Upload documents</CardTitle>
          <CardDescription>
            PDF, image, or text. Up to 200 pages per file (the soft cap warns
            at 10).
          </CardDescription>
        </CardHeader>
        <CardBody>
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            className={cn(
              "rounded-md border-2 border-dashed p-8 text-center",
              "border-[rgb(var(--border))] bg-[rgb(var(--surface-muted))]",
              "transition-colors hover:bg-slate-100 dark:hover:bg-slate-800",
            )}
          >
            <UploadCloud className="h-8 w-8 mx-auto text-brand-500" />
            <p className="mt-2 text-sm font-medium">
              Drag files here, or{" "}
              <label className="text-brand-600 dark:text-brand-400 cursor-pointer underline">
                browse
                <input
                  type="file"
                  multiple
                  className="hidden"
                  onChange={onPick}
                  accept=".pdf,.png,.jpg,.jpeg,.tiff,.txt"
                />
              </label>
            </p>
            <p className="text-xs text-[rgb(var(--fg-muted))] mt-1">
              Multiple files OK. They're processed concurrently.
            </p>
          </div>

          {files.length > 0 && (
            <div className="mt-4 space-y-2">
              {files.map((f, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 text-sm border border-[rgb(var(--border))] rounded-md p-2.5"
                >
                  <FileText className="h-4 w-4 text-[rgb(var(--fg-muted))] shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{f.name}</div>
                    <div className="text-xs text-[rgb(var(--fg-muted))]">
                      {(f.size / 1024).toFixed(1)} KB · {f.type || "unknown"}
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => removeFile(i)}>
                    Remove
                  </Button>
                </div>
              ))}

              <div className="pt-2 flex items-center justify-between">
                <div className="text-sm text-[rgb(var(--fg-muted))]">
                  {files.length} file{files.length === 1 ? "" : "s"} queued
                </div>
                <Button
                  onClick={() => upload.mutate(files)}
                  disabled={upload.isPending}
                >
                  {upload.isPending ? <><Spinner className="border-white border-t-transparent" /> Processing…</> : "Process"}
                </Button>
              </div>
            </div>
          )}

          {upload.isError && (
            <div className="mt-4 rounded-md border border-red-300 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300 flex gap-2 items-start">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              <div>
                <div className="font-medium">Processing failed</div>
                <div className="mt-0.5">{(upload.error as Error)?.message}</div>
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* ───────────── Recent batches ───────────── */}
      <RecentBatches
        selectedId={selectedBatchId}
        onSelect={(r, summary) => {
          setReport(r);
          setSelectedBatchId(summary.id);
        }}
      />

      {/* ───────────── Batch detail ───────────── */}
      {report ? (
        <BatchDetail report={report} />
      ) : (
        <Card>
          <CardBody>
            <EmptyState
              icon={<FileText className="h-8 w-8" />}
              title="No batch selected"
              subtitle="Upload above or pick one from the list to see its results."
            />
          </CardBody>
        </Card>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BatchDetail — collapsible Results / Insights / Corrections.
// ─────────────────────────────────────────────────────────────────────────────
type Section = "results" | "insights" | "corrections" | null;

function BatchDetail({ report }: { report: BatchReport }) {
  // Default open: Results (most-asked first). Mobile-friendly accordion
  // lets analysts collapse what they don't need.
  const [openSection, setOpenSection] = useState<Section>("results");

  const docCount = report.documents.length;
  const insightCount = report.insights?.length || 0;
  const anomalyCount = report.anomalies?.length || 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Selected batch</CardTitle>
            <CardDescription>
              {docCount} document{docCount === 1 ? "" : "s"} processed in{" "}
              {durationSince(report.started_at, report.finished_at)} ·{" "}
              cost ${report.total_cost_usd.toFixed(4)}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Badge tone={anomalyCount ? "danger" : "neutral"}>
              {anomalyCount} anomal{anomalyCount === 1 ? "y" : "ies"}
            </Badge>
            <Badge tone={insightCount ? "info" : "neutral"}>
              {insightCount} insight{insightCount === 1 ? "" : "s"}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardBody className="p-0">
        <Section
          label="Results — what was extracted"
          isOpen={openSection === "results"}
          onToggle={() => setOpenSection(openSection === "results" ? null : "results")}
          badge={`${docCount} docs`}
        >
          <ResultsSection report={report} />
        </Section>
        <Section
          label="Insights & anomalies"
          isOpen={openSection === "insights"}
          onToggle={() => setOpenSection(openSection === "insights" ? null : "insights")}
          badge={`${insightCount + anomalyCount}`}
        >
          <InsightsSection report={report} />
        </Section>
        <Section
          label="Review & corrections"
          isOpen={openSection === "corrections"}
          onToggle={() => setOpenSection(openSection === "corrections" ? null : "corrections")}
        >
          <CorrectionsSection report={report} />
        </Section>
      </CardBody>
    </Card>
  );
}

function Section({
  label, isOpen, onToggle, badge, children,
}: {
  label: string;
  isOpen: boolean;
  onToggle: () => void;
  badge?: string | number;
  children: React.ReactNode;
}) {
  return (
    <div className="border-t border-[rgb(var(--border))] first:border-t-0">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-5 py-3.5 text-left text-sm font-medium hover:bg-[rgb(var(--surface-muted))]"
      >
        {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <span className="flex-1">{label}</span>
        {badge !== undefined && (
          <Badge tone="neutral">{badge}</Badge>
        )}
      </button>
      {isOpen && <div className="px-5 pb-5">{children}</div>}
    </div>
  );
}

function ResultsSection({ report }: { report: BatchReport }) {
  if (report.documents.length === 0) {
    return <EmptyState title="No documents in this batch" />;
  }
  return (
    <div className="space-y-3">
      {report.documents.map((doc) => {
        const cluster = report.clusters[doc.document_id];
        const fields = report.extractions[doc.document_id]?.fields || {};
        const entries = Object.entries(fields);
        return (
          <div key={doc.document_id} className="border border-[rgb(var(--border))] rounded-md p-4">
            <div className="flex items-baseline justify-between mb-2">
              <h4 className="font-medium">{doc.filename}</h4>
              {cluster && (
                <div className="text-xs text-[rgb(var(--fg-muted))]">
                  {cluster.industry} · {cluster.vendor} · {cluster.doc_type} ·{" "}
                  conf {(cluster.confidence * 100).toFixed(0)}%
                </div>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-sm">
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
                <span className="text-xs text-[rgb(var(--fg-muted))]">No fields extracted.</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
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
    return <EmptyState icon={<CheckCircle className="h-6 w-6" />} title="Nothing flagged." subtitle="No insights and no anomalies on this batch." />;
  }
  return (
    <div className="space-y-2">
      {all.map((f, i) => (
        <div key={i} className="border border-[rgb(var(--border))] rounded-md p-3">
          <div className="flex items-center gap-2 mb-1">
            <SeverityBadge severity={f.severity} />
            <span className="text-xs text-[rgb(var(--fg-muted))]">{f.insight_type}</span>
          </div>
          <div className="text-sm font-medium">{f.title}</div>
          {f.body && (
            <div className="text-sm text-[rgb(var(--fg-muted))] mt-1 whitespace-pre-wrap">
              {f.body}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function CorrectionsSection({ report }: { report: BatchReport }) {
  return (
    <div className="space-y-3 text-sm">
      <div className="text-[rgb(var(--fg-muted))]">
        Click any field in the Results section above to correct it. Corrections
        embed into the brain immediately and bias future similar documents.
      </div>
      <div className="text-xs text-[rgb(var(--fg-muted))]">
        Pending Wave 3.x: inline-edit affordance + a queue view of recent
        analyst corrections. For now, use POST /correction directly.
      </div>
      {report.pattern_matches && report.pattern_matches.length > 0 && (
        <div className="mt-3 border border-[rgb(var(--border))] rounded-md p-3">
          <div className="text-xs font-medium mb-2">Pattern matches</div>
          <div className="space-y-1">
            {report.pattern_matches.slice(0, 10).map((m, i) => (
              <div key={i} className="flex gap-3 text-xs">
                <span className="font-mono text-[rgb(var(--fg-muted))]">#{m.rank}</span>
                <span className="font-mono">{m.pattern_id.slice(0, 8)}</span>
                <span className="text-[rgb(var(--fg-muted))]">
                  similarity {(m.similarity * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function SeverityBadge({ severity }: { severity: string }) {
  const tone =
    severity === "HIGH" ? "danger" :
    severity === "MEDIUM" ? "warning" :
    severity === "LOW" ? "info" : "neutral";
  return <Badge tone={tone}>{severity}</Badge>;
}

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
