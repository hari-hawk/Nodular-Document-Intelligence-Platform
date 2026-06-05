"use client";

import { useMutation } from "@tanstack/react-query";
import { Check, Pencil, X } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Badge, Button, Input, Spinner } from "./ui";

/**
 * One row of "field_name: value" with an inline correction affordance.
 *
 * UX choice: hover reveals a pencil icon; click flips the row into
 * edit mode showing an Input pre-populated with the current value plus
 * Save/Cancel actions. On success, a small "corrected" pill appears
 * after the value so the analyst sees their feedback registered.
 *
 * Why inline (not a modal):
 *   - Analysts batch-correct several fields on a single document.
 *     A modal would force a click sequence per field; inline lets
 *     them blow through corrections row by row.
 *   - The correction context (industry, vendor, doc_type, field) all
 *     comes from the parent — no form needed.
 *
 * Failure mode: the optimistic UI is conservative. If the POST fails,
 * the original extracted value stays visible AND we surface the error
 * inline. We don't roll the value back to "original" because the user
 * is correcting it precisely BECAUSE the original was wrong.
 */
export function FieldRow({
  fieldName,
  displayValue,
  editValue,
  industry,
  vendor,
  docType,
}: {
  fieldName: string;
  /** Human-friendly truncated string shown in read mode. */
  displayValue: string;
  /** Full string used to seed the edit input + as the original-value
   *  payload sent with the correction. */
  editValue: string;
  industry: string;
  vendor: string;
  docType: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(editValue);
  const [confirmed, setConfirmed] = useState<string | null>(null); // shows the new value after success

  const mutate = useMutation({
    mutationFn: () =>
      api.postCorrection({
        industry, vendor, doc_type: docType,
        field_path: fieldName,
        extracted_value: editValue || null,
        corrected_value: draft,
      }),
    onSuccess: () => {
      setConfirmed(draft);
      setEditing(false);
    },
  });

  const displayed = confirmed ?? displayValue;

  if (editing) {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2 text-xs text-[rgb(var(--fg-muted))]">
          Correcting <span className="font-mono">{fieldName}</span>
        </div>
        <div className="flex gap-2 items-center">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") mutate.mutate();
              if (e.key === "Escape") { setEditing(false); setDraft(editValue); }
            }}
            className="flex-1 font-mono text-sm"
          />
          <Button
            size="sm"
            onClick={() => mutate.mutate()}
            disabled={mutate.isPending || draft === editValue}
          >
            {mutate.isPending ? <Spinner className="border-white border-t-transparent" /> : <Check className="h-4 w-4" />}
            Save
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => { setEditing(false); setDraft(editValue); }}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        {mutate.isError && (
          <div className="text-xs text-red-600 dark:text-red-400">
            Save failed: {(mutate.error as Error)?.message}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group flex gap-2 text-sm items-center",
        "py-0.5 rounded hover:bg-[rgb(var(--surface-muted))] -mx-1 px-1",
      )}
    >
      <span className="text-[rgb(var(--fg-muted))] min-w-[140px] shrink-0">{fieldName}:</span>
      <span className="font-mono truncate flex-1" title={displayed}>
        {displayed || <span className="text-[rgb(var(--fg-muted))]">—</span>}
      </span>
      {confirmed !== null && (
        <Badge tone="success" className="text-[10px] shrink-0">corrected</Badge>
      )}
      <button
        onClick={() => { setEditing(true); setDraft(editValue); }}
        className={cn(
          "shrink-0 p-1 rounded text-[rgb(var(--fg-muted))]",
          "opacity-0 group-hover:opacity-100 focus:opacity-100",
          "hover:text-[rgb(var(--fg))] hover:bg-[rgb(var(--border))]",
          "transition-opacity",
        )}
        aria-label={`Correct ${fieldName}`}
        title={`Correct ${fieldName}`}
      >
        <Pencil className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/** Stable string-ification — kept in lockstep with formatFieldValue in
 *  workspace/page.tsx so the edit input always starts from the same
 *  string the user just saw. */
export function fieldValueAsString(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v) || typeof v === "object") return JSON.stringify(v);
  return String(v);
}
