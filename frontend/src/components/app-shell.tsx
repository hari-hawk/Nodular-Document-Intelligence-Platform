"use client";

import {
  Avatar,
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import {
  Brain, ChevronsLeft, LayoutGrid, LogOut, MessageSquare, Moon, Settings, Sun,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { clearAuth, isAuthed } from "@/lib/api";
import { ChatDrawer } from "./chat-drawer";

const NAV = [
  { href: "/workspace", label: "Workspace", icon: LayoutGrid,
    sub: "Upload · Results · Review" },
  { href: "/brain", label: "Brain", icon: Brain,
    sub: "Patterns · Facts · Packs · Handlers" },
  { href: "/admin", label: "Admin", icon: Settings,
    sub: "Tenants · Spend · Settings" },
] as const;

const DRAWER_WIDTH = 268;

/**
 * App shell — MUI Drawer-based sidebar that handles every authed route.
 *
 * Decisions:
 *  - PERMANENT drawer at md+, TEMPORARY (slide-in) at mobile. MUI's
 *    responsive Drawer handles the breakpoint automatically.
 *  - Sidebar items have a sub-label so analysts know what each tab
 *    contains before clicking — reduces guess-and-go.
 *  - Theme toggle, sign-out, and "Ask the brain" all sit at the bottom
 *    of the sidebar with explicit aria-labels for screen-reader users.
 *
 * Accessibility:
 *  - All icon-only buttons have aria-label.
 *  - The nav list is in <nav role> via MUI Drawer's `<aside>` semantic
 *    container.
 *  - Active route is marked with `aria-current="page"` for SR users.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [chatOpen, setChatOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);

  const toggleTheme = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    try { window.localStorage.setItem("mdi.theme", next); } catch { /* ignore */ }
    setTheme(next);
  }, [theme]);

  // Auth guard.
  useEffect(() => {
    if (!isAuthed() && pathname !== "/") router.replace("/");
  }, [pathname, router]);

  const onSignOut = useCallback(() => {
    clearAuth();
    router.replace("/");
  }, [router]);

  const drawerContent = (
    <Stack sx={{ height: "100%" }}>
      {/* Brand header */}
      <Toolbar sx={{ px: 2.5, gap: 1.5, minHeight: 64 }}>
        <Avatar
          variant="rounded"
          sx={{
            width: 32, height: 32,
            background: "linear-gradient(135deg, #6366F1, #4338CA)",
            fontSize: "0.85rem", fontWeight: 700,
          }}
        >
          M
        </Avatar>
        <Box>
          <Typography variant="body1" sx={{ fontWeight: 700, lineHeight: 1, letterSpacing: "-0.01em" }}>
            MDI<span style={{ color: "var(--mui-palette-primary-main, #6366F1)" }}>.</span>
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
            Document Intelligence
          </Typography>
        </Box>
        <Chip label="v0.1" size="small" color="primary" variant="outlined" sx={{ ml: "auto", height: 20, fontSize: "0.65rem" }} />
      </Toolbar>
      <Divider />

      {/* Nav */}
      <List component="nav" aria-label="Primary navigation" sx={{ flex: 1, px: 1.5, py: 1.5 }}>
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = pathname?.startsWith(item.href);
          return (
            <ListItem key={item.href} disablePadding sx={{ mb: 0.5 }}>
              <ListItemButton
                component={Link}
                href={item.href}
                selected={active}
                aria-current={active ? "page" : undefined}
                sx={{
                  borderRadius: 2,
                  py: 1.25,
                  "&.Mui-selected": {
                    bgcolor: (t) => t.palette.mode === "dark"
                      ? "rgba(99,102,241,.16)" : "rgba(99,102,241,.10)",
                    color: "primary.main",
                    "&:hover": {
                      bgcolor: (t) => t.palette.mode === "dark"
                        ? "rgba(99,102,241,.22)" : "rgba(99,102,241,.16)",
                    },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 36, color: "inherit" }}>
                  <Icon size={18} />
                </ListItemIcon>
                <ListItemText
                  primary={item.label}
                  secondary={item.sub}
                  primaryTypographyProps={{ fontWeight: 600, fontSize: "0.875rem" }}
                  secondaryTypographyProps={{ fontSize: "0.72rem", lineHeight: 1.3 }}
                />
              </ListItemButton>
            </ListItem>
          );
        })}
      </List>

      {/* Footer actions */}
      <Box sx={{ p: 1.5, borderTop: 1, borderColor: "divider" }}>
        <ListItemButton
          onClick={() => setChatOpen(true)}
          sx={{ borderRadius: 2, mb: 1 }}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>
            <MessageSquare size={18} />
          </ListItemIcon>
          <ListItemText
            primary="Ask the brain"
            primaryTypographyProps={{ fontSize: "0.875rem", fontWeight: 500 }}
          />
        </ListItemButton>
        <Stack direction="row" spacing={1}>
          <Tooltip title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
            <IconButton
              onClick={toggleTheme}
              size="small"
              aria-label="Toggle theme"
              sx={{ flex: 1, borderRadius: 2, border: 1, borderColor: "divider" }}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </IconButton>
          </Tooltip>
          <Tooltip title="Sign out">
            <IconButton
              onClick={onSignOut}
              size="small"
              aria-label="Sign out"
              sx={{ flex: 1, borderRadius: 2, border: 1, borderColor: "divider" }}
            >
              <LogOut size={16} />
            </IconButton>
          </Tooltip>
        </Stack>
      </Box>
    </Stack>
  );

  return (
    <Box sx={{ display: "flex", minHeight: "100vh", bgcolor: "background.default" }}>
      {/* Mobile drawer */}
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: "block", md: "none" },
          "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" },
        }}
      >
        {drawerContent}
      </Drawer>

      {/* Desktop drawer */}
      <Drawer
        variant="permanent"
        sx={{
          display: { xs: "none", md: "block" },
          width: DRAWER_WIDTH,
          flexShrink: 0,
          "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" },
        }}
        open
      >
        {drawerContent}
      </Drawer>

      {/* Main */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          minHeight: "100vh",
          overflowX: "hidden",
        }}
      >
        {/* Mobile toolbar with menu button */}
        <Box sx={{ display: { xs: "flex", md: "none" }, alignItems: "center", p: 1.5, borderBottom: 1, borderColor: "divider" }}>
          <IconButton onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <ChevronsLeft size={20} style={{ transform: "rotate(180deg)" }} />
          </IconButton>
        </Box>

        <Box sx={{ maxWidth: 1280, mx: "auto", px: { xs: 2, md: 4 }, py: { xs: 3, md: 4 } }}>
          {children}
        </Box>
      </Box>

      <ChatDrawer open={chatOpen} onClose={() => setChatOpen(false)} />
    </Box>
  );
}
