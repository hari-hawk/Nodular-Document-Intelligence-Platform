"use client";

import { Brain, LayoutGrid, MessageSquare, Moon, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { clearAuth, isAuthed } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Badge, Button, Logomark } from "./ui";
import { ChatDrawer } from "./chat-drawer";

/**
 * Three-route shell, plus a chat drawer that slides in from the right
 * edge of any page. The sidebar is intentionally narrow (icons + small
 * labels) — analysts spend most screen time on the page body, not the
 * nav, so we save horizontal real-estate.
 *
 * Auth guard: routes are client-side gated. If localStorage doesn't
 * have an admin key OR an api key set, we bounce back to /.
 */
const NAV = [
  { href: "/workspace", label: "Workspace", icon: LayoutGrid,
    sub: "Upload · Results · Review" },
  { href: "/brain", label: "Brain", icon: Brain,
    sub: "Patterns · Facts · Packs · Handlers" },
  { href: "/admin", label: "Admin", icon: Settings,
    sub: "Tenants · Spend · Settings" },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [chatOpen, setChatOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  // Theme — keep React state in sync with what ThemeBoot put on <html>.
  useEffect(() => {
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);

  const toggleTheme = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    try { window.localStorage.setItem("mdi.theme", next); } catch { /* ignore */ }
    setTheme(next);
  }, [theme]);

  // Bounce to login if we ended up here without credentials.
  useEffect(() => {
    if (!isAuthed() && pathname !== "/") {
      router.replace("/");
    }
  }, [pathname, router]);

  const onSignOut = useCallback(() => {
    clearAuth();
    router.replace("/");
  }, [router]);

  return (
    <div className="flex h-screen">
      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      <aside
        className={cn(
          "w-64 shrink-0 border-r border-[rgb(var(--border))]",
          "bg-[rgb(var(--surface))] flex flex-col",
        )}
      >
        <div className="h-14 flex items-center px-5 border-b border-[rgb(var(--border))]">
          <Logomark className="mr-2" />
          <div className="font-semibold tracking-tight">
            MDI<span className="text-brand-500">.</span>
          </div>
          <Badge tone="brand" className="ml-2 text-[10px]">v0.1</Badge>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = pathname?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-start gap-3 rounded-md px-3 py-2.5 text-sm transition-colors",
                  active
                    ? "bg-brand-50 dark:bg-brand-900/30 text-brand-700 dark:text-brand-200"
                    : "text-[rgb(var(--fg-muted))] hover:bg-[rgb(var(--surface-muted))] hover:text-[rgb(var(--fg))]",
                )}
              >
                <Icon className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-medium">{item.label}</div>
                  <div className="text-xs text-[rgb(var(--fg-muted))] mt-0.5">
                    {item.sub}
                  </div>
                </div>
              </Link>
            );
          })}
        </nav>

        <div className="p-3 border-t border-[rgb(var(--border))] space-y-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            onClick={() => setChatOpen(true)}
          >
            <MessageSquare className="h-4 w-4" />
            Ask the brain
          </Button>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="flex-1 justify-center"
              onClick={toggleTheme}
              aria-label="Toggle theme"
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              className="flex-1"
              onClick={onSignOut}
            >
              Sign out
            </Button>
          </div>
        </div>
      </aside>

      {/* ── Main ────────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-6 py-8">{children}</div>
      </main>

      <ChatDrawer open={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
