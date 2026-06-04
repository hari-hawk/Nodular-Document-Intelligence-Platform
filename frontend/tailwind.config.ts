import type { Config } from "tailwindcss";

/**
 * MDI design tokens. Two intentional choices worth calling out:
 *
 * 1. We target `darkMode: 'class'` rather than `media`, so the theme is a
 *    user preference (persisted in localStorage by the app-shell), not an
 *    OS pref. Demo environments need to look the same regardless of the
 *    presenter's laptop settings.
 * 2. The brand palette is a small set of indigo/slate values — the same
 *    tokens DD uses, so a future merge of the two surfaces costs nothing.
 */
const config: Config = {
  content: [
    "./src/**/*.{ts,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#EEF2FF",
          100: "#E0E7FF",
          200: "#C7D2FE",
          300: "#A5B4FC",
          400: "#818CF8",
          500: "#6366F1",
          600: "#4F46E5",
          700: "#4338CA",
          800: "#3730A3",
          900: "#312E81",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system", "BlinkMacSystemFont", "Segoe UI",
          "Roboto", "Helvetica", "Arial", "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
