import { atom } from "recoil";

export type ScreeningMode = "SINGLE" | "BATCH";
export type HitResult = "HIT" | "NO_HIT" | "PROCESSING" | "FAILED" | "ERROR";

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

const STORAGE_KEY = "tapan_ofac_submissions_v1";

function loadInitial(): Submission[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as Submission[];
  } catch {
    return [];
  }
}

export const submissionsState = atom<Submission[]>({
  key: "submissionsState",
  default: loadInitial(),
  effects: [
    ({ onSet }) => {
      onSet((newValue) => {
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(newValue));
        } catch {
          // ignore storage errors
        }
      });
    },
  ],
});

export const latestResultState = atom<Submission | null>({
  key: "latestResultState",
  default: null,
});
