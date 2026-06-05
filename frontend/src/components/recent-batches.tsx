"use client";

import {
  Alert, Box, Card, CardContent, Chip, Skeleton, Stack, Typography,
} from "@mui/material";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Clock, FileStack, Sparkles } from "lucide-react";

import { api, type BatchReport, type BatchSummary } from "@/lib/api";

/**
 * Recent batches list — MUI-styled. Each row is an actionable card-row
 * with the document count, cost, and severity chips.
 *
 * Accessibility:
 *   - Each row is a real <button> so keyboard users tab through and
 *     Enter / Space activates the row.
 *   - The selected row has aria-selected="true" so SR users hear the
 *     state change.
 *   - Loading skeletons preserve the layout footprint (no CLS).
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
  });

  if (q.isLoading) {
    return (
      <Card>
        <CardContent>
          <Typography variant="h3" sx={{ mb: 1 }}>Recent batches</Typography>
          <Stack spacing={1.5}>
            {Array.from({ length: 3 }).map((_, i) => (
              <Stack key={i} direction="row" spacing={2} alignItems="center">
                <Skeleton variant="circular" width={32} height={32} />
                <Box sx={{ flex: 1 }}>
                  <Skeleton width="70%" />
                  <Skeleton width="40%" />
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
    if (is401) {
      return (
        <Card>
          <CardContent sx={{ textAlign: "center", py: 6 }}>
            <FileStack size={28} style={{ opacity: 0.3, marginBottom: 12 }} />
            <Typography variant="h4">Sign in to see your batches</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: 460, mx: "auto" }}>
              Provide a tenant API key on the sign-in page to see this tenant&apos;s
              batches, OR an admin key to see batches across all tenants. (You can
              create a tenant + key from Admin → Tenants.)
            </Typography>
          </CardContent>
        </Card>
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
        <CardContent sx={{ textAlign: "center", py: 6 }}>
          <FileStack size={28} style={{ opacity: 0.3, marginBottom: 12 }} />
          <Typography variant="h4">No batches yet</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Upload some documents above. Past batches will appear here once they finish processing.
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
        <Box sx={{ p: 3, pb: 2 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between">
            <Box>
              <Typography variant="h3">Recent batches</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
                {authMode === "admin"
                  ? "Admin view — across all tenants. Click any row to load."
                  : "Click a batch to load its results below."}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              {authMode === "admin" && <Chip label="admin view" color="primary" size="small" variant="outlined" />}
              <Chip label={batches.length} size="small" variant="outlined" />
            </Stack>
          </Stack>
        </Box>
        <Box component="ul" role="listbox" aria-label="Recent batches" sx={{ listStyle: "none", m: 0, p: 0 }}>
          {batches.map((b) => {
            const active = b.id === selectedId;
            return (
              <Box
                key={b.id}
                component="li"
                role="option"
                aria-selected={active}
                sx={{ borderTop: 1, borderColor: "divider" }}
              >
                <Box
                  component="button"
                  onClick={() => loadAndSelect(b)}
                  sx={{
                    width: "100%",
                    textAlign: "left",
                    border: 0,
                    bgcolor: active
                      ? (t) => t.palette.mode === "dark" ? "rgba(99,102,241,.12)" : "rgba(99,102,241,.06)"
                      : "transparent",
                    cursor: "pointer",
                    p: 2.5,
                    transition: "background-color .12s",
                    "&:hover": { bgcolor: "action.hover" },
                  }}
                >
                  <Stack direction="row" spacing={2} alignItems="flex-start">
                    <Box sx={{ pt: 0.5 }}>
                      <FileStack size={18} color={active ? "var(--mui-palette-primary-main)" : undefined} />
                    </Box>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Stack direction="row" justifyContent="space-between" alignItems="baseline" sx={{ gap: 1, mb: 0.25 }}>
                        <Typography variant="caption" sx={{ fontFamily: "monospace" }}>
                          {b.id.slice(0, 8)}…
                          {authMode === "admin" && b.tenant_id && (
                            <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                              · tenant {b.tenant_id.slice(0, 8)}
                            </Typography>
                          )}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                          <Clock size={12} />
                          {formatRelative(b.started_at)}
                        </Typography>
                      </Stack>
                      {b.narrator_preview && (
                        <Typography
                          variant="body2"
                          sx={{
                            mt: 0.5,
                            display: "-webkit-box",
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: "vertical",
                            overflow: "hidden",
                          }}
                        >
                          {b.narrator_preview}
                        </Typography>
                      )}
                      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary">
                          {b.total_documents} doc{b.total_documents === 1 ? "" : "s"}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">·</Typography>
                        <Typography variant="caption" color="text.secondary">${b.cost_usd.toFixed(4)}</Typography>
                        {b.anomaly_count > 0 && (
                          <Chip size="small" color="error" label={`${b.anomaly_count} anomal${b.anomaly_count === 1 ? "y" : "ies"}`} sx={{ height: 18, fontSize: "0.65rem" }} />
                        )}
                        {b.insight_count > 0 && (
                          <Chip
                            size="small"
                            color="info"
                            icon={<Sparkles size={10} />}
                            label={b.insight_count}
                            sx={{ height: 18, fontSize: "0.65rem", "& .MuiChip-icon": { ml: 0.5 } }}
                          />
                        )}
                      </Stack>
                    </Box>
                  </Stack>
                </Box>
              </Box>
            );
          })}
        </Box>
      </CardContent>
    </Card>
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
