import { getAccessToken } from "../auth/session";
import { appEnv } from "../config/env";

export type EntityExample = {
  schema: string;
  properties: Record<string, any>;
};

export type EntityMatchQuery = {
  queries: Record<string, EntityExample>;
  screening_types?: string[];
  mock_screening?: boolean;
  business_unit_code?: string;
  daily_screening?: boolean;
  schedule_frequency?: string;
  schedule_id?: string;
  source_upload_id?: string;
  batch_name?: string;
  user_id?: string;
  user_name?: string;
};

export type ScoredEntity = {
  id: string;
  caption: string;
  schema: string;
  score: number;
  match: boolean;
  datasets?: string[];
  properties?: Record<string, any>;
};

export type EntityMatches = {
  results: ScoredEntity[];
  total: { value: number; relation?: string };
  query: EntityExample;
  status?: number;
  error_text?: string | null;
};

export type EntityMatchResponse = {
  responses: Record<string, EntityMatches>;
  limit: number;
  dailyScheduleId?: string;
};

export type DailySchedule = {
  schedule_id: string;
  batch_name: string;
  user_id?: string | null;
  user_name?: string | null;
  business_unit_code?: string | null;
  screening_types: string[];
  schedule_frequency?: string;
  timezone: string;
  run_hour: number;
  run_minute: number;
  created_at: string;
  last_run_at?: string | null;
  next_run_at: string;
  total_items: number;
  is_active: boolean;
  source_file_name?: string | null;
  source_s3_uri?: string | null;
  source_upload_id?: string | null;
};

export type ScheduleSubscription = {
  subscription_id: string;
  schedule_id: string;
  user_id?: string | null;
  user_name?: string | null;
  email: string;
  is_active: boolean;
  created_at: string;
};

export type AuditEvent = {
  event_id: number;
  created_at: string;
  user_id?: string | null;
  user_name?: string | null;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  details?: Record<string, unknown>;
};

export type SubmissionHistoryEntry = Record<string, unknown>;

export type BusinessUnit = {
  business_unit_code: string;
  business_unit_name: string;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type UserBusinessUnitMapping = {
  user_id: string;
  user_name?: string | null;
  business_unit_codes: string[];
};

export type AdminUserOption = {
  user_id: string;
  display_name: string;
};

export type JobStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";

export type JobAccepted = {
  job_id: string;
  status: JobStatus;
  submitted_at: string;
  total_items: number;
  business_unit_code?: string;
  daily_schedule_id?: string;
  screened_item_keys?: string[];
};

export type BatchUploadAccepted = {
  job_id: string;
  status: JobStatus;
  submitted_at: string;
  total_items: number;
  business_unit_code?: string;
  daily_schedule_id?: string;
  screened_item_keys?: string[];
  source_upload_id?: string;
  file_name: string;
  s3_uri?: string | null;
  schedule_frequency?: string | null;
};

export type JobProgress = {
  job_id: string;
  status: JobStatus;
  submitted_at: string;
  total_items: number;
  completed_items: number;
  failed_items: number;
  pending_items: number;
  processing_items: number;
  responses?: Record<string, EntityMatches>;
  limit?: number;
};

function env(name: string, fallback = ""): string {
  return appEnv(name, fallback);
}

function normalizeBaseUrl(raw: string): string {
  const v = String(raw ?? "").trim();
  if (!v) throw new Error("Missing VITE_SCREENING_API_BASE_URL");

  if (v.startsWith("http://") || v.startsWith("https://")) {
    return v.replace(/\/$/, "");
  }

  if (v.startsWith("/")) {
    return new URL(v, window.location.origin).toString().replace(/\/$/, "");
  }

  return `https://${v}`.replace(/\/$/, "");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function parseApiError(resp: Response): Promise<string> {
  const raw = await resp.text();
  if (!raw) return `${resp.status} ${resp.statusText}`;

  try {
    const json = JSON.parse(raw) as { detail?: string };
    if (json?.detail) return `${resp.status}: ${json.detail}`;
  } catch {
    // ignore json parse errors
  }

  const contentType = (resp.headers.get("content-type") ?? "").toLowerCase();
  const looksLikeHtml = contentType.includes("text/html") || /^\s*</.test(raw);
  if (looksLikeHtml) {
    if (resp.status === 504) {
      return "504: Gateway Timeout. Please retry in a moment (your upload may still be processing).";
    }
    return `${resp.status}: ${resp.statusText || "Request failed"}`;
  }

  const trimmed = raw.trim();
  const truncated = trimmed.length > 800 ? `${trimmed.slice(0, 800)}…` : trimmed;
  return `${resp.status}: ${truncated}`;
}

function withAuthHeaders(headers: Record<string, string> = {}): Record<string, string> {
  const merged: Record<string, string> = { ...headers };
  const token = getAccessToken();
  if (token) {
    merged.Authorization = `Bearer ${token}`;
  }
  return merged;
}

type BatchOptions = {
  dailyScreening?: boolean;
  scheduleFrequency?: string;
  scheduleId?: string;
  sourceUploadId?: string;
  businessUnitCode?: string;
  batchName?: string;
  userId?: string;
  userName?: string;
};

function buildBatchBody(
  queries: Record<string, EntityExample>,
  screeningTypes: string[] = [],
  options: BatchOptions = {}
): EntityMatchQuery {
  const body: EntityMatchQuery = { queries };
  if (screeningTypes.length) body.screening_types = screeningTypes;
  if (options.dailyScreening) body.daily_screening = true;
  if (options.scheduleFrequency && options.scheduleFrequency.trim()) body.schedule_frequency = options.scheduleFrequency.trim();
  if (options.scheduleId && options.scheduleId.trim()) body.schedule_id = options.scheduleId.trim();
  if (options.sourceUploadId && options.sourceUploadId.trim()) body.source_upload_id = options.sourceUploadId.trim();
  if (options.businessUnitCode && options.businessUnitCode.trim()) body.business_unit_code = options.businessUnitCode.trim();
  if (options.batchName && options.batchName.trim()) body.batch_name = options.batchName.trim();
  if (options.userId && options.userId.trim()) body.user_id = options.userId.trim();
  if (options.userName && options.userName.trim()) body.user_name = options.userName.trim();
  return body;
}

type BatchUploadRequest = {
  file: File;
  queries: Record<string, EntityExample>;
  screeningTypes?: string[];
  batchName: string;
  dailyScreening?: boolean;
  scheduleFrequency?: "DAILY" | "WEEKLY" | "MONTHLY";
  scheduleRunAt?: string;
  scheduleId?: string;
  businessUnitCode?: string;
  mockScreening?: boolean;
  subscribeResults?: boolean;
  subscribeEmail?: string;
  subscribeEmails?: string[];
  userName?: string;
};

export async function uploadBatchAndSubmitJob(payload: BatchUploadRequest): Promise<BatchUploadAccepted> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const form = new FormData();
  form.set("file", payload.file);
  form.set("queries_json", JSON.stringify(payload.queries));
  form.set("screening_types_json", JSON.stringify(payload.screeningTypes ?? []));
  form.set("batch_name", payload.batchName);
  form.set("daily_screening", payload.dailyScreening ? "true" : "false");
  if (payload.scheduleFrequency) form.set("schedule_frequency", payload.scheduleFrequency);
  if (payload.scheduleRunAt && payload.scheduleRunAt.trim()) form.set("schedule_run_at", payload.scheduleRunAt.trim());
  if (payload.scheduleId && payload.scheduleId.trim()) form.set("schedule_id", payload.scheduleId.trim());
  if (payload.businessUnitCode && payload.businessUnitCode.trim()) form.set("business_unit_code", payload.businessUnitCode.trim());
  form.set("mock_screening", payload.mockScreening ? "true" : "false");
  form.set("subscribe_results", payload.subscribeResults ? "true" : "false");
  if (payload.subscribeEmail && payload.subscribeEmail.trim()) form.set("subscribe_email", payload.subscribeEmail.trim());
  if (payload.subscribeEmails?.length) form.set("subscribe_emails", payload.subscribeEmails.join(","));
  if (payload.userName && payload.userName.trim()) form.set("user_name", payload.userName.trim());

  const resp = await fetch(`${baseUrl}/screenings/batch-upload`, {
    method: "POST",
    headers: withAuthHeaders(),
    body: form,
  });
  if (!resp.ok) {
    throw new Error(`Failed to submit batch upload: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as BatchUploadAccepted;
}

export async function submitScreeningJob(
  queries: Record<string, EntityExample>,
  screeningTypes: string[] = [],
  options: BatchOptions = {}
): Promise<JobAccepted> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const body = buildBatchBody(queries, screeningTypes, options);
  const createResp = await fetch(`${baseUrl}/screenings/jobs`, {
    method: "POST",
    headers: withAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });

  if (!createResp.ok) {
    throw new Error(`Failed to submit screening job: ${await parseApiError(createResp)}`);
  }
  return (await createResp.json()) as JobAccepted;
}

export async function getScreeningJob(jobId: string): Promise<JobProgress> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const statusResp = await fetch(`${baseUrl}/screenings/jobs/${encodeURIComponent(jobId)}`, {
    headers: withAuthHeaders(),
  });
  if (!statusResp.ok) {
    throw new Error(`Failed to check screening job status: ${await parseApiError(statusResp)}`);
  }
  return (await statusResp.json()) as JobProgress;
}

export async function waitForScreeningJob(
  jobId: string,
  options: { pollMs?: number; timeoutMs?: number } = {}
): Promise<JobProgress> {
  const pollMs = options.pollMs ?? Number(env("VITE_SCREENING_POLL_INTERVAL_MS", "750"));
  const timeoutMs = options.timeoutMs ?? Number(env("VITE_SCREENING_JOB_TIMEOUT_MS", "90000"));
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const progress = await getScreeningJob(jobId);
    if (progress.status === "COMPLETED" || progress.status === "FAILED") {
      return progress;
    }
    await sleep(Math.max(200, pollMs));
  }

  throw new Error(`Screening job ${jobId} timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
}

export async function matchBatch(
  queries: Record<string, EntityExample>,
  screeningTypes: string[] = [],
  options: BatchOptions = {}
): Promise<EntityMatchResponse> {
  const accepted = await submitScreeningJob(queries, screeningTypes, options);
  const progress = await waitForScreeningJob(accepted.job_id);
  if (progress.status === "FAILED") {
    throw new Error(`Screening job ${progress.job_id} failed.`);
  }

  return {
    responses: progress.responses ?? {},
    limit: typeof progress.limit === "number" ? progress.limit : 5,
    dailyScheduleId: accepted.daily_schedule_id,
  };
}

export async function matchSync(
  queries: Record<string, EntityExample>,
  screeningTypes: string[] = [],
  mockScreening = false,
  user?: { id: string; name: string },
  businessUnitCode?: string
): Promise<EntityMatchResponse> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const body: EntityMatchQuery = { queries };
  if (screeningTypes.length) body.screening_types = screeningTypes;
  body.mock_screening = Boolean(mockScreening);
  if (businessUnitCode && businessUnitCode.trim()) body.business_unit_code = businessUnitCode.trim();
  if (user?.id) body.user_id = user.id;
  if (user?.name) body.user_name = user.name;

  const resp = await fetch(`${baseUrl}/screenings/match`, {
    method: "POST",
    headers: withAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    throw new Error(`Failed to run synchronous screening: ${await parseApiError(resp)}`);
  }

  return (await resp.json()) as EntityMatchResponse;
}

export async function listAuditEvents(limit = 200, userId?: string, offset = 0): Promise<AuditEvent[]> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const url = new URL(`${baseUrl}/audit-events`, window.location.origin);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(Math.max(0, offset)));
  if (userId && userId.trim()) {
    url.searchParams.set("user_id", userId.trim());
  }
  const resp = await fetch(url.toString(), {
    headers: withAuthHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to load audit events: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as AuditEvent[];
}

export async function listDailySchedules(): Promise<DailySchedule[]> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const resp = await fetch(`${baseUrl}/screenings/daily-schedules`, {
    headers: withAuthHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to load daily schedules: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as DailySchedule[];
}

export async function listMyBusinessUnits(): Promise<BusinessUnit[]> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const resp = await fetch(`${baseUrl}/business-units`, {
    headers: withAuthHeaders(),
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new Error(`Failed to load business units: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as BusinessUnit[];
}

export async function listAdminBusinessUnits(includeInactive = true): Promise<BusinessUnit[]> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const url = new URL(`${baseUrl}/admin/business-units`, window.location.origin);
  url.searchParams.set("include_inactive", includeInactive ? "true" : "false");
  const resp = await fetch(url.toString(), {
    headers: withAuthHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to load business units: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as BusinessUnit[];
}

export async function createAdminBusinessUnit(code: string, name: string): Promise<BusinessUnit> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const resp = await fetch(`${baseUrl}/admin/business-units`, {
    method: "POST",
    headers: withAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ business_unit_code: code, business_unit_name: name }),
  });
  if (!resp.ok) {
    throw new Error(`Failed to create business unit: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as BusinessUnit;
}

export async function updateAdminBusinessUnit(
  currentCode: string,
  nextCode: string,
  nextName: string
): Promise<BusinessUnit> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const resp = await fetch(`${baseUrl}/admin/business-units/${encodeURIComponent(currentCode)}`, {
    method: "PUT",
    headers: withAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ business_unit_code: nextCode, business_unit_name: nextName }),
  });
  if (!resp.ok) {
    throw new Error(`Failed to update business unit: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as BusinessUnit;
}

export async function deleteAdminBusinessUnit(code: string): Promise<void> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const resp = await fetch(`${baseUrl}/admin/business-units/${encodeURIComponent(code)}`, {
    method: "DELETE",
    headers: withAuthHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to delete business unit: ${await parseApiError(resp)}`);
  }
}

export async function listBusinessUnitMappings(): Promise<UserBusinessUnitMapping[]> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const resp = await fetch(`${baseUrl}/admin/business-unit-mappings`, {
    headers: withAuthHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to load business unit mappings: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as UserBusinessUnitMapping[];
}

export async function listAdminUsers(): Promise<AdminUserOption[]> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const resp = await fetch(`${baseUrl}/admin/users`, {
    headers: withAuthHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to load users: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as AdminUserOption[];
}

export async function updateBusinessUnitMapping(
  userId: string,
  payload: { userName?: string; businessUnitCodes: string[] }
): Promise<UserBusinessUnitMapping> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const resp = await fetch(`${baseUrl}/admin/business-unit-mappings/${encodeURIComponent(userId)}`, {
    method: "PUT",
    headers: withAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      user_name: payload.userName,
      business_unit_codes: payload.businessUnitCodes,
    }),
  });
  if (!resp.ok) {
    throw new Error(`Failed to update business unit mapping: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as UserBusinessUnitMapping;
}

export async function removeDailySchedule(scheduleId: string, user?: { id?: string; name?: string }): Promise<void> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const url = new URL(`${baseUrl}/screenings/daily-schedules/${encodeURIComponent(scheduleId)}`, window.location.origin);
  if (user?.id) url.searchParams.set("user_id", user.id);
  if (user?.name) url.searchParams.set("user_name", user.name);

  const resp = await fetch(url.toString(), {
    method: "DELETE",
    headers: withAuthHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to remove daily schedule: ${await parseApiError(resp)}`);
  }
}

export async function subscribeToDailySchedule(scheduleId: string, email?: string): Promise<ScheduleSubscription> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const url = new URL(`${baseUrl}/screenings/daily-schedules/${encodeURIComponent(scheduleId)}/subscriptions`, window.location.origin);
  if (email && email.trim()) {
    url.searchParams.set("email", email.trim());
  }
  const resp = await fetch(url.toString(), {
    method: "POST",
    headers: withAuthHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to subscribe to schedule: ${await parseApiError(resp)}`);
  }
  return (await resp.json()) as ScheduleSubscription;
}

export async function listScreeningSubmissions(limit = 200): Promise<SubmissionHistoryEntry[]> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const url = new URL(`${baseUrl}/screenings/submissions`, window.location.origin);
  url.searchParams.set("limit", String(limit));
  const resp = await fetch(url.toString(), {
    headers: withAuthHeaders(),
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new Error(`Failed to load screening submissions: ${await parseApiError(resp)}`);
  }
  const parsed = (await resp.json()) as unknown;
  return Array.isArray(parsed) ? (parsed as SubmissionHistoryEntry[]) : [];
}
