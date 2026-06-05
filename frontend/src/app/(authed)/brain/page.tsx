"use client";

import {
  Alert, Box, Button, Card, CardContent, Chip, Skeleton, Stack, Tab, Tabs,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Brain as BrainIcon, Cpu, Database, Layers, Sparkles, Tag } from "lucide-react";
import { useState } from "react";

import { api, type PatternDetail, type PatternSummary } from "@/lib/api";
import { HandlerRunner } from "@/components/handler-runner";
import { KpiTile } from "@/components/kpi-tile";

/**
 * Brain — what the platform has learned. The KPI hero strip shows
 * counts across each surface so analysts get a sense of "how much
 * does the brain know" before drilling in. Tabs reveal the four
 * memory surfaces: Patterns / Tenant Facts / Auto-packs / Handlers.
 */
type TabKey = "auto-packs" | "facts" | "patterns" | "handlers";

export default function BrainPage() {
  const [tab, setTab] = useState<TabKey>("patterns");

  const factsQ = useQuery({
    queryKey: ["facts"], queryFn: () => api.listTenantFacts(),
    enabled: tab === "facts",
  });
  const autoPacksQ = useQuery({
    queryKey: ["auto-packs"], queryFn: () => api.listAutoPacks("pending"),
    enabled: tab === "auto-packs",
  });
  const handlersQ = useQuery({
    queryKey: ["handlers"], queryFn: () => api.listHandlers(),
    enabled: tab === "handlers",
  });
  const patternsQ = useQuery({
    queryKey: ["patterns"], queryFn: () => api.listPatterns({ limit: 200 }),
    enabled: tab === "patterns",
  });

  // KPI counts run independently so the strip is populated regardless of
  // which tab is active. Stale-while-revalidate means switches are instant.
  const patternsKpi = useQuery({
    queryKey: ["patterns-kpi"], queryFn: () => api.listPatterns({ limit: 500 }),
  });
  const factsKpi = useQuery({
    queryKey: ["facts-kpi"], queryFn: () => api.listTenantFacts(),
  });
  const autoKpi = useQuery({
    queryKey: ["auto-packs-kpi"], queryFn: () => api.listAutoPacks("pending"),
  });
  const handlersKpi = useQuery({
    queryKey: ["handlers-kpi"], queryFn: () => api.listHandlers(),
  });

  return (
    <Stack spacing={4}>
      <Box>
        <Typography variant="h1">Brain</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          What the platform has learned about your documents. Patterns + facts persist
          across batches; auto-packs surface vendors not yet covered by a curated pack.
        </Typography>
      </Box>

      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", md: "repeat(4, 1fr)" },
        }}
      >
        <KpiTile
          label="Patterns memorised"
          value={patternsKpi.data?.patterns.length ?? "—"}
          caption="distinct (industry × vendor × doc_type)"
          icon={<BrainIcon size={18} />}
          loading={patternsKpi.isLoading}
        />
        <KpiTile
          label="Tenant facts"
          value={factsKpi.data?.facts.length ?? "—"}
          caption="durable knowledge"
          icon={<Database size={18} />}
          tone="info"
          loading={factsKpi.isLoading}
        />
        <KpiTile
          label="Auto-pack proposals"
          value={autoKpi.data?.proposals.length ?? "—"}
          caption={autoKpi.data?.proposals.length ? "review pending" : "none pending"}
          tone={autoKpi.data?.proposals.length ? "warning" : "success"}
          icon={<Tag size={18} />}
          loading={autoKpi.isLoading}
        />
        <KpiTile
          label="Handlers registered"
          value={handlersKpi.data?.handlers.length ?? "—"}
          caption="code-bridge entry points"
          icon={<Cpu size={18} />}
          loading={handlersKpi.isLoading}
        />
      </Box>

      <Card>
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v as TabKey)}
          aria-label="Brain surfaces"
          variant="scrollable"
          scrollButtons="auto"
          sx={{ borderBottom: 1, borderColor: "divider", px: 2 }}
        >
          <Tab
            value="patterns"
            iconPosition="start"
            icon={<BrainIcon size={16} />}
            label={`Patterns${patternsKpi.data ? ` (${patternsKpi.data.patterns.length})` : ""}`}
          />
          <Tab
            value="facts"
            iconPosition="start"
            icon={<Database size={16} />}
            label={`Tenant facts${factsKpi.data ? ` (${factsKpi.data.facts.length})` : ""}`}
          />
          <Tab
            value="auto-packs"
            iconPosition="start"
            icon={<Tag size={16} />}
            label={`Auto-packs${autoKpi.data ? ` (${autoKpi.data.proposals.length})` : ""}`}
          />
          <Tab
            value="handlers"
            iconPosition="start"
            icon={<Cpu size={16} />}
            label={`Handlers${handlersKpi.data ? ` (${handlersKpi.data.handlers.length})` : ""}`}
          />
        </Tabs>

        <CardContent sx={{ pt: 3 }}>
          {tab === "patterns" && <PatternsTab q={patternsQ} />}
          {tab === "facts" && <FactsTab q={factsQ} />}
          {tab === "auto-packs" && <AutoPacksTab q={autoPacksQ} refetch={() => autoPacksQ.refetch()} />}
          {tab === "handlers" && <HandlersTab q={handlersQ} />}
        </CardContent>
      </Card>
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Patterns
// ─────────────────────────────────────────────────────────────────────────────
function PatternsTab({ q }: { q: ReturnType<typeof useQuery<{ patterns: PatternSummary[] }>> }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detailQ = useQuery({
    queryKey: ["pattern", selectedId],
    queryFn: () => api.getPattern(selectedId!),
    enabled: selectedId !== null,
  });

  if (q.isLoading) return <LoadingTable rows={5} />;
  if (q.isError) return <Alert severity="error">{(q.error as Error).message}</Alert>;
  const patterns = q.data?.patterns || [];
  if (!patterns.length) {
    return <EmptyTab title="No patterns yet" subtitle="Patterns appear here as Hippocampus memorises documents the platform sees." />;
  }
  return (
    <Box sx={{ display: "grid", gap: 3, gridTemplateColumns: { xs: "1fr", md: "minmax(0, 2fr) minmax(0, 3fr)" } }}>
      {/* Pattern list */}
      <Card variant="outlined">
        <Box component="ul" role="listbox" aria-label="Memorised patterns" sx={{ listStyle: "none", m: 0, p: 0, maxHeight: 560, overflowY: "auto" }}>
          {patterns.map((p) => {
            const active = p.id === selectedId;
            return (
              <Box
                key={p.id}
                component="li"
                role="option"
                aria-selected={active}
                onClick={() => setSelectedId(p.id)}
                sx={{
                  px: 2, py: 1.5,
                  cursor: "pointer",
                  borderBottom: 1,
                  borderColor: "divider",
                  bgcolor: active
                    ? (t) => t.palette.mode === "dark" ? "rgba(99,102,241,.12)" : "rgba(99,102,241,.06)"
                    : "transparent",
                  "&:hover": { bgcolor: "action.hover" },
                  "&:last-child": { borderBottom: 0 },
                }}
              >
                <Typography variant="body2" sx={{ fontWeight: 600 }} noWrap>{p.vendor}</Typography>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 0.5 }}>
                  <Chip label={p.industry} size="small" variant="outlined" sx={{ height: 18, fontSize: "0.65rem" }} />
                  <Typography variant="caption" color="text.secondary">{p.doc_type}</Typography>
                </Stack>
                <Stack direction="row" spacing={1.5} sx={{ mt: 0.75 }}>
                  <Typography variant="caption" color="text.secondary"><Layers size={11} style={{ marginRight: 4, verticalAlign: -1 }} />{p.field_count} fields</Typography>
                  <Typography variant="caption" color="text.secondary">{p.rule_count} rules</Typography>
                  <Typography variant="caption" color="text.secondary">seen {p.seen_count}×</Typography>
                </Stack>
              </Box>
            );
          })}
        </Box>
      </Card>

      {/* Detail */}
      <Box>
        {selectedId === null ? (
          <Card variant="outlined">
            <CardContent sx={{ textAlign: "center", py: 6 }}>
              <BrainIcon size={28} style={{ opacity: 0.3, marginBottom: 12 }} />
              <Typography variant="h4">Pick a pattern</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Click one on the left to inspect its schema and rules.
              </Typography>
            </CardContent>
          </Card>
        ) : detailQ.isLoading ? (
          <LoadingTable rows={4} />
        ) : detailQ.isError ? (
          <Alert severity="error">{(detailQ.error as Error).message}</Alert>
        ) : (
          <PatternDetailView detail={detailQ.data!} />
        )}
      </Box>
    </Box>
  );
}

function PatternDetailView({ detail }: { detail: PatternDetail }) {
  const fields = detail.schema_def.fields || [];
  const rules = detail.rules.rules || [];
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h3">{detail.vendor}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {detail.industry} · {detail.doc_type} · seen {detail.seen_count}×
          {detail.last_seen_at && ` · last ${new Date(detail.last_seen_at).toLocaleString()}`}
        </Typography>
      </CardContent>

      <Section title={`Schema (${fields.length} fields)`}>
        {fields.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>No fields recorded.</Typography>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: "40%" }}>Name</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell align="center">Required</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {fields.map((f, i) => (
                  <TableRow key={i}>
                    <TableCell sx={{ fontFamily: "monospace" }}>{f.name}</TableCell>
                    <TableCell><Chip label={f.type} size="small" variant="outlined" sx={{ height: 20 }} /></TableCell>
                    <TableCell align="center">{f.required ? "yes" : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Section>

      <Section title={`Rules (${rules.length})`}>
        {rules.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>No rules recorded.</Typography>
        ) : (
          <Box>
            {rules.map((r, i) => (
              <Box key={i} sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: "divider", "&:last-child": { borderBottom: 0 } }}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                  <Typography variant="caption" sx={{ fontFamily: "monospace" }}>{r.rule_id}</Typography>
                  <Chip
                    size="small"
                    label={r.severity}
                    color={r.severity === "HIGH" ? "error" : r.severity === "MEDIUM" ? "warning" : "info"}
                    sx={{ height: 18, fontSize: "0.65rem" }}
                  />
                  {r.invented && <Chip size="small" label="invented" color="primary" variant="outlined" sx={{ height: 18, fontSize: "0.65rem" }} />}
                </Stack>
                <Typography variant="body2">{r.message || "—"}</Typography>
                <Box component="pre" sx={{ fontSize: "0.7rem", color: "text.secondary", whiteSpace: "pre-wrap", wordBreak: "break-all", m: 0, mt: 0.5 }}>
                  {r.expression}
                </Box>
              </Box>
            ))}
          </Box>
        )}
      </Section>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Box sx={{ borderTop: 1, borderColor: "divider" }}>
      <Typography
        variant="caption"
        sx={{
          display: "block",
          px: 2, py: 1,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          fontWeight: 600,
          color: "text.secondary",
          bgcolor: "action.hover",
        }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Auto-packs
// ─────────────────────────────────────────────────────────────────────────────
function AutoPacksTab({
  q, refetch,
}: { q: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.listAutoPacks>>>>; refetch: () => void }) {
  if (q.isLoading) return <LoadingTable rows={3} />;
  if (q.isError) return <Alert severity="error">{(q.error as Error).message}</Alert>;
  const proposals = q.data?.proposals || [];
  if (!proposals.length) {
    return <EmptyTab title="No pending pack proposals" subtitle="Auto-discovered vendors surface here for one-click promotion." />;
  }
  return (
    <Stack spacing={2}>
      {proposals.map((p) => (
        <Card key={p.id} variant="outlined" sx={{ p: 2 }}>
          <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} justifyContent="space-between" spacing={2}>
            <Box>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                <Typography variant="body1" sx={{ fontWeight: 600 }}>{p.vendor_name}</Typography>
                <Chip size="small" label={p.vendor_slug} variant="outlined" sx={{ fontFamily: "monospace", height: 20 }} />
                {p.doc_type_hint && <Chip size="small" label={p.doc_type_hint} color="info" variant="outlined" sx={{ height: 20 }} />}
              </Stack>
              <Typography variant="caption" color="text.secondary">
                Seen {p.sighting_count}× · first sighting {new Date(p.created_at).toLocaleString()}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button
                variant="contained"
                size="small"
                onClick={async () => { await api.promoteAutoPack(p.id); refetch(); }}
              >
                Promote
              </Button>
              <Button
                variant="outlined"
                size="small"
                onClick={async () => { await api.rejectAutoPack(p.id); refetch(); }}
              >
                Reject
              </Button>
            </Stack>
          </Stack>
        </Card>
      ))}
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tenant facts
// ─────────────────────────────────────────────────────────────────────────────
function FactsTab({
  q,
}: { q: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.listTenantFacts>>>> }) {
  if (q.isLoading) return <LoadingTable rows={5} />;
  if (q.isError) return <Alert severity="error">{(q.error as Error).message}</Alert>;
  const facts = q.data?.facts || [];
  if (!facts.length) {
    return <EmptyTab title="No facts yet" subtitle="Facts populate automatically as the platform extracts documents." />;
  }
  // Group by fact_type for visual separation
  const byType: Record<string, typeof facts> = {};
  for (const f of facts) (byType[f.fact_type] ??= []).push(f);
  return (
    <Stack spacing={2.5}>
      {Object.entries(byType).map(([type, items]) => (
        <Card key={type} variant="outlined">
          <Box sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: "divider", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <Box>
              <Typography variant="body1" sx={{ fontWeight: 600, fontFamily: "monospace", fontSize: "0.8rem" }}>{type}</Typography>
              <Typography variant="caption" color="text.secondary">{items.length} fact{items.length === 1 ? "" : "s"}</Typography>
            </Box>
          </Box>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: "30%" }}>Key</TableCell>
                  <TableCell>Value</TableCell>
                  <TableCell align="right">Conf.</TableCell>
                  <TableCell align="right">Sightings</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: "0.75rem" }}>{f.key}</TableCell>
                    <TableCell>{f.value}</TableCell>
                    <TableCell align="right">{(f.confidence * 100).toFixed(0)}%</TableCell>
                    <TableCell align="right">{f.sighting_count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      ))}
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Handlers
// ─────────────────────────────────────────────────────────────────────────────
function HandlersTab({
  q,
}: { q: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.listHandlers>>>> }) {
  if (q.isLoading) return <LoadingTable rows={2} />;
  if (q.isError) return <Alert severity="error">{(q.error as Error).message}</Alert>;
  const handlers = q.data?.handlers || [];
  if (!handlers.length) {
    return <EmptyTab title="No handlers registered" subtitle="Register handlers in mdi.handlers to make them invokable from chat or patterns." />;
  }
  return (
    <Stack spacing={2}>
      {handlers.map((h) => (
        <Card key={h.handler_id} variant="outlined" sx={{ p: 2 }}>
          <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 1 }}>
            <Typography variant="body1" sx={{ fontWeight: 600, fontFamily: "monospace", fontSize: "0.875rem" }}>
              {h.handler_id}
            </Typography>
            <Chip label="handler" size="small" color="primary" variant="outlined" sx={{ height: 20 }} />
          </Stack>
          <Typography variant="body2">{h.description}</Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
            <Box component="strong" sx={{ color: "text.primary" }}>When to use:</Box> {h.when_to_use}
          </Typography>
          <Box sx={{ mt: 2 }}>
            <HandlerRunner handler={h} />
          </Box>
        </Card>
      ))}
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared
// ─────────────────────────────────────────────────────────────────────────────
function LoadingTable({ rows = 3 }: { rows?: number }) {
  return (
    <Stack spacing={1.5} sx={{ p: 2 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <Stack key={i} direction="row" spacing={2} alignItems="center">
          <Skeleton width="20%" />
          <Skeleton sx={{ flex: 1 }} />
          <Skeleton width={80} />
        </Stack>
      ))}
    </Stack>
  );
}

function EmptyTab({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <Box sx={{ textAlign: "center", py: 6 }}>
      <Sparkles size={28} style={{ opacity: 0.3, marginBottom: 12 }} />
      <Typography variant="h4">{title}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: 460, mx: "auto" }}>
        {subtitle}
      </Typography>
    </Box>
  );
}
