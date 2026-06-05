"use client";

import "@fontsource/inter/300.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";

import { CssBaseline, ThemeProvider } from "@mui/material";
import { AppRouterCacheProvider } from "@mui/material-nextjs/v15-appRouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { darkTheme, lightTheme } from "@/theme";

/**
 * Providers stack — order matters:
 *   1. AppRouterCacheProvider: emotion-cache integration with Next.js App
 *      Router. Without this, MUI styles inject AFTER hydration → visible
 *      flash. The provider injects them inline during SSR so the first
 *      paint is styled.
 *   2. ThemeProvider: feeds the brand-coloured theme into every MUI
 *      component. Re-reads the `dark` class on <html> so the theme
 *      tracks the existing dark-mode toggle.
 *   3. CssBaseline: MUI's normalising stylesheet. Ours runs BEFORE
 *      Tailwind's preflight so Tailwind utilities still win in
 *      cascade ties (which is what we want — Tailwind is the
 *      primary styling layer, MUI is layered on for primitives).
 *   4. QueryClientProvider: data-fetching cache, shared across pages.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({
      defaultOptions: {
        queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
        mutations: { retry: 0 },
      },
    }),
  );

  // Watch the `dark` class on <html> so MUI's theme tracks the existing
  // toggle. MutationObserver fires on any class-list change.
  const [mode, setMode] = useState<"light" | "dark">("light");
  useEffect(() => {
    const root = document.documentElement;
    setMode(root.classList.contains("dark") ? "dark" : "light");
    const obs = new MutationObserver(() => {
      setMode(root.classList.contains("dark") ? "dark" : "light");
    });
    obs.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  const theme = mode === "dark" ? darkTheme : lightTheme;

  return (
    <AppRouterCacheProvider options={{ enableCssLayer: true }}>
      <ThemeProvider theme={theme}>
        <CssBaseline enableColorScheme />
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </ThemeProvider>
    </AppRouterCacheProvider>
  );
}
