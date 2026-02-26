import { getAccessToken } from "../auth/session";

export type EntityExample = {
  schema: string;
  properties: Record<string, any>;
};

export type EntityMatchQuery = {
  queries: Record<string, EntityExample>;
  screening_types?: string[];
  mock_screening?: boolean;
  daily_screening?: boolean;
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
};

export type EntityMatchResponse = {
  responses: Record<string, EntityMatches>;
  limit: number;
  dailyScheduleId?: string;
};

export type DailySchedule = {
  schedule_id: string;
  batch_name: string;
  screening_types: string[];
  timezone: string;
  run_hour: number;
  run_minute: number;
  created_at: string;
  last_run_at?: string | null;
  next_run_at: string;
  total_items: number;
  is_active: boolean;
};

export type JobStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";

export type JobAccepted = {
  job_id: string;
  status: JobStatus;
  submitted_at: string;
  total_items: number;
  daily_schedule_id?: string;
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
  const v = (import.meta.env[name] as string) ?? fallback;
  return String(v).trim();
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

  return `${resp.status}: ${raw}`;
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
  if (options.batchName && options.batchName.trim()) body.batch_name = options.batchName.trim();
  if (options.userId && options.userId.trim()) body.user_id = options.userId.trim();
  if (options.userName && options.userName.trim()) body.user_name = options.userName.trim();
  return body;
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
  user?: { id: string; name: string }
): Promise<EntityMatchResponse> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const body: EntityMatchQuery = { queries };
  if (screeningTypes.length) body.screening_types = screeningTypes;
  body.mock_screening = Boolean(mockScreening);
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
