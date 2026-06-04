import { AppShell } from "@/components/app-shell";

/**
 * Route-group layout. The parenthesised `(authed)` segment groups
 * /workspace, /brain, /admin under one shared shell without adding a
 * URL segment. That's why the URLs stay clean: /workspace not
 * /authed/workspace.
 */
export default function AuthedLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
