"use client";

import { Box, Card, CardContent, Skeleton, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";

/**
 * KPI tile — the dashboard-style stat card pattern common across SaaS
 * products (Linear, Vercel, Stripe). One number, one label, an optional
 * trend or icon. Surfaces best on a horizontal Grid at the top of any
 * data-heavy page.
 *
 * Accessibility:
 *   - The semantic role is "group" with an aria-label so screen readers
 *     announce the tile as one unit rather than dropping the relationship
 *     between the value and its label.
 *   - Loading skeletons preserve the same vertical footprint so the
 *     page doesn't shift on data arrival (CLS = 0).
 */
export function KpiTile({
  label,
  value,
  caption,
  icon,
  loading,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  caption?: ReactNode;
  icon?: ReactNode;
  loading?: boolean;
  tone?: "default" | "success" | "warning" | "danger" | "info";
}) {
  const toneColor = {
    default: "primary.main",
    success: "success.main",
    warning: "warning.main",
    danger:  "error.main",
    info:    "secondary.main",
  }[tone];

  return (
    <Card
      role="group"
      aria-label={`${label}: ${typeof value === "string" || typeof value === "number" ? value : ""}`}
      sx={{
        height: "100%",
        position: "relative",
        overflow: "hidden",
        transition: "transform .15s ease, box-shadow .15s ease",
        "&:hover": {
          transform: "translateY(-1px)",
          boxShadow: 1,
        },
      }}
    >
      <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
        <Stack direction="row" spacing={2} alignItems="flex-start">
          {icon && (
            <Box
              sx={{
                width: 36, height: 36, flexShrink: 0,
                borderRadius: 2,
                bgcolor: (theme) => theme.palette.mode === "dark"
                  ? `${toneColor}22` : `${toneColor}15`,
                color: toneColor,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {icon}
            </Box>
          )}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ fontWeight: 500, fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.04em" }}
            >
              {label}
            </Typography>
            {loading ? (
              <Skeleton width="60%" height={32} />
            ) : (
              <Typography
                variant="h2"
                sx={{ mt: 0.5, fontWeight: 700, lineHeight: 1.1, fontSize: "1.625rem" }}
              >
                {value}
              </Typography>
            )}
            {caption && !loading && (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: "block", mt: 0.5 }}
              >
                {caption}
              </Typography>
            )}
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}
