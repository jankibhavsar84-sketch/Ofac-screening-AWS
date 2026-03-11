import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRecoilState } from "recoil";
import { useAuth } from "react-oidc-context";
import { z } from "zod";
import { submissionsState, latestResultState, type Submission, type BatchSubmission, type SingleSubmission } from "../state/submissions";
import {
  listDailySchedules,
  listMyBusinessUnits,
  listScreeningSubmissions,
  matchSync,
  uploadBatchAndSubmitJob,
  waitForScreeningJob,
  type BusinessUnit,
  type EntityExample,
  type EntityMatches,
} from "../api/screeningApi";
import { buildIdentity, getPrimaryRole, hasPermission } from "../auth/claims";
import { parseCsv, parseExcel } from "../utils/batchParse";
import { CountryAutosuggest } from "../components/CountryAutoSuggest";
import { IsoDateInput } from "../components/IsoDateInput";

type Mode = "SINGLE" | "BATCH" | "SCHEDULE";
type UiType = "Individual" | "Organization" | "Unknown" | "Vessel" | "Aircraft";
type ScreeningType = "Sanction" | "PEP" | "AME" | "Fincen 314(a)" | "Global Sanction";
type ScheduleFrequency = "DAILY" | "WEEKLY" | "MONTHLY";

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
type ResultSortDirection = "asc" | "desc";
type SelectOption<T extends string> = { value: T; label: string; icon?: React.ReactNode };

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

function parseSubscriptionEmails(value: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  value
    .split(/[\n,;]+/g)
    .map((v) => safeTrim(v).toLowerCase())
    .forEach((email) => {
      if (!email || !email.includes("@") || seen.has(email)) return;
      seen.add(email);
      out.push(email);
    });
  return out;
}

function toFriendlyBusinessUnitError(error: unknown): string {
  const text = safeTrim(String((error as any)?.message ?? ""));
  if (!text) return "Failed to load Business Units.";
  if (text.includes("502") || text.includes("503") || text.includes("504")) {
    return "Business Unit service is temporarily unavailable. Please retry in a moment.";
  }
  return text;
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

const SCREENING_TYPE_OPTIONS: { value: ScreeningType; desc: string }[] = [
  { value: "Sanction", desc: "Primary sanctions lists and watchlist controls" },
  { value: "PEP", desc: "Politically Exposed Person checks" },
  { value: "AME", desc: "Adverse media and negative news" },
  { value: "Fincen 314(a)", desc: "US FinCEN 314(a) request screening" },
  { value: "Global Sanction", desc: "Aggregated global sanctions coverage" },
];

const SCHEDULE_FREQUENCY_OPTIONS: { value: ScheduleFrequency; label: string; hint: string }[] = [
  { value: "DAILY", label: "Daily", hint: "Runs every day at configured schedule time." },
  { value: "WEEKLY", label: "Weekly", hint: "Runs once every 7 days at configured schedule time." },
  { value: "MONTHLY", label: "Monthly", hint: "Runs once each month at configured schedule time." },
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

// map country -> ISO2 if user types full name
function toCountryCode(input: string) {
  const v = safeTrim(input).toLowerCase();
  if (!v) return "";
  if (v.length === 2) return v;
  const map: Record<string, string> = {
    "united states": "us",
    usa: "us",
    america: "us",
    india: "in",
    "united kingdom": "gb",
    uk: "gb",
    canada: "ca",
  };
  return map[v] ?? v;
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

  // Name
  const nameValues: string[] = [];
  if (item.uiType === "Individual") {
    const splitName = [safeTrim(item.firstName), safeTrim(item.middleName), safeTrim(item.lastName)].filter(Boolean).join(" ");
    const fullName = safeTrim(item.fullName);
    if (splitName) nameValues.push(splitName);
    if (fullName && fullName.toLowerCase() !== splitName.toLowerCase()) nameValues.push(fullName);
  } else {
    const fullName = safeTrim(item.fullName);
    if (fullName) nameValues.push(fullName);
  }

  const props: Record<string, any> = { name: nameValues };

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

function parseCommaValues(input: unknown): string[] {
  const value = safeTrim(String(input ?? ""));
  if (!value) return [];
  return value
    .split(",")
    .map((token) => safeTrim(token))
    .filter(Boolean);
}

function buildStructuredName(first: string, middle: string, last: string, maiden: string, fullName: string): string {
  const split = [safeTrim(first), safeTrim(middle), safeTrim(last), safeTrim(maiden)].filter(Boolean).join(" ");
  return safeTrim(fullName) || split;
}

function buildAddressLine(
  line1: unknown,
  line2: unknown,
  city: unknown,
  stateProvince: unknown,
  zipCode: unknown,
  country: unknown
): string {
  return [line1, line2, city, stateProvince, zipCode, country]
    .map((v) => safeTrim(String(v ?? "")))
    .filter(Boolean)
    .join(", ");
}

function parseBatchRows(rows: any[]): {
  queries: Record<string, EntityExample>;
  rowMeta: { key: string; displayName: string; uiType: UiType }[]; 
  validationErrors: string[];
} {
  const queries: Record<string, EntityExample> = {};
  const rowMeta: { key: string; displayName: string; uiType: UiType }[] = [];
  const validationErrors: string[] = [];
  const seenPartyKeys = new Set<string>();

  rows.forEach((r, idx) => {
    const rowNumber = idx + 2; // 1-based + header row
    const partyKey = safeTrim(String(r.partyKey || ""));
    const normalizedPartyKey = partyKey.toUpperCase();
    const missingPartyKey = !partyKey;
    const duplicatePartyKey = Boolean(partyKey && seenPartyKeys.has(normalizedPartyKey));

    if (missingPartyKey) {
      validationErrors.push(`Row ${rowNumber}: PartyKey is required.`);
    } else if (duplicatePartyKey) {
      validationErrors.push(`Row ${rowNumber}: Duplicate PartyKey '${partyKey}'. PartyKey must be unique within the file.`);
    } else {
      seenPartyKeys.add(normalizedPartyKey);
    }

    const rawPartyType = safeTrim(String(r.partyType || ""));
    const normalizedPartyType = rawPartyType.toUpperCase();
    const hasLegacyCustomerType = Boolean(safeTrim(String(r.customerTypeRaw || "")));
    const customerType = r.customerType === "Entity" ? "Entity" : "Person";

    let uiType: UiType;
    if (normalizedPartyType === "I") uiType = "Individual";
    else if (normalizedPartyType === "E") uiType = "Organization";
    else if (rawPartyType) uiType = "Unknown";
    else if (hasLegacyCustomerType) uiType = customerType === "Entity" ? "Organization" : "Individual";
    else if (safeTrim(String(r.firstName || "")) || safeTrim(String(r.lastName || ""))) uiType = "Individual";
    else if (safeTrim(String(r.fullName || ""))) uiType = "Organization";
    else uiType = "Unknown";

    const rawGender = safeTrim(String(r.gender || ""));
    const normalizedGender = rawGender.toUpperCase();
    if (rawGender && normalizedGender !== "M" && normalizedGender !== "F") {
      validationErrors.push(`Row ${rowNumber}: Gender code must be M, F, or blank.`);
    }

    const firstName = safeTrim(r.primaryFirstName || r.firstName || "");
    const middleName = safeTrim(r.primaryMiddleName || r.middleName || "");
    const lastName = safeTrim(r.primaryLastName || r.lastName || "");
    const maidenName = safeTrim(r.primaryMaidenName || "");
    const splitName = [firstName, middleName, lastName].filter(Boolean).join(" ");
    const explicitFullName = buildStructuredName(firstName, middleName, lastName, maidenName, safeTrim(r.primaryFullName || r.fullName || ""));
    const hasSplitFirstLast = Boolean(firstName && lastName);
    const hasFullName = Boolean(explicitFullName);
    const fullName = explicitFullName || (uiType === "Individual" ? splitName : "");

    const display =
      uiType === "Individual" ? fullName || [firstName, lastName].filter(Boolean).join(" ") : fullName || lastName;

    const key = partyKey || `row_${idx + 1}`;
    rowMeta.push({ key, displayName: display || `(Row ${idx + 1})`, uiType });
    if (missingPartyKey || duplicatePartyKey) return;

    if (uiType === "Individual" && !hasFullName && !hasSplitFirstLast) {
      validationErrors.push(`Row ${rowNumber}: For Individual, provide either Full Name or both First Name and Last Name.`);
      return;
    }
    if (uiType !== "Individual" && !fullName) {
      validationErrors.push(`Row ${rowNumber}: For Organization or Unknown, Full Name is required.`);
      return;
    }

    const addresses = parseCommaValues(r.addresses || "");
    const addressCandidates = [
      buildAddressLine(r.address1Line1, r.address1Line2, r.address1City, r.address1stateProvince, r.address1ZipCode, r.address1Country),
      buildAddressLine(r.address2Line1, r.address2Line2, r.address2City, r.address2stateProvince, r.address2ZipCode, r.address2Country),
      buildAddressLine(r.address3Line1, r.address3Line2, r.address3City, r.address3stateProvince, r.address3ZipCode, r.address3Country),
      buildAddressLine(r.addressLine1, r.addressLine2, r.city, r.state, r.zip, r.country),
    ]
      .map((value) => safeTrim(value))
      .filter(Boolean);
    addressCandidates.forEach((value) => {
      if (!addresses.includes(value)) addresses.push(value);
    });
    if (!addresses.length) {
      const oneLineAddress = [safeTrim(r.addressLine1 || ""), safeTrim(r.addressLine2 || ""), safeTrim(r.city || ""), safeTrim(r.state || ""), safeTrim(r.zip || "")]
        .filter(Boolean)
        .join(", ");
      if (oneLineAddress) addresses.push(oneLineAddress);
    }

    const countries = Array.from(
      new Set(
        [
          ...parseCommaValues(r.countries || ""),
          safeTrim(r.country || ""),
          safeTrim(r.countryOfCitizenship || ""),
          safeTrim(r.address1Country || ""),
          safeTrim(r.address2Country || ""),
          safeTrim(r.address3Country || ""),
          safeTrim(r.birthCountry || ""),
          safeTrim(r.nationalityCountry1 || ""),
          safeTrim(r.nationalityCountry2 || ""),
          safeTrim(r.nationalityCountry3 || ""),
        ]
          .map((value) => safeTrim(value))
          .filter(Boolean)
      )
    );

    const alias1 = buildStructuredName(
      safeTrim(r.alias1FirstName || ""),
      safeTrim(r.alias1MiddleName || ""),
      safeTrim(r.alias1LastName || ""),
      safeTrim(r.alias1MaidenName || ""),
      safeTrim(r.alias1FullName || "")
    );
    const alias2 = buildStructuredName(
      safeTrim(r.alias2FirstName || ""),
      safeTrim(r.alias2MiddleName || ""),
      safeTrim(r.alias2LastName || ""),
      safeTrim(r.alias2MaidenName || ""),
      safeTrim(r.alias2FullName || "")
    );
    const alias3 = buildStructuredName(
      safeTrim(r.alias3FirstName || ""),
      safeTrim(r.alias3MiddleName || ""),
      safeTrim(r.alias3LastName || ""),
      safeTrim(r.alias3MaidenName || ""),
      safeTrim(r.alias3FullName || "")
    );
    const mergedAlias = [safeTrim(r.aliasName || ""), alias1, alias2, alias3].filter(Boolean).join(", ");

    const ids = [
      { idType: safeTrim(r.partyId1Type || r.idType || r.idCode || ""), idNumber: safeTrim(r.partyId1Value || r.idNumber || ""), idCountry: safeTrim(r.partyId1IDCountry || r.idCountry || r.idIssueCountry || "") },
      { idType: safeTrim(r.partyId2Type || ""), idNumber: safeTrim(r.partyId2Value || ""), idCountry: safeTrim(r.partyId2IDCountry || "") },
      { idType: safeTrim(r.partyId3Type || ""), idNumber: safeTrim(r.partyId3Value || ""), idCountry: safeTrim(r.partyId3IDCountry || "") },
    ].filter((doc) => Boolean(doc.idNumber));

    const item: NameItem = {
      id: key,
      uiType,
      nameMode: uiType === "Individual" ? "split" : "full",
      firstName,
      lastName,
      middleName,
      fullName,
      aliasName: mergedAlias,
      dateOfBirth: safeTrim(r.dateOfBirth || r.yearOfBirth || ""),
      countries,
      addresses,
      ids,
      birthLocation: safeTrim(r.birthLocation || r.birthCountry || ""),
      gender: rawGender,
      title: safeTrim(r.title || ""),
    };

    queries[partyKey] = buildEntityExampleFromNameItem(item);
  });

  return { queries, rowMeta, validationErrors };
}

type EngineStatus = "NO_HIT" | "HIT" | "PROCESSING" | "FAILED" | "ERROR";
type UiStatus = "Clear" | "Potential Match" | "Pending" | "Failed" | "Match";
type ResultMode = "SINGLE" | "BATCH";

function engineToUiStatus(s: EngineStatus, manualMatch?: boolean): UiStatus {
  if (manualMatch) return "Match";
  if (s === "NO_HIT") return "Clear";
  if (s === "HIT") return "Potential Match";
  if (s === "PROCESSING") return "Pending";
  return "Failed";
}

function classifyEngine(results: { match: boolean }[]): EngineStatus {
  return results?.some((r) => r.match) ? "HIT" : "NO_HIT";
}

function badge(status: UiStatus) {
  if (status === "Clear") return <span className="statusPill statusClear">Clear</span>;
  if (status === "Potential Match") return <span className="statusPill statusPotential">Potential Match</span>;
  if (status === "Pending") return <span className="statusPill statusPending">Pending</span>;
  if (status === "Failed") return <span className="statusPill statusFailed">Failed</span>;
  return <span className="statusPill statusMatch">Match</span>;
}

function modeBadge(mode: ResultMode) {
  if (mode === "SINGLE") return <span className="modePill modePillSingle">Single</span>;
  return <span className="modePill modePillBatch">Batch</span>;
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

function toCountryDisplay(values: string[]): string {
  const normalized = values
    .map((v) => {
      const t = safeTrim(v);
      if (!t) return "";
      return t.length === 2 ? t.toUpperCase() : t;
    })
    .filter(Boolean);
  return Array.from(new Set(normalized)).join(", ");
}

function extractCountryFromQuery(query: any): string {
  const props = query?.properties;
  if (!props || typeof props !== "object") return "";

  const candidates: string[][] = [
    asStringList((props as any).country),
    asStringList((props as any).nationality),
    asStringList((props as any).countries),
    asStringList((props as any).jurisdiction),
  ];

  for (const list of candidates) {
    const rendered = toCountryDisplay(list);
    if (rendered) return rendered;
  }
  return "";
}

function extractCountryFromRaw(raw: any): string {
  const fromQuery =
    extractCountryFromQuery(raw?.matches?.query) ||
    extractCountryFromQuery(raw?.item?.details?.matches?.query) ||
    extractCountryFromQuery(raw?.details?.query) ||
    extractCountryFromQuery(raw?.item?.details?.query);

  if (fromQuery) return fromQuery;

  const fallback = raw?.country ?? raw?.item?.country ?? raw?.submission?.country;
  if (typeof fallback === "string") return safeTrim(fallback);
  return "";
}

function extractPartyKeyFromQuery(query: any): string {
  const props = query?.properties;
  if (!props || typeof props !== "object") return "";

  const values = [
    ...asStringList((props as any).partyKey),
    ...asStringList((props as any).party_key),
    ...asStringList((props as any)["party key"]),
    ...asStringList((props as any).PartyKey),
  ].map((value) => safeTrim(value));
  return values.find(Boolean) || "";
}

function extractPartyKeyFromRaw(raw: any): string {
  const fromQuery =
    extractPartyKeyFromQuery(raw?.matches?.query) ||
    extractPartyKeyFromQuery(raw?.item?.details?.matches?.query) ||
    extractPartyKeyFromQuery(raw?.details?.query) ||
    extractPartyKeyFromQuery(raw?.item?.details?.query);

  if (fromQuery) return fromQuery;

  const results = getResultCandidatesFromRaw(raw);
  for (const result of results) {
    const props = result?.properties;
    if (props && typeof props === "object") {
      const fromProps = [
        ...asStringList((props as any).partyKey),
        ...asStringList((props as any).party_key),
        ...asStringList((props as any)["party key"]),
      ]
        .map((value) => safeTrim(value))
        .find(Boolean);
      if (fromProps) return fromProps;
    }

    const fromId = safeTrim(String(result?.id ?? ""));
    if (fromId) return fromId;
  }

  return "";
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

function topMatchingScore(results: any[] | undefined): number | null {
  if (!Array.isArray(results) || results.length === 0) return null;
  const best = results
    .filter((r) => r && typeof r === "object" && typeof r.score === "number")
    .map((r) => Number(r.score))
    .sort((a, b) => b - a)[0];
  return typeof best === "number" && Number.isFinite(best) ? best : null;
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
}: {
  selected: ScreeningType[];
  onToggle: (type: ScreeningType) => void;
}) {
  return (
    <div className="screeningTypeWrap">
      <div className="sectionRow" style={{ marginBottom: 8 }}>
        <div className="sectionTitle">Screening Types <span className="requiredMark">*</span></div>
      </div>
      <div className="screeningTypeGrid">
        {SCREENING_TYPE_OPTIONS.map((option) => {
          const active = selected.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              className={active ? "screeningTypeCard active" : "screeningTypeCard"}
              onClick={() => onToggle(option.value)}
              aria-pressed={active}
            >
              <div className="screeningTypeHead">
                <span className="screeningTypeName">{option.value}</span>
                <span className={active ? "screeningTypeTick active" : "screeningTypeTick"} aria-hidden="true">
                  {active ? "\u2713" : "+"}
                </span>
              </div>
              <div className="screeningTypeDesc">{option.desc}</div>
            </button>
          );
        })}
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
  const [mode, setMode] = useState<Mode>("SINGLE");

  const [submissions, setSubmissions] = useRecoilState(submissionsState);
  const [, setLatest] = useRecoilState(latestResultState);
  const [resultsRefreshing, setResultsRefreshing] = useState(false);
  const [resultsRefreshError, setResultsRefreshError] = useState<string | null>(null);
  const [resultsLastRefreshedAt, setResultsLastRefreshedAt] = useState<Date | null>(null);
  const submissionsRefreshInFlightRef = useRef(false);
  const businessUnitsRequestSeqRef = useRef(0);
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
  const [singleScreeningTypes, setSingleScreeningTypes] = useState<ScreeningType[]>(["Sanction"]);
  const [singleMockScreening, setSingleMockScreening] = useState(true);
  const [singleBusinessUnitCode, setSingleBusinessUnitCode] = useState("");

  // BATCH
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [batchName, setBatchName] = useState("");
  const [batchScreeningTypes, setBatchScreeningTypes] = useState<ScreeningType[]>(["Sanction"]);
  const [batchBusinessUnitCode, setBatchBusinessUnitCode] = useState("");
  const [batchFile, setBatchFile] = useState<File | null>(null);
  const [batchFileName, setBatchFileName] = useState("");
  const [batchError, setBatchError] = useState<string | null>(null);

  // SCHEDULE
  const [scheduleTemplatesOpen, setScheduleTemplatesOpen] = useState(false);
  const [scheduleName, setScheduleName] = useState("");
  const [scheduleScreeningTypes, setScheduleScreeningTypes] = useState<ScreeningType[]>(["Sanction"]);
  const [scheduleBusinessUnitCode, setScheduleBusinessUnitCode] = useState("");
  const [scheduleFrequency, setScheduleFrequency] = useState<ScheduleFrequency>("DAILY");
  const [scheduleRunAt, setScheduleRunAt] = useState(defaultScheduleRunAtValue);
  const [scheduleSubscriptionEmails, setScheduleSubscriptionEmails] = useState("");
  const [scheduleFile, setScheduleFile] = useState<File | null>(null);
  const [scheduleFileName, setScheduleFileName] = useState("");
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  const [singleError, setSingleError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [businessUnits, setBusinessUnits] = useState<BusinessUnit[]>([]);
  const [businessUnitsError, setBusinessUnitsError] = useState<string | null>(null);
  const [businessUnitsLoading, setBusinessUnitsLoading] = useState(false);
  const selectedEntityType: UiType = names[0]?.uiType ?? "Individual";
  const primaryName = names[0];
  const aliasNames = names.slice(1);

  // Results filters + paging
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("All Statuses");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("All Types");
  const [resultSortKey, setResultSortKey] = useState<ResultSortKey>("submittedAt");
  const [resultSortDirection, setResultSortDirection] = useState<ResultSortDirection>("desc");
  const [page, setPage] = useState(1);

  // dropzone
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const scheduleRunAtInputRef = useRef<HTMLInputElement | null>(null);
  const hitDialogCloseBtnRef = useRef<HTMLButtonElement | null>(null);
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
      setMode("SINGLE");
    }
  }, [canBatchScreen, mode]);

  useEffect(() => {
    if (!canDailyScreening && mode === "SCHEDULE") {
      setMode("SINGLE");
    }
  }, [canDailyScreening, mode]);

  const businessUnitOptions = useMemo(
    () =>
      [...businessUnits]
        .map((row) => ({
          code: safeTrim(String(row.business_unit_code || "")).toUpperCase(),
          name: safeTrim(String(row.business_unit_name || "")),
        }))
        .filter((row) => row.code && row.name)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [businessUnits]
  );

  const reloadBusinessUnits = useCallback(async () => {
    if (!currentUser?.id) return;
    const requestSeq = businessUnitsRequestSeqRef.current + 1;
    businessUnitsRequestSeqRef.current = requestSeq;
    setBusinessUnitsLoading(true);
    setBusinessUnitsError(null);
    try {
      const rows = await listMyBusinessUnits();
      if (requestSeq !== businessUnitsRequestSeqRef.current) return;
      setBusinessUnits(Array.isArray(rows) ? rows : []);
    } catch (error: unknown) {
      if (requestSeq !== businessUnitsRequestSeqRef.current) return;
      setBusinessUnitsError(toFriendlyBusinessUnitError(error));
    } finally {
      if (requestSeq === businessUnitsRequestSeqRef.current) {
        setBusinessUnitsLoading(false);
      }
    }
  }, [currentUser?.id]);

  useEffect(() => {
    void reloadBusinessUnits();
  }, [reloadBusinessUnits]);

  useEffect(() => {
    const validCodes = new Set(businessUnitOptions.map((row) => row.code));
    const firstCode = businessUnitOptions[0]?.code ?? "";

    if (!validCodes.has(singleBusinessUnitCode)) setSingleBusinessUnitCode(firstCode);
    if (!validCodes.has(batchBusinessUnitCode)) setBatchBusinessUnitCode(firstCode);
    if (!validCodes.has(scheduleBusinessUnitCode)) setScheduleBusinessUnitCode(firstCode);
  }, [businessUnitOptions, singleBusinessUnitCode, batchBusinessUnitCode, scheduleBusinessUnitCode]);

  const loadSubmissionHistory = useCallback(
    async ({ silent, updateTimestamp, resetPage }: { silent: boolean; updateTimestamp: boolean; resetPage: boolean }) => {
      if (!currentUser?.id) return;
      if (submissionsRefreshInFlightRef.current) return;

      submissionsRefreshInFlightRef.current = true;
      if (!silent) {
        setResultsRefreshing(true);
        setResultsRefreshError(null);
      }
      try {
        const historyRows = await listScreeningSubmissions(500);
        const reconciled = await reconcileDailyScheduleFlags(historyRows as Submission[]);
        setSubmissions(reconciled);
        if (updateTimestamp) {
          setResultsLastRefreshedAt(new Date());
        }
        if (resetPage) {
          setPage(1);
        }
      } catch (err: any) {
        if (!silent) {
          setResultsRefreshError(err?.message ?? "Failed to refresh screening results.");
        }
      } finally {
        submissionsRefreshInFlightRef.current = false;
        if (!silent) {
          setResultsRefreshing(false);
        }
      }
    },
    [currentUser?.id, setSubmissions]
  );

  useEffect(() => {
    if (!currentUser?.id) return;
    void loadSubmissionHistory({ silent: true, updateTimestamp: false, resetPage: false });
  }, [currentUser?.id, loadSubmissionHistory]);

  function toggleScreeningType(
    value: ScreeningType,
    setSelected: React.Dispatch<React.SetStateAction<ScreeningType[]>>
  ) {
    setSelected((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]));
  }

  async function reconcileDailyScheduleFlags(items: Submission[]): Promise<Submission[]> {
    try {
      const schedules = await listDailySchedules();
      const activeScheduleIds = new Set(
        schedules
          .map((s) => safeTrim(String(s.schedule_id || "")))
          .filter(Boolean)
      );

      return items.map((s) => {
        if (s.mode !== "BATCH") return s;
        const scheduleId = safeTrim(String((s as any).dailyScheduleId || ""));
        if (!scheduleId) return s;

        const isActive = activeScheduleIds.has(scheduleId);
        const currentlyActive = Boolean((s as any).dailyScheduleActive === true);
        if (isActive === currentlyActive) return s;
        return {
          ...s,
          dailyScheduleActive: isActive,
          dailyScreening: isActive ? Boolean((s as any).dailyScreening ?? true) : false,
        } as BatchSubmission;
      });
    } catch {
      return items;
    }
  }

  function refreshResults() {
    void loadSubmissionHistory({ silent: false, updateTimestamp: true, resetPage: true });
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
    setLatest(null);

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
      setSingleScreeningTypes(["Sanction"]);
      setSingleMockScreening(true);
    } else if (mode === "BATCH") {
      setBatchName("");
      setBatchScreeningTypes(["Sanction"]);
      setBatchFile(null);
      setBatchFileName("");
      setTemplatesOpen(false);
    } else {
      setScheduleName("");
      setScheduleScreeningTypes(["Sanction"]);
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
    setSubmitting(true);

    try {
      if (!canSingleScreen) {
        setSingleError("You do not have permission to run single screening.");
        setSubmitting(false);
        return;
      }
      if (!currentUser) {
        setSingleError("Authenticated user context is missing. Please sign in again.");
        setSubmitting(false);
        return;
      }
      if (viewerMockOnly && !singleMockScreening) {
        setSingleError("Viewer role can run only mock single screening.");
        setSubmitting(false);
        return;
      }
      if (!singleScreeningTypes.length) {
        setSingleError("Select at least one screening type.");
        setSubmitting(false);
        return;
      }
      if (!safeTrim(singleBusinessUnitCode)) {
        setSingleError("Business Unit is required.");
        setSubmitting(false);
        return;
      }

      const parsed = singleSchema.safeParse(names);
      if (!parsed.success) {
        setSingleError(parsed.error.issues[0]?.message ?? "Fix validation errors.");
        setSubmitting(false);
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

        if (mergedNames.length) {
          props.name = mergedNames;
          query.properties = props;
        }
      }

      meta.push({ key, uiType: primaryName.uiType, displayName: displayName || "(Item 1)" });
      queries[key] = query;

      const resp = await matchSync(queries, singleScreeningTypes, singleMockScreening, {
        id: currentUser.id,
        name: currentUser.name,
      }, singleBusinessUnitCode);

      // Convert to a single "SINGLE" submission containing multiple items (still SINGLE mode for your history)
      // We store as SingleSubmission but keep details so results table can read it
      const entry: SingleSubmission = {
        id: uuid(),
        createdAt: new Date().toISOString(),
        mode: "SINGLE",
        createdByUserId: currentUser.id,
        createdByUserName: currentUser.name,
        businessUnitCode: singleBusinessUnitCode,
        customerType: "Person", // not used by new results table; keep for backward compatibility
        displayName: `Single Screening (${meta.length})`,
        result: "NO_HIT",
        screeningTypes: singleScreeningTypes,
        message: notes ? `Notes: ${notes}` : undefined,
        details: {
          meta,
          responses: resp.responses,
          notes,
          screeningTypes: singleScreeningTypes,
          mockScreening: singleMockScreening,
          businessUnitCode: singleBusinessUnitCode,
        },
      };

      // derive top result for the main record (if any potential match -> HIT)
      let anyHit = false;
      let anyError = false;

      meta.forEach((m) => {
        const matches = resp.responses[m.key];
        if (!matches) {
          anyError = true;
          return;
        }
        const engine = classifyEngine(matches.results ?? []);
        if (engine === "HIT") anyHit = true;
      });

      entry.result = anyHit ? "HIT" : anyError ? "ERROR" : "NO_HIT";

      const next = [entry, ...submissions].slice(0, 500);
      setSubmissions(next);
      setLatest(entry);
      setPage(1);
    } catch (err: any) {
      setSingleError(err?.message ?? "Failed to screen.");
    } finally {
      setSubmitting(false);
    }
  }

  // ---------- Batch submit ----------
  async function submitBatch(e: React.FormEvent) {
    e.preventDefault();
    setBatchError(null);

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
      setBatchError("Please drop or select a CSV/XLSX file.");
      return;
    }

    setSubmitting(true);
    try {
      const name = batchFile.name.toLowerCase();
      let rows: any[] = [];

      if (name.endsWith(".csv")) rows = await parseCsv(batchFile);
      else if (name.endsWith(".xlsx") || name.endsWith(".xls")) rows = await parseExcel(batchFile);
      else throw new Error("Only CSV or Excel files are allowed.");

      if (!rows.length) throw new Error("No rows found in the file.");

      const { queries, rowMeta, validationErrors } = parseBatchRows(rows);
      if (validationErrors.length) {
        const preview = validationErrors.slice(0, 4).join(" ");
        const remaining = validationErrors.length > 4 ? ` (+${validationErrors.length - 4} more)` : "";
        throw new Error(`Upload validation failed. ${preview}${remaining}`);
      }

      if (!Object.keys(queries).length) throw new Error("All rows are invalid (missing required names).");

      const accepted = await uploadBatchAndSubmitJob({
        file: batchFile,
        queries,
        screeningTypes: batchScreeningTypes,
        batchName,
        businessUnitCode: batchBusinessUnitCode,
        dailyScreening: false,
        mockScreening: false,
        subscribeResults: false,
        userName: currentUser.name,
      });

      const screenedKeySet = new Set(
        (accepted.screened_item_keys ?? [])
          .map((key) => safeTrim(String(key)))
          .filter(Boolean)
      );
      const hasScreenedSubset = screenedKeySet.size > 0;

      const placeholderItems: BatchSubmission["items"] = rowMeta.map((m) => {
        const isScheduledSkip = hasScreenedSubset && !screenedKeySet.has(m.key);
        const fallbackMatches: EntityMatches = {
          results: [],
          total: { value: 0, relation: "eq" },
          query: queries[m.key],
          status: isScheduledSkip ? 204 : 202,
        };
        return {
          customerType: m.uiType === "Individual" ? "Person" : "Entity",
          displayName: m.displayName,
          result: isScheduledSkip ? "NO_HIT" : "PROCESSING",
          message: isScheduledSkip ? "Skipped (already screened in previous schedule runs)." : "Screening in progress",
          details: { uiType: m.uiType, matches: fallbackMatches },
        };
      });

      const entry: BatchSubmission = {
        id: uuid(),
        createdAt: new Date().toISOString(),
        mode: "BATCH",
        createdByUserId: currentUser.id,
        createdByUserName: currentUser.name,
        businessUnitCode: batchBusinessUnitCode,
        jobId: accepted.job_id,
        fileName: batchFile.name,
        overallResult: accepted.total_items === 0 ? "NO_HIT" : "PROCESSING",
        screeningTypes: batchScreeningTypes,
        dailyScreening: false,
        dailyScheduleId: accepted.daily_schedule_id ?? undefined,
        dailyScheduleActive: false,
        sourceUploadId: accepted.source_upload_id,
        sourceS3Uri: accepted.s3_uri ?? undefined,
        items: placeholderItems,
      };

      setSubmissions((prev) => [entry, ...prev].slice(0, 500));
      setLatest(entry);
      setPage(1);

      if (accepted.total_items > 0) {
        // Non-blocking async completion: keep UI responsive and update results when worker finishes.
        void (async () => {
          try {
            const progress = await waitForScreeningJob(accepted.job_id, { timeoutMs: 1000 * 60 * 60 });
            const responses = progress.responses ?? {};

            const resolvedItems: BatchSubmission["items"] = rowMeta.map((m) => {
              const isScheduledSkip = hasScreenedSubset && !screenedKeySet.has(m.key);
              if (isScheduledSkip) {
                const fallbackMatches: EntityMatches = {
                  results: [],
                  total: { value: 0, relation: "eq" },
                  query: queries[m.key],
                  status: 204,
                };
                return {
                  customerType: m.uiType === "Individual" ? "Person" : "Entity",
                  displayName: m.displayName,
                  result: "NO_HIT",
                  message: "Skipped (already screened in previous schedule runs).",
                  details: { uiType: m.uiType, matches: fallbackMatches },
                };
              }

              const matches = responses[m.key];
              if (!matches) {
                const fallbackMatches: EntityMatches = {
                  results: [],
                  total: { value: 0, relation: "eq" },
                  query: queries[m.key],
                  status: 500,
                };
                return {
                  customerType: m.uiType === "Individual" ? "Person" : "Entity",
                  displayName: m.displayName,
                  result: "ERROR",
                  message: "Screening failed for this row",
                  details: { uiType: m.uiType, matches: fallbackMatches },
                };
              }

              const engine = classifyEngine(matches.results ?? []);
              return {
                customerType: m.uiType === "Individual" ? "Person" : "Entity",
                displayName: m.displayName,
                result: engine === "HIT" ? "HIT" : engine === "NO_HIT" ? "NO_HIT" : "ERROR",
                message: matches?.results?.[0]?.caption ? `Top match: ${matches.results[0].caption}` : undefined,
                details: { uiType: m.uiType, matches },
              };
            });

            const overall =
              progress.status === "FAILED"
                ? "ERROR"
                : resolvedItems.some((i) => i.result === "HIT")
                  ? "HIT"
                  : resolvedItems.some((i) => i.result === "ERROR")
                    ? "ERROR"
                    : "NO_HIT";

            setSubmissions((prev) =>
              prev.map((s) =>
                s.mode === "BATCH" &&
                (s.id === entry.id || s.id === accepted.job_id || safeTrim(String((s as any).jobId || "")) === accepted.job_id)
                  ? ({ ...s, overallResult: overall, items: resolvedItems } as BatchSubmission)
                  : s
              )
            );
          } catch (err: any) {
            const failureText = safeTrim(String(err?.message ?? "Batch screening failed."));
            setSubmissions((prev) =>
              prev.map((s) => {
                if (
                  s.mode !== "BATCH" ||
                  (s.id !== entry.id && s.id !== accepted.job_id && safeTrim(String((s as any).jobId || "")) !== accepted.job_id)
                ) {
                  return s;
                }
                const failedItems = s.items.map((it) =>
                  it.result === "PROCESSING"
                    ? { ...it, result: "ERROR", message: failureText || "Batch screening failed." }
                    : it
                );
                return { ...s, overallResult: "ERROR", items: failedItems } as BatchSubmission;
              })
            );
          }
        })();
      }

      // reset batch inputs after success
      setBatchFile(null);
      setBatchFileName("");
      setBatchName("");
      setBatchScreeningTypes(["Sanction"]);
      setTemplatesOpen(false);
    } catch (err: any) {
      setBatchError(err?.message ?? "Batch screening failed.");
    } finally {
      setSubmitting(false);
    }
  }

  // ---------- Scheduled batch submit ----------
  async function submitSchedule(e: React.FormEvent) {
    e.preventDefault();
    setScheduleError(null);

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

    const subscriptionEmails = parseSubscriptionEmails(scheduleSubscriptionEmails);
    setSubmitting(true);
    try {
      const name = scheduleFile.name.toLowerCase();
      let rows: any[] = [];

      if (name.endsWith(".csv")) rows = await parseCsv(scheduleFile);
      else if (name.endsWith(".xlsx") || name.endsWith(".xls")) rows = await parseExcel(scheduleFile);
      else throw new Error("Only CSV or Excel files are allowed.");

      if (!rows.length) throw new Error("No rows found in the file.");

      const { queries, rowMeta, validationErrors } = parseBatchRows(rows);
      if (validationErrors.length) {
        const preview = validationErrors.slice(0, 4).join(" ");
        const remaining = validationErrors.length > 4 ? ` (+${validationErrors.length - 4} more)` : "";
        throw new Error(`Upload validation failed. ${preview}${remaining}`);
      }

      if (!Object.keys(queries).length) throw new Error("All rows are invalid (missing required names).");

      const accepted = await uploadBatchAndSubmitJob({
        file: scheduleFile,
        queries,
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

      const screenedKeySet = new Set((accepted.screened_item_keys ?? []).map((key) => safeTrim(String(key))).filter(Boolean));
      const hasScreenedSubset = screenedKeySet.size > 0;
      const isDeferredScheduleStart = accepted.total_items === 0 && Boolean(accepted.daily_schedule_id);

      const placeholderItems: BatchSubmission["items"] = rowMeta.map((m) => {
        const isScheduledSkip = hasScreenedSubset && !screenedKeySet.has(m.key);
        const fallbackMatches: EntityMatches = {
          results: [],
          total: { value: 0, relation: "eq" },
          query: queries[m.key],
          status: isScheduledSkip ? 204 : 202,
        };
        return {
          customerType: m.uiType === "Individual" ? "Person" : "Entity",
          displayName: m.displayName,
          result: isScheduledSkip ? "NO_HIT" : "PROCESSING",
          message: isScheduledSkip
            ? "Skipped (already screened in previous schedule runs)."
            : isDeferredScheduleStart
              ? "Scheduled. Screening will start at the configured run time."
              : "Screening in progress",
          details: { uiType: m.uiType, matches: fallbackMatches },
        };
      });

      const entry: BatchSubmission = {
        id: uuid(),
        createdAt: new Date().toISOString(),
        mode: "BATCH",
        createdByUserId: currentUser.id,
        createdByUserName: currentUser.name,
        businessUnitCode: scheduleBusinessUnitCode,
        jobId: accepted.job_id,
        fileName: scheduleFile.name,
        overallResult: isDeferredScheduleStart ? "PROCESSING" : accepted.total_items === 0 ? "NO_HIT" : "PROCESSING",
        screeningTypes: scheduleScreeningTypes,
        dailyScreening: true,
        scheduleFrequency,
        dailyScheduleId: accepted.daily_schedule_id ?? undefined,
        dailyScheduleActive: Boolean(accepted.daily_schedule_id),
        sourceUploadId: accepted.source_upload_id,
        sourceS3Uri: accepted.s3_uri ?? undefined,
        items: placeholderItems,
      };

      setSubmissions((prev) => [entry, ...prev].slice(0, 500));
      setLatest(entry);
      setPage(1);

      if (accepted.total_items > 0) {
        void (async () => {
          try {
            const progress = await waitForScreeningJob(accepted.job_id, { timeoutMs: 1000 * 60 * 60 });
            const responses = progress.responses ?? {};

            const resolvedItems: BatchSubmission["items"] = rowMeta.map((m) => {
              const isScheduledSkip = hasScreenedSubset && !screenedKeySet.has(m.key);
              if (isScheduledSkip) {
                const fallbackMatches: EntityMatches = {
                  results: [],
                  total: { value: 0, relation: "eq" },
                  query: queries[m.key],
                  status: 204,
                };
                return {
                  customerType: m.uiType === "Individual" ? "Person" : "Entity",
                  displayName: m.displayName,
                  result: "NO_HIT",
                  message: "Skipped (already screened in previous schedule runs).",
                  details: { uiType: m.uiType, matches: fallbackMatches },
                };
              }

              const matches = responses[m.key];
              if (!matches) {
                const fallbackMatches: EntityMatches = {
                  results: [],
                  total: { value: 0, relation: "eq" },
                  query: queries[m.key],
                  status: 500,
                };
                return {
                  customerType: m.uiType === "Individual" ? "Person" : "Entity",
                  displayName: m.displayName,
                  result: "ERROR",
                  message: "Screening failed for this row",
                  details: { uiType: m.uiType, matches: fallbackMatches },
                };
              }

              const engine = classifyEngine(matches.results ?? []);
              return {
                customerType: m.uiType === "Individual" ? "Person" : "Entity",
                displayName: m.displayName,
                result: engine === "HIT" ? "HIT" : engine === "NO_HIT" ? "NO_HIT" : "ERROR",
                message: matches?.results?.[0]?.caption ? `Top match: ${matches.results[0].caption}` : undefined,
                details: { uiType: m.uiType, matches },
              };
            });

            const overall =
              progress.status === "FAILED"
                ? "ERROR"
                : resolvedItems.some((i) => i.result === "HIT")
                  ? "HIT"
                  : resolvedItems.some((i) => i.result === "ERROR")
                    ? "ERROR"
                    : "NO_HIT";

            setSubmissions((prev) =>
              prev.map((s) =>
                s.mode === "BATCH" &&
                (s.id === entry.id || s.id === accepted.job_id || safeTrim(String((s as any).jobId || "")) === accepted.job_id)
                  ? ({ ...s, overallResult: overall, items: resolvedItems } as BatchSubmission)
                  : s
              )
            );
          } catch (err: any) {
            const failureText = safeTrim(String(err?.message ?? "Scheduled screening failed."));
            setSubmissions((prev) =>
              prev.map((s) => {
                if (
                  s.mode !== "BATCH" ||
                  (s.id !== entry.id && s.id !== accepted.job_id && safeTrim(String((s as any).jobId || "")) !== accepted.job_id)
                ) {
                  return s;
                }
                const failedItems = s.items.map((it) =>
                  it.result === "PROCESSING" ? { ...it, result: "ERROR", message: failureText || "Scheduled screening failed." } : it
                );
                return { ...s, overallResult: "ERROR", items: failedItems } as BatchSubmission;
              })
            );
          }
        })();
      }

      setScheduleName("");
      setScheduleScreeningTypes(["Sanction"]);
      setScheduleFrequency("DAILY");
      setScheduleRunAt(defaultScheduleRunAtValue());
      setScheduleSubscriptionEmails("");
      setScheduleFile(null);
      setScheduleFileName("");
      setScheduleTemplatesOpen(false);
    } catch (err: any) {
      setScheduleError(err?.message ?? "Scheduled screening failed.");
    } finally {
      setSubmitting(false);
    }
  }

  // ---------- Flatten results (used under BOTH tabs) ----------
  type ResultRow = {
    id: string;
    entity: string;
    partyKey: string;
    mode: ResultMode;
    type: UiType;
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

  const flattened: ResultRow[] = useMemo(() => {
    if (!currentUser) return [];
    const rows: ResultRow[] = [];

    submissions.forEach((s: Submission) => {
      const created = formatSubmittedDateTime((s as any).createdAt);
      const submittedAtRaw = safeTrim(String((s as any).createdAt || ""));

      // SINGLE: our new single submission stores details.meta + responses
      if (s.mode === "SINGLE" && (s as any).details?.meta && (s as any).details?.responses) {
        const meta = (s as any).details.meta as { key: string; uiType: UiType; displayName: string }[];
        const responses = (s as any).details.responses as Record<string, any>;

        meta.forEach((m) => {
          const matches = responses[m.key];
          let engine: EngineStatus = "ERROR";
          if (matches) engine = classifyEngine(matches.results ?? []);

          const manualMatch = Boolean((matches as any)?.manualMatch === true); // not present initially
          const ui = engineToUiStatus(engine, manualMatch);
          const matchingScore = topMatchingScore(matches?.results);

          rows.push({
            id: `${s.id}_${m.key}`,
            entity: m.displayName,
            partyKey: extractPartyKeyFromRaw({ submission: s, m, matches }) || safeTrim(String(m.key || "")),
            mode: "SINGLE",
            type: m.uiType,
            country: extractCountryFromQuery(matches?.query),
            engineStatus: engine,
            manualMatch,
            uiStatus: ui,
            matchingScore,
            date: created,
            submittedAt: submittedAtRaw,
            batchSubmissionId: null,
            dailyScheduleId: null,
            dailyScheduleActive: false,
            raw: { submission: s, m, matches },
          });
        });

        return;
      }

      // Legacy SINGLE (older structure)
      if (s.mode === "SINGLE") {
        const engine = (s as any).result as EngineStatus;
        const uiType: UiType = (s as any).customerType === "Entity" ? "Organization" : "Individual";
        const manualMatch = Boolean((s as any).manualMatch === true);
        const ui = engineToUiStatus(engine, manualMatch);
        rows.push({
          id: s.id,
          entity: (s as any).displayName,
          partyKey: extractPartyKeyFromRaw(s),
          mode: "SINGLE",
          type: uiType,
          country: extractCountryFromRaw(s),
          engineStatus: engine,
          manualMatch,
          uiStatus: ui,
          matchingScore: topMatchingScore((s as any)?.details?.results),
          date: created,
          submittedAt: submittedAtRaw,
          batchSubmissionId: null,
          dailyScheduleId: null,
          dailyScheduleActive: false,
          raw: s,
        });
        return;
      }

      // BATCH
      if (s.mode === "BATCH") {
        (s as any).items.forEach((it: any, idx: number) => {
          const engine = it.result as EngineStatus;
          const uiType: UiType = it.details?.uiType ?? (it.customerType === "Entity" ? "Organization" : "Individual");
          const manualMatch = Boolean(it.manualMatch === true);
          const ui = engineToUiStatus(engine, manualMatch);
          rows.push({
            id: `${s.id}_${idx}`,
            entity: it.displayName,
            partyKey: extractPartyKeyFromRaw({ submission: s, item: it }),
            mode: "BATCH",
            type: uiType,
            country: extractCountryFromQuery(it?.details?.matches?.query),
            engineStatus: engine,
            manualMatch,
            uiStatus: ui,
            matchingScore: topMatchingScore(it?.details?.matches?.results),
            date: created,
            submittedAt: submittedAtRaw,
            batchSubmissionId: s.id,
            dailyScheduleId: typeof (s as any).dailyScheduleId === "string" ? (s as any).dailyScheduleId : null,
            dailyScheduleActive: Boolean((s as any).dailyScheduleActive === true),
            raw: { submission: s, item: it },
          });
        });
      }
    });

    return rows;
  }, [submissions, currentUser]);

  const hasPendingResults = useMemo(() => flattened.some((row) => row.uiStatus === "Pending"), [flattened]);

  useEffect(() => {
    if (!currentUser?.id || !hasPendingResults) return;
    const timerId = window.setInterval(() => {
      void loadSubmissionHistory({ silent: true, updateTimestamp: false, resetPage: false });
    }, 15000);
    return () => window.clearInterval(timerId);
  }, [currentUser?.id, hasPendingResults, loadSubmissionHistory]);

  const summaryCounts = useMemo(() => {
    let total = 0;
    let clear = 0;
    let potential = 0;
    let pending = 0;
    let failed = 0;
    let match = 0;

    flattened.forEach((row) => {
      total += 1;
      if (row.uiStatus === "Clear") clear += 1;
      if (row.uiStatus === "Potential Match") potential += 1;
      if (row.uiStatus === "Pending") pending += 1;
      if (row.uiStatus === "Failed") failed += 1;
      if (row.uiStatus === "Match") match += 1;
    });

    return { total, clear, potential, pending, failed, match };
  }, [flattened]);

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
      const hay = `${r.entity} ${r.partyKey} ${r.mode} ${r.type} ${r.country} ${r.uiStatus} ${r.date}`.toLowerCase();
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
      if (resultSortKey === "mode") return a.mode.localeCompare(b.mode);
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
      "Country",
      "Status",
      "Matching Score",
      "Submitted Date/Time",
      "Screening Types",
      "Daily Screening",
      "Batch Name",
      "Top Hit Name",
      "Top Hit Score",
      "Top Hit Keyword/Category",
      "Total Hits",
    ];

    const rows = filtered.map((row) => {
      const submission = row.raw?.submission;
      const screeningTypesRaw =
        submission?.screeningTypes ??
        submission?.details?.screeningTypes ??
        [];
      const screeningTypes = Array.isArray(screeningTypesRaw)
        ? screeningTypesRaw.map((value: unknown) => safeTrim(String(value))).filter(Boolean).join(", ")
        : "";

      const batchName = safeTrim(String(submission?.fileName ?? ""));
      const hitRows = getHitMatchesFromRaw(row.raw);
      const topHit = hitRows[0];

      return [
        row.entity,
        row.partyKey,
        row.mode === "SINGLE" ? "Single" : "Batch",
        row.type,
        row.country || "",
        row.uiStatus,
        formatMatchingScore(row.matchingScore),
        row.date,
        screeningTypes,
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
  const [hitEntityDialog, setHitEntityDialog] = useState<{
    sourceEntity: string;
    hits: HitMatch[];
    error: { status: number | null; text: string } | null;
    pending: boolean;
  } | null>(null);

  function sortIndicator(key: ResultSortKey): string {
    if (resultSortKey !== key) return "\u21C5";
    return resultSortDirection === "asc" ? "\u25B2" : "\u25BC";
  }

  function toggleResultSort(key: ResultSortKey): void {
    if (resultSortKey === key) {
      setResultSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setResultSortKey(key);
    setResultSortDirection(key === "submittedAt" || key === "score" ? "desc" : "asc");
  }

  function openHitEntity(row: ResultRow) {
    const hits = getHitMatchesFromRaw(row.raw);
    const error = row.uiStatus === "Failed" ? extractEngineErrorFromRaw(row.raw) : null;
    setHitEntityDialog({
      sourceEntity: row.entity,
      hits,
      error: error ? { status: error.status, text: error.errorText } : null,
      pending: row.uiStatus === "Pending",
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
      setMode(available[0]);
      return;
    }
    if (e.key === "End") {
      setMode(available[available.length - 1]);
      return;
    }
    const delta = e.key === "ArrowRight" ? 1 : -1;
    const next = (idx + delta + available.length) % available.length;
    setMode(available[next]);
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
            onClick={() => setMode("SINGLE")}
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
            onClick={() => setMode("BATCH")}
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
            onClick={() => setMode("SCHEDULE")}
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

        <button className="btnGhost" type="button" onClick={clearAll} disabled={submitting} style={{ marginLeft: "auto" }}>
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
                    disabled={businessUnitsLoading}
                  >
                    <option value="">Select Business Unit</option>
                    {businessUnitOptions.map((row) => (
                      <option key={row.code} value={row.code}>
                        {row.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {businessUnitsLoading ? (
                <div className="infoBox" role="status" aria-live="polite">
                  Loading Business Units…
                </div>
              ) : null}
              {businessUnitsError ? (
                <div className="errorBox" role="alert" aria-live="assertive">
                  {businessUnitsError}
                  <div style={{ marginTop: 8 }}>
                    <button type="button" className="btnGhostSmall" onClick={reloadBusinessUnits} disabled={businessUnitsLoading}>
                      Retry
                    </button>
                  </div>
                </div>
              ) : null}
              {!businessUnitsLoading && currentUser && !businessUnitOptions.length && !businessUnitsError ? (
                <div className="errorBox" role="alert" aria-live="polite">
                  No Business Unit is mapped to your user. Please contact an administrator. (User ID: {currentUser.id})
                </div>
              ) : null}

              <ScreeningTypeCards
                selected={singleScreeningTypes}
                onToggle={(value) => toggleScreeningType(value, setSingleScreeningTypes)}
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
                            <label>{i === 0 ? "ID Type" : ""}</label>
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
                            <label>{i === 0 ? "ID Number" : ""}</label>
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
              <button className="btnRunWide" type="submit" disabled={submitting}>
                {submitting ? "Running..." : "Run OFAC Screening"}
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
                disabled={businessUnitsLoading}
              >
                <option value="">Select Business Unit</option>
                {businessUnitOptions.map((row) => (
                  <option key={row.code} value={row.code}>
                    {row.name}
                  </option>
                ))}
              </select>
            </div>

            <ScreeningTypeCards
              selected={batchScreeningTypes}
              onToggle={(value) => toggleScreeningType(value, setBatchScreeningTypes)}
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
              <div className="dropSub">Supports CSV and Excel files</div>
              <div className="dropSub">
                <strong>Max File Size: {MAX_UPLOAD_DISPLAY_MB} MB</strong> <span className="muted">(system limit: {MAX_UPLOAD_VALIDATION_MB} MB)</span>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  if (validateUploadFile(f, setBatchError)) {
                    setBatchFile(f);
                    setBatchFileName(f.name);
                    setBatchError(null);
                  }
                  e.currentTarget.value = "";
                }}
              />
            </div>

            {businessUnitsLoading ? (
              <div className="infoBox" role="status" aria-live="polite">
                Loading Business Units…
              </div>
            ) : null}
            {businessUnitsError ? (
              <div className="errorBox" role="alert" aria-live="assertive">
                {businessUnitsError}
                <div style={{ marginTop: 8 }}>
                  <button type="button" className="btnGhostSmall" onClick={reloadBusinessUnits} disabled={businessUnitsLoading}>
                    Retry
                  </button>
                </div>
              </div>
            ) : null}
            {!businessUnitsLoading && currentUser && !businessUnitOptions.length && !businessUnitsError ? (
              <div className="errorBox" role="alert" aria-live="polite">
                No Business Unit is mapped to your user. Please contact an administrator. (User ID: {currentUser.id})
              </div>
            ) : null}
            {batchError ? <div className="errorBox" role="alert" aria-live="assertive">{batchError}</div> : null}
            <form onSubmit={submitBatch}>
              <button className="btnBatchWide" type="submit" disabled={submitting}>
                {submitting ? "Starting..." : "Start Batch Screening"}
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
                  disabled={businessUnitsLoading}
                >
                  <option value="">Select Business Unit</option>
                  {businessUnitOptions.map((row) => (
                    <option key={row.code} value={row.code}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </div>

              <ScreeningTypeCards
                selected={scheduleScreeningTypes}
                onToggle={(value) => toggleScreeningType(value, setScheduleScreeningTypes)}
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
                  placeholder="compliance@company.com, analyst@company.com"
                />
                <div className="hintText">
                  Use comma, semicolon, or new line to enter multiple email addresses. First-time SNS email subscriptions require clicking the confirmation email once before notifications can be delivered. Subscription actions are recorded in Audit Log.
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
                <div className="dropSub">Supports CSV and Excel files</div>
                <div className="dropSub">
                  <strong>Max File Size: {MAX_UPLOAD_DISPLAY_MB} MB</strong> <span className="muted">(system limit: {MAX_UPLOAD_VALIDATION_MB} MB)</span>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    if (validateUploadFile(f, setScheduleError)) {
                      setScheduleFile(f);
                      setScheduleFileName(f.name);
                      setScheduleError(null);
                    }
                    e.currentTarget.value = "";
                  }}
                />
              </div>

              {businessUnitsLoading ? (
                <div className="infoBox" role="status" aria-live="polite">
                  Loading Business Units…
                </div>
              ) : null}
              {businessUnitsError ? (
                <div className="errorBox" role="alert" aria-live="assertive">
                  {businessUnitsError}
                  <div style={{ marginTop: 8 }}>
                    <button type="button" className="btnGhostSmall" onClick={reloadBusinessUnits} disabled={businessUnitsLoading}>
                      Retry
                    </button>
                  </div>
                </div>
              ) : null}
              {!businessUnitsLoading && currentUser && !businessUnitOptions.length && !businessUnitsError ? (
                <div className="errorBox" role="alert" aria-live="polite">
                  No Business Unit is mapped to your user. Please contact an administrator. (User ID: {currentUser.id})
                </div>
              ) : null}
              {scheduleError ? <div className="errorBox" role="alert" aria-live="assertive">{scheduleError}</div> : null}
              <button className="btnBatchWide" type="submit" disabled={submitting}>
                {submitting ? "Starting..." : "Create Scheduled Screening"}
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
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Search entities..."
              />
            </div>

            <select
              aria-label="Filter results by status"
              className="filterSelect"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value as StatusFilter);
                setPage(1);
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
                setTypeFilter(e.target.value as TypeFilter);
                setPage(1);
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
          <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col" style={{ width: 220 }}>
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("entity")}>
                      Entity {sortIndicator("entity")}
                    </button>
                  </th>
                  <th scope="col" style={{ width: 120 }}>
                    Party Key
                  </th>
                  <th scope="col" style={{ width: 120 }}>
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("mode")}>
                      Mode {sortIndicator("mode")}
                    </button>
                  </th>
                  <th scope="col" style={{ width: 120 }}>
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("type")}>
                      Type {sortIndicator("type")}
                    </button>
                  </th>
                  <th scope="col" style={{ width: 120 }}>
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("country")}>
                      Country {sortIndicator("country")}
                    </button>
                  </th>
                  <th scope="col" style={{ width: 140 }}>
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("status")}>
                      Screening Result {sortIndicator("status")}
                    </button>
                  </th>
                  <th scope="col" style={{ width: 140 }}>
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("score")}>
                      Matching Score {sortIndicator("score")}
                    </button>
                  </th>
                  <th scope="col" style={{ width: 190 }}>
                    <button type="button" className="linkBtn" onClick={() => toggleResultSort("submittedAt")}>
                      Submitted Date/Time {sortIndicator("submittedAt")}
                    </button>
                  </th>
                  <th scope="col" style={{ width: 230 }}>Actions</th>
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
                    return (
                      <tr key={r.id}>
                        <td className="entityCell">
                          <span className="entityIcon" aria-hidden="true">
                            {uiTypeIcon(r.type)}
                          </span>
                          <span className="entityValue" title={r.entity}>{r.entity}</span>
                        </td>
                        <td className="muted partyKeyCell">
                          <span className="partyKeyValue" title={r.partyKey || ""}>{r.partyKey || "\u2014"}</span>
                        </td>
                        <td>{modeBadge(r.mode)}</td>
                        <td className="muted">{r.type}</td>
                        <td className="muted">{r.country || "\u2014"}</td>
                        <td>{badge(r.uiStatus)}</td>
                        <td className="muted">{formatMatchingScore(r.matchingScore)}</td>
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
                <button className="pagerBtn" disabled={pageSafe <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))} type="button">
                  {"\u2039"}
                </button>
                <div className="pagerText">Page {pageSafe} of {totalPages}</div>
                <button className="pagerBtn" disabled={pageSafe >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))} type="button">
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





