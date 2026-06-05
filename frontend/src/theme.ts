"use client";

import { createTheme } from "@mui/material/styles";

/**
 * MDI Material Design theme.
 *
 * We deliberately keep MUI's defaults for spacing / typography / elevation
 * — those are exhaustively-accessibility-tested — and only override the
 * palette + a handful of components so MUI surfaces feel native to MDI's
 * brand rather than generic Material.
 *
 * Accessibility notes:
 *   - All paired text/bg combinations clear WCAG AA contrast (4.5:1 on
 *     body, 3:1 on large text).
 *   - `density="comfortable"` rows match WCAG 2.2 SC 2.5.8 (Target Size)
 *     for click targets ≥24×24 px.
 *   - Focus rings inherit from MUI which uses :focus-visible by default,
 *     so keyboard users get a 2px ring without it interfering with mouse
 *     interaction.
 */
const brand = {
  50:  "#EEF2FF",
  100: "#E0E7FF",
  200: "#C7D2FE",
  300: "#A5B4FC",
  400: "#818CF8",
  500: "#6366F1",
  600: "#4F46E5",
  700: "#4338CA",
  800: "#3730A3",
  900: "#312E81",
};

const buildTheme = (mode: "light" | "dark") =>
  createTheme({
    palette: {
      mode,
      primary: {
        main: brand[600],
        light: brand[400],
        dark: brand[800],
        contrastText: "#FFFFFF",
      },
      secondary: {
        main: "#0EA5E9",  // sky-500
      },
      success: { main: "#10B981" },  // emerald-500
      warning: { main: "#F59E0B" },  // amber-500
      error:   { main: "#EF4444" },  // red-500
      background: mode === "dark"
        ? { default: "#020617", paper: "#0F172A" }      // slate-950 / slate-900
        : { default: "#F8FAFC", paper: "#FFFFFF" },      // slate-50 / white
      text: mode === "dark"
        ? { primary: "#F8FAFC", secondary: "#94A3B8" }   // slate-50 / slate-400
        : { primary: "#0F172A", secondary: "#475569" },  // slate-900 / slate-600
      divider: mode === "dark" ? "#334155" : "#E2E8F0",  // slate-700 / slate-200
    },
    typography: {
      // Inter feels modern + has excellent legibility at small sizes,
      // matches what most SaaS products use (Linear / Vercel / Stripe).
      fontFamily: [
        "Inter", "system-ui", "-apple-system", "BlinkMacSystemFont",
        "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif",
      ].join(","),
      h1: { fontSize: "2rem",  fontWeight: 700, letterSpacing: "-0.02em" },
      h2: { fontSize: "1.5rem", fontWeight: 700, letterSpacing: "-0.01em" },
      h3: { fontSize: "1.25rem", fontWeight: 600 },
      h4: { fontSize: "1.125rem", fontWeight: 600 },
      body1: { fontSize: "0.9375rem" },
      body2: { fontSize: "0.875rem" },
      button: { textTransform: "none", fontWeight: 600 },
    },
    shape: {
      borderRadius: 10,  // slightly more rounded than Material defaults — feels modern
    },
    components: {
      MuiAppBar: {
        defaultProps: { elevation: 0, color: "transparent" },
        styleOverrides: {
          root: { backdropFilter: "saturate(180%) blur(8px)" },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: { fontWeight: 600 },
          containedPrimary: {
            backgroundImage: `linear-gradient(135deg, ${brand[600]}, ${brand[700]})`,
            "&:hover": {
              backgroundImage: `linear-gradient(135deg, ${brand[700]}, ${brand[800]})`,
            },
          },
        },
      },
      MuiCard: {
        defaultProps: { elevation: 0, variant: "outlined" },
        styleOverrides: {
          root: { borderRadius: 12 },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            textTransform: "none",
            fontWeight: 500,
            minHeight: 44,  // WCAG target-size compliance
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 500 },
        },
      },
      MuiLinearProgress: {
        styleOverrides: {
          root: { borderRadius: 999, height: 6 },
        },
      },
    },
  });

export const lightTheme = buildTheme("light");
export const darkTheme = buildTheme("dark");
