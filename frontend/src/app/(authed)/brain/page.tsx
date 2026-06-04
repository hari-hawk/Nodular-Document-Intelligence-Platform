"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api";
import {
  Badge, Button, Card, CardBody, CardDescription, CardHeader, CardTitle,
  EmptyState, Spinner, Tabs,
} from "@/components/ui";

/**
 * Brain — what the platform has learned. Four tabs:
 *
 *   Patterns       — Hippocampus patterns (memory of seen documents)
 *   Tenant Facts   — per-tenant master data (account→vendor etc.)
 *   Auto-packs     — pending vendor proposals (one-click promote)
 *   Handlers       — registered Python handlers (the code-bridge)
 *
 * Why grouped: all four answer the same question — "what's the
 * platform's persistent state about this tenant?" — and analysts
 * usually need to cross-reference them ("we have a pattern for AT&T,
 * do we also have a fact, and is the handler wired?").
 */
type TabKey = "patterns" | "facts" | "auto-packs" | "handlers";

export default function BrainPage() {
  const [tab, setTab] = useState<TabKey>("auto-packs");

  // Lightweight per-tab loaders — only the active tab's data fetches,
  // but the cache survives switching back.
  const factsQ = useQuery({
    queryKey: ["facts"],
    queryFn: () => api.listTenantFacts(),
    enabled: tab === "facts",
  });
  const autoPacksQ = useQuery({
    queryKey: ["auto-packs"],
    queryFn: () => api.listAutoPacks("pending"),
    enabled: tab === "auto-packs",
  });
  const handlersQ = useQuery({
    queryKey: ["handlers"],
    queryFn: () => api.listHandlers(),
    enabled: tab === "handlers",
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Brain</h1>
        <p className="text-sm text-[rgb(var(--fg-muted))] mt-1">
          What the platform has learned about your documents.
        </p>
      </header>

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as TabKey)}
        tabs={[
          { value: "auto-packs", label: "Auto-packs",
            badge: autoPacksQ.data?.proposals.length },
          { value: "facts", label: "Tenant facts",
            badge: factsQ.data?.facts.length },
          { value: "patterns", label: "Patterns" },
          { value: "handlers", label: "Handlers",
            badge: handlersQ.data?.handlers.length },
        ]}
      />

      {tab === "auto-packs" && <AutoPacksTab refetch={() => autoPacksQ.refetch()} q={autoPacksQ} />}
      {tab === "facts" && <FactsTab q={factsQ} />}
      {tab === "patterns" && <PatternsStub />}
      {tab === "handlers" && <HandlersTab q={handlersQ} />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Auto-packs tab — one-click promote workflow
// ─────────────────────────────────────────────────────────────────────────────
function AutoPacksTab({ q, refetch }: { q: ReturnType<typeof useQuery<{ proposals: Awaited<ReturnType<typeof api.listAutoPacks>>["proposals"] }>>; refetch: () => void }) {
  if (q.isLoading) return <SpinnerCard />;
  if (q.isError) return <ErrorCard error={q.error as Error} />;
  const proposals = q.data?.proposals || [];
  if (!proposals.length) {
    return (
      <Card><CardBody>
        <EmptyState
          title="No pending pack proposals"
          subtitle="The system will surface vendors here once it sees one outside the existing packs."
        />
      </CardBody></Card>
    );
  }
  return (
    <div className="space-y-3">
      {proposals.map((p) => (
        <Card key={p.id}>
          <CardBody className="flex items-start gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <h4 className="font-medium">{p.vendor_name}</h4>
                <Badge tone="brand" className="text-[10px]">{p.vendor_slug}</Badge>
                {p.doc_type_hint && <Badge tone="info">{p.doc_type_hint}</Badge>}
              </div>
              <div className="text-xs text-[rgb(var(--fg-muted))]">
                Seen {p.sighting_count}× · first sighting {new Date(p.created_at).toLocaleString()}
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={async () => {
                  await api.promoteAutoPack(p.id);
                  refetch();
                }}
              >
                Promote
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={async () => {
                  await api.rejectAutoPack(p.id);
                  refetch();
                }}
              >
                Reject
              </Button>
            </div>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Facts tab
// ─────────────────────────────────────────────────────────────────────────────
function FactsTab({ q }: { q: ReturnType<typeof useQuery<{ facts: Awaited<ReturnType<typeof api.listTenantFacts>>["facts"] }>> }) {
  if (q.isLoading) return <SpinnerCard />;
  if (q.isError) return <ErrorCard error={q.error as Error} />;
  const facts = q.data?.facts || [];
  if (!facts.length) {
    return <Card><CardBody><EmptyState title="No facts yet" subtitle="Facts populate automatically as the platform extracts documents." /></CardBody></Card>;
  }
  // Group by fact_type
  const byType: Record<string, typeof facts> = {};
  for (const f of facts) (byType[f.fact_type] ??= []).push(f);
  return (
    <div className="space-y-4">
      {Object.entries(byType).map(([type, items]) => (
        <Card key={type}>
          <CardHeader>
            <CardTitle className="text-sm font-mono">{type}</CardTitle>
            <CardDescription>{items.length} fact{items.length === 1 ? "" : "s"}</CardDescription>
          </CardHeader>
          <CardBody className="p-0">
            <table className="w-full text-sm">
              <thead className="bg-[rgb(var(--surface-muted))] text-xs">
                <tr>
                  <th className="text-left px-4 py-2">Key</th>
                  <th className="text-left px-4 py-2">Value</th>
                  <th className="text-right px-4 py-2">Confidence</th>
                  <th className="text-right px-4 py-2">Sightings</th>
                </tr>
              </thead>
              <tbody>
                {items.map((f) => (
                  <tr key={f.id} className="border-t border-[rgb(var(--border))]">
                    <td className="px-4 py-2 font-mono text-xs truncate max-w-[180px]">{f.key}</td>
                    <td className="px-4 py-2 truncate max-w-[280px]">{f.value}</td>
                    <td className="px-4 py-2 text-right text-xs">{(f.confidence * 100).toFixed(0)}%</td>
                    <td className="px-4 py-2 text-right text-xs">{f.sighting_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Patterns stub — needs a /admin/patterns endpoint that doesn't exist yet
// ─────────────────────────────────────────────────────────────────────────────
function PatternsStub() {
  return (
    <Card><CardBody>
      <EmptyState
        title="Patterns explorer pending"
        subtitle={
          "Backend endpoint /admin/patterns is not yet implemented. " +
          "Wave 2.1 surfaces per-batch pattern matches in BatchReport.pattern_matches " +
          "— see the Workspace page's batch detail."
        }
      />
    </CardBody></Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Handlers tab — list + manually run
// ─────────────────────────────────────────────────────────────────────────────
function HandlersTab({ q }: { q: ReturnType<typeof useQuery<{ handlers: Awaited<ReturnType<typeof api.listHandlers>>["handlers"] }>> }) {
  if (q.isLoading) return <SpinnerCard />;
  if (q.isError) return <ErrorCard error={q.error as Error} />;
  const handlers = q.data?.handlers || [];
  return (
    <div className="space-y-3">
      {handlers.map((h) => (
        <Card key={h.handler_id}>
          <CardBody>
            <div className="flex items-baseline justify-between mb-1">
              <h4 className="font-mono text-sm font-medium">{h.handler_id}</h4>
              <Badge tone="brand" className="text-[10px]">handler</Badge>
            </div>
            <p className="text-sm text-[rgb(var(--fg))] mt-1">{h.description}</p>
            <p className="text-xs text-[rgb(var(--fg-muted))] mt-2">
              <strong>When to use:</strong> {h.when_to_use}
            </p>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared
// ─────────────────────────────────────────────────────────────────────────────
function SpinnerCard() {
  return <Card><CardBody className="flex items-center justify-center py-10"><Spinner /></CardBody></Card>;
}

function ErrorCard({ error }: { error: Error }) {
  return (
    <Card><CardBody>
      <div className="text-sm text-red-600 dark:text-red-400">
        <div className="font-medium">Couldn't load.</div>
        <div className="mt-1 text-xs">{error.message}</div>
      </div>
    </CardBody></Card>
  );
}
