"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { setAuth } from "@/lib/api";
import { Button, Card, CardBody, CardDescription, CardHeader, CardTitle, Input } from "./ui";

/**
 * Login surface. There's no real auth yet — for local dev the user
 * provides their admin key + (optionally) an API key for tenant routes.
 * Both go to localStorage and the API client attaches them on every
 * subsequent request.
 *
 * v2 will add OAuth + a session cookie + a real /me endpoint. For now
 * this matches Digital-Direction's `dd2026` passphrase pattern and is
 * deliberately not a security boundary — the API itself is the source
 * of truth on what's reachable.
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
    <div className="min-h-screen flex items-center justify-center p-6 bg-[rgb(var(--bg))]">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="flex items-center gap-2">
            <div className="text-xl font-semibold tracking-tight">
              MDI<span className="text-brand-500">.</span>
            </div>
            <CardTitle className="m-0">Sign in</CardTitle>
          </div>
          <CardDescription>
            Local-dev sign-in. Use the admin key for admin endpoints, or an
            API key for tenant endpoints. Both are stored in your browser
            only.
          </CardDescription>
        </CardHeader>
        <CardBody>
          <form onSubmit={onSubmit} className="space-y-3">
            <label className="block">
              <span className="text-sm font-medium">Admin key</span>
              <Input
                type="password"
                placeholder="local-dev-admin-key"
                value={adminKey}
                onChange={(e) => setAdminKey(e.target.value)}
                className="mt-1"
                autoFocus
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium">API key <span className="text-[rgb(var(--fg-muted))] font-normal">(optional)</span></span>
              <Input
                type="password"
                placeholder="paste your tenant API key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="mt-1"
              />
            </label>
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={submitting || (!adminKey && !apiKey)}
            >
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
