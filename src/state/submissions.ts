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

export const submissionsState = atom<Submission[]>({
  key: "submissionsState",
  default: [],
});

export const latestResultState = atom<Submission | null>({
  key: "latestResultState",
  default: null,
});
