"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, Plus } from "lucide-react";
import { useState } from "react";

import { api, type TenantCreateResult } from "@/lib/api";
import {
  Badge, Button, Card, CardBody, CardDescription, CardHeader, CardTitle,
  EmptyState, Input, Spinner, Tabs,
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
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ["tenants"], queryFn: () => api.listTenants() });
  const [showCreate, setShowCreate] = useState(false);
  const [newest, setNewest] = useState<TenantCreateResult | null>(null);

  return (
    <div className="space-y-4">
      {/* Create-tenant flash card — shows the freshly-issued API key ONCE */}
      {newest && (
        <Card className="border-emerald-300 dark:border-emerald-700">
          <CardBody>
            <div className="flex items-start gap-3">
              <CheckCircle2 className="h-5 w-5 mt-0.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="font-medium">
                  Tenant <span className="font-mono">{newest.slug}</span> created
                </div>
                <CardDescription className="mt-0.5">
                  Cap: ${newest.monthly_cost_cap_usd.toFixed(2)}/month. Below is the
                  initial API key — it&apos;s shown <strong>once</strong>; copy it now.
                </CardDescription>
                <div className="mt-3 flex items-center gap-2">
                  <code className="flex-1 text-xs font-mono bg-[rgb(var(--surface-muted))] px-3 py-2 rounded-md break-all">
                    {newest.api_key}
                  </code>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => navigator.clipboard.writeText(newest.api_key)}
                  >
                    <Copy className="h-3.5 w-3.5" /> Copy
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setNewest(null)}
                  >
                    Dismiss
                  </Button>
                </div>
              </div>
            </div>
          </CardBody>
        </Card>
      )}

      {/* Create form */}
      {showCreate && (
        <CreateTenantForm
          onCreated={(r) => {
            setNewest(r);
            setShowCreate(false);
            queryClient.invalidateQueries({ queryKey: ["tenants"] });
          }}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {/* List header */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-[rgb(var(--fg-muted))]">
          {q.data?.tenants.length ?? "—"} tenant{q.data?.tenants.length === 1 ? "" : "s"}
        </div>
        {!showCreate && (
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="h-3.5 w-3.5" /> New tenant
          </Button>
        )}
      </div>

      {/* List */}
      {q.isLoading ? (
        <Card><CardBody className="flex justify-center py-10"><Spinner /></CardBody></Card>
      ) : q.isError ? (
        <Card><CardBody className="text-sm text-red-600">{(q.error as Error).message}</CardBody></Card>
      ) : (q.data?.tenants.length ?? 0) === 0 ? (
        <Card><CardBody>
          <EmptyState
            title="No tenants yet"
            subtitle="Click New tenant above to onboard the first one."
          />
        </CardBody></Card>
      ) : (
        <Card>
          <CardBody className="p-0">
            <table className="w-full text-sm">
              <thead className="bg-[rgb(var(--surface-muted))] text-xs">
                <tr>
                  <th className="text-left px-5 py-2">Slug</th>
                  <th className="text-left px-5 py-2">Display name</th>
                  <th className="text-left px-5 py-2">Pack</th>
                  <th className="text-right px-5 py-2">Monthly cap</th>
                  <th className="text-right px-5 py-2">Created</th>
                </tr>
              </thead>
              <tbody>
                {q.data!.tenants.map((t) => (
                  <tr key={t.id} className="border-t border-[rgb(var(--border))]">
                    <td className="px-5 py-2.5 font-mono text-xs">{t.slug}</td>
                    <td className="px-5 py-2.5">{t.display_name}</td>
                    <td className="px-5 py-2.5">
                      {t.pack_slug ? (
                        <Badge tone="brand" className="text-[10px]">{t.pack_slug}</Badge>
                      ) : (
                        <span className="text-xs text-[rgb(var(--fg-muted))]">—</span>
                      )}
                    </td>
                    <td className="px-5 py-2.5 text-right text-xs font-mono">
                      ${t.monthly_cost_cap_usd.toFixed(2)}
                    </td>
                    <td className="px-5 py-2.5 text-right text-xs text-[rgb(var(--fg-muted))]">
                      {new Date(t.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function CreateTenantForm({
  onCreated,
  onCancel,
}: {
  onCreated: (r: TenantCreateResult) => void;
  onCancel: () => void;
}) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [monthlyCap, setMonthlyCap] = useState("200");
  const [packSlug, setPackSlug] = useState("");

  const mutate = useMutation({
    mutationFn: () =>
      api.createTenant({
        slug: slug.trim(),
        display_name: displayName.trim(),
        monthly_cost_cap_usd: Number(monthlyCap) || 200,
        pack_slug: packSlug.trim() || null,
      }),
    onSuccess: (r) => onCreated(r),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">New tenant</CardTitle>
        <CardDescription>
          Slug is the canonical identifier; display name is shown in the UI.
          The initial API key will be issued once on creation.
        </CardDescription>
      </CardHeader>
      <CardBody className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs font-medium">Slug *</span>
            <Input
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
              placeholder="acme-corp"
              className="mt-1 font-mono"
              autoFocus
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium">Display name *</span>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Acme Corporation"
              className="mt-1"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium">Monthly cap (USD)</span>
            <Input
              type="number"
              value={monthlyCap}
              onChange={(e) => setMonthlyCap(e.target.value)}
              className="mt-1"
              min="0"
              step="10"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium">
              Pack slug <span className="font-normal text-[rgb(var(--fg-muted))]">(optional)</span>
            </span>
            <Input
              value={packSlug}
              onChange={(e) => setPackSlug(e.target.value)}
              placeholder="telecom_billing"
              className="mt-1 font-mono"
            />
          </label>
        </div>

        {mutate.isError && (
          <div className="text-sm text-red-600 dark:text-red-400">
            {(mutate.error as Error).message}
          </div>
        )}

        <div className="flex items-center justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel}>Cancel</Button>
          <Button
            size="sm"
            onClick={() => mutate.mutate()}
            disabled={mutate.isPending || !slug.trim() || !displayName.trim()}
          >
            {mutate.isPending && <Spinner className="border-white border-t-transparent" />}
            Create
          </Button>
        </div>
      </CardBody>
    </Card>
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
