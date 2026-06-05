"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Clock, FileStack, Sparkles } from "lucide-react";

import { api, type BatchReport, type BatchSummary } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Badge, Card, CardBody, CardDescription, CardHeader, CardTitle, EmptyState, Spinner } from "./ui";

/**
 * Recent-batches list. Sits between Upload and Selected-batch on the
 * Workspace page. Each row is a button that loads the full report and
 * pushes it up to the parent via onSelect — the parent then renders
 * the BatchDetail with that report.
 *
 * Why a flat list and not a sidebar tree: at small batch counts
 * (typical: <100 per tenant), a vertical scrollable list is faster to
 * scan than a navigation tree. When tenants start uploading thousands
 * of batches we'll add a search + date filter + pagination — but
 * that's a Wave 3.x polish item, not blocking the cockpit's usability.
 */
export function RecentBatches({
  selectedId,
  onSelect,
}: {
  selectedId?: string | null;
  onSelect: (report: BatchReport, summary: BatchSummary) => void;
}) {
  const queryClient = useQueryClient();
  const q = useQuery({
    queryKey: ["recent-batches"],
    queryFn: () => api.listBatches(20),
    // The list could be refetched on focus to catch batches finished
    // in other tabs, but that's also covered by manual refresh after
    // an upload completes (parent invalidates the cache).
  });

  if (q.isLoading) {
    return (
      <Card><CardBody className="flex justify-center py-6"><Spinner /></CardBody></Card>
    );
  }
  if (q.isError) {
    return (
      <Card>
        <CardBody className="flex items-start gap-2 text-sm text-red-600 dark:text-red-400">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">Couldn't load recent batches.</div>
            <div className="mt-0.5 text-xs">{(q.error as Error).message}</div>
          </div>
        </CardBody>
      </Card>
    );
  }
  const batches = q.data?.batches || [];
  if (batches.length === 0) {
    return (
      <Card><CardBody>
        <EmptyState
          icon={<FileStack className="h-8 w-8" />}
          title="No batches yet"
          subtitle="Upload some documents above. Past batches will appear here once they finish processing."
        />
      </CardBody></Card>
    );
  }

  const loadAndSelect = async (b: BatchSummary) => {
    // Use the React Query cache so repeat-clicks are instant.
    const cached = queryClient.getQueryData<BatchReport>(["report", b.id]);
    if (cached) {
      onSelect(cached, b);
      return;
    }
    const fetched = await queryClient.fetchQuery<BatchReport>({
      queryKey: ["report", b.id],
      queryFn: () => api.getReport(b.id),
    });
    onSelect(fetched, b);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Recent batches</CardTitle>
            <CardDescription>
              Click a batch to load its results below.
            </CardDescription>
          </div>
          <Badge tone="neutral">{batches.length}</Badge>
        </div>
      </CardHeader>
      <CardBody className="p-0">
        <ul className="divide-y divide-[rgb(var(--border))]">
          {batches.map((b) => {
            const active = b.id === selectedId;
            return (
              <li key={b.id}>
                <button
                  onClick={() => loadAndSelect(b)}
                  className={cn(
                    "w-full text-left px-5 py-3.5 transition-colors flex gap-3",
                    "hover:bg-[rgb(var(--surface-muted))]",
                    active && "bg-brand-50 dark:bg-brand-900/30",
                  )}
                >
                  <div className="shrink-0 mt-0.5">
                    <FileStack className={cn(
                      "h-4 w-4",
                      active ? "text-brand-600 dark:text-brand-300" : "text-[rgb(var(--fg-muted))]",
                    )} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-mono text-xs truncate">
                        {b.id.slice(0, 8)}…
                      </span>
                      <span className="text-xs text-[rgb(var(--fg-muted))] flex items-center gap-1 shrink-0">
                        <Clock className="h-3 w-3" />
                        {formatRelative(b.started_at)}
                      </span>
                    </div>
                    {b.narrator_preview && (
                      <div className="mt-1 text-sm text-[rgb(var(--fg))] line-clamp-2">
                        {b.narrator_preview}
                      </div>
                    )}
                    <div className="mt-1.5 flex items-center gap-2 text-xs text-[rgb(var(--fg-muted))]">
                      <span>{b.total_documents} doc{b.total_documents === 1 ? "" : "s"}</span>
                      <span aria-hidden>·</span>
                      <span>${b.cost_usd.toFixed(4)}</span>
                      {b.anomaly_count > 0 && (
                        <>
                          <span aria-hidden>·</span>
                          <Badge tone="danger" className="text-[10px] py-0">
                            {b.anomaly_count} anomal{b.anomaly_count === 1 ? "y" : "ies"}
                          </Badge>
                        </>
                      )}
                      {b.insight_count > 0 && (
                        <>
                          <span aria-hidden>·</span>
                          <Badge tone="info" className="text-[10px] py-0 flex items-center gap-1">
                            <Sparkles className="h-3 w-3" />
                            {b.insight_count}
                          </Badge>
                        </>
                      )}
                    </div>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </CardBody>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (!isFinite(then)) return "—";
  const delta = Date.now() - then;
  if (delta < 60_000) return "just now";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`;
  if (delta < 7 * 86_400_000) return `${Math.floor(delta / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString();
}
