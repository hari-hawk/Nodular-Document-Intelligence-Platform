"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api";
import {
  Badge, Card, CardBody, CardDescription, CardHeader, CardTitle,
  EmptyState, Spinner, Tabs,
} from "@/components/ui";

/**
 * Admin — three tabs: Spend, Tenants, Settings. Rarely visited; the
 * page is intentionally less polished than Workspace because the
 * usage frequency is dramatically lower.
 */
type TabKey = "spend" | "tenants" | "settings";

export default function AdminPage() {
  const [tab, setTab] = useState<TabKey>("spend");

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
        <p className="text-sm text-[rgb(var(--fg-muted))] mt-1">
          Platform-level controls and reporting.
        </p>
      </header>

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as TabKey)}
        tabs={[
          { value: "spend", label: "Spend" },
          { value: "tenants", label: "Tenants" },
          { value: "settings", label: "Settings" },
        ]}
      />

      {tab === "spend" && <SpendTab />}
      {tab === "tenants" && <TenantsTab />}
      {tab === "settings" && <SettingsStub />}
    </div>
  );
}

function SpendTab() {
  const q = useQuery({ queryKey: ["spend"], queryFn: () => api.getSpend() });
  if (q.isLoading) return <Card><CardBody className="flex justify-center py-10"><Spinner /></CardBody></Card>;
  if (q.isError) return <Card><CardBody className="text-sm text-red-600">{(q.error as Error).message}</CardBody></Card>;
  const d = q.data!;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Cumulative LLM spend</CardTitle>
          <CardDescription>
            Persists across process restarts. Cap behaviour: {d.cap_enabled
              ? `enabled at $${d.cumulative_cap_usd.toFixed(2)}`
              : "disabled (observer mode)"}.
          </CardDescription>
        </CardHeader>
        <CardBody>
          <div className="text-3xl font-semibold">${d.total_usd.toFixed(4)}</div>
          {d.cap_enabled && (
            <div className="mt-2">
              <div className="h-2 bg-[rgb(var(--surface-muted))] rounded-full overflow-hidden">
                <div
                  className="h-full bg-brand-500"
                  style={{ width: `${Math.min(100, (d.total_usd / d.cumulative_cap_usd) * 100)}%` }}
                />
              </div>
              <div className="text-xs text-[rgb(var(--fg-muted))] mt-1">
                {((d.total_usd / d.cumulative_cap_usd) * 100).toFixed(1)}% of cap
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>By backend</CardTitle>
        </CardHeader>
        <CardBody className="p-0">
          {Object.keys(d.by_backend).length === 0 ? (
            <div className="px-5 py-6 text-sm text-[rgb(var(--fg-muted))]">No spend yet.</div>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {Object.entries(d.by_backend)
                  .sort((a, b) => b[1] - a[1])
                  .map(([backend, amount]) => (
                  <tr key={backend} className="border-t border-[rgb(var(--border))] first:border-t-0">
                    <td className="px-5 py-3"><Badge tone="brand">{backend}</Badge></td>
                    <td className="px-5 py-3 text-right font-mono">${amount.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function TenantsTab() {
  return (
    <Card><CardBody>
      <EmptyState
        title="Tenant management pending"
        subtitle={
          "GET /admin/tenants exists but isn't yet wired here. Tenant " +
          "creation works via the existing POST /admin/tenants endpoint."
        }
      />
    </CardBody></Card>
  );
}

function SettingsStub() {
  return (
    <Card><CardBody>
      <EmptyState
        title="Settings pending"
        subtitle="Theme + spend cap + provider chain controls will live here."
      />
    </CardBody></Card>
  );
}
