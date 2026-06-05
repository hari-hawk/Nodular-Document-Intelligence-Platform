"use client";

import {
  Alert, Avatar, Box, Button, Card, CardContent, Stack,
  TextField, Typography,
} from "@mui/material";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { setAuth } from "@/lib/api";

/**
 * Login surface. Local-dev sign-in via admin key + optional tenant
 * API key. Stored in localStorage; no real auth boundary (the API is
 * the source of truth on what's reachable).
 *
 * Accessibility:
 *   - Real form semantics: <form onSubmit>, real <label> via TextField,
 *     Enter submits.
 *   - autoComplete="off" + type="password" on both fields so password
 *     managers don't aggressively offer to save the local-dev values.
 *   - The disabled state on submit is reflected in aria-disabled
 *     automatically by MUI.
 */
export function LoginScreen() {
  const router = useRouter();
  const [adminKey, setAdminKey] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!adminKey && !apiKey) return;
    setSubmitting(true);
    setAuth({ adminKey: adminKey || undefined, apiKey: apiKey || undefined });
    router.replace("/workspace");
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 3,
        background: (t) => t.palette.mode === "dark"
          ? "radial-gradient(circle at 30% 20%, rgba(99,102,241,.15), transparent 50%), radial-gradient(circle at 80% 80%, rgba(14,165,233,.10), transparent 50%), #020617"
          : "radial-gradient(circle at 30% 20%, rgba(99,102,241,.10), transparent 50%), radial-gradient(circle at 80% 80%, rgba(14,165,233,.08), transparent 50%), #F8FAFC",
      }}
    >
      <Card sx={{ maxWidth: 460, width: "100%", boxShadow: 4 }}>
        <CardContent sx={{ p: 4 }}>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 3 }}>
            <Avatar
              variant="rounded"
              sx={{
                width: 44, height: 44,
                background: "linear-gradient(135deg, #6366F1, #4338CA)",
                fontSize: "1.125rem", fontWeight: 700,
              }}
            >
              M
            </Avatar>
            <Box>
              <Typography variant="h3" sx={{ fontWeight: 700 }}>
                MDI<Box component="span" sx={{ color: "primary.main" }}>.</Box>
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Document Intelligence Platform
              </Typography>
            </Box>
          </Stack>

          <Typography variant="h4" sx={{ mb: 1, fontWeight: 600 }}>
            Sign in
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Local-dev sign-in. Use the admin key for admin endpoints, or an
            API key for tenant endpoints. Both are stored in your browser only.
          </Typography>

          <Box component="form" onSubmit={onSubmit}>
            <Stack spacing={2}>
              <TextField
                label="Admin key"
                type="password"
                value={adminKey}
                onChange={(e) => setAdminKey(e.target.value)}
                placeholder="local-dev-admin-key"
                fullWidth
                autoFocus
                autoComplete="off"
                helperText="Grants access to /admin endpoints and cross-tenant views."
              />
              <TextField
                label="API key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="paste your tenant API key (optional)"
                fullWidth
                autoComplete="off"
                helperText="Scopes the UI to one tenant's data. Created via Admin → Tenants."
              />
              {!adminKey && !apiKey && (
                <Alert severity="info" sx={{ py: 0.5 }}>
                  Provide at least one key to continue.
                </Alert>
              )}
              <Button
                type="submit"
                variant="contained"
                size="large"
                disabled={submitting || (!adminKey && !apiKey)}
                sx={{ py: 1.25 }}
              >
                {submitting ? "Signing in…" : "Sign in"}
              </Button>
            </Stack>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
