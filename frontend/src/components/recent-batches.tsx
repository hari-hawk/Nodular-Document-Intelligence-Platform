"use client";

import {
  Alert, Box, Card, CardContent, Chip, Divider, Skeleton, Stack, Typography,
} from "@mui/material";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ChevronRight, Clock, FileStack, Sparkles } from "lucide-react";

import { api, type BatchReport, type BatchSummary } from "@/lib/api";

/**
 * Recent batches — MUI list, click any row to load the report.
 *
 * Visual rhythm (8px grid):
 *   - Card outer padding: 24 (p=3)
 *   - Header to list gap:  16 (mt=2)
 *   - Row vertical pad:    20 (py=2.5)
 *   - Row horizontal pad:  24 (px=3)
 *   - Row internal gap:    16 (gap=2)
 *   - Meta-pill gap:        8 (gap=1)
 *
 * Each row is a button with:
 *   - Strong "Open" affordance: ChevronRight on the right edge that
 *     becomes more prominent on hover so users see clicking opens a
 *     view (matches mobile-detail-disclosure pattern).
 *   - Hover state: background tint + chevron color shift.
 *   - Active state (currently selected): brand-tinted bg + brand chevron.
 *   - Focus-visible: 2px primary ring offset -2px (WCAG 2.4.7).
 *
 * Accessibility:
 *   - role="listbox" + role="option" + aria-selected on each row.
 *   - Each row is a real <button> so Tab + Enter work.
 *   - aria-label includes filename / batch context.
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
    // Retry once with a 1s backoff — covers a transient backend hiccup
    // without keeping skeleton bars visible for 30+ seconds.
    retry: 1,
    retryDelay: 1_000,
    // Don't refetch the list every time the window regains focus —
    // analysts often tab back from a doc viewer; refetch is wasted.
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  if (q.isLoading) {
    return (
      <Card>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h3" sx={{ mb: 2 }}>Recent batches</Typography>
          <Stack spacing={2}>
            {Array.from({ length: 3 }).map((_, i) => (
              <Stack key={i} direction="row" spacing={2} alignItems="center">
                <Skeleton variant="circular" width={32} height={32} />
                <Box sx={{ flex: 1 }}>
                  <Skeleton width="70%" />
                  <Skeleton width="40%" sx={{ mt: 0.5 }} />
                </Box>
              </Stack>
            ))}
          </Stack>
        </CardContent>
      </Card>
    );
  }

  if (q.isError) {
    const msg = (q.error as Error).message;
    const is401 = /\b401\b/.test(msg);
    const isTimeout = /timed out|backend is running|Network error/i.test(msg);
    if (is401) {
      return (
        <Card>
          <CardContent sx={{ textAlign: "center", py: 8 }}>
            <FileStack size={28} style={{ opacity: 0.3, marginBottom: 16 }} />
            <Typography variant="h4">Sign in to see your batches</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: 480, mx: "auto" }}>
              Provide a tenant API key on the sign-in page to see this tenant&apos;s
              batches, OR an admin key to see batches across all tenants.
            </Typography>
          </CardContent>
        </Card>
      );
    }
    if (isTimeout) {
      return (
        <Alert
          severity="warning"
          icon={<AlertCircle size={18} />}
          action={
            <Box
              component="button"
              onClick={() => q.refetch()}
              sx={{
                border: 0, bgcolor: "transparent", cursor: "pointer",
                color: "primary.main", fontWeight: 600, fontSize: 13,
                "&:hover": { textDecoration: "underline" },
              }}
            >
              Retry
            </Box>
          }
        >
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            Backend isn&apos;t responding.
          </Typography>
          <Typography variant="caption" sx={{ display: "block", mt: 0.5 }}>
            The API at <code>/api/batches</code> didn&apos;t reply within 15s. Check
            that <code>mdi-server</code> is running on its expected port, then click
            Retry above. {msg}
          </Typography>
        </Alert>
      );
    }
    return (
      <Alert severity="error" icon={<AlertCircle size={18} />}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>Couldn&apos;t load recent batches.</Typography>
        <Typography variant="caption">{msg}</Typography>
      </Alert>
    );
  }

  const batches = q.data?.batches || [];
  const authMode = q.data?.auth_mode;

  if (batches.length === 0) {
    return (
      <Card>
        <CardContent sx={{ textAlign: "center", py: 8 }}>
          <FileStack size={28} style={{ opacity: 0.3, marginBottom: 16 }} />
          <Typography variant="h4">No batches yet</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Upload some documents above. Past batches will appear here once processed.
          </Typography>
        </CardContent>
      </Card>
    );
  }

  const loadAndSelect = async (b: BatchSummary) => {
    const cached = queryClient.getQueryData<BatchReport>(["report", b.id]);
    if (cached) { onSelect(cached, b); return; }
    const fetched = await queryClient.fetchQuery<BatchReport>({
      queryKey: ["report", b.id],
      queryFn: () => api.getReport(b.id),
    });
    onSelect(fetched, b);
  };

  return (
    <Card>
      <CardContent sx={{ p: 0 }}>
        {/* Header row — 24px outer padding, 16px below */}
        <Box sx={{ p: 3, pb: 2 }}>
          <Stack
            direction="row"
            alignItems="flex-start"
            justifyContent="space-between"
            spacing={2}
          >
            <Box sx={{ flex: 1 }}>
              <Typography variant="h3">Recent batches</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {authMode === "admin"
                  ? "Admin view — across all tenants. Click any row to load."
                  : "Click any row below to load its results."}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} alignItems="center">
              {authMode === "admin" && (
                <Chip label="admin view" color="primary" size="small" variant="outlined" />
              )}
              <Chip
                label={`${batches.length}`}
                size="small"
                sx={{ fontWeight: 600, minWidth: 32 }}
              />
            </Stack>
          </Stack>
        </Box>
        <Divider />
        {/* List — each row is a real button with consistent 24/20 padding */}
        <Box component="ul" role="listbox" aria-label="Recent batches" sx={{ listStyle: "none", m: 0, p: 0 }}>
          {batches.map((b, idx) => {
            const active = b.id === selectedId;
            return (
              <Box
                key={b.id}
                component="li"
                role="option"
                aria-selected={active}
                sx={{
                  borderBottom: idx < batches.length - 1 ? 1 : 0,
                  borderColor: "divider",
                }}
              >
                <Box
                  component="button"
                  onClick={() => loadAndSelect(b)}
                  aria-label={`Open batch ${b.id.slice(0, 8)} from ${formatRelative(b.started_at)}`}
                  sx={{
                    width: "100%",
                    px: 3, py: 2.5,
                    textAlign: "left",
                    border: 0,
                    bgcolor: active
                      ? (t) => t.palette.mode === "dark"
                        ? "rgba(99,102,241,.14)" : "rgba(99,102,241,.06)"
                      : "transparent",
                    cursor: "pointer",
                    transition: "background-color .15s ease",
                    display: "flex",
                    alignItems: "center",
                    gap: 2,
                    "&:hover": {
                      bgcolor: active
                        ? (t) => t.palette.mode === "dark"
                          ? "rgba(99,102,241,.18)" : "rgba(99,102,241,.10)"
                        : "action.hover",
                      "& .open-chevron": { transform: "translateX(2px)", opacity: 0.8 },
                    },
                    "&:focus-visible": {
                      outline: "2px solid",
                      outlineColor: "primary.main",
                      outlineOffset: -2,
                      bgcolor: "action.hover",
                    },
                  }}
                >
                  {/* Icon column */}
                  <Box sx={{ flexShrink: 0, color: active ? "primary.main" : "text.secondary", pt: 0.25 }}>
                    <FileStack size={20} />
                  </Box>

                  {/* Content column */}
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    {/* Row 1: id + tenant + timestamp */}
                    <Stack
                      direction="row"
                      alignItems="center"
                      justifyContent="space-between"
                      spacing={2}
                      sx={{ mb: 0.75 }}
                    >
                      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ minWidth: 0 }}>
                        <Typography
                          variant="caption"
                          sx={{ fontFamily: "monospace", fontWeight: 600, color: active ? "primary.main" : "text.primary" }}
                        >
                          {b.id.slice(0, 8)}…
                        </Typography>
                        {authMode === "admin" && b.tenant_id && (
                          <>
                            <Box component="span" sx={{ color: "text.disabled" }}>·</Box>
                            <Typography variant="caption" color="text.secondary">
                              tenant <Box component="span" sx={{ fontFamily: "monospace" }}>{b.tenant_id.slice(0, 8)}</Box>
                            </Typography>
                          </>
                        )}
                      </Stack>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: "flex", alignItems: "center", gap: 0.5, flexShrink: 0 }}
                      >
                        <Clock size={12} />
                        {formatRelative(b.started_at)}
                      </Typography>
                    </Stack>

                    {/* Row 2: narrator preview */}
                    {b.narrator_preview && (
                      <Typography
                        variant="body2"
                        sx={{
                          color: "text.primary",
                          lineHeight: 1.5,
                          mb: 1.5,
                          display: "-webkit-box",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                          overflow: "hidden",
                        }}
                      >
                        {b.narrator_preview}
                      </Typography>
                    )}

                    {/* Row 3: meta strip — proper 8px gaps */}
                    <Stack direction="row" alignItems="center" spacing={1.5} useFlexGap flexWrap="wrap">
                      <MetaItem>{b.total_documents} doc{b.total_documents === 1 ? "" : "s"}</MetaItem>
                      <MetaSeparator />
                      <MetaItem>${b.cost_usd.toFixed(4)}</MetaItem>
                      {b.anomaly_count > 0 && (
                        <>
                          <MetaSeparator />
                          <Chip
                            size="small"
                            color="error"
                            label={`${b.anomaly_count} anomal${b.anomaly_count === 1 ? "y" : "ies"}`}
                            sx={{ height: 22, fontSize: "0.7rem", fontWeight: 500 }}
                          />
                        </>
                      )}
                      {b.insight_count > 0 && (
                        <Chip
                          size="small"
                          color="info"
                          icon={<Sparkles size={11} />}
                          label={`${b.insight_count} insight${b.insight_count === 1 ? "" : "s"}`}
                          sx={{ height: 22, fontSize: "0.7rem", fontWeight: 500, "& .MuiChip-icon": { ml: 0.5 } }}
                        />
                      )}
                    </Stack>
                  </Box>

                  {/* Open chevron — strong affordance that this is clickable */}
                  <Box
                    className="open-chevron"
                    sx={{
                      flexShrink: 0,
                      color: active ? "primary.main" : "text.disabled",
                      opacity: active ? 1 : 0.5,
                      transition: "transform .15s ease, opacity .15s ease",
                    }}
                  >
                    <ChevronRight size={20} />
                  </Box>
                </Box>
              </Box>
            );
          })}
        </Box>
      </CardContent>
    </Card>
  );
}

function MetaItem({ children }: { children: React.ReactNode }) {
  return (
    <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: "tabular-nums" }}>
      {children}
    </Typography>
  );
}

function MetaSeparator() {
  return (
    <Box component="span" aria-hidden sx={{ color: "text.disabled", lineHeight: 1 }}>·</Box>
  );
}

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
