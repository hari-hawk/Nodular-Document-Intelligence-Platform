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
  /** Present in admin-auth mode (cross-tenant). */
  tenant_id?: string;
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
  tenant_id?: string;
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

export type TenantRow = {
  id: string;
  slug: string;
  display_name: string;
  monthly_cost_cap_usd: number;
  pack_slug: string | null;
  created_at: string;
};

export type TenantCreateResult = {
  tenant_id: string;
  slug: string;
  display_name: string;
  api_key: string;  // SHOWN ONCE on creation
  monthly_cost_cap_usd: number;
};

export type SpendSnapshot = {
  total_usd: number;
  by_backend: Record<string, number>;
  cumulative_cap_usd: number;
  cap_enabled: boolean;
};

export type PatternSummary = {
  id: string;
  tenant_id?: string;
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
  tenant_id?: string;
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
  /** Present when the endpoint was called in admin-auth mode — admins see
   *  batches across all tenants and need to know which is which. */
  tenant_id?: string;
  status: string;
  total_documents: number;
  started_at: string | null;
  finished_at: string | null;
  cost_usd: number;
  narrator_preview: string;
  anomaly_count: number;
  insight_count: number;
};

export type ListBatchesResult = {
  /** 'admin' when listed via X-Admin-Key (cross-tenant), 'tenant' when
   *  scoped via X-API-Key (RLS-isolated to one tenant). */
  auth_mode: "admin" | "tenant";
  batches: BatchSummary[];
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
  opts: { admin?: boolean; bothAuth?: boolean } = {},
): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  // bothAuth: send both keys whichever are present and let the server
  // pick a mode. Used by endpoints that accept tenant OR admin auth
  // (currently /batches; the Workspace page lets analysts AND admins
  // see it without forcing the analyst to know which mode they're in).
  if (opts.bothAuth) {
    const ak = getAdminKey();
    if (ak) headers.set("X-Admin-Key", ak);
    const tk = getApiKey();
    if (tk) headers.set("X-API-Key", tk);
  } else if (opts.admin) {
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

  getReport: (batchId: string) =>
    request<BatchReport>(`/report/${batchId}`, {}, { bothAuth: true }),

  // Wave 3.2 — light-weight list of recent batches.
  // Accepts EITHER tenant API key OR admin key — both get sent and the
  // server picks the mode. Admin mode lists across all tenants.
  listBatches: (limit = 20) =>
    request<ListBatchesResult>(`/batches?limit=${limit}`, {}, { bothAuth: true }),

  // Hippocampus patterns explorer (admin OR tenant auth).
  listPatterns: (params: { industry?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.industry) q.set("industry", params.industry);
    if (params.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<{ auth_mode: "admin" | "tenant"; patterns: PatternSummary[] }>(
      `/admin/patterns${qs ? `?${qs}` : ""}`, {}, { bothAuth: true },
    );
  },
  getPattern: (id: string) =>
    request<PatternDetail>(`/admin/patterns/${id}`, {}, { bothAuth: true }),

  // Auto-pack proposals (admin OR tenant auth).
  listAutoPacks: (statusFilter = "pending") =>
    request<{ auth_mode: "admin" | "tenant"; proposals: AutoPackProposal[] }>(
      `/admin/auto-packs?status_filter=${encodeURIComponent(statusFilter)}`,
      {}, { bothAuth: true },
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

  // Tenant facts (admin OR tenant auth).
  listTenantFacts: (factType?: string, limit = 500) => {
    const q = factType
      ? `?fact_type=${encodeURIComponent(factType)}&limit=${limit}`
      : `?limit=${limit}`;
    return request<{ auth_mode: "admin" | "tenant"; facts: TenantFact[] }>(
      `/admin/tenant-facts${q}`, {}, { bothAuth: true },
    );
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

  // Tenants (admin onboarding)
  listTenants: () =>
    request<{ tenants: TenantRow[] }>("/admin/tenants", {}, { admin: true }),
  createTenant: (payload: { slug: string; display_name: string; monthly_cost_cap_usd?: number; pack_slug?: string | null }) =>
    request<TenantCreateResult>("/admin/tenants", {
      method: "POST",
      body: JSON.stringify(payload),
    }, { admin: true }),

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

  // Per-document inspection (Wave 3.x — needed because LLM-driven
  // extraction can be rate-limited; analysts still need to see what
  // the parser captured + can trigger deterministic field extraction).
  getDocumentText: (docId: string) =>
    request<{ document_id: string; text: string; chunk_count: number }>(
      `/admin/documents/${docId}/text`, {}, { bothAuth: true },
    ),
  extractHeuristic: (docId: string) =>
    request<{ document_id: string; fields: Record<string, unknown>; updated: number }>(
      `/admin/documents/${docId}/extract-heuristic`,
      { method: "POST" },
      { bothAuth: true },
    ),

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
