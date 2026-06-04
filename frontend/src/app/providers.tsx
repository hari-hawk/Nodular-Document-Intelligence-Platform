"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

/**
 * QueryClient lives at the app root so every page shares the cache
 * (recent batches list stays warm when you visit Brain and come back).
 *
 * defaultOptions:
 *   - staleTime 30s — lists like /admin/spend or /admin/tenant-facts
 *     don't change second-to-second, and aggressive refetch wastes a
 *     round-trip.
 *   - retry 1 — the API is on localhost; transient network failures
 *     are unusual and bouncing a 5xx three times just delays the
 *     error UI.
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
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
