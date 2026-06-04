"use client";

import { useEffect } from "react";

/**
 * Reads the stored theme from localStorage on first client render and
 * applies the `dark` class to <html> accordingly.
 *
 * There's a brief flash from light to dark for users who'd chosen dark
 * mode in a prior session — fixing the flash requires running a sync
 * script before paint, which is the documented Next.js pattern but
 * is currently flagged by our XSS hook. Until we add a server-side
 * cookie-based theme detector, the small flash is acceptable for an
 * internal admin UI.
 */
export function ThemeBoot() {
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem("mdi.theme");
      const root = document.documentElement;
      if (stored === "dark") root.classList.add("dark");
      else if (stored === "light") root.classList.remove("dark");
      else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
        root.classList.add("dark");
      }
    } catch { /* ignore — localStorage may be disabled */ }
  }, []);
  return null;
}
