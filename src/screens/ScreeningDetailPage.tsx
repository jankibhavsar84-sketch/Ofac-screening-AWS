import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRecoilState } from "recoil";
import { useAuth } from "react-oidc-context";
import { z } from "zod";
import { appEnv } from "../config/env";
import {
  screeningWorkspaceState,
  screeningResultsMetaState,
  type ScreeningWorkspaceState,
} from "../state/submissions";
import {
  getScreeningSummary,
  listScreeningTypes,
  listRecentScreeningResults,
  matchSync,
  uploadBatchAndSubmitJob,
  type EntityExample,
  type RecentScreeningResultRow,
  type ScreeningTypeOption,
  type ScreeningSummaryCounts,
} from "../api/screeningApi";
import { buildIdentity, getPrimaryRole, hasPermission } from "../auth/claims";
import { CountryAutosuggest } from "../components/CountryAutoSuggest";
import { IsoDateInput } from "../components/IsoDateInput";
import { useBusinessUnits } from "../context/BusinessUnitsContext";

type Mode = "SINGLE" | "BATCH" | "SCHEDULE";
type UiType = "Individual" | "Organization" | "Unknown" | "Vessel" | "Aircraft";
type ScreeningType = string;
type ScheduleFrequency = "DAILY" | "WEEKLY" | "MONTHLY" | "QUARTERLY";

type IdDoc = { idType: string; idNumber: string; idCountry: string };
type NameItem =
  | {
      id: string;
      uiType: UiType;
      nameMode: "split" | "full"; // "split" only meaningful for Individual
      firstName: string;
      lastName: string;
      middleName: string;
      fullName: string; // also used for org/vessel/aircraft
      aliasName: string;
      dateOfBirth: string; // optional, Individual only
      countries: string[];
      addresses: string[];
      ids: IdDoc[];
      birthLocation?: string;
      gender?: string;
      title?: string;
    };

type StatusFilter = "All Statuses" | "Clear" | "Potential Match" | "Pending" | "Failed" | "Match";
type TypeFilter = "All Types" | UiType;
type ResultSortKey = "entity" | "mode" | "type" | "country" | "status" | "score" | "submittedAt";
type ResultTableColumnKey =
  | "entity"
  | "partyKey"
  | "mode"
  | "type"
  | "screeningType"
  | "country"
  | "screeningResult"
  | "submittedAt"
  | "actions";
type SelectOption<T extends string> = { value: T; label: string; icon?: React.ReactNode };
type DashboardScreeningTypeOption = {
  value: ScreeningType;
  label: string;
  shortLabel: string;
  searchDefinition: string;
  searchDefinitionName: string;
  screeningTypeName: string;
  displayOrder: number;
};

const RECENT_RESULTS_CACHE_MS = 2 * 60 * 1000;
const RECENT_RESULTS_LIMIT = 2000;
const RECENT_RESULT_ROWS_STORAGE_KEY = "ofac-screening:recent-result-rows";
const RECENT_RESULT_SUMMARY_STORAGE_KEY = "ofac-screening:recent-result-summary";
const RESULT_TABLE_DEFAULT_COLUMN_WIDTHS: Record<ResultTableColumnKey, number> = {
  entity: 220,
  partyKey: 320,
  mode: 120,
  type: 120,
  screeningType: 180,
  country: 120,
  screeningResult: 140,
  submittedAt: 190,
  actions: 108,
};
const RESULT_TABLE_MIN_COLUMN_WIDTHS: Record<ResultTableColumnKey, number> = {
  entity: 160,
  partyKey: 220,
  mode: 90,
  type: 90,
  screeningType: 130,
  country: 90,
  screeningResult: 120,
  submittedAt: 150,
  actions: 96,
};
const RESULT_TABLE_COLUMN_LABELS: Record<ResultTableColumnKey, string> = {
  entity: "Entity",
  partyKey: "Party Key",
  mode: "Mode",
  type: "Type",
  screeningType: "Screening Type",
  country: "Country",
  screeningResult: "Screening Result",
  submittedAt: "Submitted Date/Time",
  actions: "Actions",
};

function FormSelect<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: T;
  onChange: (value: T) => void;
  options: SelectOption<T>[];
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((o) => o.value === value) ?? options[0];
  const listboxId = React.useId();

  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (!rootRef.current) return;
      if (e.target instanceof Node && !rootRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  return (
    <div ref={rootRef} className="formSelectWrap">
      <button
        type="button"
        className="formSelectBtn"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        <span className="formSelectValue">
          {selected?.icon ? <span className="formSelectLeadIcon" aria-hidden="true">{selected.icon}</span> : null}
          <span>{selected?.label ?? value}</span>
        </span>
        <span className="formSelectCaret">{open ? "\u25B2" : "\u25BC"}</span>
      </button>

      {open ? (
        <div id={listboxId} className="formSelectMenu" role="listbox" aria-label={ariaLabel}>
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`formSelectOption ${opt.value === value ? "active" : ""}`}
              role="option"
              aria-selected={opt.value === value}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(opt.value);
                setOpen(false);
              }}
            >
              <span className="formSelectValue">
                {opt.icon ? <span className="formSelectLeadIcon" aria-hidden="true">{opt.icon}</span> : null}
                <span>{opt.label}</span>
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function safeTrim(v: string) {
  return (v ?? "").trim();
}

function readLocalStorageJson<T>(storageKey: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeLocalStorageJson(storageKey: string, value: unknown) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // Ignore storage quota and browser policy errors.
  }
}

function clearLocalStorageKey(storageKey: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(storageKey);
  } catch {
    // Ignore browser policy errors.
  }
}

function formatSubmittedDateTime(value: unknown): string {
  const raw = safeTrim(String(value ?? ""));
  if (!raw) return "\u2014";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString();
}

function toLocalDateTimeInputValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function defaultScheduleRunAtValue(): string {
  const now = new Date();
  now.setMinutes(0, 0, 0);
  now.setHours(now.getHours() + 1);
  return toLocalDateTimeInputValue(now);
}

function localDateTimeToUtcIso(value: string): string {
  const raw = safeTrim(value);
  if (!raw) return "";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toISOString();
}

const SUBSCRIPTION_EMAIL_DOMAIN = "prudential.com";
const BASIC_EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function isAllowedSubscriptionEmail(value: string): boolean {
  const email = safeTrim(value).toLowerCase();
  if (!email || !BASIC_EMAIL_REGEX.test(email)) return false;
  return email.endsWith(`@${SUBSCRIPTION_EMAIL_DOMAIN}`);
}

function parseSubscriptionEmails(value: string): { validEmails: string[]; invalidEmails: string[] } {
  const seen = new Set<string>();
  const validEmails: string[] = [];
  const invalidEmails: string[] = [];
  value
    .split(/[\n,;]+/g)
    .map((v) => safeTrim(v).toLowerCase())
    .forEach((email) => {
      if (!email || seen.has(email)) return;
      seen.add(email);
      if (isAllowedSubscriptionEmail(email)) {
        validEmails.push(email);
      } else {
        invalidEmails.push(email);
      }
    });
  return { validEmails, invalidEmails };
}

function uiTypeIcon(type: UiType): string {
  if (type === "Individual") return "\u{1F464}";
  if (type === "Organization") return "\u{1F3E2}";
  if (type === "Unknown") return "\u{1F3E2}";
  if (type === "Vessel") return "\u{1F6F3}\uFE0F";
  return "\u2708\uFE0F";
}

const ENTITY_TYPE_OPTIONS: SelectOption<UiType>[] = [
  { value: "Individual", label: "Individual", icon: uiTypeIcon("Individual") },
  { value: "Organization", label: "Organization", icon: uiTypeIcon("Organization") },
  { value: "Unknown", label: "Unknown", icon: uiTypeIcon("Unknown") },
  { value: "Vessel", label: "Vessel", icon: uiTypeIcon("Vessel") },
  { value: "Aircraft", label: "Aircraft", icon: uiTypeIcon("Aircraft") },
];

function normalizeScreeningTypeKey(value: string): string {
  return safeTrim(value)
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function normalizeBusinessUnitCode(value: string): string {
  return safeTrim(value).toUpperCase();
}

function screeningTypeCacheKey(userId: string | undefined, businessUnitCode: string): string {
  const safeUser = safeTrim(userId || "").toLowerCase() || "anonymous";
  const safeBusinessUnit = normalizeBusinessUnitCode(businessUnitCode);
  return `${safeUser}::${safeBusinessUnit}`;
}

function screeningTypeOptionFromApi(row: ScreeningTypeOption): DashboardScreeningTypeOption | null {
  const screeningType = safeTrim(String(row?.screening_type || row?.value || row?.label || ""));
  const searchDefinition = safeTrim(String(row?.search_definition_id || ""));
  const value = screeningType;
  if (!value || !searchDefinition) return null;
  const searchDefinitionName = safeTrim(String(row?.search_definition_name || "")) || searchDefinition;
  const shortLabel = screeningType;
  const parsedDisplayOrder = Number(row?.display_order);
  const displayOrder = Number.isFinite(parsedDisplayOrder) ? parsedDisplayOrder : 1000;
  return {
    value,
    label: screeningType,
    shortLabel,
    searchDefinition,
    searchDefinitionName,
    screeningTypeName: screeningType || value,
    displayOrder,
  };
}

function areScreeningTypeSelectionsEqual(left: ScreeningType[], right: ScreeningType[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((value, index) => value === right[index]);
}

const SCHEDULE_FREQUENCY_OPTIONS: { value: ScheduleFrequency; label: string; hint: string }[] = [
  { value: "DAILY", label: "Daily", hint: "Runs every day at configured schedule time." },
  { value: "WEEKLY", label: "Weekly", hint: "Runs once every 7 days at configured schedule time." },
  { value: "MONTHLY", label: "Monthly", hint: "Runs once each month at configured schedule time." },
  { value: "QUARTERLY", label: "Quarterly", hint: "Runs once every 3 months at configured schedule time." },
];

const ID_TYPE_OPTIONS = [
  "PASSPORT",
  "TIN",
  "SSN",
] as const;

const UNIFIED_TEMPLATE = {
  fileName: "Actimize_SSB1_template.xlsx",
  title: "Unified Screening Template",
  desc: "Includes the full Actimize Batch/Schedule column set required for upload.",
  chips: ["Primary + 3 aliases", "3 IDs + 3 addresses", "Birth/Nationality/Gender", "62 columns"],
} as const;

function uuid() {
  return crypto?.randomUUID?.() ?? `${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function parseISODate(s: string): Date | null {
  const v = safeTrim(s);
  if (!v) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const d = new Date(v + "T00:00:00");
  if (Number.isNaN(d.getTime())) return null;

  const [yy, mm, dd] = v.split("-").map(Number);
  if (d.getUTCFullYear() !== yy || d.getUTCMonth() + 1 !== mm || d.getUTCDate() !== dd) return null;
  return d;
}

// Keep caller-provided country code (ISO3 from dropdown) without conversion.
function toCountryCode(input: string) {
  return safeTrim(input).toUpperCase();
}

function uiTypeToSchema(ui: UiType): EntityExample["schema"] {
  if (ui === "Individual") return "Person";
  if (ui === "Organization") return "Company";
  if (ui === "Unknown") return "Unknown";
  // These values are supported by the screening payload mapper; if your API rejects, switch to "Company"
  if (ui === "Vessel") return "Vessel";
  return "Aircraft";
}

function buildEntityExampleFromNameItem(item: NameItem): EntityExample {
  const schema = uiTypeToSchema(item.uiType);

  const firstName = safeTrim(item.firstName);
  const middleName = safeTrim(item.middleName);
  const lastName = safeTrim(item.lastName);
  const explicitFullName = safeTrim(item.fullName);
  const splitFullName = [firstName, middleName, lastName].filter(Boolean).join(" ");
  const resolvedFullName = explicitFullName || splitFullName;

  // Name
  const nameValues: string[] = [];
  if (item.uiType === "Individual") {
    const splitName = splitFullName;
    const fullName = resolvedFullName;
    if (splitName) nameValues.push(splitName);
    if (fullName && fullName.toLowerCase() !== splitName.toLowerCase()) nameValues.push(fullName);
  } else {
    const fullName = resolvedFullName;
    if (fullName) nameValues.push(fullName);
  }

  const props: Record<string, any> = { name: nameValues };

  // Keep split-name fields explicit so Actimize request can map first/last directly.
  if (item.uiType === "Individual") {
    if (firstName) props.firstName = [firstName];
    if (middleName) props.middleName = [middleName];
    if (lastName) props.lastName = [lastName];
    if (resolvedFullName) props.fullName = [resolvedFullName];
  }

  // alias
  if (safeTrim(item.aliasName)) props.alias = [safeTrim(item.aliasName)];

  // DOB (individual only)
  if (item.uiType === "Individual" && safeTrim(item.dateOfBirth)) props.birthDate = [safeTrim(item.dateOfBirth)];

  // countries (multi)
  const isoCountries = (item.countries || []).map((c) => toCountryCode(c)).filter(Boolean);
  if (isoCountries.length) {
    // For persons: nationality; for org: country; for vessel/aircraft: country is acceptable
    if (schema === "Person") props.nationality = isoCountries;
    else props.country = isoCountries;
  }

  // addresses (multi)
  const addr = (item.addresses || []).map(safeTrim).filter(Boolean);
  if (addr.length) props.address = addr;

  // IDs (multi)
  const normalizedIds = (item.ids || [])
    .map((value) => ({
      idType: safeTrim(value.idType || ""),
      idValue: safeTrim(value.idNumber || ""),
      idCountry: safeTrim(value.idCountry || ""),
    }))
    .filter((value) => Boolean(value.idValue));
  const idNumbers = normalizedIds.map((value) => value.idValue);
  if (idNumbers.length) {
    if (schema === "Person") props.idNumber = idNumbers;
    else props.registrationNumber = idNumbers;
    props.ids = normalizedIds;
  }

  const birthLocation = safeTrim(String(item.birthLocation || ""));
  if (birthLocation) props.birthLocation = [birthLocation];
  const gender = safeTrim(String(item.gender || ""));
  if (gender) props.gender = [gender];
  const title = safeTrim(String(item.title || ""));
  if (title) props.title = [title];

  return { schema, properties: props };
}

type EngineStatus = "NO_HIT" | "HIT" | "PROCESSING" | "FAILED" | "ERROR";
type UiStatus = "Clear" | "Potential Match" | "Pending" | "Failed" | "Match";
type ResultMode = "SINGLE" | "BATCH";
type ResultRow = {
  id: string;
  entity: string;
  partyKey: string;
  mode: ResultMode;
  type: UiType;
  screeningType: string;
  country: string;
  engineStatus: EngineStatus;
  manualMatch: boolean;
  uiStatus: UiStatus;
  matchingScore: number | null;
  date: string;
  submittedAt: string;
  batchSubmissionId: string | null;
  dailyScheduleId: string | null;
  dailyScheduleActive: boolean;
  raw: any;
};

type SummaryCounts = ScreeningSummaryCounts;

function defaultSummaryCounts(): SummaryCounts {
  return {
    total: 0,
    clear: 0,
    potential: 0,
    pending: 0,
    failed: 0,
    match: 0,
  };
}

function normalizeResultRow(row: RecentScreeningResultRow): ResultRow | null {
  const typeRaw = safeTrim(String(row?.type || ""));
  const uiStatusRaw = safeTrim(String(row?.uiStatus || ""));
  const modeRaw = safeTrim(String(row?.mode || "")).toUpperCase();
  const engineStatusRaw = safeTrim(String(row?.engineStatus || "")).toUpperCase();

  const allowedTypes = new Set<UiType>(["Individual", "Organization", "Unknown", "Vessel", "Aircraft"]);
  const allowedModes = new Set<ResultMode>(["SINGLE", "BATCH"]);

  function normalizeEngineStatus(value: string): EngineStatus | null {
    const safe = safeTrim(value).toUpperCase().replace(/\s+/g, "_");
    if (!safe) return null;
    if (safe === "NO_HIT" || safe === "CLEAR") return "NO_HIT";
    if (safe === "HIT" || safe === "MATCH") return "HIT";
    if (safe === "PROCESSING" || safe === "PENDING" || safe === "QUEUED" || safe === "IN_PROGRESS") return "PROCESSING";
    if (safe === "FAILED" || safe === "FAIL" || safe === "ERROR" || safe === "UNKNOWN") return "FAILED";
    return null;
  }

  function normalizeUiStatus(value: string, engineStatus: EngineStatus, manualMatch: boolean): UiStatus {
    if (manualMatch) return "Match";
    const safe = safeTrim(value).toUpperCase().replace(/\s+/g, "_");
    if (safe === "MATCH" || safe === "TRUE_POSITIVE") return "Match";
    if (safe === "CLEAR" || safe === "NO_HIT") return "Clear";
    if (safe === "POTENTIAL_MATCH" || safe === "POTENTIAL" || safe === "HIT") return "Potential Match";
    if (safe === "PENDING" || safe === "PROCESSING" || safe === "QUEUED" || safe === "IN_PROGRESS") return "Pending";
    if (safe === "FAILED" || safe === "FAIL" || safe === "ERROR") return "Failed";
    if (engineStatus === "NO_HIT") return "Clear";
    if (engineStatus === "HIT") return "Potential Match";
    if (engineStatus === "PROCESSING") return "Pending";
    return "Failed";
  }

  const id = safeTrim(String(row?.id || ""));
  const entity = safeTrim(String(row?.entity || ""));
  const submittedAt = safeTrim(String(row?.submittedAt || ""));
  if (!id || !entity || !submittedAt) return null;
  if (!allowedTypes.has(typeRaw as UiType)) return null;
  if (!allowedModes.has(modeRaw as ResultMode)) return null;
  const manualMatch = Boolean(row?.manualMatch === true);
  const normalizedEngineStatus = normalizeEngineStatus(engineStatusRaw);
  if (!normalizedEngineStatus) return null;
  const normalizedUiStatus = normalizeUiStatus(uiStatusRaw, normalizedEngineStatus, manualMatch);

  const rawScreeningType = safeTrim(String((row as any)?.screeningType || ""));

  return {
    id,
    entity,
    partyKey: safeTrim(String(row?.partyKey || "")),
    mode: modeRaw as ResultMode,
    type: typeRaw as UiType,
    screeningType: rawScreeningType,
    country: safeTrim(String(row?.country || "")),
    engineStatus: normalizedEngineStatus,
    manualMatch,
    uiStatus: normalizedUiStatus,
    matchingScore: typeof row?.matchingScore === "number" ? row.matchingScore : null,
    date: formatSubmittedDateTime(submittedAt),
    submittedAt,
    batchSubmissionId: typeof row?.batchSubmissionId === "string" ? row.batchSubmissionId : null,
    dailyScheduleId: typeof row?.dailyScheduleId === "string" ? row.dailyScheduleId : null,
    dailyScheduleActive: Boolean(row?.dailyScheduleActive === true),
    raw: row?.raw ?? {},
  };
}

function normalizeResultRows(rows: RecentScreeningResultRow[] | unknown): ResultRow[] {
  if (!Array.isArray(rows)) return [];
  return rows
    .map((row) => normalizeResultRow(row as RecentScreeningResultRow))
    .filter((row): row is ResultRow => row !== null);
}

function normalizeSummaryCounts(value: Partial<SummaryCounts> | unknown): SummaryCounts {
  const summary = (value ?? {}) as Partial<SummaryCounts>;
  return {
    total: Number(summary.total ?? 0),
    clear: Number(summary.clear ?? 0),
    potential: Number(summary.potential ?? 0),
    pending: Number(summary.pending ?? 0),
    failed: Number(summary.failed ?? 0),
    match: Number(summary.match ?? 0),
  };
}

function badge(status: UiStatus) {
  if (status === "Clear") return <span className="statusPill statusClear">Clear</span>;
  if (status === "Potential Match") return <span className="statusPill statusPotential">Potential Match</span>;
  if (status === "Pending") return <span className="statusPill statusPending">Pending</span>;
  if (status === "Failed") return <span className="statusPill statusFailed">Failed</span>;
  return <span className="statusPill statusMatch">Match</span>;
}

function resultModeLabel(row: Pick<ResultRow, "mode" | "dailyScheduleId">): "OnDemand" | "Batch" | "Schedule" {
  if (safeTrim(String(row.dailyScheduleId || ""))) return "Schedule";
  if (row.mode === "SINGLE") return "OnDemand";
  return "Batch";
}

function modeBadge(row: Pick<ResultRow, "mode" | "dailyScheduleId">) {
  const label = resultModeLabel(row);
  if (label === "OnDemand") return <span className="modePill modePillSingle">OnDemand</span>;
  return <span className="modePill modePillBatch">{label}</span>;
}

function formatMatchingScore(score: number | null) {
  if (typeof score !== "number" || Number.isNaN(score)) return "";
  return `${(score * 100).toFixed(2)}%`;
}

const STATUS_SORT_RANK: Record<UiStatus, number> = {
  Clear: 1,
  "Potential Match": 2,
  Match: 3,
  Pending: 4,
  Failed: 5,
};

type HitMatch = {
  name: string;
  matchingScore: number | null;
  keywordOrCategory: string;
};

const DEFAULT_ACTIMIZE_REVIEW_ALERT_URL = "http://actimizeuat";

function asStringList(input: unknown): string[] {
  if (Array.isArray(input)) {
    return input.map((v) => safeTrim(String(v))).filter(Boolean);
  }
  if (typeof input === "string") {
    const v = safeTrim(input);
    return v ? [v] : [];
  }
  return [];
}

function extractHitTag(result: any): string {
  const props = result?.properties;
  const keywords = asStringList(props?.keyword).concat(asStringList(props?.keywords));
  if (keywords.length) return `Keyword: ${Array.from(new Set(keywords)).join(", ")}`;

  const categories = asStringList(props?.category).concat(asStringList(props?.categories));
  if (categories.length) return `Category: ${Array.from(new Set(categories)).join(", ")}`;

  return "";
}

function getResultCandidatesFromRaw(raw: any): any[] {
  const direct = raw?.matches?.results;
  const batch = raw?.item?.details?.matches?.results;
  const legacy = raw?.details?.results ?? raw?.details?.matches?.results;
  return Array.isArray(direct) ? direct : Array.isArray(batch) ? batch : Array.isArray(legacy) ? legacy : [];
}

function normalizeReviewUrl(value: unknown): string {
  const safe = safeTrim(String(value ?? ""));
  if (!safe) return "";
  if (/^https?:\/\//i.test(safe)) return safe;
  return `https://${safe}`;
}

function resolveActimizeReviewUrlFromRaw(raw: any): string {
  const candidates = [
    raw?.matches?.actimize_alert_review_url,
    raw?.item?.details?.matches?.actimize_alert_review_url,
    raw?.details?.matches?.actimize_alert_review_url,
    raw?.matches?.actimize_alert?.review_url,
    raw?.item?.details?.matches?.actimize_alert?.review_url,
    raw?.details?.matches?.actimize_alert?.review_url,
    raw?.submission?.actimizeAlertReviewUrl,
    raw?.submission?.actimize_alert_review_url,
  ];
  for (const candidate of candidates) {
    const normalized = normalizeReviewUrl(candidate);
    if (normalized) return normalized;
  }
  return "";
}

function getHitMatchesFromRaw(raw: any): HitMatch[] {
  const results = getResultCandidatesFromRaw(raw);
  const matched = results.filter((r) => r && typeof r === "object" && r.match === true);

  return matched
    .map((r) => ({
    name: safeTrim(String(r.caption ?? r.name ?? r.id ?? "")) || "Unknown entity",
    matchingScore: typeof r.score === "number" ? r.score : null,
    keywordOrCategory: extractHitTag(r),
    }))
    .sort((a, b) => {
      const aScore = typeof a.matchingScore === "number" ? a.matchingScore : -1;
      const bScore = typeof b.matchingScore === "number" ? b.matchingScore : -1;
      return bScore - aScore;
    });
}

function extractEngineErrorFromRaw(raw: any): { status: number | null; errorText: string } | null {
  const candidates: any[] = [
    raw?.matches,
    raw?.item?.details?.matches,
    raw?.details?.matches,
    raw?.m?.matches,
    raw?.matches?.matches,
  ].filter(Boolean);

  for (const m of candidates) {
    const status = typeof m?.status === "number" ? m.status : null;
    const errorText = safeTrim(String(m?.error_text ?? m?.errorText ?? m?.error ?? ""));
    if ((status != null && status >= 400) || errorText) {
      return { status, errorText: errorText || "Screening failed for this record." };
    }
  }

  const msg = safeTrim(String(raw?.item?.message ?? raw?.message ?? ""));
  if (!msg) return null;

  const resultHint = safeTrim(String(raw?.item?.result ?? raw?.submission?.result ?? "")).toUpperCase();
  const isFailureResult = resultHint === "FAILED" || resultHint === "ERROR";
  const isFailureMessage = /(fail|error|timeout|exception)/i.test(msg);
  if (isFailureResult || isFailureMessage) return { status: null, errorText: msg };

  return null;
}

function ViewIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="2.5" />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 3h7v7" />
      <path d="M10 14 21 3" />
      <path d="M21 14v7h-7" />
      <path d="M3 10V3h7" />
      <path d="M3 3 14 14" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M3 21h18" />
    </svg>
  );
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvEscape(v: any) {
  const s = String(v ?? "");
  if (/[,"\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function exportTimestamp() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const mi = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  return `${yyyy}${mm}${dd}_${hh}${mi}${ss}`;
}

function downloadUnifiedTemplate() {
  const a = document.createElement("a");
  a.href = `/${UNIFIED_TEMPLATE.fileName}`;
  a.download = UNIFIED_TEMPLATE.fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function RefreshIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.5 9A9 9 0 0 1 19.3 5.7L23 10" />
      <path d="M20.5 15A9 9 0 0 1 4.7 18.3L1 14" />
    </svg>
  );
}

function ScreeningTypeCards({
  selected,
  onToggle,
  options,
}: {
  selected: ScreeningType[];
  onToggle: (type: ScreeningType) => void;
  options: DashboardScreeningTypeOption[];
}) {
  return (
    <div className="screeningTypeWrap">
      <div className="sectionRow" style={{ marginBottom: 8 }}>
        <div className="sectionTitle">Screening Types <span className="requiredMark">*</span></div>
      </div>
      <div className="screeningTypeHint">Hover a tile to view search definition details. Scroll left/right for more types.</div>
      <div className="screeningTypeScroller" role="region" aria-label="Available screening types" tabIndex={0}>
        <div className="screeningTypeGrid">
          {options.map((option) => {
            const active = selected.includes(option.value);
            const tooltip = [
              `Screening Type: ${option.value}`,
              `Search Definition ID: ${option.searchDefinition}`,
              `Search Definition Name: ${option.searchDefinitionName}`,
            ].join("\n");
            const ariaTooltip = tooltip.replace(/\n+/g, ". ");
            return (
              <button
                key={option.value}
                type="button"
                className={active ? "screeningTypeCard active" : "screeningTypeCard"}
                onClick={() => onToggle(option.value)}
                aria-pressed={active}
                title={tooltip}
                aria-label={`${option.label}. ${ariaTooltip}${active ? ". Selected" : ""}`}
              >
                <div className="screeningTypeHead">
                  <span className="screeningTypeName">{option.value}</span>
                  <span className={active ? "screeningTypeTick active" : "screeningTypeTick"} aria-hidden="true">
                    {active ? "\u2713" : "+"}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function ScreeningDetailPage() {
  const auth = useAuth();
  const identity = useMemo(() => buildIdentity(auth.user), [auth.user]);
  const primaryRole = useMemo(() => getPrimaryRole(identity), [identity]);
  const canSingleScreen = hasPermission(identity, "screening.write", "screening.single.mock", "screening.admin");
  const canRunNonMockSingle = hasPermission(identity, "screening.write", "screening.admin");
  const canBatchScreen = hasPermission(identity, "screening.write", "screening.admin");
  const canDailyScreening = hasPermission(identity, "screening.daily", "screening.admin");
  const viewerMockOnly = canSingleScreen && !canRunNonMockSingle;

  const [screeningWorkspace, setScreeningWorkspace] = useRecoilState(screeningWorkspaceState);
  const [screeningResultsMeta, setScreeningResultsMeta] = useRecoilState(screeningResultsMetaState);
  const [recentResultRows, setRecentResultRows] = useState<ResultRow[]>(
    () => normalizeResultRows(readLocalStorageJson<RecentScreeningResultRow[]>(RECENT_RESULT_ROWS_STORAGE_KEY, []))
  );
  const [summaryCounts, setSummaryCounts] = useState<SummaryCounts>(
    () => normalizeSummaryCounts(readLocalStorageJson<Partial<SummaryCounts>>(RECENT_RESULT_SUMMARY_STORAGE_KEY, defaultSummaryCounts()))
  );
  const [resultsRefreshing, setResultsRefreshing] = useState(false);
  const [resultsRefreshError, setResultsRefreshError] = useState<string | null>(null);
  const [resultColumnWidths, setResultColumnWidths] = useState<Record<ResultTableColumnKey, number>>(
    () => ({ ...RESULT_TABLE_DEFAULT_COLUMN_WIDTHS })
  );
  const resultColumnResizeRef = useRef<{
    key: ResultTableColumnKey;
    startX: number;
    startWidth: number;
  } | null>(null);
  const recentResultsRefreshInFlightRef = useRef(false);
  const pendingRecentResultsRefreshRef = useRef<{
    silent: boolean;
    updateTimestamp: boolean;
    resetPage: boolean;
    requestUserId?: string;
  } | null>(null);
  const screeningResultsMetaRef = useRef(screeningResultsMeta);
  const {
    businessUnitOptions,
    businessUnitsAvailable,
    businessUnitsError,
    businessUnitsPending,
    businessUnitsResolved,
    reloadBusinessUnits,
  } = useBusinessUnits();
  const resultsLastRefreshedAt = useMemo(() => {
    const raw = safeTrim(screeningResultsMeta.lastRefreshedAt || "");
    if (!raw) return null;
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }, [screeningResultsMeta.lastRefreshedAt]);
  const mode = screeningWorkspace.mode;
  const search = screeningWorkspace.search;
  const statusFilter = screeningWorkspace.statusFilter;
  const typeFilter = screeningWorkspace.typeFilter;
  const resultSortKey = screeningWorkspace.resultSortKey;
  const resultSortDirection = screeningWorkspace.resultSortDirection;
  const page = screeningWorkspace.page;
  const currentUser = useMemo(
    () =>
      identity
        ? {
            id: identity.id,
            name: identity.name,
          }
        : null,
    [identity]
  );

  useEffect(() => {
    screeningResultsMetaRef.current = screeningResultsMeta;
  }, [screeningResultsMeta]);
  const updateScreeningWorkspace = useCallback(
    (patch: Partial<ScreeningWorkspaceState>) => {
      setScreeningWorkspace((prev) => ({ ...prev, ...patch }));
    },
    [setScreeningWorkspace]
  );

  const startResultColumnResize = useCallback(
    (key: ResultTableColumnKey, event: React.MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
      resultColumnResizeRef.current = {
        key,
        startX: event.clientX,
        startWidth: resultColumnWidths[key],
      };
      document.body.classList.add("colResizeActive");
    },
    [resultColumnWidths]
  );

  useEffect(() => {
    function onMouseMove(event: MouseEvent) {
      const activeResize = resultColumnResizeRef.current;
      if (!activeResize) return;
      const delta = event.clientX - activeResize.startX;
      const minWidth = RESULT_TABLE_MIN_COLUMN_WIDTHS[activeResize.key];
      const nextWidth = Math.max(minWidth, Math.round(activeResize.startWidth + delta));
      setResultColumnWidths((prev) => {
        if (prev[activeResize.key] === nextWidth) return prev;
        return {
          ...prev,
          [activeResize.key]: nextWidth,
        };
      });
    }

    function stopResize() {
      if (!resultColumnResizeRef.current) return;
      resultColumnResizeRef.current = null;
      document.body.classList.remove("colResizeActive");
    }

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", stopResize);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", stopResize);
      document.body.classList.remove("colResizeActive");
    };
  }, []);

  useEffect(() => {
    writeLocalStorageJson(RECENT_RESULT_ROWS_STORAGE_KEY, recentResultRows);
  }, [recentResultRows]);

  useEffect(() => {
    writeLocalStorageJson(RECENT_RESULT_SUMMARY_STORAGE_KEY, summaryCounts);
  }, [summaryCounts]);

  // SINGLE (multi-add)
  const [names, setNames] = useState<NameItem[]>([
    {
      id: uuid(),
      uiType: "Individual",
      nameMode: "split",
      firstName: "",
      lastName: "",
      middleName: "",
      fullName: "",
      aliasName: "",
      dateOfBirth: "",
      countries: [""],
      addresses: [""],
      ids: [{ idType: "PASSPORT", idNumber: "", idCountry: "" }],
    },
  ]);

  const [notes, setNotes] = useState("");
  const [screeningTypeOptionsByBusinessUnit, setScreeningTypeOptionsByBusinessUnit] = useState<
    Record<string, DashboardScreeningTypeOption[]>
  >({});
  const screeningTypeLoadsInFlightRef = useRef<Set<string>>(new Set());
  const [singleScreeningTypes, setSingleScreeningTypes] = useState<ScreeningType[]>([]);
  const [singleMockScreening, setSingleMockScreening] = useState(true);
  const [singleBusinessUnitCode, setSingleBusinessUnitCode] = useState("");

  // BATCH
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [batchName, setBatchName] = useState("");
  const [batchScreeningTypes, setBatchScreeningTypes] = useState<ScreeningType[]>([]);
  const [batchBusinessUnitCode, setBatchBusinessUnitCode] = useState("");
  const [batchFile, setBatchFile] = useState<File | null>(null);
  const [batchFileName, setBatchFileName] = useState("");
  const [batchError, setBatchError] = useState<string | null>(null);
  const [batchSuccess, setBatchSuccess] = useState<string | null>(null);

  // SCHEDULE
  const [scheduleTemplatesOpen, setScheduleTemplatesOpen] = useState(false);
  const [scheduleName, setScheduleName] = useState("");
  const [scheduleScreeningTypes, setScheduleScreeningTypes] = useState<ScreeningType[]>([]);
  const [scheduleBusinessUnitCode, setScheduleBusinessUnitCode] = useState("");
  const [scheduleFrequency, setScheduleFrequency] = useState<ScheduleFrequency>("DAILY");
  const [scheduleRunAt, setScheduleRunAt] = useState(defaultScheduleRunAtValue);
  const [scheduleSubscriptionEmails, setScheduleSubscriptionEmails] = useState("");
  const [scheduleFile, setScheduleFile] = useState<File | null>(null);
  const [scheduleFileName, setScheduleFileName] = useState("");
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduleSuccess, setScheduleSuccess] = useState<string | null>(null);

  useEffect(() => {
    // Clear screening-type cache when auth user changes to avoid stale options across sessions.
    setScreeningTypeOptionsByBusinessUnit({});
    screeningTypeLoadsInFlightRef.current.clear();
  }, [currentUser?.id]);

  const [singleError, setSingleError] = useState<string | null>(null);
  const [singleSubmitting, setSingleSubmitting] = useState(false);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [scheduleSubmitting, setScheduleSubmitting] = useState(false);
  const selectedEntityType: UiType = names[0]?.uiType ?? "Individual";
  const primaryName = names[0];
  const aliasNames = names.slice(1);

  // dropzone
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const scheduleRunAtInputRef = useRef<HTMLInputElement | null>(null);
  const hitDialogCloseBtnRef = useRef<HTMLButtonElement | null>(null);
  const anySubmitting = singleSubmitting || batchSubmitting || scheduleSubmitting;
  // NOTE: The system supports up to ~25 MB, but we guide users to keep uploads smaller
  // for reliability/performance.
  const MAX_UPLOAD_VALIDATION_MB = 25;
  const MAX_UPLOAD_DISPLAY_MB = 5;
  // Enforce the user-facing limit in the UI, even though the backend can handle larger uploads.
  const MAX_UPLOAD_BYTES = MAX_UPLOAD_DISPLAY_MB * 1024 * 1024;

  function openScheduleRunAtPicker() {
    const picker = scheduleRunAtInputRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    if (!picker) return;
    if (typeof picker.showPicker === "function") {
      picker.showPicker();
      return;
    }
    picker.focus();
    picker.click();
  }

  function openFilePicker() {
    fileInputRef.current?.click();
  }

  function validateUploadFile(file: File | null, setError: (value: string | null) => void): file is File {
    if (!file) return false;
    if (file.size <= MAX_UPLOAD_BYTES) return true;

    const mb = file.size / (1024 * 1024);
    setError(
      `This file is ${mb.toFixed(2)} MB, which exceeds the maximum allowed upload size (${MAX_UPLOAD_DISPLAY_MB} MB). ` +
        `Please split the file into smaller batches and try again.`
    );
    return false;
  }

  function handleDropzoneKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openFilePicker();
    }
  }

  useEffect(() => {
    if (!canBatchScreen && mode === "BATCH") {
      updateScreeningWorkspace({ mode: "SINGLE" });
    }
  }, [canBatchScreen, mode, updateScreeningWorkspace]);

  useEffect(() => {
    if (!canDailyScreening && mode === "SCHEDULE") {
      updateScreeningWorkspace({ mode: "SINGLE" });
    }
  }, [canDailyScreening, mode, updateScreeningWorkspace]);
  const fallbackBusinessUnitCode = safeTrim(appEnv("VITE_DEFAULT_BUSINESS_UNIT_CODE", "US_PRU_HR")).toUpperCase();
  const fallbackBusinessUnitName = safeTrim(appEnv("VITE_DEFAULT_BUSINESS_UNIT_NAME", "Human Resources"));
  const selectableBusinessUnitOptions = useMemo(
    () =>
      businessUnitOptions.length > 0
        ? businessUnitOptions
        : fallbackBusinessUnitCode
          ? [{ code: fallbackBusinessUnitCode, name: fallbackBusinessUnitName || fallbackBusinessUnitCode }]
          : [],
    [businessUnitOptions, fallbackBusinessUnitCode, fallbackBusinessUnitName]
  );
  const businessUnitsEffectiveAvailable = selectableBusinessUnitOptions.length > 0;
  const businessUnitsSelectDisabled = !businessUnitsEffectiveAvailable;
  const businessUnitsPlaceholderLabel = businessUnitsPending && !businessUnitsAvailable
    ? "Loading Business Units..."
    : businessUnitsEffectiveAvailable
      ? "Select Business Unit"
      : "No Business Unit options are currently available.";

  useEffect(() => {
    const validCodes = new Set(selectableBusinessUnitOptions.map((row) => row.code));
    const firstCode = selectableBusinessUnitOptions[0]?.code ?? "";

    if (!validCodes.has(singleBusinessUnitCode)) setSingleBusinessUnitCode(firstCode);
    if (!validCodes.has(batchBusinessUnitCode)) setBatchBusinessUnitCode(firstCode);
    if (!validCodes.has(scheduleBusinessUnitCode)) setScheduleBusinessUnitCode(firstCode);
  }, [selectableBusinessUnitOptions, singleBusinessUnitCode, batchBusinessUnitCode, scheduleBusinessUnitCode]);

  const loadScreeningTypeOptionsForBusinessUnit = useCallback(async (businessUnitCode: string) => {
    const safeBusinessUnitCode = normalizeBusinessUnitCode(businessUnitCode);
    if (!safeBusinessUnitCode) return;
    const cacheKey = screeningTypeCacheKey(currentUser?.id, safeBusinessUnitCode);
    if (screeningTypeLoadsInFlightRef.current.has(cacheKey)) return;
    if (Object.prototype.hasOwnProperty.call(screeningTypeOptionsByBusinessUnit, cacheKey)) return;
    screeningTypeLoadsInFlightRef.current.add(cacheKey);
    try {
      // Build union from the BU options currently shown in UI so screening types
      // always stay aligned with visible BU access for the signed-in user.
      const buCodesFromUi = Array.from(
        new Set(
          selectableBusinessUnitOptions
            .map((row) => normalizeBusinessUnitCode(row.code))
            .filter(Boolean)
        )
      );
      const buCodesForUnion = buCodesFromUi.length ? buCodesFromUi : [safeBusinessUnitCode];

      const responses = await Promise.allSettled(
        buCodesForUnion.map((code) => listScreeningTypes(code))
      );
      const rows: ScreeningTypeOption[] = [];
      responses.forEach((result) => {
        if (result.status === "fulfilled" && Array.isArray(result.value)) {
          rows.push(...result.value);
        }
      });
      const sortedRows = (Array.isArray(rows) ? rows : []).slice().sort((left, right) => {
        const leftOrder = Number(left?.display_order);
        const rightOrder = Number(right?.display_order);
        const safeLeftOrder = Number.isFinite(leftOrder) ? leftOrder : 1000;
        const safeRightOrder = Number.isFinite(rightOrder) ? rightOrder : 1000;
        if (safeLeftOrder !== safeRightOrder) return safeLeftOrder - safeRightOrder;
        const leftType = safeTrim(String(left?.screening_type || left?.value || ""));
        const rightType = safeTrim(String(right?.screening_type || right?.value || ""));
        return leftType.localeCompare(rightType);
      });
      const deduped = new Map<string, DashboardScreeningTypeOption>();
      sortedRows.forEach((row) => {
        const mapped = screeningTypeOptionFromApi(row);
        if (!mapped) return;
        const dedupeKey = normalizeScreeningTypeKey(mapped.value || "");
        if (!deduped.has(dedupeKey)) {
          deduped.set(dedupeKey, mapped);
        }
      });
      const unionOptions = Array.from(deduped.values());
      setScreeningTypeOptionsByBusinessUnit((prev) => {
        const next = { ...prev };
        buCodesForUnion.forEach((code) => {
          next[screeningTypeCacheKey(currentUser?.id, code)] = unionOptions;
        });
        next[cacheKey] = unionOptions;
        return next;
      });
    } catch {
      setScreeningTypeOptionsByBusinessUnit((prev) => ({
        ...prev,
        [cacheKey]: [],
      }));
    } finally {
      screeningTypeLoadsInFlightRef.current.delete(cacheKey);
    }
  }, [currentUser?.id, screeningTypeOptionsByBusinessUnit, selectableBusinessUnitOptions]);

  useEffect(() => {
    const targetCodes = [
      normalizeBusinessUnitCode(singleBusinessUnitCode),
      normalizeBusinessUnitCode(batchBusinessUnitCode),
      normalizeBusinessUnitCode(scheduleBusinessUnitCode),
    ].filter(Boolean);
    const dedupedCodes = Array.from(new Set(targetCodes));
    dedupedCodes.forEach((code) => {
      void loadScreeningTypeOptionsForBusinessUnit(code);
    });
  }, [
    singleBusinessUnitCode,
    batchBusinessUnitCode,
    scheduleBusinessUnitCode,
    loadScreeningTypeOptionsForBusinessUnit,
  ]);

  const singleScreeningTypeOptions = useMemo(
    () =>
      screeningTypeOptionsByBusinessUnit[
        screeningTypeCacheKey(currentUser?.id, normalizeBusinessUnitCode(singleBusinessUnitCode))
      ] ?? [],
    [currentUser?.id, screeningTypeOptionsByBusinessUnit, singleBusinessUnitCode]
  );
  const batchScreeningTypeOptions = useMemo(
    () =>
      screeningTypeOptionsByBusinessUnit[
        screeningTypeCacheKey(currentUser?.id, normalizeBusinessUnitCode(batchBusinessUnitCode))
      ] ?? [],
    [currentUser?.id, screeningTypeOptionsByBusinessUnit, batchBusinessUnitCode]
  );
  const scheduleScreeningTypeOptions = useMemo(
    () =>
      screeningTypeOptionsByBusinessUnit[
        screeningTypeCacheKey(currentUser?.id, normalizeBusinessUnitCode(scheduleBusinessUnitCode))
      ] ?? [],
    [currentUser?.id, screeningTypeOptionsByBusinessUnit, scheduleBusinessUnitCode]
  );

  useEffect(() => {
    const validTypes = new Set(singleScreeningTypeOptions.map((option) => option.value));
    const fallbackType = singleScreeningTypeOptions[0]?.value || "";
    const next = singleScreeningTypes.filter((value) => validTypes.has(value));
    const normalized = next.length ? Array.from(new Set(next)) : (fallbackType ? [fallbackType] : []);
    if (!areScreeningTypeSelectionsEqual(singleScreeningTypes, normalized)) {
      setSingleScreeningTypes(normalized);
    }
  }, [singleScreeningTypeOptions, singleScreeningTypes]);

  useEffect(() => {
    const validTypes = new Set(batchScreeningTypeOptions.map((option) => option.value));
    const fallbackType = batchScreeningTypeOptions[0]?.value || "";
    const next = batchScreeningTypes.filter((value) => validTypes.has(value));
    const normalized = next.length ? Array.from(new Set(next)) : (fallbackType ? [fallbackType] : []);
    if (!areScreeningTypeSelectionsEqual(batchScreeningTypes, normalized)) {
      setBatchScreeningTypes(normalized);
    }
  }, [batchScreeningTypeOptions, batchScreeningTypes]);

  useEffect(() => {
    const validTypes = new Set(scheduleScreeningTypeOptions.map((option) => option.value));
    const fallbackType = scheduleScreeningTypeOptions[0]?.value || "";
    const next = scheduleScreeningTypes.filter((value) => validTypes.has(value));
    const normalized = next.length ? Array.from(new Set(next)) : (fallbackType ? [fallbackType] : []);
    if (!areScreeningTypeSelectionsEqual(scheduleScreeningTypes, normalized)) {
      setScheduleScreeningTypes(normalized);
    }
  }, [scheduleScreeningTypeOptions, scheduleScreeningTypes]);

  const singleDefaultScreeningType = singleScreeningTypeOptions[0]?.value || "";
  const batchDefaultScreeningType = batchScreeningTypeOptions[0]?.value || "";
  const scheduleDefaultScreeningType = scheduleScreeningTypeOptions[0]?.value || "";

  const loadRecentResults = useCallback(
    async ({
      silent,
      updateTimestamp,
      resetPage,
      requestUserId,
    }: {
      silent: boolean;
      updateTimestamp: boolean;
      resetPage: boolean;
      requestUserId?: string;
    }) => {
      const activeUserId = safeTrim(requestUserId || currentUser?.id || "");
      if (recentResultsRefreshInFlightRef.current) {
        const existing = pendingRecentResultsRefreshRef.current;
        pendingRecentResultsRefreshRef.current = {
          // If any queued request is interactive, keep it interactive.
          silent: (existing?.silent ?? true) && silent,
          // If any queued request needs metadata/page updates, preserve that.
          updateTimestamp: Boolean(existing?.updateTimestamp || updateTimestamp),
          resetPage: Boolean(existing?.resetPage || resetPage),
          requestUserId: requestUserId || existing?.requestUserId,
        };
        return;
      }

      recentResultsRefreshInFlightRef.current = true;
      if (!silent) {
        setResultsRefreshing(true);
        setResultsRefreshError(null);
      }
      try {
        const [summary, rows] = await Promise.all([
          getScreeningSummary(),
          listRecentScreeningResults(RECENT_RESULTS_LIMIT),
        ]);
        setSummaryCounts(normalizeSummaryCounts(summary));
        setRecentResultRows(normalizeResultRows(rows));
        setScreeningResultsMeta((prev) => ({
          lastRefreshedAt: updateTimestamp ? new Date().toISOString() : prev.lastRefreshedAt,
          submissionsOwnerUserId: activeUserId || prev.submissionsOwnerUserId,
        }));
        if (resetPage) {
          updateScreeningWorkspace({ page: 1 });
        }
      } catch (err: any) {
        if (!silent) {
          setResultsRefreshError(err?.message ?? "Failed to refresh screening results.");
        }
      } finally {
        recentResultsRefreshInFlightRef.current = false;
        if (!silent) {
          setResultsRefreshing(false);
        }
        const queuedRefresh = pendingRecentResultsRefreshRef.current;
        if (queuedRefresh) {
          pendingRecentResultsRefreshRef.current = null;
          void loadRecentResults(queuedRefresh);
        }
      }
    },
    [currentUser?.id, setScreeningResultsMeta, updateScreeningWorkspace]
  );

  useEffect(() => {
    const userId = safeTrim(currentUser?.id || "");
    setResultsRefreshError(null);
    if (!userId) {
      setRecentResultRows([]);
      setSummaryCounts(defaultSummaryCounts());
      clearLocalStorageKey(RECENT_RESULT_ROWS_STORAGE_KEY);
      clearLocalStorageKey(RECENT_RESULT_SUMMARY_STORAGE_KEY);
      setScreeningResultsMeta({
        lastRefreshedAt: null,
        submissionsOwnerUserId: null,
      });
      setResultsRefreshing(false);
      return;
    }
    const cachedOwnerUserId = screeningResultsMetaRef.current.submissionsOwnerUserId;
    const hasCachedResultsForUser = cachedOwnerUserId === userId;
    const hasFreshCachedResults =
      hasCachedResultsForUser &&
      recentResultRows.length > 0 &&
      !!resultsLastRefreshedAt &&
      Date.now() - resultsLastRefreshedAt.getTime() <= RECENT_RESULTS_CACHE_MS;
    if (!hasCachedResultsForUser && cachedOwnerUserId) {
      setRecentResultRows([]);
      setSummaryCounts(defaultSummaryCounts());
      clearLocalStorageKey(RECENT_RESULT_ROWS_STORAGE_KEY);
      clearLocalStorageKey(RECENT_RESULT_SUMMARY_STORAGE_KEY);
      setScreeningResultsMeta({
        lastRefreshedAt: null,
        submissionsOwnerUserId: userId,
      });
    }
    if (hasFreshCachedResults) {
      return;
    }
    if (businessUnitsPending) {
      return;
    }
    void loadRecentResults({
      silent: hasCachedResultsForUser,
      updateTimestamp: true,
      resetPage: !hasCachedResultsForUser,
      requestUserId: userId,
    });
  }, [
    businessUnitOptions.length,
    businessUnitsPending,
    businessUnitsResolved,
    currentUser?.id,
    loadRecentResults,
    recentResultRows.length,
    resultsLastRefreshedAt,
    setScreeningResultsMeta,
  ]);

  function toggleScreeningType(
    value: ScreeningType,
    setSelected: React.Dispatch<React.SetStateAction<ScreeningType[]>>
  ) {
    setSelected((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]));
  }

  function refreshResults() {
    void loadRecentResults({ silent: false, updateTimestamp: true, resetPage: true });
  }

  const singleSchema = useMemo(() => {
    // Validate each name item basic requirements + DOB rules for individual only
    return z.array(
      z.object({
        uiType: z.enum(["Individual", "Organization", "Unknown", "Vessel", "Aircraft"]),
        nameMode: z.enum(["split", "full"]),
        firstName: z.string(),
        lastName: z.string(),
        fullName: z.string(),
        dateOfBirth: z.string(),
        countries: z.array(z.string()),
      }).superRefine((data, ctx) => {
        if (data.uiType === "Individual") {
          const hasSplit = !!safeTrim(data.firstName) && !!safeTrim(data.lastName);
          const hasFull = !!safeTrim(data.fullName);
          if (!hasSplit && !hasFull) {
            ctx.addIssue({ code: "custom", path: ["firstName"], message: "Provide First+Last name or Full Name for Individual." });
          }

          const dob = safeTrim(data.dateOfBirth);
          if (dob) {
            const d = parseISODate(dob);
            if (!d) {
              ctx.addIssue({ code: "custom", path: ["dateOfBirth"], message: "DOB must be valid YYYY-MM-DD." });
            } else {
              const now = new Date();
              const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
              if (d > today) ctx.addIssue({ code: "custom", path: ["dateOfBirth"], message: "DOB cannot be in the future." });
              const oldest = new Date(today);
              oldest.setFullYear(oldest.getFullYear() - 100);
              if (d < oldest) ctx.addIssue({ code: "custom", path: ["dateOfBirth"], message: "DOB cannot be more than 100 years old." });
            }
          }
        } else {
          // Non-individual: full name required
          if (!safeTrim(data.fullName)) ctx.addIssue({ code: "custom", path: ["fullName"], message: "Name is required." });
        }
      })
    );
  }, []);

  function clearAll() {
    setSingleError(null);
    setBatchError(null);
    setScheduleError(null);
    setBatchSuccess(null);
    setScheduleSuccess(null);

    if (mode === "SINGLE") {
      setNames([
        {
          id: uuid(),
          uiType: "Individual",
          nameMode: "split",
          firstName: "",
          lastName: "",
          middleName: "",
          fullName: "",
          aliasName: "",
          dateOfBirth: "",
          countries: [""],
          addresses: [""],
          ids: [{ idType: "PASSPORT", idNumber: "", idCountry: "" }],
        },
      ]);
      setNotes("");
      setSingleScreeningTypes(singleDefaultScreeningType ? [singleDefaultScreeningType] : []);
      setSingleMockScreening(true);
    } else if (mode === "BATCH") {
      setBatchName("");
      setBatchScreeningTypes(batchDefaultScreeningType ? [batchDefaultScreeningType] : []);
      setBatchFile(null);
      setBatchFileName("");
      setTemplatesOpen(false);
    } else {
      setScheduleName("");
      setScheduleScreeningTypes(scheduleDefaultScreeningType ? [scheduleDefaultScreeningType] : []);
      setScheduleFrequency("DAILY");
      setScheduleRunAt(defaultScheduleRunAtValue());
      setScheduleSubscriptionEmails("");
      setScheduleFile(null);
      setScheduleFileName("");
      setScheduleTemplatesOpen(false);
    }
  }

  // ---------- Single tab +Add handlers ----------
  function updateNameItem(id: string, patch: Partial<NameItem>) {
    setNames((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch } : n)));
  }

  function setEntityTypeForAll(uiType: UiType) {
    setNames((prev) => {
      const normalized = prev.map((n) => ({
        ...n,
        uiType,
        nameMode: uiType === "Individual" ? n.nameMode : "full",
        firstName: uiType === "Individual" ? n.firstName : "",
        lastName: uiType === "Individual" ? n.lastName : "",
        middleName: uiType === "Individual" ? n.middleName : "",
      }));
      const supportsAlias = uiType === "Individual" || uiType === "Organization" || uiType === "Unknown";
      return supportsAlias ? normalized : normalized.slice(0, 1);
    });
  }

  function addName() {
    setNames((prev) => {
      const primaryType = prev[0]?.uiType ?? "Individual";
      if (primaryType !== "Individual" && primaryType !== "Organization" && primaryType !== "Unknown") return prev;
      const isIndividual = primaryType === "Individual";
      return [
        ...prev,
        {
          id: uuid(),
          uiType: primaryType,
          nameMode: isIndividual ? "split" : "full",
          firstName: "",
          lastName: "",
          middleName: "",
          fullName: "",
          aliasName: "",
          dateOfBirth: "",
          countries: [""],
          addresses: [""],
          ids: [{ idType: "PASSPORT", idNumber: "", idCountry: "" }],
        },
      ];
    });
  }

  function removeName(id: string) {
    setNames((prev) => (prev.length <= 1 ? prev : prev.filter((n) => n.id !== id)));
  }

  function addCountry(id: string) {
    setNames((prev) => prev.map((n) => (n.id === id ? { ...n, countries: [...n.countries, ""] } : n)));
  }

  function removeCountry(id: string, index: number) {
    setNames((prev) =>
      prev.map((n) => {
        if (n.id !== id || n.countries.length <= 1) return n;
        return { ...n, countries: n.countries.filter((_, i) => i !== index) };
      })
    );
  }

  function addAddress(id: string) {
    setNames((prev) => prev.map((n) => (n.id === id ? { ...n, addresses: [...n.addresses, ""] } : n)));
  }

  function removeAddress(id: string, index: number) {
    setNames((prev) =>
      prev.map((n) => {
        if (n.id !== id || n.addresses.length <= 1) return n;
        return { ...n, addresses: n.addresses.filter((_, i) => i !== index) };
      })
    );
  }

  function addIdDoc(id: string) {
    setNames((prev) =>
      prev.map((n) => (n.id === id ? { ...n, ids: [...n.ids, { idType: "PASSPORT", idNumber: "", idCountry: "" }] } : n))
    );
  }

  function removeIdDoc(id: string, index: number) {
    setNames((prev) =>
      prev.map((n) => {
        if (n.id !== id || n.ids.length <= 1) return n;
        return { ...n, ids: n.ids.filter((_, i) => i !== index) };
      })
    );
  }

  // ---------- Submit Single (multi-query) ----------
  async function submitSingle(e: React.FormEvent) {
    e.preventDefault();
    setSingleError(null);
    setSingleSubmitting(true);

    try {
      if (!canSingleScreen) {
        setSingleError("You do not have permission to run single screening.");
        setSingleSubmitting(false);
        return;
      }
      if (!currentUser) {
        setSingleError("Authenticated user context is missing. Please sign in again.");
        setSingleSubmitting(false);
        return;
      }
      if (viewerMockOnly && !singleMockScreening) {
        setSingleError("Viewer role can run only mock single screening.");
        setSingleSubmitting(false);
        return;
      }
      if (!singleScreeningTypes.length) {
        setSingleError("Select at least one screening type.");
        setSingleSubmitting(false);
        return;
      }
      if (!safeTrim(singleBusinessUnitCode)) {
        setSingleError("Business Unit is required.");
        setSingleSubmitting(false);
        return;
      }

      const parsed = singleSchema.safeParse(names);
      if (!parsed.success) {
        setSingleError(parsed.error.issues[0]?.message ?? "Fix validation errors.");
        setSingleSubmitting(false);
        return;
      }

      // Build one API call containing one query. For Individual/Organization/Unknown, merge AKA/Alias into the same name list.
      const queries: Record<string, EntityExample> = {};
      const meta: { key: string; uiType: UiType; displayName: string }[] = [];
      const [primaryName, ...akaNames] = names;
      if (!primaryName) throw new Error("At least one name is required.");

      const key = "single_1";
      const displayName =
        primaryName.uiType === "Individual"
          ? safeTrim(primaryName.fullName) || [safeTrim(primaryName.firstName), safeTrim(primaryName.lastName)].filter(Boolean).join(" ")
          : safeTrim(primaryName.fullName);

      const query = buildEntityExampleFromNameItem(primaryName);

      if ((primaryName.uiType === "Individual" || primaryName.uiType === "Organization" || primaryName.uiType === "Unknown") && akaNames.length) {
        const aliasNameValues = akaNames.flatMap((alias) => {
          const values: string[] = [];
          if (primaryName.uiType === "Individual") {
            const split = [safeTrim(alias.firstName), safeTrim(alias.middleName), safeTrim(alias.lastName)].filter(Boolean).join(" ");
            const full = safeTrim(alias.fullName);
            const aliasField = safeTrim(alias.aliasName);
            if (split) values.push(split);
            if (full && full.toLowerCase() !== split.toLowerCase()) values.push(full);
            if (aliasField) values.push(aliasField);
          } else {
            const full = safeTrim(alias.fullName);
            const aliasField = safeTrim(alias.aliasName);
            if (full) values.push(full);
            if (aliasField && aliasField.toLowerCase() !== full.toLowerCase()) values.push(aliasField);
          }
          return values;
        });

        const props = (query.properties ?? {}) as Record<string, any>;
        if (primaryName.uiType === "Individual") {
          const aliasObjects = akaNames
            .map((alias) => {
              const aliasFirstName = safeTrim(alias.firstName);
              const aliasMiddleName = safeTrim(alias.middleName);
              const aliasLastName = safeTrim(alias.lastName);
              const aliasFullName = safeTrim(alias.fullName) || [aliasFirstName, aliasMiddleName, aliasLastName].filter(Boolean).join(" ");
              const aliasEntry: Record<string, string> = {};
              if (aliasFirstName) aliasEntry.firstName = aliasFirstName;
              if (aliasMiddleName) aliasEntry.middleName = aliasMiddleName;
              if (aliasLastName) aliasEntry.lastName = aliasLastName;
              if (aliasFullName) aliasEntry.fullName = aliasFullName;
              return aliasEntry;
            })
            .filter((entry) => Object.keys(entry).length > 0);
          if (aliasObjects.length) {
            props.aliases = aliasObjects;
          }
        }
        const existingNames = Array.isArray(props.name)
          ? props.name.map((v) => safeTrim(String(v))).filter(Boolean)
          : [];

        const mergedNames: string[] = [];
        const seenNames = new Set<string>();
        [...existingNames, ...aliasNameValues].forEach((value) => {
          const safeValue = safeTrim(value);
          if (!safeValue) return;
          const dedupeKey = safeValue.toLowerCase();
          if (seenNames.has(dedupeKey)) return;
          seenNames.add(dedupeKey);
          mergedNames.push(safeValue);
        });

        if (mergedNames.length && primaryName.uiType !== "Individual") {
          props.name = mergedNames;
        }
        query.properties = props;
      }

      const singleProps = (query.properties ?? {}) as Record<string, any>;
      const safeSingleBusinessUnitCode = safeTrim(singleBusinessUnitCode).toUpperCase();
      const safeSingleNotes = safeTrim(notes);
      if (safeSingleBusinessUnitCode) {
        singleProps.businessUnit = safeSingleBusinessUnitCode;
      }
      if (safeSingleNotes) {
        singleProps.screeningNotes = [safeSingleNotes];
      }
      query.properties = singleProps;

      meta.push({ key, uiType: primaryName.uiType, displayName: displayName || "(Item 1)" });
      queries[key] = query;

      await matchSync(queries, singleScreeningTypes, singleMockScreening, {
        id: currentUser.id,
        name: currentUser.name,
      }, singleBusinessUnitCode);
      void loadRecentResults({ silent: false, updateTimestamp: true, resetPage: true, requestUserId: currentUser.id });
    } catch (err: any) {
      setSingleError(err?.message ?? "Failed to screen.");
    } finally {
      setSingleSubmitting(false);
    }
  }

  // ---------- Batch submit ----------
  async function submitBatch(e: React.FormEvent) {
    e.preventDefault();
    setBatchError(null);
    setBatchSuccess(null);

    if (!canBatchScreen) {
      setBatchError("You do not have permission to run batch screening.");
      return;
    }
    if (!currentUser) {
      setBatchError("Authenticated user context is missing. Please sign in again.");
      return;
    }
    if (!safeTrim(batchName)) {
      setBatchError("Batch Name is required.");
      return;
    }
    if (!batchScreeningTypes.length) {
      setBatchError("Select at least one screening type.");
      return;
    }
    if (!safeTrim(batchBusinessUnitCode)) {
      setBatchError("Business Unit is required.");
      return;
    }
    if (!batchFile) {
      setBatchError("Please drop or select a CSV or XLSX file.");
      return;
    }

    setBatchSubmitting(true);
    try {
      const accepted = await uploadBatchAndSubmitJob({
        file: batchFile,
        screeningTypes: batchScreeningTypes,
        batchName,
        businessUnitCode: batchBusinessUnitCode,
        dailyScreening: false,
        mockScreening: false,
        subscribeResults: false,
        userName: currentUser.name,
      });
      const safeFileName = safeTrim(accepted.file_name) || safeTrim(batchFile?.name) || "Batch file";
      setBatchSuccess(
        `${safeFileName} file upload completed successfully. Batch screening job ${accepted.job_id} is submitted.`
      );
      void loadRecentResults({ silent: false, updateTimestamp: true, resetPage: true, requestUserId: currentUser.id });

      // reset batch inputs after success
      setBatchFile(null);
      setBatchFileName("");
      setBatchName("");
      setBatchScreeningTypes(batchDefaultScreeningType ? [batchDefaultScreeningType] : []);
      setTemplatesOpen(false);
    } catch (err: any) {
      setBatchSuccess(null);
      setBatchError(err?.message ?? "Batch screening failed.");
    } finally {
      setBatchSubmitting(false);
    }
  }

  // ---------- Scheduled batch submit ----------
  async function submitSchedule(e: React.FormEvent) {
    e.preventDefault();
    setScheduleError(null);
    setScheduleSuccess(null);

    if (!canDailyScreening) {
      setScheduleError("Only Compliance/Admin can configure scheduled screening.");
      return;
    }
    if (!currentUser) {
      setScheduleError("Authenticated user context is missing. Please sign in again.");
      return;
    }
    if (!safeTrim(scheduleName)) {
      setScheduleError("Schedule Name is required.");
      return;
    }
    if (!scheduleScreeningTypes.length) {
      setScheduleError("Select at least one screening type.");
      return;
    }
    if (!safeTrim(scheduleBusinessUnitCode)) {
      setScheduleError("Business Unit is required.");
      return;
    }
    if (!safeTrim(scheduleRunAt)) {
      setScheduleError("Run date/time is required.");
      return;
    }
    if (!scheduleFile) {
      setScheduleError("Please drop or select a CSV/XLSX file.");
      return;
    }

    const scheduleRunAtUtc = localDateTimeToUtcIso(scheduleRunAt);
    if (!scheduleRunAtUtc) {
      setScheduleError("Run date/time is invalid.");
      return;
    }

    const parsedSubscriptions = parseSubscriptionEmails(scheduleSubscriptionEmails);
    if (parsedSubscriptions.invalidEmails.length > 0) {
      const invalidPreview = parsedSubscriptions.invalidEmails.slice(0, 5).join(", ");
      const suffix = parsedSubscriptions.invalidEmails.length > 5 ? " ..." : "";
      setScheduleError(`Only @${SUBSCRIPTION_EMAIL_DOMAIN} emails are allowed. Invalid: ${invalidPreview}${suffix}`);
      return;
    }
    const subscriptionEmails = parsedSubscriptions.validEmails;
    setScheduleSubmitting(true);
    try {
      const accepted = await uploadBatchAndSubmitJob({
        file: scheduleFile,
        screeningTypes: scheduleScreeningTypes,
        batchName: scheduleName,
        businessUnitCode: scheduleBusinessUnitCode,
        dailyScreening: true,
        scheduleFrequency,
        scheduleRunAt: scheduleRunAtUtc,
        mockScreening: false,
        subscribeResults: subscriptionEmails.length > 0,
        subscribeEmails: subscriptionEmails,
        userName: currentUser.name,
      });
      const safeFileName = safeTrim(accepted.file_name) || safeTrim(scheduleFile?.name) || "Batch file";
      const safeFrequency = safeTrim(String(accepted.schedule_frequency || scheduleFrequency)).toUpperCase() || "DAILY";
      const safeScheduleId = safeTrim(String(accepted.daily_schedule_id || ""));
      const scheduleIdMsg = safeScheduleId ? ` Schedule ID ${safeScheduleId} created.` : "";
      setScheduleSuccess(`${safeFileName} scheduled batch submitted successfully.${scheduleIdMsg} Frequency: ${safeFrequency}.`);
      void loadRecentResults({ silent: false, updateTimestamp: true, resetPage: true, requestUserId: currentUser.id });

      setScheduleName("");
      setScheduleScreeningTypes(scheduleDefaultScreeningType ? [scheduleDefaultScreeningType] : []);
      setScheduleFrequency("DAILY");
      setScheduleRunAt(defaultScheduleRunAtValue());
      setScheduleSubscriptionEmails("");
      setScheduleFile(null);
      setScheduleFileName("");
      setScheduleTemplatesOpen(false);
    } catch (err: any) {
      setScheduleSuccess(null);
      setScheduleError(err?.message ?? "Scheduled screening failed.");
    } finally {
      setScheduleSubmitting(false);
    }
  }

  // ---------- Flatten results (used under BOTH tabs) ----------
  const flattened = recentResultRows;

  const hasPendingResults = useMemo(() => flattened.some((row) => row.uiStatus === "Pending"), [flattened]);

  useEffect(() => {
    if (!currentUser?.id || !hasPendingResults) return;
    const timerId = window.setInterval(() => {
      void loadRecentResults({ silent: true, updateTimestamp: false, resetPage: false });
    }, 15000);
    return () => window.clearInterval(timerId);
  }, [currentUser?.id, hasPendingResults, loadRecentResults]);

  // ---------- Filters ----------
  const filtered = useMemo(() => {
    const q = safeTrim(search).toLowerCase();

    return flattened.filter((r) => {
      // All types
      if (typeFilter !== "All Types" && r.type !== typeFilter) return false;

      // All statuses
      if (statusFilter !== "All Statuses" && r.uiStatus !== statusFilter) return false;

      // Search on core visible fields to keep filtering fast.
      if (!q) return true;
      const hay = `${r.entity} ${r.partyKey} ${r.mode} ${resultModeLabel(r)} ${r.type} ${r.screeningType} ${r.country} ${r.uiStatus} ${r.date}`.toLowerCase();
      return hay.includes(q);
    });
  }, [flattened, search, statusFilter, typeFilter]);

  const sorted = useMemo(() => {
    const rows = [...filtered];
    rows.sort((a, b) => {
      if (resultSortKey === "score") {
        const aScore = typeof a.matchingScore === "number" ? a.matchingScore : -1;
        const bScore = typeof b.matchingScore === "number" ? b.matchingScore : -1;
        return aScore - bScore;
      }
      if (resultSortKey === "status") {
        return STATUS_SORT_RANK[a.uiStatus] - STATUS_SORT_RANK[b.uiStatus];
      }
      if (resultSortKey === "submittedAt") {
        const aTime = Date.parse(a.submittedAt || "") || 0;
        const bTime = Date.parse(b.submittedAt || "") || 0;
        return aTime - bTime;
      }
      if (resultSortKey === "entity") return a.entity.localeCompare(b.entity);
      if (resultSortKey === "mode") return resultModeLabel(a).localeCompare(resultModeLabel(b));
      if (resultSortKey === "type") return a.type.localeCompare(b.type);
      return (a.country || "").localeCompare(b.country || "");
    });
    if (resultSortDirection === "desc") rows.reverse();
    return rows;
  }, [filtered, resultSortDirection, resultSortKey]);

  function exportFilteredResultsCsv() {
    if (!filtered.length) return;

    const headers = [
      "Entity",
      "Party Key",
      "Mode",
      "Type",
      "Screening Type",
      "Country",
      "Status",
      "Matching Score",
      "Submitted Date/Time",
      "Daily Screening",
      "Batch Name",
      "Top Hit Name",
      "Top Hit Score",
      "Top Hit Keyword/Category",
      "Total Hits",
    ];

    const rows = filtered.map((row) => {
      const submission = row.raw?.submission;
      const screeningTypesRaw = submission?.screeningTypes ?? submission?.details?.screeningTypes ?? [];
      const screeningTypes = Array.isArray(screeningTypesRaw)
        ? screeningTypesRaw.map((value: unknown) => safeTrim(String(value))).filter(Boolean).join(", ")
        : "";
      const screeningType = row.screeningType || screeningTypes;

      const batchName = safeTrim(String(submission?.fileName ?? ""));
      const hitRows = getHitMatchesFromRaw(row.raw);
      const topHit = hitRows[0];

      return [
        row.entity,
        row.partyKey,
        resultModeLabel(row),
        row.type,
        screeningType,
        row.country || "",
        row.uiStatus,
        formatMatchingScore(row.matchingScore),
        row.date,
        row.dailyScheduleActive ? "Yes" : "No",
        batchName,
        topHit?.name ?? "",
        topHit?.matchingScore != null ? formatMatchingScore(topHit.matchingScore) : "",
        topHit?.keywordOrCategory ?? "",
        String(hitRows.length),
      ];
    });

    const csv = [
      headers.map(csvEscape).join(","),
      ...rows.map((line) => line.map(csvEscape).join(",")),
    ].join("\n");

    const filename = `screening_results_${exportTimestamp()}.csv`;
    downloadBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), filename);
  }

  // ---------- Pagination (10) ----------
  const pageSize = 10;
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const pageSafe = Math.min(page, totalPages);
  const startIdx = (pageSafe - 1) * pageSize;
  const pageRows = sorted.slice(startIdx, startIdx + pageSize);
  const resultTableMinWidth = useMemo(
    () => Object.values(resultColumnWidths).reduce((sum, width) => sum + Number(width || 0), 0),
    [resultColumnWidths]
  );
  const configuredActimizeReviewAlertUrl = normalizeReviewUrl(appEnv("VITE_ACTIMIZE_REVIEW_ALERT_URL", "").trim());
  const actimizeReviewAlertUrl = configuredActimizeReviewAlertUrl || DEFAULT_ACTIMIZE_REVIEW_ALERT_URL;
  const [hitEntityDialog, setHitEntityDialog] = useState<{
    sourceEntity: string;
    hits: HitMatch[];
    error: { status: number | null; text: string } | null;
    pending: boolean;
    reviewUrl: string;
  } | null>(null);

  function sortIndicator(key: ResultSortKey): string {
    if (resultSortKey !== key) return "\u21C5";
    return resultSortDirection === "asc" ? "\u25B2" : "\u25BC";
  }

  function toggleResultSort(key: ResultSortKey): void {
    if (resultSortKey === key) {
      updateScreeningWorkspace({
        resultSortDirection: resultSortDirection === "asc" ? "desc" : "asc",
      });
      return;
    }
    updateScreeningWorkspace({
      resultSortKey: key,
      resultSortDirection: key === "submittedAt" || key === "score" ? "desc" : "asc",
    });
  }

  function renderResizableResultHeader(
    columnKey: ResultTableColumnKey,
    label: React.ReactNode,
    options?: { align?: "left" | "right" }
  ) {
    return (
      <th scope="col" style={{ width: resultColumnWidths[columnKey] }}>
        <div className={`resizableHeaderCell${options?.align === "right" ? " alignRight" : ""}`}>
          <div className="resizableHeaderContent">{label}</div>
          <button
            type="button"
            className="colResizeHandle"
            aria-label={`Resize ${RESULT_TABLE_COLUMN_LABELS[columnKey]} column`}
            onMouseDown={(event) => startResultColumnResize(columnKey, event)}
          />
        </div>
      </th>
    );
  }

  function openHitEntity(row: ResultRow) {
    const hits = getHitMatchesFromRaw(row.raw);
    const error = row.uiStatus === "Failed" ? extractEngineErrorFromRaw(row.raw) : null;
    const rowReviewUrl = resolveActimizeReviewUrlFromRaw(row.raw);
    setHitEntityDialog({
      sourceEntity: row.entity,
      hits,
      error: error ? { status: error.status, text: error.errorText } : null,
      pending: row.uiStatus === "Pending",
      reviewUrl: rowReviewUrl || actimizeReviewAlertUrl,
    });
  }

  useEffect(() => {
    if (!hitEntityDialog) return;
    hitDialogCloseBtnRef.current?.focus();
  }, [hitEntityDialog]);

  useEffect(() => {
    if (!hitEntityDialog) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setHitEntityDialog(null);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [hitEntityDialog]);

  function handleModeTabKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, current: Mode) {
    const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!keys.includes(e.key)) return;
    e.preventDefault();

    const available: Mode[] = [
      "SINGLE",
      ...(canBatchScreen ? ["BATCH"] : []),
      ...(canDailyScreening ? ["SCHEDULE"] : []),
    ] as Mode[];

    const idx = available.indexOf(current);
    if (idx < 0) return;

    if (e.key === "Home") {
      updateScreeningWorkspace({ mode: available[0] });
      return;
    }
    if (e.key === "End") {
      updateScreeningWorkspace({ mode: available[available.length - 1] });
      return;
    }
    const delta = e.key === "ArrowRight" ? 1 : -1;
    const next = (idx + delta + available.length) % available.length;
    updateScreeningWorkspace({ mode: available[next] });
  }
  const roleDisplay = primaryRole ? primaryRole[0].toUpperCase() + primaryRole.slice(1) : "Unknown";
  const scheduleTimezoneLabel = useMemo(() => {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Local";
    const tzPart = Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
      .formatToParts(new Date())
      .find((part) => part.type === "timeZoneName")?.value;
    return tzPart ? `${tzPart} (${zone})` : zone;
  }, []);

  return (
    <div className="page">
      <section className="pageHero" aria-label="Screening">
        <div className="pageHeroMain">
          <div className="pageHeroHead">
            <span className="pageHeroIcon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 6h18M3 12h18M3 18h11" />
              </svg>
            </span>
            <div>
              <p className="pageHeroEyebrow">Screening</p>
              <h1 className="pageHeroTitle">Entity Screening Workbench</h1>
            </div>
          </div>
          <p className="pageHeroSub">Run single checks in real-time, submit queued batch files, and configure scheduled screening from one workspace.</p>
        </div>
        <div className="pageHeroMeta" aria-hidden="true">
          <span className="pageHeroPill">Role: {roleDisplay}</span>
          <span className="pageHeroPill">{canDailyScreening ? "Schedule Enabled" : "Schedule Restricted"}</span>
          <span className="pageHeroPill">{viewerMockOnly ? "Mock-only Single" : "Production Screening"}</span>
        </div>
      </section>

      <SummaryCards counts={summaryCounts} />
      <div className="tabsRow">
        <div className="tabSwitch" role="tablist" aria-label="Screening mode" aria-orientation="horizontal">
          <button
            id="tab-single"
            role="tab"
            aria-selected={mode === "SINGLE"}
            aria-controls="panel-single"
            className={mode === "SINGLE" ? "tabBtn active" : "tabBtn"}
            onClick={() => updateScreeningWorkspace({ mode: "SINGLE" })}
            onKeyDown={(e) => handleModeTabKeyDown(e, "SINGLE")}
            type="button"
          >
            <span className="tabIcon">&#x1F50D;</span>
            <span>Single Screening</span>
            <span className="executionModeBadge executionModeBadgeSync">Real-time</span>
          </button>
          <button
            id="tab-batch"
            role="tab"
            aria-selected={mode === "BATCH"}
            aria-controls="panel-batch"
            className={mode === "BATCH" ? "tabBtn active" : "tabBtn"}
            onClick={() => updateScreeningWorkspace({ mode: "BATCH" })}
            onKeyDown={(e) => handleModeTabKeyDown(e, "BATCH")}
            type="button"
            disabled={!canBatchScreen}
            title={canBatchScreen ? "Batch screening" : "Batch screening is not allowed for your role"}
          >
            <span className="tabIcon">&#x1F4C4;</span>
            <span>Batch Screening</span>
            <span className="executionModeBadge executionModeBadgeAsync">Queued</span>
          </button>
          <button
            id="tab-schedule"
            role="tab"
            aria-selected={mode === "SCHEDULE"}
            aria-controls="panel-schedule"
            className={mode === "SCHEDULE" ? "tabBtn active" : "tabBtn"}
            onClick={() => updateScreeningWorkspace({ mode: "SCHEDULE" })}
            onKeyDown={(e) => handleModeTabKeyDown(e, "SCHEDULE")}
            type="button"
            disabled={!canDailyScreening}
            title={canDailyScreening ? "Schedule recurring screening" : "Scheduled screening is allowed for Compliance/Admin only"}
          >
            <span className="tabIcon">&#x1F4C5;</span>
            <span>Schedule Screening</span>
            <span className="executionModeBadge executionModeBadgeAsync">Queued</span>
          </button>
        </div>
        <div className="muted" style={{ fontSize: 12 }}>
          Role: {roleDisplay}
          {viewerMockOnly ? " (mock-only single screening)" : ""}
        </div>

        <button className="btnGhost" type="button" onClick={clearAll} disabled={anySubmitting} style={{ marginLeft: "auto" }}>
          Clear
        </button>
      </div>

      {/* SINGLE */}
      {mode === "SINGLE" && (
        <div id="panel-single" role="tabpanel" aria-labelledby="tab-single" className="card">
          <div className="cardHeader">
            <h2>Single Entity Screening</h2>
          </div>

          <div className="cardBody">
            <form onSubmit={submitSingle}>
              <div className="singleEntityTypeRow">
                <div className="field singleEntityTypeField">
                  <label>Entity Type <span className="requiredMark">*</span></label>
                  <FormSelect
                    value={selectedEntityType}
                    onChange={(uiType) => setEntityTypeForAll(uiType)}
                    options={ENTITY_TYPE_OPTIONS}
                    ariaLabel="Entity type"
                  />
                </div>
                <div className="field singleEntityTypeField">
                  <label>Business Unit <span className="requiredMark">*</span></label>
                  <select
                    value={singleBusinessUnitCode}
                    onChange={(e) => setSingleBusinessUnitCode(e.target.value)}
                    required
                    disabled={businessUnitsSelectDisabled}
                    aria-busy={businessUnitsPending}
                  >
                    <option value="">{businessUnitsPlaceholderLabel}</option>
                    {selectableBusinessUnitOptions.map((row) => (
                      <option key={row.code} value={row.code}>
                        {row.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {businessUnitsPending && !businessUnitsAvailable ? (
                <div className="infoBox" role="status" aria-live="polite">
                  Loading Business Units...
                </div>
              ) : null}
              {businessUnitsError ? (
                <div className="errorBox" role="alert" aria-live="assertive">
                  {businessUnitsError}
                  <div style={{ marginTop: 8 }}>
                    <button type="button" className="btnGhostSmall" onClick={() => void reloadBusinessUnits()} disabled={businessUnitsPending}>
                      Retry
                    </button>
                  </div>
                </div>
              ) : null}
              {businessUnitsResolved && currentUser && !businessUnitsEffectiveAvailable && !businessUnitsError ? (
                <div className="errorBox" role="alert" aria-live="polite">
                  No Business Unit is mapped to your user. Please contact an administrator. (User ID: {currentUser.id})
                </div>
              ) : null}

              <ScreeningTypeCards
                selected={singleScreeningTypes}
                onToggle={(value) => toggleScreeningType(value, setSingleScreeningTypes)}
                options={singleScreeningTypeOptions}
              />

              <div className="mockModeCard">
                <label className="mockModeCheck">
                  <input
                    type="checkbox"
                    checked={singleMockScreening}
                    onChange={(e) => setSingleMockScreening(e.target.checked)}
                    disabled={viewerMockOnly}
                  />
                  <span>Mock screening only (check hits, do not generate Actimize alert)</span>
                </label>
                <div className="mockModeHint">
                  {viewerMockOnly
                    ? "Viewer role is restricted to mock screening only."
                    : "Uncheck this to generate an alert in Actimize during single screening."}
                </div>
              </div>

              {/* Names section with +Add */}
              <div className="sectionRow">
                <div className="sectionTitle">Names</div>
              </div>

              {primaryName ? (
                <div key={primaryName.id} className="nameCard">
                  <div className="nameCardTop">
                    <div className="nameCardLabel">
                      Primary Name <span className="requiredMark">*</span>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      {primaryName.uiType === "Individual" || primaryName.uiType === "Organization" || primaryName.uiType === "Unknown" ? (
                        <button type="button" className="btnAdd" onClick={addName}>
                          + Add AKA/Alias
                        </button>
                      ) : null}
                    </div>
                  </div>

                  {/* Individual name inputs */}
                  {primaryName.uiType === "Individual" ? (
                    <>
                      <div className="grid3">
                        <div className="field">
                          <label>First Name</label>
                          <input value={primaryName.firstName} onChange={(e) => updateNameItem(primaryName.id, { firstName: e.target.value })} />
                        </div>
                        <div className="field">
                          <label>Middle Name</label>
                          <input value={primaryName.middleName} onChange={(e) => updateNameItem(primaryName.id, { middleName: e.target.value })} />
                        </div>
                        <div className="field">
                          <label>Last Name</label>
                          <input value={primaryName.lastName} onChange={(e) => updateNameItem(primaryName.id, { lastName: e.target.value })} />
                        </div>
                      </div>

                      <div className="orDivider">
                        <span>AND / OR</span>
                      </div>

                      <div className="grid2">
                        <div className="field" style={{ gridColumn: "1 / -1" }}>
                          <label>Full Name</label>
                          <input value={primaryName.fullName} onChange={(e) => updateNameItem(primaryName.id, { fullName: e.target.value })} />
                        </div>
                      </div>

                      {aliasNames.map((alias, aliasIdx) => (
                        <div key={alias.id} style={{ marginTop: 12 }}>
                          <div className="nameCardTop">
                            <div className="nameCardLabel">{`AKA/Alias #${aliasIdx + 1}`}</div>
                            <button
                              type="button"
                              className="iconRemoveBtn inlineTrashBtn"
                              onClick={() => removeName(alias.id)}
                              aria-label={`Remove AKA/Alias ${aliasIdx + 1}`}
                              title="Remove AKA/Alias"
                            >
                              {"\u{1F5D1}"}
                            </button>
                          </div>

                          <div className="grid3">
                            <div className="field">
                              <label>First Name</label>
                              <input value={alias.firstName} onChange={(e) => updateNameItem(alias.id, { firstName: e.target.value })} />
                            </div>
                            <div className="field">
                              <label>Middle Name</label>
                              <input value={alias.middleName} onChange={(e) => updateNameItem(alias.id, { middleName: e.target.value })} />
                            </div>
                            <div className="field">
                              <label>Last Name</label>
                              <input value={alias.lastName} onChange={(e) => updateNameItem(alias.id, { lastName: e.target.value })} />
                            </div>
                          </div>

                          <div className="grid2">
                            <div className="field" style={{ gridColumn: "1 / -1" }}>
                              <label>Full Name</label>
                              <input value={alias.fullName} onChange={(e) => updateNameItem(alias.id, { fullName: e.target.value })} />
                            </div>
                          </div>
                        </div>
                      ))}

                      <div className="field dobFieldCompact">
                        <label>Date of Birth</label>
                        <IsoDateInput
                          value={primaryName.dateOfBirth}
                          onChange={(value) => updateNameItem(primaryName.id, { dateOfBirth: value })}
                        />
                      </div>
                    </>
                  ) : primaryName.uiType === "Organization" || primaryName.uiType === "Unknown" ? (
                    <>
                      <div className="grid2">
                        <div className="field" style={{ gridColumn: "1 / -1" }}>
                          <label>Primary Name <span className="requiredMark">*</span></label>
                          <input value={primaryName.fullName} onChange={(e) => updateNameItem(primaryName.id, { fullName: e.target.value })} />
                        </div>
                      </div>

                      {aliasNames.map((alias, aliasIdx) => (
                        <div key={alias.id} style={{ marginTop: 12 }}>
                          <div className="nameCardTop">
                            <div className="nameCardLabel">{`AKA/Alias #${aliasIdx + 1}`}</div>
                            <button
                              type="button"
                              className="iconRemoveBtn inlineTrashBtn"
                              onClick={() => removeName(alias.id)}
                              aria-label={`Remove AKA/Alias ${aliasIdx + 1}`}
                              title="Remove AKA/Alias"
                            >
                              {"\u{1F5D1}"}
                            </button>
                          </div>

                          <div className="grid2">
                            <div className="field" style={{ gridColumn: "1 / -1" }}>
                              <label>Full Name</label>
                              <input value={alias.fullName} onChange={(e) => updateNameItem(alias.id, { fullName: e.target.value })} />
                            </div>
                          </div>
                        </div>
                      ))}
                    </>
                  ) : (
                    <div className="grid2">
                      <div className="field" style={{ gridColumn: "1 / -1" }}>
                        <label>Primary Name <span className="requiredMark">*</span></label>
                        <input value={primaryName.fullName} onChange={(e) => updateNameItem(primaryName.id, { fullName: e.target.value })} />
                      </div>
                    </div>
                  )}

                  {/* Countries (multi) */}
                  <div className="sectionRow" style={{ marginTop: 10 }}>
                    <div className="sectionTitleSmall">Countries</div>
                    <button type="button" className="btnAddSmall" onClick={() => addCountry(primaryName.id)}>
                      + Add Country
                    </button>
                  </div>

                  <div className="stack">
                    {primaryName.countries.map((c, i) => (
                      <div key={i} className="inlineItemRow">
                        <CountryAutosuggest
                          label={i === 0 ? "Country" : ""}
                          value={c}
                          onChange={(v) => {
                            const next = [...primaryName.countries];
                            next[i] = v;
                            updateNameItem(primaryName.id, { countries: next });
                          }}
                        />
                        {i > 0 ? (
                          <button
                            type="button"
                            className="iconRemoveBtn inlineTrashBtn"
                            onClick={() => removeCountry(primaryName.id, i)}
                            aria-label={`Remove country ${i + 1}`}
                            title="Remove country"
                          >
                            {"\u{1F5D1}"}
                          </button>
                        ) : null}
                      </div>
                    ))}
                  </div>

                  {/* Addresses (multi) */}
                  <div className="sectionRow" style={{ marginTop: 10 }}>
                    <div className="sectionTitleSmall">Addresses</div>
                    <button type="button" className="btnAddSmall" onClick={() => addAddress(primaryName.id)}>
                      + Add Address
                    </button>
                  </div>

                  <div className="stack">
                    {primaryName.addresses.map((a, i) => (
                      <div className="inlineItemRow" key={i}>
                        <div className="field inlineFieldFill">
                          <label>{i === 0 ? "Address" : ""}</label>
                          <input
                            placeholder="Full address line"
                            value={a}
                            onChange={(e) => {
                              const next = [...primaryName.addresses];
                              next[i] = e.target.value;
                              updateNameItem(primaryName.id, { addresses: next });
                            }}
                          />
                        </div>
                        {i > 0 ? (
                          <button
                            type="button"
                            className="iconRemoveBtn inlineTrashBtn"
                            onClick={() => removeAddress(primaryName.id, i)}
                            aria-label={`Remove address ${i + 1}`}
                            title="Remove address"
                          >
                            {"\u{1F5D1}"}
                          </button>
                        ) : null}
                      </div>
                    ))}
                  </div>

                  {/* IDs (multi) */}
                  <div className="sectionRow" style={{ marginTop: 10 }}>
                    <div className="sectionTitleSmall">Identification Documents</div>
                    <button type="button" className="btnAddSmall" onClick={() => addIdDoc(primaryName.id)}>
                      + Add Id
                    </button>
                  </div>

                  <div className="stack">
                    {primaryName.ids.map((doc, i) => (
                      <div className="inlineItemRow" key={i}>
                        <div className="grid3 inlineFieldFill">
                          <div className="field">
                            <label>{i === 0 ? "ID Type" : "\u00A0"}</label>
                            <select
                              className="idTypeSelect"
                              value={doc.idType}
                              onChange={(e) => {
                                const next = [...primaryName.ids];
                                next[i] = { ...next[i], idType: e.target.value };
                                updateNameItem(primaryName.id, { ids: next });
                              }}
                            >
                              {ID_TYPE_OPTIONS.map((type) => (
                                <option key={type} value={type}>
                                  {type}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="field">
                            <label>{i === 0 ? "ID Number" : "\u00A0"}</label>
                            <input
                              value={doc.idNumber}
                              onChange={(e) => {
                                const next = [...primaryName.ids];
                                next[i] = { ...next[i], idNumber: e.target.value };
                                updateNameItem(primaryName.id, { ids: next });
                              }}
                            />
                          </div>
                          <CountryAutosuggest
                            label={i === 0 ? "ID Country" : ""}
                            value={doc.idCountry}
                            onChange={(v) => {
                              const next = [...primaryName.ids];
                              next[i] = { ...next[i], idCountry: v };
                              updateNameItem(primaryName.id, { ids: next });
                            }}
                          />
                        </div>
                        {i > 0 ? (
                          <button
                            type="button"
                            className="iconRemoveBtn inlineTrashBtn"
                            onClick={() => removeIdDoc(primaryName.id, i)}
                            aria-label={`Remove identification row ${i + 1}`}
                            title="Remove ID"
                          >
                            {"\u{1F5D1}"}
                          </button>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {/* Notes at the end */}
              <div className="field" style={{ marginTop: 12 }}>
                <label>Notes</label>
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Additional notes or context..." />
              </div>

              {singleError ? <div className="errorBox" role="alert" aria-live="assertive">{singleError}</div> : null}
              <button className="btnRunWide" type="submit" disabled={singleSubmitting || !businessUnitsEffectiveAvailable}>
                {singleSubmitting ? "Running..." : "Run OFAC Screening"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* BATCH */}
      {mode === "BATCH" && (
        <div id="panel-batch" role="tabpanel" aria-labelledby="tab-batch" className="card">
          <div className="cardHeader">
            <h2>Batch Screening</h2>
          </div>

          <div className="cardBody">
            {/* Accordion header */}
            <button
              type="button"
              className="accordionHeader"
              onClick={() => setTemplatesOpen((v) => !v)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="accordionIcon">{"\u2B07"}</span>
                <span>Download Screening Templates</span>
                <span className="badgeCount">1 template</span>
              </div>
              <span className="chev">{templatesOpen ? "\u25B4" : "\u25BE"}</span>
            </button>

            {/* Accordion content */}
            {templatesOpen && (
              <div className="templateGrid5">
                <TemplateCard
                  title={UNIFIED_TEMPLATE.title}
                  desc={UNIFIED_TEMPLATE.desc}
                  chips={UNIFIED_TEMPLATE.chips}
                  actionLabel="Template"
                  onAction={downloadUnifiedTemplate}
                />
              </div>
            )}

            <div className="field" style={{ marginTop: 14 }}>
              <label>Batch Name <span className="requiredMark">*</span></label>
              <input required value={batchName} onChange={(e) => setBatchName(e.target.value)} placeholder="e.g., Q1 2024 Vendor Screening" />
            </div>

            <div className="field" style={{ marginTop: 10 }}>
              <label>Business Unit <span className="requiredMark">*</span></label>
              <select
                required
                value={batchBusinessUnitCode}
                onChange={(e) => setBatchBusinessUnitCode(e.target.value)}
                disabled={businessUnitsSelectDisabled}
                aria-busy={businessUnitsPending}
              >
                <option value="">{businessUnitsPlaceholderLabel}</option>
                {selectableBusinessUnitOptions.map((row) => (
                  <option key={row.code} value={row.code}>
                    {row.name}
                  </option>
                ))}
              </select>
            </div>

            <ScreeningTypeCards
              selected={batchScreeningTypes}
              onToggle={(value) => toggleScreeningType(value, setBatchScreeningTypes)}
              options={batchScreeningTypeOptions}
            />

            {/* Dropzone */}
            <div
              className={dragOver ? "dropzone dragOver" : "dropzone"}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const f = e.dataTransfer.files?.[0] ?? null;
                if (!validateUploadFile(f, setBatchError)) return;
                setBatchFile(f);
                setBatchFileName(f.name);
                setBatchError(null);
                setBatchSuccess(null);
              }}
              onClick={openFilePicker}
              onKeyDown={handleDropzoneKeyDown}
              role="button"
              aria-label="Upload batch file"
              tabIndex={0}
            >
              <div className="dropIconCircle">{"\u2B06"}</div>
              <div className="dropText">
                {batchFileName ? (
                  <>
                    Selected: <b>{batchFileName}</b>
                  </>
                ) : (
                  <>Drop your file here or click to browse</>
                )}
              </div>
              <div className="dropSub">Supports CSV and XLSX files</div>
              <div className="dropSub">
                <strong>Max File Size: {MAX_UPLOAD_DISPLAY_MB} MB</strong> <span className="muted">(system limit: {MAX_UPLOAD_VALIDATION_MB} MB)</span>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx"
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  if (validateUploadFile(f, setBatchError)) {
                    setBatchFile(f);
                    setBatchFileName(f.name);
                    setBatchError(null);
                    setBatchSuccess(null);
                  }
                  e.currentTarget.value = "";
                }}
              />
            </div>

            {businessUnitsPending && !businessUnitsAvailable ? (
              <div className="infoBox" role="status" aria-live="polite">
                Loading Business Units...
              </div>
            ) : null}
            {businessUnitsError ? (
              <div className="errorBox" role="alert" aria-live="assertive">
                {businessUnitsError}
                <div style={{ marginTop: 8 }}>
                  <button type="button" className="btnGhostSmall" onClick={() => void reloadBusinessUnits()} disabled={businessUnitsPending}>
                    Retry
                  </button>
                </div>
              </div>
            ) : null}
            {businessUnitsResolved && currentUser && !businessUnitsEffectiveAvailable && !businessUnitsError ? (
              <div className="errorBox" role="alert" aria-live="polite">
                No Business Unit is mapped to your user. Please contact an administrator. (User ID: {currentUser.id})
              </div>
            ) : null}
            {batchSuccess ? <div className="successBox" role="status" aria-live="polite">{batchSuccess}</div> : null}
            {batchError ? <div className="errorBox" role="alert" aria-live="assertive">{batchError}</div> : null}
            <form onSubmit={submitBatch}>
              <button className="btnBatchWide" type="submit" disabled={batchSubmitting || !businessUnitsEffectiveAvailable}>
                {batchSubmitting ? "Starting..." : "Start Batch Screening"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* SCHEDULE */}
      {mode === "SCHEDULE" && (
        <div id="panel-schedule" role="tabpanel" aria-labelledby="tab-schedule" className="card">
          <div className="cardHeader">
            <h2>Schedule Screening</h2>
          </div>

          <div className="cardBody">
            <button
              type="button"
              className="accordionHeader"
              onClick={() => setScheduleTemplatesOpen((v) => !v)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="accordionIcon">{"\u2B07"}</span>
                <span>Download Screening Templates</span>
                <span className="badgeCount">1 template</span>
              </div>
              <span className="chev">{scheduleTemplatesOpen ? "\u25B4" : "\u25BE"}</span>
            </button>

            {scheduleTemplatesOpen && (
              <div className="templateGrid5">
                <TemplateCard
                  title={UNIFIED_TEMPLATE.title}
                  desc={UNIFIED_TEMPLATE.desc}
                  chips={UNIFIED_TEMPLATE.chips}
                  actionLabel="Template"
                  onAction={downloadUnifiedTemplate}
                />
              </div>
            )}

            <form onSubmit={submitSchedule}>
              <div className="field" style={{ marginTop: 14 }}>
                <label>Schedule Name <span className="requiredMark">*</span></label>
                <input required value={scheduleName} onChange={(e) => setScheduleName(e.target.value)} placeholder="e.g., Daily Vendor Watchlist Run" />
              </div>

              <div className="field" style={{ marginTop: 10 }}>
                <label>Business Unit <span className="requiredMark">*</span></label>
                <select
                  required
                  value={scheduleBusinessUnitCode}
                  onChange={(e) => setScheduleBusinessUnitCode(e.target.value)}
                  disabled={businessUnitsSelectDisabled}
                  aria-busy={businessUnitsPending}
                >
                  <option value="">{businessUnitsPlaceholderLabel}</option>
                  {selectableBusinessUnitOptions.map((row) => (
                    <option key={row.code} value={row.code}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </div>

              <ScreeningTypeCards
                selected={scheduleScreeningTypes}
                onToggle={(value) => toggleScreeningType(value, setScheduleScreeningTypes)}
                options={scheduleScreeningTypeOptions}
              />

              <div className="grid2" style={{ marginTop: 10 }}>
                <div className="field">
                  <label>Frequency <span className="requiredMark">*</span></label>
                  <select
                    required
                    value={scheduleFrequency}
                    onChange={(e) => setScheduleFrequency(e.target.value as ScheduleFrequency)}
                  >
                    {SCHEDULE_FREQUENCY_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <div className="hintText">
                    {SCHEDULE_FREQUENCY_OPTIONS.find((opt) => opt.value === scheduleFrequency)?.hint ?? "Runs at selected schedule time."}
                  </div>
                </div>

                <div className="field">
                  <label>
                    First Run Date/Time <span className="requiredMark">*</span> <span className="fieldLabelMeta">({scheduleTimezoneLabel})</span>
                  </label>
                  <div className="isoDateWrap">
                    <input
                      ref={scheduleRunAtInputRef}
                      className="isoDateText noNativePickerIcon"
                      type="datetime-local"
                      required
                      value={scheduleRunAt}
                      onChange={(e) => setScheduleRunAt(e.target.value)}
                    />
                    <button
                      type="button"
                      className="isoDateBtn"
                      onClick={openScheduleRunAtPicker}
                      aria-label="Open date and time picker"
                      title="Open date and time picker"
                    >
                      <svg
                        className="isoDateIcon"
                        viewBox="0 0 24 24"
                        width="16"
                        height="16"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                        <line x1="16" y1="2" x2="16" y2="6" />
                        <line x1="8" y1="2" x2="8" y2="6" />
                        <line x1="3" y1="10" x2="21" y2="10" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>

              <div className="field" style={{ marginTop: 10 }}>
                <label>Subscription Emails</label>
                <textarea
                  value={scheduleSubscriptionEmails}
                  onChange={(e) => setScheduleSubscriptionEmails(e.target.value)}
                  placeholder="compliance@prudential.com, analyst@prudential.com"
                />
                <div className="hintText">
                  Use comma, semicolon, or new line to enter multiple email addresses. Only @prudential.com email addresses are allowed.
                </div>
              </div>

              <div
                className={dragOver ? "dropzone dragOver" : "dropzone"}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  const f = e.dataTransfer.files?.[0] ?? null;
                  if (!validateUploadFile(f, setScheduleError)) return;
                  setScheduleFile(f);
                  setScheduleFileName(f.name);
                  setScheduleError(null);
                  setScheduleSuccess(null);
                }}
                onClick={openFilePicker}
                onKeyDown={handleDropzoneKeyDown}
                role="button"
                aria-label="Upload scheduled screening file"
                tabIndex={0}
              >
                <div className="dropIconCircle">{"\u2B06"}</div>
                <div className="dropText">
                  {scheduleFileName ? (
                    <>
                      Selected: <b>{scheduleFileName}</b>
                    </>
                  ) : (
                    <>Drop your file here or click to browse</>
                  )}
                </div>
                <div className="dropSub">Supports CSV and XLSX files</div>
                <div className="dropSub">
                  <strong>Max File Size: {MAX_UPLOAD_DISPLAY_MB} MB</strong> <span className="muted">(system limit: {MAX_UPLOAD_VALIDATION_MB} MB)</span>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    if (validateUploadFile(f, setScheduleError)) {
                      setScheduleFile(f);
                      setScheduleFileName(f.name);
                      setScheduleError(null);
                      setScheduleSuccess(null);
                    }
                    e.currentTarget.value = "";
                  }}
                />
              </div>

              {businessUnitsPending && !businessUnitsAvailable ? (
                <div className="infoBox" role="status" aria-live="polite">
                  Loading Business Units...
                </div>
              ) : null}
              {businessUnitsError ? (
                <div className="errorBox" role="alert" aria-live="assertive">
                  {businessUnitsError}
                  <div style={{ marginTop: 8 }}>
                    <button type="button" className="btnGhostSmall" onClick={() => void reloadBusinessUnits()} disabled={businessUnitsPending}>
                      Retry
                    </button>
                  </div>
                </div>
              ) : null}
              {businessUnitsResolved && currentUser && !businessUnitsEffectiveAvailable && !businessUnitsError ? (
                <div className="errorBox" role="alert" aria-live="polite">
                  No Business Unit is mapped to your user. Please contact an administrator. (User ID: {currentUser.id})
                </div>
              ) : null}
              {scheduleSuccess ? <div className="successBox" role="status" aria-live="polite">{scheduleSuccess}</div> : null}
              {scheduleError ? <div className="errorBox" role="alert" aria-live="assertive">{scheduleError}</div> : null}
              <button className="btnBatchWide" type="submit" disabled={scheduleSubmitting || !businessUnitsEffectiveAvailable}>
                {scheduleSubmitting ? "Starting..." : "Create Scheduled Screening"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Screening Results (under BOTH tabs) */}
      <div className="card" style={{ marginTop: 18 }}>
        <div className="resultsHeader">
          <div className="resultsTitleRow">
            <h2>Screening Results</h2>
            <button
              type="button"
              className="iconBtn"
              title={resultsRefreshing ? "Refreshing screening results..." : "Refresh screening results"}
              aria-label={resultsRefreshing ? "Refreshing screening results" : "Refresh screening results"}
              onClick={refreshResults}
              disabled={resultsRefreshing}
              aria-busy={resultsRefreshing}
            >
              <RefreshIcon className={resultsRefreshing ? "iconSpin" : undefined} />
            </button>
            <button
              type="button"
              className="btnGhostSmall"
              title="Export filtered screening results to CSV"
              aria-label="Export filtered screening results to CSV"
              onClick={exportFilteredResultsCsv}
              disabled={filtered.length === 0}
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <DownloadIcon />
                <span>Export CSV</span>
              </span>
            </button>
          </div>

          {resultsRefreshError ? (
            <div className="errorBox" role="alert" aria-live="assertive" style={{ marginTop: 10 }}>
              {resultsRefreshError}
            </div>
          ) : null}
          {resultsRefreshing ? (
            <div className="muted" style={{ marginTop: 10 }} aria-live="polite">
              Refreshing results...
            </div>
          ) : resultsLastRefreshedAt ? (
            <div className="muted" style={{ marginTop: 10 }} aria-live="polite">
              Last refreshed: {resultsLastRefreshedAt.toLocaleString()}
            </div>
          ) : null}

          <div className="resultsFilters">
            <div className="searchBox">
              <span className="searchIcon">{"\u{1F50D}"}</span>
              <input
                aria-label="Search screening results"
                value={search}
                onChange={(e) => {
                  updateScreeningWorkspace({
                    search: e.target.value,
                    page: 1,
                  });
                }}
                placeholder="Search entities..."
              />
            </div>

            <select
              aria-label="Filter results by status"
              className="filterSelect"
              value={statusFilter}
              onChange={(e) => {
                updateScreeningWorkspace({
                  statusFilter: e.target.value as StatusFilter,
                  page: 1,
                });
              }}
            >
              <option>All Statuses</option>
              <option>Clear</option>
              <option>Potential Match</option>
              <option>Pending</option>
              <option>Failed</option>
              <option>Match</option>
            </select>

            <select
              aria-label="Filter results by entity type"
              className="filterSelect"
              value={typeFilter}
              onChange={(e) => {
                updateScreeningWorkspace({
                  typeFilter: e.target.value as TypeFilter,
                  page: 1,
                });
              }}
            >
              <option>All Types</option>
              <option>Individual</option>
              <option>Organization</option>
              <option>Unknown</option>
              <option>Vessel</option>
              <option>Aircraft</option>
            </select>
          </div>
        </div>

        <div className="cardBody">
          <div className="tableWrap resultsTableWrap">
            <table className="table resultsTable" style={{ minWidth: resultTableMinWidth }}>
              <thead>
                <tr>
                  {renderResizableResultHeader(
                    "entity",
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("entity")}>
                      Entity {sortIndicator("entity")}
                    </button>
                  )}
                  {renderResizableResultHeader("partyKey", "Party Key")}
                  {renderResizableResultHeader(
                    "mode",
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("mode")}>
                      Mode {sortIndicator("mode")}
                    </button>
                  )}
                  {renderResizableResultHeader(
                    "type",
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("type")}>
                      Type {sortIndicator("type")}
                    </button>
                  )}
                  {renderResizableResultHeader("screeningType", "Screening Type")}
                  {renderResizableResultHeader(
                    "country",
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("country")}>
                      Country {sortIndicator("country")}
                    </button>
                  )}
                  {renderResizableResultHeader(
                    "screeningResult",
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("status")}>
                      Screening Result {sortIndicator("status")}
                    </button>
                  )}
                  {renderResizableResultHeader(
                    "submittedAt",
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("submittedAt")}>
                      Submitted Date/Time {sortIndicator("submittedAt")}
                    </button>
                  )}
                  {renderResizableResultHeader("actions", "Actions", { align: "right" })}
                </tr>
              </thead>
              <tbody>
                {pageRows.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="emptyRow">
                      No results found.
                    </td>
                  </tr>
                ) : (
                  pageRows.map((r) => {
                    const rowActimizeReviewUrl = resolveActimizeReviewUrlFromRaw(r.raw) || actimizeReviewAlertUrl;
                    return (
                      <tr key={r.id}>
                        <td className="entityCell">
                          <div className="entityCellContent">
                            <span className="entityIcon" aria-hidden="true">
                              {uiTypeIcon(r.type)}
                            </span>
                            <span className="entityValue" title={r.entity}>{r.entity}</span>
                          </div>
                        </td>
                        <td className="muted partyKeyCell">
                          <span className="partyKeyValue" title={r.partyKey || ""}>{r.partyKey || "\u2014"}</span>
                        </td>
                        <td>{modeBadge(r)}</td>
                        <td className="muted">{r.type}</td>
                        <td className="muted">{r.screeningType || "\u2014"}</td>
                        <td className="muted">{r.country || "\u2014"}</td>
                        <td>{badge(r.uiStatus)}</td>
                        <td className="muted">{r.date}</td>
                        <td>
                          <div className="rowActions">
                            <div className="actionControls">
                              <button
                                type="button"
                                className="iconBtn"
                                title={r.uiStatus === "Pending" ? "Screening is in progress" : "View hit entity"}
                                aria-label={`View hit entity for ${r.entity}`}
                                onClick={() => openHitEntity(r)}
                              >
                                <ViewIcon />
                              </button>
                              <a
                                href={rowActimizeReviewUrl}
                                className="iconBtn"
                                target="_blank"
                                rel="noreferrer"
                                title={`Open Actimize review for ${r.entity}`}
                                aria-label={`Open Actimize review for ${r.entity}`}
                              >
                                <ExternalLinkIcon />
                              </a>
                            </div>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>

            {/* Pagination like screenshot */}
            <div className="pagerRow">
              <div className="muted">
                Showing {filtered.length === 0 ? 0 : startIdx + 1} to {Math.min(filtered.length, startIdx + pageSize)} of {filtered.length} results
              </div>

              <div className="pagerRight">
                <button
                  className="pagerBtn"
                  disabled={pageSafe <= 1}
                  onClick={() => updateScreeningWorkspace({ page: Math.max(1, pageSafe - 1) })}
                  type="button"
                >
                  {"\u2039"}
                </button>
                <div className="pagerText">Page {pageSafe} of {totalPages}</div>
                <button
                  className="pagerBtn"
                  disabled={pageSafe >= totalPages}
                  onClick={() => updateScreeningWorkspace({ page: Math.min(totalPages, pageSafe + 1) })}
                  type="button"
                >
                  {"\u203A"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {hitEntityDialog ? (
        <div className="hitEntityOverlay" onClick={() => setHitEntityDialog(null)}>
          <div className="hitEntityModal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="hit-entity-title">
            <div className="hitEntityHeader">
              <h3 id="hit-entity-title">Hit Entity Details</h3>
              <button ref={hitDialogCloseBtnRef} type="button" className="iconBtn" onClick={() => setHitEntityDialog(null)} aria-label="Close hit entity details">
                {"\u00D7"}
              </button>
            </div>
            <div className="hitEntityBody">
              <div className="hitEntityRow">
                <span className="muted">Source Entity</span>
                <strong>{hitEntityDialog.sourceEntity}</strong>
              </div>
              {hitEntityDialog.reviewUrl ? (
                <div className="hitEntityRow">
                  <span className="muted">Review Alert</span>
                  <a
                    href={hitEntityDialog.reviewUrl}
                    className="btnGhostSmall"
                    target="_blank"
                    rel="noreferrer"
                    title={`Review alert for ${hitEntityDialog.sourceEntity}`}
                    aria-label={`Review alert for ${hitEntityDialog.sourceEntity}`}
                  >
                    Open Actimize
                  </a>
                </div>
              ) : null}
              <div className="hitEntityRow">
                <span className="muted">Hit Entities</span>
                {hitEntityDialog.pending ? (
                  <div className="infoBox" role="status" aria-live="polite" style={{ marginTop: 0 }}>
                    Screening is still in progress. Please refresh to view hit entities after processing completes.
                  </div>
                ) : hitEntityDialog.error ? (
                  <div className="errorBox" role="alert" aria-live="polite" style={{ marginTop: 0 }}>
                    Screening failed{hitEntityDialog.error.status != null ? ` (HTTP ${hitEntityDialog.error.status})` : ""}:{" "}
                    {hitEntityDialog.error.text}
                  </div>
                ) : hitEntityDialog.hits.length === 0 ? (
                  <strong>No OFAC hit entity found.</strong>
                ) : (
                      <div className="hitEntityList">
                        {hitEntityDialog.hits.map((hit, idx) => (
                          <div className="hitEntityItem" key={`${hit.name}_${idx}`}>
                            <span className="hitEntityName">{hit.name}</span>
                            {hit.matchingScore != null ? (
                              <span className="muted">{formatMatchingScore(hit.matchingScore)}</span>
                            ) : null}
                            {hit.keywordOrCategory ? <span className="muted">{hit.keywordOrCategory}</span> : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TemplateCard(props: {
  title: string;
  desc: string;
  chips: readonly string[];
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <div className="templateCard">
      <div className="templateTop">
        <div>
          <div className="templateTitle">{props.title}</div>
          <div className="templateDesc">{props.desc}</div>
        </div>

        <button type="button" className="templateCsvBtn" onClick={props.onAction}>
          {props.actionLabel}
        </button>
      </div>

      <div className="chipRow">
        {props.chips.map((c, i) => (
          <span className="chip" key={i}>
            {c}
          </span>
        ))}
      </div>
    </div>
  );
}

type SummaryTone = "total" | "clear" | "potential" | "match" | "pending" | "failed";

function SummaryCardIcon({ tone }: { tone: SummaryTone }) {
  if (tone === "total") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <line x1="4" y1="20" x2="20" y2="20" />
        <line x1="7" y1="17" x2="7" y2="10" />
        <line x1="12" y1="17" x2="12" y2="6" />
        <line x1="17" y1="17" x2="17" y2="13" />
      </svg>
    );
  }
  if (tone === "clear") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="m9 12 2 2 4-4" />
      </svg>
    );
  }
  if (tone === "potential") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3 2 20h20L12 3z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <circle cx="12" cy="17" r="1" />
      </svg>
    );
  }
  if (tone === "match") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3l7 3v6c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6l7-3z" />
      </svg>
    );
  }
  if (tone === "failed") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <line x1="9" y1="9" x2="15" y2="15" />
        <line x1="15" y1="9" x2="9" y2="15" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <line x1="12" y1="7" x2="12" y2="12" />
      <line x1="12" y1="12" x2="15" y2="14" />
    </svg>
  );
}

function SummaryCards({ counts }: { counts: { total: number; clear: number; potential: number; pending: number; failed: number; match: number } }) {
  const items: { tone: SummaryTone; label: string; value: number }[] = [
    { tone: "total", label: "TOTAL SCREENINGS", value: counts.total },
    { tone: "clear", label: "CLEAR", value: counts.clear },
    { tone: "potential", label: "POTENTIAL MATCHES", value: counts.potential },
    { tone: "match", label: "MATCHES", value: counts.match },
    { tone: "pending", label: "PENDING", value: counts.pending },
    { tone: "failed", label: "FAILED", value: counts.failed },
  ];

  return (
    <div className="summaryGrid">
      {items.map((item) => (
        <div key={item.tone} className={`summaryCard summaryCard--${item.tone}`}>
          <div className="summaryTop">
            <div className="summaryLabel">{item.label}</div>
            <div className="summaryIconBubble" aria-hidden="true">
              <SummaryCardIcon tone={item.tone} />
            </div>
          </div>
          <div className="summaryValue">{item.value}</div>
        </div>
      ))}
    </div>
  );
}





