import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { ThemeBoot } from "@/components/theme-boot";

export const metadata: Metadata = {
  title: "MDI — Modular Data Intelligence",
  description: "Document intelligence platform with knowledge-graph backbone.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <ThemeBoot />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
