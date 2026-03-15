import { atom, type AtomEffect } from "recoil";

export type ScreeningMode = "SINGLE" | "BATCH";
export type HitResult = "HIT" | "NO_HIT" | "PROCESSING" | "FAILED" | "ERROR";
export type ScreeningWorkspaceMode = "SINGLE" | "BATCH" | "SCHEDULE";
export type ScreeningResultStatusFilter = "All Statuses" | "Clear" | "Potential Match" | "Pending" | "Failed" | "Match";
export type ScreeningResultTypeFilter = "All Types" | "Individual" | "Organization" | "Unknown" | "Vessel" | "Aircraft";
export type ScreeningResultSortKey = "entity" | "mode" | "type" | "country" | "status" | "score" | "submittedAt";
export type ScreeningResultSortDirection = "asc" | "desc";

export type SingleSubmission = {
  id: string;
  createdAt: string; // ISO string
  mode: "SINGLE";
  createdByUserId?: string;
  createdByUserName?: string;
  businessUnitCode?: string;
  customerType: "Person" | "Entity";
  displayName: string;
  result: HitResult;
  screeningTypes?: string[];
  message?: string;
  details?: unknown;
};

export type BatchItem = {
  displayName: string;
  customerType: "Person" | "Entity";
  result: HitResult;
  message?: string;
  details?: unknown;
};

export type BatchSubmission = {
  id: string;
  createdAt: string;
  mode: "BATCH";
  createdByUserId?: string;
  createdByUserName?: string;
  businessUnitCode?: string;
  jobId?: string;
  fileName: string;
  overallResult: HitResult;
  screeningTypes?: string[];
  dailyScreening?: boolean;
  scheduleFrequency?: "DAILY" | "WEEKLY" | "MONTHLY";
  dailyScheduleId?: string;
  dailyScheduleActive?: boolean;
  sourceUploadId?: string;
  sourceS3Uri?: string;
  items: BatchItem[];
};

export type Submission = SingleSubmission | BatchSubmission;

const STORAGE_PREFIX = "ofac-screening";

function createLocalStorageEffect<T>(
  storageKey: string,
  parse: (value: unknown) => T | null
): AtomEffect<T> {
  return ({ setSelf, onSet }) => {
    if (typeof window === "undefined") return;

    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw != null) {
        const parsed = parse(JSON.parse(raw));
        if (parsed != null) {
          setSelf(parsed);
        } else {
          window.localStorage.removeItem(storageKey);
        }
      }
    } catch {
      window.localStorage.removeItem(storageKey);
    }

    onSet((newValue, _, isReset) => {
      try {
        if (isReset) {
          window.localStorage.removeItem(storageKey);
          return;
        }
        window.localStorage.setItem(storageKey, JSON.stringify(newValue));
      } catch {
        // Ignore storage quota and browser policy errors.
      }
    });
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseSubmission(value: unknown): Submission | null {
  if (!isRecord(value)) return null;
  const mode = value.mode;
  const id = typeof value.id === "string" ? value.id : "";
  const createdAt = typeof value.createdAt === "string" ? value.createdAt : "";
  if (!id || !createdAt) return null;

  if (mode === "SINGLE") {
    const customerType = value.customerType;
    const displayName = typeof value.displayName === "string" ? value.displayName : "";
    const result = value.result;
    if ((customerType !== "Person" && customerType !== "Entity") || typeof displayName !== "string" || typeof result !== "string") {
      return null;
    }
    return value as SingleSubmission;
  }

  if (mode === "BATCH") {
    const fileName = typeof value.fileName === "string" ? value.fileName : "";
    const overallResult = value.overallResult;
    const items = value.items;
    if (!fileName || typeof overallResult !== "string" || !Array.isArray(items)) {
      return null;
    }
    return value as BatchSubmission;
  }

  return null;
}

function parseSubmissions(value: unknown): Submission[] | null {
  if (!Array.isArray(value)) return null;
  const parsed = value.map(parseSubmission).filter((item): item is Submission => item !== null);
  return parsed;
}

function parseLatestSubmission(value: unknown): Submission | null {
  if (value == null) return null;
  return parseSubmission(value);
}

function parseScreeningWorkspaceState(value: unknown): ScreeningWorkspaceState | null {
  if (!isRecord(value)) return null;
  const mode = value.mode;
  const search = typeof value.search === "string" ? value.search : "";
  const statusFilter = value.statusFilter;
  const typeFilter = value.typeFilter;
  const resultSortKey = value.resultSortKey;
  const resultSortDirection = value.resultSortDirection;
  const page = typeof value.page === "number" && Number.isFinite(value.page) ? Math.max(1, Math.floor(value.page)) : 1;

  if (mode !== "SINGLE" && mode !== "BATCH" && mode !== "SCHEDULE") return null;
  if (
    statusFilter !== "All Statuses" &&
    statusFilter !== "Clear" &&
    statusFilter !== "Potential Match" &&
    statusFilter !== "Pending" &&
    statusFilter !== "Failed" &&
    statusFilter !== "Match"
  ) {
    return null;
  }
  if (
    typeFilter !== "All Types" &&
    typeFilter !== "Individual" &&
    typeFilter !== "Organization" &&
    typeFilter !== "Unknown" &&
    typeFilter !== "Vessel" &&
    typeFilter !== "Aircraft"
  ) {
    return null;
  }
  if (
    resultSortKey !== "entity" &&
    resultSortKey !== "mode" &&
    resultSortKey !== "type" &&
    resultSortKey !== "country" &&
    resultSortKey !== "status" &&
    resultSortKey !== "score" &&
    resultSortKey !== "submittedAt"
  ) {
    return null;
  }
  if (resultSortDirection !== "asc" && resultSortDirection !== "desc") return null;

  return {
    mode,
    search,
    statusFilter,
    typeFilter,
    resultSortKey,
    resultSortDirection,
    page,
  };
}

function parseScreeningResultsMetaState(value: unknown): ScreeningResultsMetaState | null {
  if (!isRecord(value)) return null;
  const lastRefreshedAt = value.lastRefreshedAt;
  const submissionsOwnerUserId = value.submissionsOwnerUserId;
  if (lastRefreshedAt !== null && typeof lastRefreshedAt !== "string") return null;
  if (submissionsOwnerUserId !== null && typeof submissionsOwnerUserId !== "string") return null;
  return {
    lastRefreshedAt,
    submissionsOwnerUserId,
  };
}

export const submissionsState = atom<Submission[]>({
  key: "submissionsState",
  default: [],
  effects_UNSTABLE: [createLocalStorageEffect(`${STORAGE_PREFIX}:submissions`, parseSubmissions)],
});

export const latestResultState = atom<Submission | null>({
  key: "latestResultState",
  default: null,
  effects_UNSTABLE: [createLocalStorageEffect<Submission | null>(`${STORAGE_PREFIX}:latest-result`, parseLatestSubmission)],
});

export type ScreeningWorkspaceState = {
  mode: ScreeningWorkspaceMode;
  search: string;
  statusFilter: ScreeningResultStatusFilter;
  typeFilter: ScreeningResultTypeFilter;
  resultSortKey: ScreeningResultSortKey;
  resultSortDirection: ScreeningResultSortDirection;
  page: number;
};

export const screeningWorkspaceState = atom<ScreeningWorkspaceState>({
  key: "screeningWorkspaceState",
  default: {
    mode: "SINGLE",
    search: "",
    statusFilter: "All Statuses",
    typeFilter: "All Types",
    resultSortKey: "submittedAt",
    resultSortDirection: "desc",
    page: 1,
  },
  effects_UNSTABLE: [createLocalStorageEffect(`${STORAGE_PREFIX}:workspace`, parseScreeningWorkspaceState)],
});

export type ScreeningResultsMetaState = {
  lastRefreshedAt: string | null;
  submissionsOwnerUserId: string | null;
};

export const screeningResultsMetaState = atom<ScreeningResultsMetaState>({
  key: "screeningResultsMetaState",
  default: {
    lastRefreshedAt: null,
    submissionsOwnerUserId: null,
  },
  effects_UNSTABLE: [createLocalStorageEffect(`${STORAGE_PREFIX}:results-meta`, parseScreeningResultsMetaState)],
});
