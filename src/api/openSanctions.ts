export type EntityExample = {
  schema: string; // "Person" | "Company" | "Organization"
  properties: Record<string, any>;
};

export type EntityMatchQuery = {
  queries: Record<string, EntityExample>;
  weights?: Record<string, number>;
  config?: Record<string, any>;
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

function env(name: string, fallback = ""): string {
  const v = (import.meta.env[name] as string) ?? fallback;
  return String(v).trim();
}

function normalizeBaseUrl(raw: string): string {
  const v = String(raw ?? "").trim();
  if (!v) throw new Error("Missing VITE_OPENSANCTIONS_BASE_URL");

  // If it's already absolute -> use it
  if (v.startsWith("http://") || v.startsWith("https://")) {
    return v.replace(/\/$/, "");
  }

  // If it's relative (proxy path) -> make absolute using current origin
  if (v.startsWith("/")) {
    return new URL(v, window.location.origin).toString().replace(/\/$/, "");
  }

  // If someone put "api.opensanctions.org" without scheme -> assume https
  return `https://${v}`.replace(/\/$/, "");
}

export async function matchBatch(queries: Record<string, EntityExample>): Promise<EntityMatchResponse> {
  const baseUrl = normalizeBaseUrl(env("VITE_OPENSANCTIONS_BASE_URL"));
  const dataset = env("VITE_OPENSANCTIONS_DATASET", "sanctions");

  const threshold = env("VITE_OPENSANCTIONS_THRESHOLD", "0.7");
  const limit = env("VITE_OPENSANCTIONS_LIMIT", "5");
  const algorithm = env("VITE_OPENSANCTIONS_ALGORITHM", "logic-v2");

  const url = new URL(`${baseUrl}/match/${encodeURIComponent(dataset)}`);
  url.searchParams.set("threshold", threshold);
  url.searchParams.set("limit", limit);
  url.searchParams.set("algorithm", algorithm);

  const apiKey = env("VITE_OPENSANCTIONS_API_KEY");
  const headerName = env("VITE_OPENSANCTIONS_API_KEY_HEADER", "Authorization");
  const prefix = env("VITE_OPENSANCTIONS_API_KEY_PREFIX", "ApiKey");

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers[headerName] = prefix ? `${prefix} ${apiKey}` : apiKey;

  const body: EntityMatchQuery = { queries };

  const resp = await fetch(url.toString(), {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`OpenSanctions /match error ${resp.status}: ${txt}`);
  }

  return (await resp.json()) as EntityMatchResponse;
}
