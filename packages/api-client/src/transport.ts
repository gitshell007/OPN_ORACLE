import type { components } from "./generated/schema";

export type Problem = components["schemas"]["Problem"];

export type MembershipSummary =
  components["schemas"]["MembershipSummaryResponse"];
export type SessionIdentity = components["schemas"]["MeResponse"];

export interface PlatformBackup {
  id: string;
  backup_name: string;
  status: "available" | "expired" | "missing";
  origin: "scheduled" | "manual" | "imported";
  backup_created_at: string;
  verified_at: string | null;
  expires_at: string | null;
  size_bytes: number;
  sha256: string;
}

export interface PlatformBackupOperation {
  operation_id: string;
  operation_type: "manual_backup" | "scheduled_backup" | "restore";
  status:
    | "queued"
    | "awaiting_approval"
    | "running"
    | "succeeded"
    | "failed"
    | "cancelled";
  artifact_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
}

export interface PlatformBackupList {
  items: PlatformBackup[];
  operations: PlatformBackupOperation[];
  retention_days: number;
  storage_path: string;
}

export type PlatformBackupAction = PlatformBackupOperation;

export function isProblem(value: unknown): value is Problem {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Problem>;
  return (
    typeof candidate.status === "number" && typeof candidate.code === "string"
  );
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly problem: Problem,
    public readonly retryAfter?: number,
  ) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
  }
}

let csrfToken: string | null = null;

function requestId(): string | undefined {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : undefined;
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const problem: Problem = isProblem(payload)
    ? payload
    : {
        type: "about:blank",
        title: "No se pudo completar la solicitud",
        status: response.status,
        detail:
          response.statusText ||
          "El servidor no devolvió un error interpretable.",
        instance: "",
        code: "http_error",
        request_id: response.headers.get("X-Request-ID") ?? "",
      };
  const retry = Number(response.headers.get("Retry-After"));
  return new ApiError(
    response.status,
    problem,
    Number.isFinite(retry) ? retry : undefined,
  );
}

function publishAuthError(path: string, error: ApiError): void {
  const fatal = [
    "authentication_required",
    "session_expired",
    "tenant_suspended",
    "membership_suspended",
  ].includes(error.problem.code);
  if (!fatal) return;
  csrfToken = null;
  if (typeof window === "undefined") return;
  const publicFlow = [
    "/login",
    "/forgot-password",
    "/reset-password",
    "/accept-invitation",
    "/reauthenticate",
  ].some((suffix) => path.endsWith(suffix));
  if (!publicFlow)
    window.dispatchEvent(
      new CustomEvent("oracle:auth-error", { detail: error }),
    );
}

async function fetchCsrf(signal?: AbortSignal): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", {
    credentials: "include",
    signal,
    cache: "no-store",
  });
  if (!response.ok) throw await parseError(response);
  const payload =
    (await response.json()) as components["schemas"]["CsrfResponse"];
  csrfToken = payload.csrf_token;
  return csrfToken;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  retry?: boolean;
  ifMatch?: number;
  idempotencyKey?: string;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const mutation = method !== "GET";
  const attempts = method === "GET" && options.retry !== false ? 3 : 1;
  if (mutation && !csrfToken) await fetchCsrf(options.signal);
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const headers = new Headers({ Accept: "application/json" });
      const id = requestId();
      if (id) headers.set("X-Request-ID", id);
      if (mutation) headers.set("X-CSRF-Token", csrfToken ?? "");
      if (options.ifMatch !== undefined)
        headers.set("If-Match", `W/"${options.ifMatch}"`);
      if (options.idempotencyKey)
        headers.set("Idempotency-Key", options.idempotencyKey);
      const multipart =
        typeof FormData !== "undefined" && options.body instanceof FormData;
      if (options.body !== undefined && !multipart)
        headers.set("Content-Type", "application/json");
      const response = await fetch(path, {
        method,
        credentials: "include",
        headers,
        body:
          options.body === undefined
            ? undefined
            : multipart
              ? (options.body as FormData)
              : JSON.stringify(options.body),
        signal: options.signal,
        cache: "no-store",
      });
      if (response.ok) {
        if (response.status === 204) return undefined as T;
        return (await response.json()) as T;
      }
      if (
        method === "GET" &&
        [502, 503, 504].includes(response.status) &&
        attempt + 1 < attempts
      ) {
        await new Promise((resolve) =>
          setTimeout(resolve, 150 * (attempt + 1)),
        );
        continue;
      }
      const error = await parseError(response);
      publishAuthError(path, error);
      throw error;
    } catch (error) {
      if (
        error instanceof ApiError ||
        options.signal?.aborted ||
        attempt + 1 >= attempts
      )
        throw error;
      await new Promise((resolve) => setTimeout(resolve, 150 * (attempt + 1)));
    }
  }
  throw new Error("Solicitud agotada");
}

const auth = {
  me: (signal?: AbortSignal) =>
    request<SessionIdentity>("/api/v1/auth/me", { signal, retry: false }),
  csrf: fetchCsrf,
  login: async (
    input: components["schemas"]["LoginInput"],
    signal?: AbortSignal,
  ) => {
    const result = await request<components["schemas"]["LoginResponse"]>(
      "/api/v1/auth/login",
      {
        method: "POST",
        body: input,
        signal,
      },
    );
    await fetchCsrf(signal);
    return result;
  },
  logout: async () => {
    await request<void>("/api/v1/auth/logout", { method: "POST" });
    csrfToken = null;
  },
  reauthenticate: async (password: string) => {
    const result = await request<components["schemas"]["StatusResponse"]>(
      "/api/v1/auth/reauthenticate",
      { method: "POST", body: { password } },
    );
    await fetchCsrf();
    return result;
  },
  switchTenant: async (tenant_id: string) => {
    const result = await request<components["schemas"]["SwitchTenantResponse"]>(
      "/api/v1/auth/switch-tenant",
      { method: "POST", body: { tenant_id } },
    );
    await fetchCsrf();
    return result;
  },
  forgotPassword: (email: string) =>
    request<void>("/api/v1/auth/forgot-password", {
      method: "POST",
      body: { email },
    }),
  resetPassword: (token: string, new_password: string) =>
    request<void>("/api/v1/auth/reset-password", {
      method: "POST",
      body: { token, new_password },
    }),
  acceptInvitation: (token: string, new_password: string) =>
    request<void>("/api/v1/auth/accept-invitation", {
      method: "POST",
      body: { token, new_password },
    }),
  changePassword: async (current_password: string, new_password: string) => {
    const result = await request<void>("/api/v1/auth/change-password", {
      method: "POST",
      body: { current_password, new_password },
    });
    await fetchCsrf();
    return result;
  },
  sessions: () =>
    request<components["schemas"]["SessionListResponse"]>(
      "/api/v1/auth/sessions",
    ),
  revokeSession: (id: string) =>
    request<void>(`/api/v1/auth/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  revokeOthers: () =>
    request<void>("/api/v1/auth/sessions/revoke-others", { method: "POST" }),
};

const tenantAdmin = {
  members: () =>
    request<components["schemas"]["MemberListResponse"]>(
      "/api/v1/tenant-admin/members",
    ),
  roles: () =>
    request<components["schemas"]["RoleListResponse"]>(
      "/api/v1/tenant-admin/roles",
    ),
  audit: () =>
    request<components["schemas"]["AuditListResponse"]>(
      "/api/v1/tenant-admin/audit",
    ),
  invite: (input: components["schemas"]["InviteMemberInput"]) =>
    request<components["schemas"]["IdResponse"]>(
      "/api/v1/tenant-admin/members",
      { method: "POST", body: input },
    ),
  setStatus: (id: string, status: "active" | "suspended") =>
    request<components["schemas"]["StatusResponse"]>(
      `/api/v1/tenant-admin/members/${encodeURIComponent(id)}`,
      { method: "PATCH", body: { status } },
    ),
  remove: (id: string) =>
    request<void>(`/api/v1/tenant-admin/members/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  resend: (id: string) =>
    request<void>(
      `/api/v1/tenant-admin/members/${encodeURIComponent(id)}/resend-invite`,
      { method: "POST" },
    ),
  setRoles: (id: string, roles: string[]) =>
    request<components["schemas"]["RolesResponse"]>(
      `/api/v1/tenant-admin/members/${encodeURIComponent(id)}/roles`,
      { method: "PATCH", body: { roles } },
    ),
};

const platform = {
  tenants: () =>
    request<components["schemas"]["TenantListResponse"]>(
      "/api/v1/platform/tenants",
    ),
  tenant: (id: string) =>
    request<components["schemas"]["TenantResponse"]>(
      `/api/v1/platform/tenants/${encodeURIComponent(id)}`,
    ),
  createTenant: (input: components["schemas"]["TenantCreateInput"]) =>
    request<components["schemas"]["TenantResponse"]>(
      "/api/v1/platform/tenants",
      { method: "POST", body: input },
    ),
  setTenantStatus: (id: string, action: "suspend" | "reactivate") =>
    request<void>(
      `/api/v1/platform/tenants/${encodeURIComponent(id)}/${action}`,
      { method: "POST" },
    ),
  inviteOwner: (
    id: string,
    input: components["schemas"]["InviteMemberInput"],
  ) =>
    request<components["schemas"]["MembershipIdResponse"]>(
      `/api/v1/platform/tenants/${encodeURIComponent(id)}/invite-owner`,
      { method: "POST", body: input },
    ),
  users: () =>
    request<components["schemas"]["UserListResponse"]>(
      "/api/v1/platform/users",
    ),
  audit: () =>
    request<components["schemas"]["AuditListResponse"]>(
      "/api/v1/platform/audit",
    ),
  system: async () => {
    const [live, ready, meta] = await Promise.all([
      request<components["schemas"]["Health"]>("/health/live"),
      request<components["schemas"]["Health"]>("/health/ready"),
      request<components["schemas"]["Meta"]>("/meta"),
    ]);
    return { live, ready, meta };
  },
  backups: () => request<PlatformBackupList>("/api/v1/platform/backups"),
  createBackup: () =>
    request<PlatformBackupAction>("/api/v1/platform/backups", {
      method: "POST",
      idempotencyKey: `platform-backup-${Date.now()}`,
    }),
  restoreBackup: (id: string, confirmation: string) =>
    request<PlatformBackupAction>(
      `/api/v1/platform/backups/${encodeURIComponent(id)}/restore`,
      {
        method: "POST",
        body: { confirmation },
        idempotencyKey: `platform-restore-${id}-${Date.now()}`,
      },
    ),
};

const jobs = {
  list: (page = 1, size = 25, status?: string) => {
    const query = new URLSearchParams({
      "page[number]": String(page),
      "page[size]": String(size),
    });
    if (status) query.set("filter[status]", status);
    return request<components["schemas"]["JobListResponse"]>(
      `/api/v1/jobs?${query.toString()}`,
    );
  },
  get: (id: string) =>
    request<components["schemas"]["JobResponse"]>(
      `/api/v1/jobs/${encodeURIComponent(id)}`,
    ),
  cancel: (id: string, version: number) =>
    request<components["schemas"]["JobResponse"]>(
      `/api/v1/jobs/${encodeURIComponent(id)}/cancel`,
      { method: "POST", ifMatch: version },
    ),
  retry: (id: string, version: number) =>
    request<components["schemas"]["JobResponse"]>(
      `/api/v1/jobs/${encodeURIComponent(id)}/retry`,
      { method: "POST", ifMatch: version },
    ),
};

export interface SignalConnection {
  id: string;
  provider: string;
  name: string;
  status: string;
  adapter_mode: "mock" | "http";
  api_version: string;
  base_url: string | null;
  circuit_state: string;
  last_health_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  version: number;
}

export interface SignalMonitor {
  id: string;
  tenant_id: string;
  watchlist_id: string;
  connection_id: string | null;
  provider: string;
  name?: string;
  external_id: string | null;
  status: "active" | "paused" | "error";
  desired_status: string;
  observed_status: string;
  cursor: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  next_sync_at: string | null;
  last_sync_attempt_at: string | null;
  version: number;
}

export type SignalMonitorSourceType =
  | "news"
  | "social_signal"
  | "company_signal"
  | "official_publication"
  | "regulatory_signal";

export interface SignalMonitorEntityInput {
  type: "company" | "person" | "topic";
  name: string;
}

export interface CreateSignalMonitorInput {
  connection_id: string;
  name: string;
  query: string;
  cadence: string;
  keywords?: string[];
  entities?: SignalMonitorEntityInput[];
  source_types?: SignalMonitorSourceType[];
  languages?: string[];
  geographies?: string[];
  retention_days?: number;
}

const signalAvanza = {
  connections: () =>
    request<{ items: SignalConnection[] }>(
      "/api/v1/integrations/signal-avanza",
    ),
  create: (input: {
    name: string;
    adapter_mode: "mock" | "http";
    base_url?: string;
    api_version?: string;
    api_token?: string;
    webhook_secret?: string;
  }) =>
    request<SignalConnection>("/api/v1/integrations/signal-avanza", {
      method: "POST",
      body: input,
    }),
  rotate: (
    connectionId: string,
    input: { kind: "api_token" | "webhook_secret"; secret: string },
  ) =>
    request<{ status: "rotated" }>(
      `/api/v1/integrations/signal-avanza/${encodeURIComponent(connectionId)}/rotate`,
      { method: "POST", body: input },
    ),
  disable: (connectionId: string) =>
    request<SignalConnection>(
      `/api/v1/integrations/signal-avanza/${encodeURIComponent(connectionId)}/disable`,
      { method: "POST" },
    ),
  test: (connectionId: string) =>
    request<{ outbox_event_id: string; status: string }>(
      "/api/v1/integrations/signal-avanza/test",
      { method: "POST", body: { connection_id: connectionId } },
    ),
  health: (monitorId: string) =>
    request<{
      monitor_id: string;
      desired_status: string;
      observed_status: string;
      last_synced_at: string | null;
      last_error: string | null;
    }>(`/api/v1/signal-monitors/${encodeURIComponent(monitorId)}/health`),
  monitors: (dossierId: string) =>
    request<{
      items: Array<{
        id: string;
        connection_id: string | null;
        external_id: string | null;
        desired_status: string;
        observed_status: string;
        last_synced_at: string | null;
        last_error: string | null;
      }>;
    }>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/signal-monitors`,
    ).then(({ items }) => ({
      data: items.map((item) => ({
        ...item,
        tenant_id: "",
        watchlist_id: "",
        provider: "signal-avanza",
        status: (item.observed_status === "error"
          ? "error"
          : item.desired_status === "paused"
            ? "paused"
            : "active") as SignalMonitor["status"],
        cursor: null,
        next_sync_at: null,
        last_sync_attempt_at: null,
        version: 1,
      })),
    })),
  createMonitor: (dossierId: string, input: CreateSignalMonitorInput) =>
    request<{ id: string; outbox_event_id: string }>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/signal-monitors`,
      {
        method: "POST",
        body: input,
        idempotencyKey: `monitor-create-${dossierId}-${Date.now()}`,
      },
    ),
  reconcile: (connectionId: string) =>
    request<{ requeued: number }>(
      `/api/v1/integrations/signal-avanza/${encodeURIComponent(connectionId)}/reconcile`,
      { method: "POST" },
    ),
  action: (monitorId: string, action: "pause" | "resume" | "sync") =>
    request<{ job_id?: string; status?: string; desired_status?: string }>(
      `/api/v1/signal-monitors/${encodeURIComponent(monitorId)}/${action}`,
      {
        method: "POST",
        idempotencyKey: `${action}-${monitorId}-${Date.now()}`,
      },
    ),
};

export interface OracleDocument {
  id: string;
  dossier_id: string;
  filename: string;
  media_type: string;
  byte_size: number;
  checksum: string;
  classification: "public" | "internal";
  status:
    | "uploaded"
    | "queued"
    | "processing"
    | "ready"
    | "failed"
    | "quarantined"
    | "deleted";
  scan_status: string;
  scan_result: Record<string, unknown>;
  safe_error_code: string | null;
  current_version_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface BackendDossier {
  id: string;
  title: string;
  description: string;
  dossier_type: string;
  status: string;
  strategic_goal: string;
  health_score: number;
  opportunity_score: number;
  risk_score: number;
  owner_user_id?: string | null;
  workspace_id?: string;
  updated_at: string;
  version?: number;
}

export type DossierSort =
  | "updated_at"
  | "-updated_at"
  | "title"
  | "-title"
  | "status"
  | "-status"
  | "health_score"
  | "-health_score"
  | "opportunity_score"
  | "-opportunity_score"
  | "risk_score"
  | "-risk_score";

export interface DossierListQuery {
  page?: number;
  size?: 10 | 25 | 50 | 100;
  sort?: DossierSort;
  status?: string;
  type?: string;
  owner?: string;
  search?: string;
  selectedIds?: string[];
}

export interface DossierListResult {
  data: BackendDossier[];
  meta: { page: number; size: number; total: number };
}

const dossiers = {
  list: (input: DossierListQuery = {}) => {
    const query = new URLSearchParams({
      "page[number]": String(input.page ?? 1),
      "page[size]": String(input.size ?? 25),
      sort: input.sort ?? "-updated_at",
    });
    if (input.status) query.set("filter[status]", input.status);
    if (input.type) query.set("filter[type]", input.type);
    if (input.owner) query.set("filter[owner]", input.owner);
    if (input.search?.trim()) query.set("filter[search]", input.search.trim());
    if (input.selectedIds?.length)
      query.set("filter[selected_ids]", input.selectedIds.join(","));
    return request<DossierListResult>(`/api/v1/dossiers?${query.toString()}`);
  },
  get: (dossierId: string) =>
    request<BackendDossier>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}`,
    ),
  create: (input: components["schemas"]["DossierCreateInput"]) =>
    request<components["schemas"]["DossierResource"]>("/api/v1/dossiers", {
      method: "POST",
      body: input,
    }),
  update: (
    dossierId: string,
    input: components["schemas"]["DossierPatchInput"],
    version: number,
  ) =>
    request<BackendDossier>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}`,
      {
        method: "PATCH",
        body: input,
        ifMatch: version,
      },
    ),
  archive: (dossierId: string, version: number) =>
    request<BackendDossier>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/archive`,
      { method: "POST", ifMatch: version },
    ),
  bulkDelete: (dossierIds: string[]) =>
    request<components["schemas"]["DossierBulkDeleteResponse"]>(
      "/api/v1/dossiers/bulk-delete",
      { method: "POST", body: { dossier_ids: dossierIds } },
    ),
};

export type OracleSummaryCurrent =
  components["schemas"]["OracleSummaryCurrentResponse"];
export type OracleSummaryVersion =
  components["schemas"]["OracleSummaryVersion"];

const oracleSummary = {
  get: (dossierId: string) =>
    request<OracleSummaryCurrent>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/oracle-summary`,
    ),
  refresh: (dossierId: string, idempotencyKey: string) =>
    request<components["schemas"]["AIJobEnqueueResponse"]>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/oracle-summary/refresh`,
      { method: "POST", body: {}, idempotencyKey },
    ),
  versions: (dossierId: string) =>
    request<components["schemas"]["OracleSummaryVersionList"]>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/oracle-summary/versions`,
    ),
  version: (dossierId: string, versionId: string) =>
    request<OracleSummaryVersion>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/oracle-summary/versions/${encodeURIComponent(versionId)}`,
    ),
  feedback: (
    dossierId: string,
    versionId: string,
    input: components["schemas"]["OracleSummaryFeedbackInput"],
  ) =>
    request<components["schemas"]["OracleSummaryFeedbackResponse"]>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/oracle-summary/${encodeURIComponent(versionId)}/feedback`,
      { method: "POST", body: input },
    ),
};

export type DossierSignalEnvelope =
  components["schemas"]["DossierSignalEnvelope"];
export type DossierSignalLink = components["schemas"]["DossierSignalResource"];
export type OracleSignal = components["schemas"]["SignalResource"];
export type OracleOpportunity = components["schemas"]["OpportunityResource"];
export type OracleRisk = components["schemas"]["RiskResource"];
export type OracleEvidence = components["schemas"]["EvidenceResource"];
export type OracleObjective = components["schemas"]["ObjectiveResource"];
export type OracleHypothesis = components["schemas"]["HypothesisResource"];

export interface DossierResourceQuery {
  page?: number;
  size?: 10 | 25 | 50 | 100;
  sort?: string;
  status?: string;
  search?: string;
  scoreMin?: number;
  scoreMax?: number;
  dossierId?: string;
  type?: string;
  dateFrom?: string;
  dateTo?: string;
  selectedIds?: string[];
}

export interface DossierResourcePage<T> {
  data: T[];
  meta?: components["schemas"]["PageMeta"];
}

function dossierResourceQuery(input: DossierResourceQuery = {}): string {
  const query = new URLSearchParams({
    "page[number]": String(input.page ?? 1),
    "page[size]": String(input.size ?? 25),
    sort: input.sort ?? "-updated_at",
  });
  if (input.status) query.set("filter[status]", input.status);
  if (input.search?.trim()) query.set("filter[search]", input.search.trim());
  if (input.scoreMin !== undefined)
    query.set("filter[score_min]", String(input.scoreMin));
  if (input.scoreMax !== undefined)
    query.set("filter[score_max]", String(input.scoreMax));
  if (input.dossierId) query.set("filter[dossier_id]", input.dossierId);
  if (input.type) query.set("filter[type]", input.type);
  if (input.dateFrom) query.set("filter[date_from]", input.dateFrom);
  if (input.dateTo) query.set("filter[date_to]", input.dateTo);
  if (input.selectedIds?.length)
    query.set("filter[selected_ids]", input.selectedIds.join(","));
  return query.toString();
}

export type SignalReviewActionInput =
  components["schemas"]["SignalReviewInput"] & {
    status?: "reviewed" | "dismissed";
  };

const dossierSignals = {
  listGlobal: (input: DossierResourceQuery = {}) =>
    request<components["schemas"]["GlobalSignalListResponse"]>(
      `/api/v1/signals?${dossierResourceQuery(input)}`,
    ),
  list: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<DossierSignalEnvelope>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/signals?${dossierResourceQuery(input)}`,
    ),
  review: (linkId: string, input: SignalReviewActionInput) =>
    request<DossierSignalLink>(
      `/api/v1/signals/${encodeURIComponent(linkId)}/review`,
      { method: "POST", body: input },
    ),
  promote: (
    linkId: string,
    input: components["schemas"]["SignalPromoteInput"],
    idempotencyKey: string,
  ) =>
    request<components["schemas"]["PromotionResponse"]>(
      `/api/v1/signals/${encodeURIComponent(linkId)}/promote`,
      { method: "POST", body: input, idempotencyKey },
    ),
};

const objectives = {
  list: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleObjective>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/objectives?${dossierResourceQuery(input)}`,
    ),
  create: (
    dossierId: string,
    input: components["schemas"]["ObjectiveWriteInput"],
  ) =>
    request<OracleObjective>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/objectives`,
      { method: "POST", body: input },
    ),
  update: (
    id: string,
    input: components["schemas"]["ObjectiveWriteInput"],
    version: number,
  ) =>
    request<OracleObjective>(`/api/v1/objectives/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: input,
      ifMatch: version,
    }),
};

const hypotheses = {
  list: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleHypothesis>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/hypotheses?${dossierResourceQuery(input)}`,
    ),
  create: (
    dossierId: string,
    input: components["schemas"]["HypothesisWriteInput"],
  ) =>
    request<OracleHypothesis>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/hypotheses`,
      { method: "POST", body: input },
    ),
  update: (
    id: string,
    input: components["schemas"]["HypothesisWriteInput"],
    version: number,
  ) =>
    request<OracleHypothesis>(`/api/v1/hypotheses/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: input,
      ifMatch: version,
    }),
  remove: (id: string, version: number) =>
    request<void>(`/api/v1/hypotheses/${encodeURIComponent(id)}`, {
      method: "DELETE",
      ifMatch: version,
    }),
  evidence: (id: string) =>
    request<DossierResourcePage<OracleEvidence>>(
      `/api/v1/hypotheses/${encodeURIComponent(id)}/evidence?page%5Bnumber%5D=1&page%5Bsize%5D=100`,
    ),
  linkEvidence: (id: string, evidenceId: string) =>
    request<{ linked: true }>(
      `/api/v1/hypotheses/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}`,
      { method: "PUT" },
    ),
};

const dossierEvidence = {
  list: (dossierId: string) =>
    request<DossierResourcePage<OracleEvidence>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/evidence?page%5Bnumber%5D=1&page%5Bsize%5D=100`,
    ),
};

function evidenceList(kind: "opportunities" | "risks", resourceId: string) {
  return request<DossierResourcePage<OracleEvidence>>(
    `/api/v1/${kind}/${encodeURIComponent(resourceId)}/evidence?page%5Bnumber%5D=1&page%5Bsize%5D=25`,
  );
}

const opportunities = {
  listGlobal: (input: DossierResourceQuery = {}) =>
    request<components["schemas"]["GlobalOpportunityListResponse"]>(
      `/api/v1/opportunities?${dossierResourceQuery(input)}`,
    ),
  list: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleOpportunity>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/opportunities?${dossierResourceQuery(input)}`,
    ),
  get: (resourceId: string) =>
    request<OracleOpportunity>(
      `/api/v1/opportunities/${encodeURIComponent(resourceId)}`,
    ),
  create: (
    dossierId: string,
    input: components["schemas"]["OpportunityWriteInput"],
  ) =>
    request<OracleOpportunity>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/opportunities`,
      { method: "POST", body: input },
    ),
  update: (
    resourceId: string,
    input: components["schemas"]["OpportunityWriteInput"],
    version: number,
  ) =>
    request<OracleOpportunity>(
      `/api/v1/opportunities/${encodeURIComponent(resourceId)}`,
      { method: "PATCH", body: input, ifMatch: version },
    ),
  evidence: (resourceId: string) => evidenceList("opportunities", resourceId),
};

const risks = {
  listGlobal: (input: DossierResourceQuery = {}) =>
    request<components["schemas"]["GlobalRiskListResponse"]>(
      `/api/v1/risks?${dossierResourceQuery(input)}`,
    ),
  list: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleRisk>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/risks?${dossierResourceQuery(input)}`,
    ),
  get: (resourceId: string) =>
    request<OracleRisk>(`/api/v1/risks/${encodeURIComponent(resourceId)}`),
  create: (dossierId: string, input: components["schemas"]["RiskWriteInput"]) =>
    request<OracleRisk>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/risks`,
      { method: "POST", body: input },
    ),
  update: (
    resourceId: string,
    input: components["schemas"]["RiskWriteInput"],
    version: number,
  ) =>
    request<OracleRisk>(`/api/v1/risks/${encodeURIComponent(resourceId)}`, {
      method: "PATCH",
      body: input,
      ifMatch: version,
    }),
  evidence: (resourceId: string) => evidenceList("risks", resourceId),
};

export type OracleMeeting = components["schemas"]["MeetingResource"];
export type MeetingCompleteInput =
  components["schemas"]["MeetingCompleteInput"];
export type MeetingCompleteResponse =
  components["schemas"]["MeetingCompleteResponse"];
export type OracleTask = components["schemas"]["TaskResource"];
export type OracleActor = components["schemas"]["ActorResource"];
export type OracleDossierActor =
  components["schemas"]["DossierActorResource"] & {
    notes?: string;
    score_details?: Record<string, unknown>;
  };
export type OracleActorCandidate = components["schemas"]["ActorCandidate"];
export type OracleDecision = components["schemas"]["DecisionResource"] & {
  content?: Record<string, unknown>;
  rationale?: string;
  decided_at?: string | null;
  decided_by_user_id?: string | null;
};
export type OracleBriefing = components["schemas"]["BriefingResource"];
export type MeetingBriefingGeneration =
  components["schemas"]["MeetingBriefingGenerationResponse"];
export type OracleChange = components["schemas"]["ChangeItem"];
export type WeeklyChangeDigest =
  components["schemas"]["WeeklyChangeDigestResponse"];
export type GlobalSearchResult = components["schemas"]["GlobalSearchResult"];

const productHome = {
  get: () => request<components["schemas"]["HomeResponse"]>("/api/v1/home"),
};

const changes = {
  list: (
    input: {
      page?: number;
      size?: number;
      dossierId?: string;
      type?: string;
      since?: string;
      search?: string;
    } = {},
  ) => {
    const query = new URLSearchParams({
      "page[number]": String(input.page ?? 1),
      "page[size]": String(input.size ?? 10),
      sort: "-created_at",
    });
    if (input.dossierId) query.set("filter[dossier_id]", input.dossierId);
    if (input.type) query.set("filter[type]", input.type);
    if (input.since) query.set("filter[since]", input.since);
    if (input.search?.trim()) query.set("filter[search]", input.search.trim());
    return request<components["schemas"]["ChangeListResponse"]>(
      `/api/v1/changes?${query.toString()}`,
    );
  },
  digest: (input: { dossierId?: string } = {}) => {
    const query = new URLSearchParams();
    if (input.dossierId) query.set("filter[dossier_id]", input.dossierId);
    const suffix = query.toString();
    return request<WeeklyChangeDigest>(
      `/api/v1/changes/digest${suffix ? `?${suffix}` : ""}`,
    );
  },
  refreshDigest: (
    input: {
      dossierId?: string;
      periodStart?: string;
      periodEnd?: string;
      idempotencyKey?: string;
    } = {},
  ) =>
    request<WeeklyChangeDigest>("/api/v1/changes/digest", {
      method: "POST",
      body: {
        ...(input.dossierId ? { dossier_id: input.dossierId } : {}),
        ...(input.periodStart ? { period_start: input.periodStart } : {}),
        ...(input.periodEnd ? { period_end: input.periodEnd } : {}),
      },
      idempotencyKey: input.idempotencyKey,
    }),
};

const globalSearch = {
  query: (
    query: string,
    options: { limit?: number; types?: string[]; signal?: AbortSignal } = {},
  ) => {
    const params = new URLSearchParams({
      q: query.trim(),
      limit: String(options.limit ?? 5),
    });
    if (options.types?.length) params.set("types", options.types.join(","));
    return request<components["schemas"]["GlobalSearchResponse"]>(
      `/api/v1/search?${params.toString()}`,
      { signal: options.signal },
    );
  },
};

const meetings = {
  listGlobal: (input: DossierResourceQuery = {}) =>
    request<components["schemas"]["GlobalMeetingListResponse"]>(
      `/api/v1/meetings?${dossierResourceQuery(input)}`,
    ),
  list: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleMeeting>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/meetings?${dossierResourceQuery(input)}`,
    ),
  create: (
    dossierId: string,
    input: components["schemas"]["MeetingWriteInput"],
  ) =>
    request<OracleMeeting>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/meetings`,
      { method: "POST", body: input },
    ),
  update: (
    meetingId: string,
    input: components["schemas"]["MeetingWriteInput"],
    version: number,
  ) =>
    request<OracleMeeting>(
      `/api/v1/meetings/${encodeURIComponent(meetingId)}`,
      {
        method: "PATCH",
        body: input,
        ifMatch: version,
      },
    ),
  complete: (
    meetingId: string,
    input: MeetingCompleteInput,
    version: number,
    idempotencyKey: string,
  ) =>
    request<MeetingCompleteResponse>(
      `/api/v1/meetings/${encodeURIComponent(meetingId)}/complete`,
      {
        method: "POST",
        body: input,
        ifMatch: version,
        idempotencyKey,
      },
    ),
  briefings: (meetingId: string) =>
    request<DossierResourcePage<OracleBriefing>>(
      `/api/v1/meetings/${encodeURIComponent(meetingId)}/briefings?page%5Bnumber%5D=1&page%5Bsize%5D=25&sort=-created_at`,
    ),
  briefingState: (meetingId: string) =>
    request<MeetingBriefingGeneration>(
      `/api/v1/meetings/${encodeURIComponent(meetingId)}/briefing-state`,
    ),
  createBriefing: (meetingId: string, idempotencyKey?: string) =>
    request<MeetingBriefingGeneration>(
      `/api/v1/meetings/${encodeURIComponent(meetingId)}/briefings`,
      { method: "POST", body: {}, idempotencyKey },
    ),
};

const tasks = {
  listGlobal: (input: DossierResourceQuery = {}) =>
    request<components["schemas"]["GlobalTaskListResponse"]>(
      `/api/v1/tasks?${dossierResourceQuery(input)}`,
    ),
  list: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleTask>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/tasks?${dossierResourceQuery(input)}`,
    ),
  create: (dossierId: string, input: components["schemas"]["TaskWriteInput"]) =>
    request<OracleTask>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/tasks`,
      { method: "POST", body: input },
    ),
  update: (
    taskId: string,
    input: components["schemas"]["TaskWriteInput"],
    version: number,
  ) =>
    request<OracleTask>(`/api/v1/tasks/${encodeURIComponent(taskId)}`, {
      method: "PATCH",
      body: input,
      ifMatch: version,
    }),
};

const actors = {
  list: (input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleActor>>(
      `/api/v1/actors?${dossierResourceQuery(input)}`,
    ),
  get: (actorId: string) =>
    request<OracleActor>(`/api/v1/actors/${encodeURIComponent(actorId)}`),
  listDossier: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleDossierActor>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/actors?${dossierResourceQuery(input)}`,
    ),
  attach: (
    dossierId: string,
    input: components["schemas"]["DossierActorWriteInput"],
  ) =>
    request<OracleDossierActor>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/actors`,
      { method: "POST", body: input },
    ),
  candidates: (dossierId: string, includeDismissed = false) =>
    request<components["schemas"]["ActorCandidateListResponse"]>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/actor-candidates?include_dismissed=${includeDismissed}`,
    ),
  importCandidate: (
    dossierId: string,
    candidateId: string,
    input: components["schemas"]["ActorCandidateImportInput"],
  ) =>
    request<components["schemas"]["ActorCandidateImportResponse"]>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/actor-candidates/${encodeURIComponent(candidateId)}/import`,
      { method: "POST", body: input },
    ),
  reviewCandidate: (
    dossierId: string,
    candidateId: string,
    input: components["schemas"]["ActorCandidateReviewInput"],
  ) =>
    request<components["schemas"]["ActorCandidateReviewResponse"]>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/actor-candidates/${encodeURIComponent(candidateId)}/review`,
      { method: "POST", body: input },
    ),
  updateLink: (
    linkId: string,
    input: components["schemas"]["DossierActorWriteInput"],
    version: number,
  ) =>
    request<OracleDossierActor>(
      `/api/v1/dossier-actors/${encodeURIComponent(linkId)}`,
      { method: "PATCH", body: input, ifMatch: version },
    ),
};

const entityIntel = {
  suggest: (input: { q: string; kind?: EntityIntelKind; limit?: number }) => {
    const query = new URLSearchParams({
      q: input.q,
      kind: input.kind ?? "company",
      limit: String(input.limit ?? 8),
    });
    return request<EntityIntelSuggestResponse>(
      `/api/v1/entity-intel/suggest?${query.toString()}`,
    );
  },
  registry: (input: {
    name: string;
    type?: EntityIntelKind;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams({
      name: input.name,
      type: input.type ?? "company",
      limit: String(input.limit ?? 50),
      offset: String(input.offset ?? 0),
    });
    return request<EntityIntelRegistryResponse>(
      `/api/v1/entity-intel/registry?${query.toString()}`,
    );
  },
  dossier: (input: { name: string; type?: EntityIntelKind }) => {
    const query = new URLSearchParams({
      name: input.name,
      type: input.type ?? "company",
    });
    return request<EntityIntelDossierResponse>(
      `/api/v1/entity-intel/dossier?${query.toString()}`,
    );
  },
  graph: (input: {
    name: string;
    type?: EntityIntelKind;
    depth?: number;
    activeOnly?: boolean;
  }) => {
    const query = new URLSearchParams({
      name: input.name,
      type: input.type ?? "company",
      depth: String(input.depth ?? 2),
      active_only: String(input.activeOnly ?? false),
    });
    return request<EntityIntelGraphResponse>(
      `/api/v1/entity-intel/graph?${query.toString()}`,
    );
  },
  reports: (input: {
    name: string;
    type?: EntityIntelKind;
    limit?: number;
  }) => {
    const query = new URLSearchParams({
      name: input.name,
      type: input.type ?? "company",
      limit: String(input.limit ?? 10),
    });
    return request<EntityIntelReportListResponse>(
      `/api/v1/entity-intel/reports?${query.toString()}`,
    );
  },
  startReport: (
    input: { name: string; type?: EntityIntelKind },
    idempotencyKey: string,
  ) =>
    request<EntityIntelReportCreateResponse>("/api/v1/entity-intel/reports", {
      method: "POST",
      body: { name: input.name, type: input.type ?? "company" },
      idempotencyKey,
    }),
  incorporateReport: (jobId: string, input: { dossier_id: string }) =>
    request<EntityIntelReportIncorporateResponse>(
      `/api/v1/entity-intel/reports/${encodeURIComponent(jobId)}/incorporate`,
      { method: "POST", body: input },
    ),
};

const decisions = {
  list: (dossierId: string, input: DossierResourceQuery = {}) =>
    request<DossierResourcePage<OracleDecision>>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/decisions?${dossierResourceQuery(input)}`,
    ),
  create: (
    dossierId: string,
    input: components["schemas"]["DecisionWriteInput"],
  ) =>
    request<OracleDecision>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/decisions`,
      { method: "POST", body: input },
    ),
  update: (
    decisionId: string,
    input: components["schemas"]["DecisionWriteInput"],
    version: number,
  ) =>
    request<OracleDecision>(
      `/api/v1/decisions/${encodeURIComponent(decisionId)}`,
      { method: "PATCH", body: input, ifMatch: version },
    ),
};

export interface DocumentSearchResult {
  chunk_id: string;
  document_id: string;
  dossier_id: string;
  filename: string;
  media_type: string;
  classification: string;
  rank: number;
  snippet: string;
  text: string;
  locator: Record<string, unknown>;
}

export type OracleReport = components["schemas"]["ReportResponse"];
export type OracleNotification = components["schemas"]["NotificationResponse"];
export type NotificationPreference =
  components["schemas"]["NotificationPreferenceResponse"];
export type OracleExport = components["schemas"]["ExportResponse"];

export type EntityIntelKind = "company" | "person";

export interface EntityIntelSuggestResponse {
  kind: EntityIntelKind | string;
  suggestions: string[];
  cached_seconds: number;
  cache_hit: boolean;
}

export interface EntityIntelRegistryAct {
  company?: string | null;
  person?: string | null;
  role?: string | null;
  action?: "nombramiento" | "cese" | "socio" | string | null;
  date?: string | null;
  effective_date?: string | null;
  province?: string | null;
  source_url?: string | null;
  act_type?: string | null;
  details?: string | null;
  [key: string]: unknown;
}

export interface EntityIntelRegistryProfile {
  constitution_date?: string | null;
  constitution_published?: string | null;
  status?: "activa" | "disuelta" | "extinguida" | string | null;
  first_act_date?: string | null;
  last_act_date?: string | null;
  provinces?: string[];
  total_acts?: number | null;
  acts?: EntityIntelRegistryAct[];
  [key: string]: unknown;
}

export interface EntityIntelRegistryResponse {
  query?: unknown;
  company_norm?: unknown;
  person_norm?: unknown;
  total?: number | null;
  items: EntityIntelRegistryAct[];
  companies?: unknown[];
  roles?: unknown[];
  profile?: EntityIntelRegistryProfile | null;
  cached_seconds: number;
  cache_hit: boolean;
  [key: string]: unknown;
}

export interface EntityIntelSection<T = Record<string, unknown>> {
  ok: boolean;
  data?: T;
  error?: string | null;
  [key: string]: unknown;
}

export interface EntityIntelDossierResponse {
  entity: {
    name?: string | null;
    type?: EntityIntelKind | string | null;
    [key: string]: unknown;
  };
  sections: {
    registry?: EntityIntelSection<EntityIntelRegistryResponse>;
    graph?: EntityIntelSection<EntityIntelGraphResponse>;
    patents?: EntityIntelSection<Record<string, unknown>>;
    disclosures?: EntityIntelSection<Record<string, unknown>>;
    news?: EntityIntelSection<Record<string, unknown>>;
    [key: string]: EntityIntelSection<unknown> | undefined;
  };
  cached_seconds: number;
  cache_hit: boolean;
}

export interface EntityIntelGraphNode {
  id: string | number;
  label?: string;
  name?: string;
  type?: string;
  norm?: string;
  degree?: number;
  is_center?: boolean;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface EntityIntelGraphEdge {
  id?: string | number;
  source: string | number;
  target: string | number;
  role?: string;
  roles?: string[] | string;
  active?: boolean;
  date?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface EntityIntelGraphResponse {
  center?: unknown;
  nodes: EntityIntelGraphNode[];
  edges: EntityIntelGraphEdge[];
  truncated: boolean;
  note?: string | null;
  cached_seconds: number;
  cache_hit: boolean;
}

export type JobResponse = components["schemas"]["JobResponse"];

export interface EntityIntelReportJob extends JobResponse {
  entity?: string | null;
  entity_key?: string | null;
}

export interface EntityIntelReportListResponse {
  data: EntityIntelReportJob[];
}

export interface EntityIntelReportCreateResponse {
  job_id: string;
  job: JobResponse;
}

export interface EntityIntelReportIncorporateResponse {
  report: OracleReport;
  job: JobResponse;
}

export interface ProcurementTenderFilters {
  cpv?: string | null;
  min_amount?: number | null;
  max_amount?: number | null;
  deadline_before?: string | null;
  buyer?: string | null;
  region?: string | null;
  active?: boolean;
}

export interface ProcurementTenderQuery extends ProcurementTenderFilters {
  keywords?: string | null;
  limit?: number;
  offset?: number;
}

export interface ProcurementTenderItem {
  folder_id: string;
  title?: string | null;
  summary_feed?: string | null;
  buyer?: string | null;
  status?: string | null;
  cpv?: string[];
  amount?: number | null;
  deadline?: string | null;
  region?: string | null;
  source_url?: string | null;
  is_active?: boolean | null;
  llm_summary?: string | null;
  llm_summary_model?: string | null;
  llm_summary_at?: string | null;
  [key: string]: unknown;
}

export interface ProcurementTendersResponse {
  cache_hit: boolean;
  cached_seconds: number;
  filters?: Record<string, unknown>;
  items: ProcurementTenderItem[];
  keywords?: unknown;
  limit: number;
  offset: number;
  semantics?: Record<string, unknown>;
  total: number;
}

export interface ProcurementAwardQuery {
  company?: string | null;
  buyer?: string | null;
  limit?: number;
  offset?: number;
}

export type ProcurementSuggestKind = "winner" | "buyer";

export interface ProcurementSuggestQuery {
  q: string;
  kind: ProcurementSuggestKind;
  limit?: number;
}

export interface ProcurementSuggestResponse {
  kind: string;
  suggestions: string[];
  cached_seconds: number;
  cache_hit: boolean;
}

export interface ProcurementAwardItem {
  folder_id: string;
  lot_id?: string | null;
  title?: string | null;
  buyer?: string | null;
  winner?: string | null;
  is_ute?: boolean;
  award_amount?: number | null;
  cpv?: string[];
  status?: string | null;
  award_date?: string | null;
  source_url?: string | null;
  [key: string]: unknown;
}

export interface ProcurementAwardsResponse {
  buyer_norm: string;
  cache_hit: boolean;
  cached_seconds: number;
  company_norm: string;
  items: ProcurementAwardItem[];
  total: number;
}

export type ProcurementStatsResponse = components["schemas"]["StatsResponse"];
export type TenderSearchResource =
  components["schemas"]["TenderSearchResource"];
export type TenderSearchPayload = components["schemas"]["TenderSearchPayload"];
export type TenderSearchPatch = components["schemas"]["TenderSearchPatch"];

export interface TenderSearchListResponse {
  items: TenderSearchResource[];
}

export interface TenderSearchRunResponse {
  search: TenderSearchResource;
  results: ProcurementTendersResponse;
}

export interface TenderSummaryResponse {
  cached: boolean;
  item: ProcurementTenderItem;
}

export type DossierProcurementKind = "tender" | "award";

export interface DossierProcurementItem {
  id: string;
  tenant_id: string;
  dossier_id: string;
  kind: DossierProcurementKind;
  folder_id: string;
  snapshot: Record<string, unknown>;
  source_url?: string | null;
  evidence_id: string;
  pinned_by_user_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DossierProcurementListResponse {
  data: DossierProcurementItem[];
}

export interface ProcurementDocumentReportResponse {
  report: components["schemas"]["ReportResponse"];
  job_id: string;
  replayed: boolean;
}

function appendQuery(
  query: URLSearchParams,
  key: string,
  value: string | number | boolean | null | undefined,
) {
  if (value === undefined || value === null || value === "") return;
  query.set(key, String(value));
}

const procurement = {
  tenders: (input: ProcurementTenderQuery = {}) => {
    const query = new URLSearchParams({
      limit: String(input.limit ?? 25),
      offset: String(input.offset ?? 0),
    });
    appendQuery(query, "keywords", input.keywords?.trim());
    appendQuery(query, "cpv", input.cpv?.trim());
    appendQuery(query, "min_amount", input.min_amount);
    appendQuery(query, "max_amount", input.max_amount);
    appendQuery(query, "deadline_before", input.deadline_before);
    appendQuery(query, "buyer", input.buyer?.trim());
    appendQuery(query, "region", input.region?.trim());
    appendQuery(query, "active", input.active);
    return request<ProcurementTendersResponse>(
      `/api/v1/procurement/tenders?${query.toString()}`,
    );
  },
  summarizeTender: (folderId: string) =>
    request<TenderSummaryResponse>(
      `/api/v1/procurement/tenders/${encodeURIComponent(folderId)}/summary`,
      { method: "POST" },
    ),
  suggest: (input: ProcurementSuggestQuery) => {
    const query = new URLSearchParams({
      q: input.q.trim(),
      kind: input.kind,
      limit: String(input.limit ?? 8),
    });
    return request<ProcurementSuggestResponse>(
      `/api/v1/procurement/suggest?${query.toString()}`,
    );
  },
  awards: (input: ProcurementAwardQuery = {}) => {
    const query = new URLSearchParams({
      limit: String(input.limit ?? 25),
      offset: String(input.offset ?? 0),
    });
    appendQuery(query, "company", input.company?.trim());
    appendQuery(query, "buyer", input.buyer?.trim());
    return request<ProcurementAwardsResponse>(
      `/api/v1/procurement/awards?${query.toString()}`,
    );
  },
  stats: () => request<ProcurementStatsResponse>("/api/v1/procurement/stats"),
  searches: () =>
    request<TenderSearchListResponse>("/api/v1/procurement/tender-searches"),
  createSearch: (input: TenderSearchPayload) =>
    request<TenderSearchResource>("/api/v1/procurement/tender-searches", {
      method: "POST",
      body: input,
    }),
  patchSearch: (searchId: string, input: TenderSearchPatch) =>
    request<TenderSearchResource>(
      `/api/v1/procurement/tender-searches/${encodeURIComponent(searchId)}`,
      { method: "PATCH", body: input },
    ),
  deleteSearch: (searchId: string) =>
    request<TenderSearchResource>(
      `/api/v1/procurement/tender-searches/${encodeURIComponent(searchId)}`,
      { method: "DELETE" },
    ),
  runSearch: (
    searchId: string,
    input: { limit?: number; offset?: number } = {},
  ) => {
    const query = new URLSearchParams({
      limit: String(input.limit ?? 25),
      offset: String(input.offset ?? 0),
    });
    return request<TenderSearchRunResponse>(
      `/api/v1/procurement/tender-searches/${encodeURIComponent(searchId)}/run?${query.toString()}`,
    );
  },
};

const dossierProcurement = {
  list: (dossierId: string) =>
    request<DossierProcurementListResponse>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/procurement`,
    ),
  pin: (
    dossierId: string,
    input: { kind: DossierProcurementKind; folder_id: string },
  ) =>
    request<DossierProcurementItem>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/procurement`,
      { method: "POST", body: input },
    ),
  remove: (dossierId: string, itemId: string) =>
    request<{ deleted: boolean; id: string }>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/procurement/${encodeURIComponent(itemId)}`,
      { method: "DELETE" },
    ),
  createDocumentReport: (
    dossierId: string,
    input: { options?: Record<string, unknown> } = {},
    idempotencyKey = `procurement-report-${dossierId}-${Date.now()}`,
  ) =>
    request<ProcurementDocumentReportResponse>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/procurement/reports`,
      { method: "POST", body: input, idempotencyKey },
    ),
};

const reports = {
  templates: () =>
    request<components["schemas"]["ReportTemplateListResponse"]>(
      "/api/v1/report-templates",
    ),
  list: (page = 1, size = 25, status?: string) => {
    const query = new URLSearchParams({
      "page[number]": String(page),
      "page[size]": String(size),
    });
    if (status) query.set("filter[status]", status);
    return request<components["schemas"]["ReportListResponse"]>(
      `/api/v1/reports?${query.toString()}`,
    );
  },
  listDossier: (dossierId: string, page = 1, size = 25) =>
    request<components["schemas"]["ReportListResponse"]>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/reports?page[number]=${page}&page[size]=${size}`,
    ),
  get: (reportId: string) =>
    request<OracleReport>(`/api/v1/reports/${encodeURIComponent(reportId)}`),
  generate: (
    dossierId: string,
    input: components["schemas"]["ReportGenerateInput"],
    idempotencyKey: string,
  ) =>
    request<components["schemas"]["ReportEnqueueResponse"]>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/reports`,
      { method: "POST", body: input, idempotencyKey },
    ),
  retry: (reportId: string, idempotencyKey: string) =>
    request<components["schemas"]["ReportEnqueueResponse"]>(
      `/api/v1/reports/${encodeURIComponent(reportId)}/retry`,
      { method: "POST", body: {}, idempotencyKey },
    ),
  revise: (
    reportId: string,
    input: components["schemas"]["ReportRevisionInput"],
  ) =>
    request<OracleReport>(
      `/api/v1/reports/${encodeURIComponent(reportId)}/revisions`,
      { method: "POST", body: input },
    ),
  review: (
    reportId: string,
    input: components["schemas"]["ReportReviewInput"],
  ) =>
    request<components["schemas"]["ReportReviewResponse"]>(
      `/api/v1/reports/${encodeURIComponent(reportId)}/reviews`,
      { method: "POST", body: input },
    ),
  publish: (reportId: string, version: number) =>
    request<OracleReport>(
      `/api/v1/reports/${encodeURIComponent(reportId)}/publish`,
      { method: "POST", body: { version } },
    ),
  downloadLink: (reportId: string, artifactId: string) =>
    request<components["schemas"]["DownloadLinkResponse"]>(
      `/api/v1/reports/${encodeURIComponent(reportId)}/artifacts/${encodeURIComponent(artifactId)}/download-link`,
      { method: "POST" },
    ),
};

const notifications = {
  list: (page = 1, size = 25) =>
    request<components["schemas"]["NotificationListResponse"]>(
      `/api/v1/notifications?page[number]=${page}&page[size]=${size}`,
    ),
  read: (id: string) =>
    request<OracleNotification>(
      `/api/v1/notifications/${encodeURIComponent(id)}/read`,
      { method: "POST" },
    ),
  readAll: () =>
    request<components["schemas"]["NotificationReadAllResponse"]>(
      "/api/v1/notifications/read-all",
      { method: "POST" },
    ),
  dismiss: (id: string) =>
    request<OracleNotification>(
      `/api/v1/notifications/${encodeURIComponent(id)}/dismiss`,
      { method: "POST" },
    ),
  preferences: () =>
    request<components["schemas"]["NotificationPreferenceListResponse"]>(
      "/api/v1/notification-preferences",
    ),
  updatePreference: (
    input: components["schemas"]["NotificationPreferenceInput"],
  ) =>
    request<NotificationPreference>("/api/v1/notification-preferences", {
      method: "PATCH",
      body: input,
    }),
};

const exportsApi = {
  list: (page = 1, size = 25) =>
    request<components["schemas"]["ExportListResponse"]>(
      `/api/v1/exports?page[number]=${page}&page[size]=${size}`,
    ),
  create: (
    input: components["schemas"]["ExportCreateInput"],
    idempotencyKey: string,
  ) =>
    request<components["schemas"]["ExportEnqueueResponse"]>("/api/v1/exports", {
      method: "POST",
      body: input,
      idempotencyKey,
    }),
  get: (id: string) =>
    request<OracleExport>(`/api/v1/exports/${encodeURIComponent(id)}`),
  downloadLink: (id: string) =>
    request<components["schemas"]["DownloadLinkResponse"]>(
      `/api/v1/exports/${encodeURIComponent(id)}/download-link`,
      { method: "POST" },
    ),
};

const documents = {
  list: (dossierId: string) =>
    request<{ items: OracleDocument[] }>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/documents`,
    ),
  get: (documentId: string) =>
    request<OracleDocument>(
      `/api/v1/documents/${encodeURIComponent(documentId)}`,
    ),
  upload: (
    dossierId: string,
    file: File,
    classification: "public" | "internal",
  ) => {
    const body = new FormData();
    body.set("file", file);
    body.set("classification", classification);
    return request<{ document: OracleDocument; job_id: string }>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/documents`,
      { method: "POST", body },
    );
  },
  search: (dossierId: string, query: string) =>
    request<{ items: DocumentSearchResult[] }>(
      `/api/v1/dossiers/${encodeURIComponent(dossierId)}/search?q=${encodeURIComponent(query)}`,
    ),
  reprocess: (documentId: string) =>
    request<{ document: OracleDocument; job_id: string }>(
      `/api/v1/documents/${encodeURIComponent(documentId)}/reprocess`,
      { method: "POST" },
    ),
  remove: (documentId: string) =>
    request<void>(`/api/v1/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    }),
  createEvidence: (
    documentId: string,
    chunkId: string,
    start: number,
    end: number,
  ) =>
    request<{ id: string; extract: string; locator: Record<string, unknown> }>(
      `/api/v1/documents/${encodeURIComponent(documentId)}/create-evidence`,
      { method: "POST", body: { chunk_id: chunkId, start, end } },
    ),
};

export const api = {
  auth,
  tenantAdmin,
  platform,
  jobs,
  signalAvanza,
  dossiers,
  oracleSummary,
  dossierSignals,
  objectives,
  hypotheses,
  dossierEvidence,
  opportunities,
  risks,
  home: productHome,
  changes,
  search: globalSearch,
  meetings,
  tasks,
  actors,
  entityIntel,
  procurement,
  dossierProcurement,
  decisions,
  documents,
  reports,
  notifications,
  exports: exportsApi,
};
