export type EntityExample = {
  schema: string;
  properties: Record<string, any>;
};

export type EntityMatchQuery = {
  queries: Record<string, EntityExample>;
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
};

type JobStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";

type JobAccepted = {
  job_id: string;
  status: JobStatus;
  submitted_at: string;
  total_items: number;
};

type JobProgress = {
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

export async function matchBatch(queries: Record<string, EntityExample>): Promise<EntityMatchResponse> {
  const baseUrl = normalizeBaseUrl(env("VITE_SCREENING_API_BASE_URL", "/api/v1"));
  const pollMs = Number(env("VITE_SCREENING_POLL_INTERVAL_MS", "750"));
  const timeoutMs = Number(env("VITE_SCREENING_JOB_TIMEOUT_MS", "90000"));

  const createResp = await fetch(`${baseUrl}/screenings/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ queries } satisfies EntityMatchQuery),
  });

  if (!createResp.ok) {
    throw new Error(`Failed to submit screening job: ${await parseApiError(createResp)}`);
  }

  const accepted = (await createResp.json()) as JobAccepted;
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const statusResp = await fetch(`${baseUrl}/screenings/jobs/${encodeURIComponent(accepted.job_id)}`);
    if (!statusResp.ok) {
      throw new Error(`Failed to check screening job status: ${await parseApiError(statusResp)}`);
    }

    const progress = (await statusResp.json()) as JobProgress;
    if (progress.status === "COMPLETED") {
      return {
        responses: progress.responses ?? {},
        limit: typeof progress.limit === "number" ? progress.limit : 5,
      };
    }

    if (progress.status === "FAILED") {
      throw new Error(`Screening job ${progress.job_id} failed.`);
    }

    await sleep(Math.max(200, pollMs));
  }

  throw new Error(`Screening job ${accepted.job_id} timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
}

