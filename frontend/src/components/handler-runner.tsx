"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Play } from "lucide-react";
import { useState } from "react";

import { api, type HandlerManifest } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Badge, Button, Input, Spinner } from "./ui";

/**
 * Inline runner for a single handler. Lives inside the Handlers tab's
 * card — clicking Run expands the card downward to show the input
 * panel + result panel.
 *
 * Design choice: inline expansion, not a modal. Modals would be
 * heavier and the handler manifest is small enough that the page
 * never feels crowded. Inline expansion also keeps the visual link
 * between WHICH handler is running and the output it produced.
 *
 * kwargs UX: a single `reason` text input. Two of the seed handlers
 * (`flag_for_review`, future error/escalation handlers) use that
 * key; the others ignore it. When a handler needs richer args
 * (multi-field forms, file pickers), it owns its own kwargs editor
 * and registers itself with a `customRunner` flag that this
 * component will check for.
 */
export function HandlerRunner({ handler }: { handler: HandlerManifest }) {
  const [open, setOpen] = useState(false);
  const [documentId, setDocumentId] = useState("");
  const [reason, setReason] = useState("");

  const mutate = useMutation({
    mutationFn: () =>
      api.runHandler(handler.handler_id, {
        document_id: documentId.trim() || undefined,
        kwargs: reason.trim() ? { reason: reason.trim() } : {},
      }),
  });

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button
          size="sm"
          variant={open ? "secondary" : "primary"}
          onClick={() => setOpen((v) => !v)}
        >
          <Play className="h-3.5 w-3.5" />
          {open ? "Hide runner" : "Run handler"}
        </Button>
      </div>

      {open && (
        <div className="border border-[rgb(var(--border))] rounded-md p-3 space-y-3 bg-[rgb(var(--surface-muted))]">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <label className="block">
              <span className="text-xs font-medium text-[rgb(var(--fg-muted))]">
                Document ID <span className="font-normal">(optional)</span>
              </span>
              <Input
                placeholder="paste a document UUID, or leave empty"
                value={documentId}
                onChange={(e) => setDocumentId(e.target.value)}
                className="mt-1 font-mono text-xs"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[rgb(var(--fg-muted))]">
                Reason <span className="font-normal">(passed as kwargs.reason)</span>
              </span>
              <Input
                placeholder="e.g. suspected duplicate"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="mt-1"
              />
            </label>
          </div>

          <div className="flex items-center justify-end gap-2">
            <Button
              size="sm"
              onClick={() => mutate.mutate()}
              disabled={mutate.isPending}
            >
              {mutate.isPending ? (
                <Spinner className="border-white border-t-transparent" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              Execute
            </Button>
          </div>

          {/* Result panel */}
          {mutate.data && (
            <div
              className={cn(
                "border rounded-md p-3",
                mutate.data.ok
                  ? "border-emerald-300 bg-emerald-50 dark:bg-emerald-900/20 dark:border-emerald-700"
                  : "border-red-300 bg-red-50 dark:bg-red-900/20 dark:border-red-700",
              )}
            >
              <div className="flex items-start gap-2">
                {mutate.data.ok ? (
                  <CheckCircle2 className="h-4 w-4 mt-0.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                ) : (
                  <AlertCircle className="h-4 w-4 mt-0.5 text-red-600 dark:text-red-400 shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{mutate.data.output}</div>
                  {mutate.data.side_effects.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {mutate.data.side_effects.map((s, i) => (
                        <Badge key={i} tone="info" className="font-mono text-[10px]">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {Boolean(
                    mutate.data.data &&
                    typeof mutate.data.data === "object" &&
                    Object.keys(mutate.data.data as object).length > 0,
                  ) && (
                    <details className="mt-2">
                      <summary className="text-xs cursor-pointer text-[rgb(var(--fg-muted))]">
                        result data
                      </summary>
                      <pre className="mt-1 text-xs font-mono whitespace-pre-wrap break-all bg-[rgb(var(--surface))] border border-[rgb(var(--border))] rounded p-2">
                        {JSON.stringify(mutate.data.data, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              </div>
            </div>
          )}

          {mutate.isError && (
            <div className="border border-red-300 bg-red-50 dark:bg-red-900/20 dark:border-red-700 rounded-md p-3 text-sm flex gap-2 items-start">
              <AlertCircle className="h-4 w-4 mt-0.5 text-red-600 dark:text-red-400 shrink-0" />
              <div>
                <div className="font-medium text-red-700 dark:text-red-300">
                  Couldn't run handler
                </div>
                <div className="mt-0.5 text-xs text-red-600 dark:text-red-400">
                  {(mutate.error as Error)?.message}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
