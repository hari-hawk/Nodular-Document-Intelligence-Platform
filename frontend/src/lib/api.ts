/**
 * Thin typed client over MDI's FastAPI surface.
 *
 * Design choice: this is hand-typed rather than generated from OpenAPI.
 * The codegen step would be cleaner long-term, but for v1 the surface is
 * small enough that a thin wrapper is faster to ship and easier to
 * understand at review time. When the API grows past ~30 endpoints,
 * swap in openapi-typescript.
 *
 * Auth: the API is gated by `X-Admin-Key` on /admin/* routes (local
 * shared secret) and `X-API-Key` on tenant routes. The browser stores
 * both in localStorage and the client attaches them automatically.
 */

const ADMIN_KEY_STORAGE = "mdi.admin_key";
const API_KEY_STORAGE = "mdi.api_key";

export type AutoPackProposal = {
  id: string;
  vendor_slug: string;
  vendor_name: string;
  doc_type_hint: string | null;
  sighting_count: number;
  status: "pending" | "approved" | "rejected" | "superseded";
  decided_by: string | null;
  decided_at: string | null;
  promoted_path: string | null;
  created_at: string;
  last_seen_at: string;
};

export type TenantFact = {
  id: string;
  fact_type: string;
  key: string;
  value: string;
  confidence: number;
  source_doc_id: string | null;
  sighting_count: number;
  last_seen_at: string;
  created_at: string;
};

export type HandlerManifest = {
  handler_id: string;
  description: string;
  when_to_use: string;
};

export type SpendSnapshot = {
  total_usd: number;
  by_backend: Record<string, number>;
  cumulative_cap_usd: number;
  cap_enabled: boolean;
};

export type PatternSummary = {
  id: string;
  industry: string;
  vendor: string;
  doc_type: string;
  seen_count: number;
  last_seen_at: string | null;
  created_at: string | null;
  field_count: number;
  rule_count: number;
};

export type PatternDetail = {
  id: string;
  industry: string;
  vendor: string;
  doc_type: string;
  schema_def: { fields?: Array<{ name: string; type: string; required?: boolean; description?: string }>; primary_keys?: string[]; discovered_from?: string };
  rules: { rules?: Array<{ rule_id: string; expression: string; severity: string; message: string; invented?: boolean }> };
  seen_count: number;
  last_seen_at: string | null;
  created_at: string | null;
};

export type BatchSummary = {
  id: string;
  status: string;
  total_documents: number;
  started_at: string | null;
  finished_at: string | null;
  cost_usd: number;
  narrator_preview: string;
  anomaly_count: number;
  insight_count: number;
};

export type BatchReport = {
  batch_id?: string;
  tenant_id: string;
  started_at: string;
  finished_at: string;
  documents: Array<{ document_id: string; filename: string; page_count: number; bytes: number }>;
  clusters: Record<string, { industry: string; vendor: string; doc_type: string; confidence: number; rationale: string }>;
  extractions: Record<string, { fields: Record<string, { value: unknown; confidence: number; source_text?: string }> }>;
  anomalies: Array<{ rule_id: string; severity: string; field_path: string | null; message: string }>;
  insights: Array<{ insight_type: string; severity: string; title: string; body: string }>;
  pattern_matches?: Array<{ document_id: string; pattern_id: string; similarity: number; rank: number }>;
  narrator_summary: string;
  total_cost_usd: number;
  progress: string[];
};

function getAdminKey(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ADMIN_KEY_STORAGE) || "";
}

function getApiKey(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(API_KEY_STORAGE) || "";
}

export function setAuth(args: { adminKey?: string; apiKey?: string }) {
  if (typeof window === "undefined") return;
  if (args.adminKey !== undefined) {
    window.localStorage.setItem(ADMIN_KEY_STORAGE, args.adminKey);
  }
  if (args.apiKey !== undefined) {
    window.localStorage.setItem(API_KEY_STORAGE, args.apiKey);
  }
}

export function clearAuth() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ADMIN_KEY_STORAGE);
  window.localStorage.removeItem(API_KEY_STORAGE);
}

export function isAuthed(): boolean {
  return Boolean(getAdminKey() || getApiKey());
}

class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  opts: { admin?: boolean } = {},
): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (opts.admin) {
    const k = getAdminKey();
    if (k) headers.set("X-Admin-Key", k);
  } else {
    const k = getApiKey();
    if (k) headers.set("X-API-Key", k);
  }
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* ignore */ }
    throw new ApiError(res.status, body, `${res.status} ${res.statusText} on ${path}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ─────────────────────────────────────────────────────────────────────────────
// Endpoints
// ─────────────────────────────────────────────────────────────────────────────
export const api = {
  health: () => request<{ status: string }>("/health"),

  // Process a batch of uploaded files (multipart).
  processBatch: (files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return request<BatchReport>("/process", { method: "POST", body: fd });
  },

  getReport: (batchId: string) => request<BatchReport>(`/report/${batchId}`),

  // Wave 3.2 — light-weight list of recent batches for the current tenant.
  listBatches: (limit = 20) =>
    request<{ batches: BatchSummary[] }>(`/batches?limit=${limit}`),

  // Wave 3.3 — Hippocampus patterns explorer.
  listPatterns: (params: { industry?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.industry) q.set("industry", params.industry);
    if (params.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<{ patterns: PatternSummary[] }>(
      `/admin/patterns${qs ? `?${qs}` : ""}`, {}, { admin: true },
    );
  },
  getPattern: (id: string) =>
    request<PatternDetail>(`/admin/patterns/${id}`, {}, { admin: true }),

  // Auto-pack proposals
  listAutoPacks: (statusFilter = "pending") =>
    request<{ proposals: AutoPackProposal[] }>(
      `/admin/auto-packs?status_filter=${encodeURIComponent(statusFilter)}`,
      {}, { admin: true },
    ),
  promoteAutoPack: (id: string, decidedBy = "analyst") =>
    request(`/admin/auto-packs/${id}/promote`, {
      method: "POST",
      body: JSON.stringify({ decided_by: decidedBy }),
    }, { admin: true }),
  rejectAutoPack: (id: string, decidedBy = "analyst") =>
    request(`/admin/auto-packs/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ decided_by: decidedBy }),
    }, { admin: true }),

  // Tenant facts
  listTenantFacts: (factType?: string, limit = 500) => {
    const q = factType
      ? `?fact_type=${encodeURIComponent(factType)}&limit=${limit}`
      : `?limit=${limit}`;
    return request<{ facts: TenantFact[] }>(`/admin/tenant-facts${q}`, {}, { admin: true });
  },

  // Handler registry
  listHandlers: () => request<{ handlers: HandlerManifest[] }>("/admin/handlers", {}, { admin: true }),
  runHandler: (handlerId: string, payload: { document_id?: string; kwargs?: Record<string, unknown> }) =>
    request<{ ok: boolean; output: string; data: unknown; side_effects: string[] }>(
      `/admin/handlers/${handlerId}/run`,
      { method: "POST", body: JSON.stringify(payload) },
      { admin: true },
    ),

  // Spend ledger
  getSpend: () => request<SpendSnapshot>("/admin/spend", {}, { admin: true }),

  // Packs
  listPacks: () => request<{ packs: string[] }>("/admin/packs", {}, { admin: true }),

  // Tenant usage
  getTenantUsage: () => request<{ tenant_id: string; monthly_cap_usd: number; spent_usd: number; events: number }>("/tenant/usage"),

  // Chat
  chat: (question: string, history: Array<{ role: string; content: string }> = []) =>
    request<{ answer: string; route: string; citations: string[]; elapsed_ms: number }>("/chat", {
      method: "POST",
      body: JSON.stringify({ question, history }),
    }),

  // Corrections
  postCorrection: (payload: {
    industry: string; vendor: string; doc_type: string;
    field_path: string; extracted_value?: string | null;
    corrected_value: string; note?: string;
  }) =>
    request<{ correction_id: string }>("/correction", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export { ApiError };
