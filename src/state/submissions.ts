import { atom } from "recoil";

export type ScreeningMode = "SINGLE" | "BATCH";
export type HitResult = "HIT" | "NO_HIT" | "ERROR";

export type SingleSubmission = {
  id: string;
  createdAt: string; // ISO string
  mode: "SINGLE";
  customerType: "Person" | "Entity";
  displayName: string;
  result: HitResult;
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
  fileName: string;
  overallResult: HitResult;
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
