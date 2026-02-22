import React, { useEffect, useMemo, useRef, useState } from "react";
import * as XLSX from "xlsx";
import { useRecoilState } from "recoil";
import { z } from "zod";
import { submissionsState, latestResultState, type Submission, type BatchSubmission, type SingleSubmission } from "../state/submissions";
import { matchBatch, type EntityExample } from "../api/openSanctions";
import { parseCsv, parseExcel } from "../utils/batchParse";
import { CountryAutosuggest } from "../components/CountryAutosuggest";
import { IsoDateInput } from "../components/IsoDateInput";

type Mode = "SINGLE" | "BATCH";
type UiType = "Individual" | "Organization" | "Vessel" | "Aircraft";

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
    };

type StatusFilter = "All Statuses" | "Clear" | "Potential Match" | "Pending" | "Match";
type TypeFilter = "All Types" | UiType;
type SelectOption<T extends string> = { value: T; label: string };

function FormSelect<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (value: T) => void;
  options: SelectOption<T>[];
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((o) => o.value === value) ?? options[0];

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
        onClick={() => setOpen((v) => !v)}
      >
        <span>{selected?.label ?? value}</span>
        <span className="formSelectCaret">{open ? "▲" : "▼"}</span>
      </button>

      {open ? (
        <div className="formSelectMenu" role="listbox">
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`formSelectOption ${opt.value === value ? "active" : ""}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(opt.value);
                setOpen(false);
              }}
            >
              {opt.label}
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

const ENTITY_TYPE_OPTIONS: SelectOption<UiType>[] = [
  { value: "Individual", label: "Individual" },
  { value: "Organization", label: "Organization" },
  { value: "Vessel", label: "Vessel" },
  { value: "Aircraft", label: "Aircraft" },
];

const ID_TYPE_OPTIONS = [
  "Passport",
  "National ID",
  "Driver's License",
  "Tax ID/EIN",
  "Company Registration Number",
  "Business License",
  "IATA Number",
  "Other",
] as const;

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
  // These are supported in OpenSanctions entity models; if your API rejects, we can switch to "Company"
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

  // IDs (multi) -> put idNumber list
  const idNumbers = (item.ids || []).map((x) => safeTrim(x.idNumber)).filter(Boolean);
  if (idNumbers.length) {
    if (schema === "Person") props.idNumber = idNumbers;
    else props.registrationNumber = idNumbers;
  }

  return { schema, properties: props };
}

type EngineStatus = "NO_HIT" | "HIT" | "ERROR";
type UiStatus = "Clear" | "Potential Match" | "Pending" | "Match";

function engineToUiStatus(s: EngineStatus, manualMatch?: boolean): UiStatus {
  if (manualMatch) return "Match";
  if (s === "NO_HIT") return "Clear";
  if (s === "HIT") return "Potential Match";
  return "Pending";
}

function classifyEngine(results: { match: boolean }[]): EngineStatus {
  return results?.some((r) => r.match) ? "HIT" : "NO_HIT";
}

function badge(status: UiStatus) {
  if (status === "Clear") return <span className="statusPill statusClear">Clear</span>;
  if (status === "Potential Match") return <span className="statusPill statusPotential">Potential Match</span>;
  if (status === "Pending") return <span className="statusPill statusPending">Pending</span>;
  return <span className="statusPill statusMatch">Match</span>;
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

function downloadTemplate(kind: UiType | "Mixed", format: "csv" | "xlsx") {
  // Base fields you already parse; extra fields are ok (ignored if not used)
  const headers = [
    "customerType", // Person/Entity
    "firstName",
    "middleName",
    "lastName",
    "fullName",
    "aliasName",
    "dateOfBirth",
    "countries",      // comma separated optional
    "addresses",      // comma separated optional
    "idType",
    "idNumber",
    "idCountry",
    // extra demo fields
    "imoNumber",
    "tailNumber",
  ];

  const sampleRows: any[] = [];

  if (kind === "Individual") {
    sampleRows.push({
      customerType: "Person",
      firstName: "John",
      middleName: "",
      lastName: "Doe",
      fullName: "",
      aliasName: "Johnny",
      dateOfBirth: "1980-01-01",
      countries: "US,CA",
      addresses: "123 Main St, New York, NY 10001",
      idType: "Passport",
      idNumber: "X1234567",
      idCountry: "US",
      imoNumber: "",
      tailNumber: "",
    });
  } else if (kind === "Organization") {
    sampleRows.push({
      customerType: "Entity",
      firstName: "",
      middleName: "",
      lastName: "",
      fullName: "ACME Holdings LLC",
      aliasName: "",
      dateOfBirth: "",
      countries: "US",
      addresses: "200 Business Rd, Newark, NJ 07102",
      idType: "EIN",
      idNumber: "12-3456789",
      idCountry: "US",
      imoNumber: "",
      tailNumber: "",
    });
  } else if (kind === "Vessel") {
    sampleRows.push({
      customerType: "Entity",
      firstName: "",
      middleName: "",
      lastName: "",
      fullName: "MV Example Vessel",
      aliasName: "",
      dateOfBirth: "",
      countries: "PA",
      addresses: "",
      idType: "IMO",
      idNumber: "9395044",
      idCountry: "",
      imoNumber: "9395044",
      tailNumber: "",
    });
  } else if (kind === "Aircraft") {
    sampleRows.push({
      customerType: "Entity",
      firstName: "",
      middleName: "",
      lastName: "",
      fullName: "Example Aircraft",
      aliasName: "",
      dateOfBirth: "",
      countries: "US",
      addresses: "",
      idType: "Tail",
      idNumber: "N123AB",
      idCountry: "US",
      imoNumber: "",
      tailNumber: "N123AB",
    });
  } else {
    // Mixed
    sampleRows.push(
      {
        customerType: "Person",
        firstName: "John",
        middleName: "",
        lastName: "Doe",
        fullName: "",
        aliasName: "",
        dateOfBirth: "1980-01-01",
        countries: "US",
        addresses: "",
        idType: "Passport",
        idNumber: "X1234567",
        idCountry: "US",
        imoNumber: "",
        tailNumber: "",
      },
      {
        customerType: "Entity",
        firstName: "",
        middleName: "",
        lastName: "",
        fullName: "ACME Holdings LLC",
        aliasName: "",
        dateOfBirth: "",
        countries: "CA",
        addresses: "",
        idType: "Reg",
        idNumber: "REG-001",
        idCountry: "CA",
        imoNumber: "",
        tailNumber: "",
      }
    );
  }

  if (format === "csv") {
    const lines = [
      headers.join(","),
      ...sampleRows.map((r) => headers.map((h) => csvEscape((r as any)[h])).join(",")),
    ].join("\n");
    downloadBlob(new Blob([lines], { type: "text/csv;charset=utf-8" }), `ofac_${kind.toLowerCase()}_template.csv`);
    return;
  }

  const ws = XLSX.utils.json_to_sheet(sampleRows, { header: headers });
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Template");
  const out = XLSX.write(wb, { type: "array", bookType: "xlsx" });
  downloadBlob(new Blob([out], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), `ofac_${kind.toLowerCase()}_template.xlsx`);
}

export function ScreeningDetailPage() {
  const [mode, setMode] = useState<Mode>("SINGLE");

  const [submissions, setSubmissions] = useRecoilState(submissionsState);
  const [, setLatest] = useRecoilState(latestResultState);

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
      ids: [{ idType: "Passport", idNumber: "", idCountry: "" }],
    },
  ]);

  const [notes, setNotes] = useState("");

  // BATCH
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [batchName, setBatchName] = useState("");
  const [batchFile, setBatchFile] = useState<File | null>(null);
  const [batchFileName, setBatchFileName] = useState("");
  const [batchError, setBatchError] = useState<string | null>(null);
  const [singleError, setSingleError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const selectedEntityType: UiType = names[0]?.uiType ?? "Individual";
  const primaryName = names[0];
  const aliasNames = names.slice(1);

  // Results filters + paging
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("All Statuses");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("All Types");
  const [page, setPage] = useState(1);

  // dropzone
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const singleSchema = useMemo(() => {
    // Validate each name item basic requirements + DOB rules for individual only
    return z.array(
      z.object({
        uiType: z.enum(["Individual", "Organization", "Vessel", "Aircraft"]),
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
          ids: [{ idType: "Passport", idNumber: "", idCountry: "" }],
        },
      ]);
      setNotes("");
    } else {
      setBatchName("");
      setBatchFile(null);
      setBatchFileName("");
      setTemplatesOpen(false);
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
      return uiType === "Individual" ? normalized : normalized.slice(0, 1);
    });
  }

  function addName() {
    setNames((prev) => {
      if ((prev[0]?.uiType ?? "Individual") !== "Individual") return prev;
      return [
        ...prev,
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
          ids: [{ idType: "Passport", idNumber: "", idCountry: "" }],
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
      prev.map((n) => (n.id === id ? { ...n, ids: [...n.ids, { idType: "Passport", idNumber: "", idCountry: "" }] } : n))
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
      const parsed = singleSchema.safeParse(names);
      if (!parsed.success) {
        setSingleError(parsed.error.issues[0]?.message ?? "Fix validation errors.");
        setSubmitting(false);
        return;
      }

      // Build one API call containing multiple queries
      const queries: Record<string, EntityExample> = {};
      const meta: { key: string; uiType: UiType; displayName: string }[] = [];

      names.forEach((n, idx) => {
        const key = `single_${idx + 1}`;

        let displayName = "";
        if (n.uiType === "Individual") {
          const splitName = [safeTrim(n.firstName), safeTrim(n.lastName)].filter(Boolean).join(" ");
          displayName = safeTrim(n.fullName) || splitName;
        } else {
          displayName = safeTrim(n.fullName);
        }

        meta.push({ key, uiType: n.uiType, displayName: displayName || `(Item ${idx + 1})` });
        queries[key] = buildEntityExampleFromNameItem(n);
      });

      const resp = await matchBatch(queries);

      // Convert to a single "SINGLE" submission containing multiple items (still SINGLE mode for your history)
      // We store as SingleSubmission but keep details so results table can read it
      const entry: SingleSubmission = {
        id: uuid(),
        createdAt: new Date().toISOString(),
        mode: "SINGLE",
        customerType: "Person", // not used by new results table; keep for backward compatibility
        displayName: `Single Screening (${meta.length})`,
        result: "NO_HIT",
        message: notes ? `Notes: ${notes}` : undefined,
        details: { meta, responses: resp.responses, notes },
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

    if (!safeTrim(batchName)) {
      setBatchError("Batch Name is required.");
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

      // Build queries (one API call)
      const queries: Record<string, EntityExample> = {};
      const rowMeta: { key: string; displayName: string; uiType: UiType }[] = [];

      rows.forEach((r, idx) => {
        const customerType = r.customerType === "Entity" ? "Entity" : "Person";
        const uiType: UiType =
          customerType === "Person" ? "Individual" : "Organization";

        const display =
          uiType === "Individual"
            ? [safeTrim(r.firstName || ""), safeTrim(r.lastName || "")].filter(Boolean).join(" ")
            : safeTrim(r.fullName || "");

        const key = `row_${idx + 1}`;
        rowMeta.push({ key, displayName: display || `(Row ${idx + 1})`, uiType });

        // required names
        if (uiType === "Individual" && (!safeTrim(r.firstName || "") || !safeTrim(r.lastName || ""))) return;
        if (uiType !== "Individual" && !safeTrim(r.fullName || "")) return;

        // Reuse your existing batchRow conversion idea
        const item: NameItem = {
          id: key,
          uiType,
          nameMode: uiType === "Individual" ? "split" : "full",
          firstName: safeTrim(r.firstName || ""),
          lastName: safeTrim(r.lastName || ""),
          middleName: safeTrim(r.middleName || ""),
          fullName: safeTrim(r.fullName || ""),
          aliasName: safeTrim(r.aliasName || ""),
          dateOfBirth: safeTrim(r.dateOfBirth || ""),
          countries: safeTrim(r.countries || "") ? String(r.countries).split(",").map((x) => safeTrim(x)) : [safeTrim(r.country || "")].filter(Boolean),
          addresses: safeTrim(r.addresses || "") ? String(r.addresses).split(",").map((x) => safeTrim(x)) : [],
          ids: [
            {
              idType: safeTrim(r.idType || r.idCode || ""),
              idNumber: safeTrim(r.idNumber || ""),
              idCountry: safeTrim(r.idCountry || r.idIssueCountry || ""),
            },
          ],
        };

        queries[key] = buildEntityExampleFromNameItem(item);
      });

      if (!Object.keys(queries).length) throw new Error("All rows are invalid (missing required names).");

      const resp = await matchBatch(queries);

      const items: BatchSubmission["items"] = rowMeta.map((m) => {
        const matches = resp.responses[m.key];
        if (!matches) {
          return { customerType: m.uiType === "Individual" ? "Person" : "Entity", displayName: m.displayName, result: "ERROR", message: "Invalid row" };
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
        items.some((i) => i.result === "HIT") ? "HIT" : items.some((i) => i.result === "ERROR") ? "ERROR" : "NO_HIT";

      const entry: BatchSubmission = {
        id: uuid(),
        createdAt: new Date().toISOString(),
        mode: "BATCH",
        fileName: batchFile.name,
        overallResult: overall,
        items,
      };

      const next = [entry, ...submissions].slice(0, 500);
      setSubmissions(next);
      setLatest(entry);

      // reset batch inputs after success
      setBatchFile(null);
      setBatchFileName("");
      setBatchName("");
      setTemplatesOpen(false);
      setPage(1);
    } catch (err: any) {
      setBatchError(err?.message ?? "Batch screening failed.");
    } finally {
      setSubmitting(false);
    }
  }

  // ---------- Flatten results (used under BOTH tabs) ----------
  type ResultRow = {
    id: string;
    entity: string;
    type: UiType;
    country: string;
    engineStatus: EngineStatus;
    manualMatch: boolean;
    uiStatus: UiStatus;
    risk: number;
    date: string;
    raw: any;
  };

  const flattened: ResultRow[] = useMemo(() => {
    const rows: ResultRow[] = [];

    submissions.forEach((s: Submission) => {
      const created = new Date((s as any).createdAt).toLocaleDateString();

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

          // simple risk heuristic: 0 clear, 1 potential, 0 pending
          const risk = ui === "Potential Match" ? 1 : ui === "Match" ? 2 : 0;

          // country best effort (from stored request isn't kept here; optional)
          rows.push({
            id: `${s.id}_${m.key}`,
            entity: m.displayName,
            type: m.uiType,
            country: "",
            engineStatus: engine,
            manualMatch,
            uiStatus: ui,
            risk,
            date: created,
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
          type: uiType,
          country: "",
          engineStatus: engine,
          manualMatch,
          uiStatus: ui,
          risk: ui === "Potential Match" ? 1 : ui === "Match" ? 2 : 0,
          date: created,
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
            type: uiType,
            country: "",
            engineStatus: engine,
            manualMatch,
            uiStatus: ui,
            risk: ui === "Potential Match" ? 1 : ui === "Match" ? 2 : 0,
            date: created,
            raw: { submission: s, item: it },
          });
        });
      }
    });

    return rows;
  }, [submissions]);

  // ---------- Filters ----------
  const filtered = useMemo(() => {
    const q = safeTrim(search).toLowerCase();

    return flattened.filter((r) => {
      // All types
      if (typeFilter !== "All Types" && r.type !== typeFilter) return false;

      // All statuses
      if (statusFilter !== "All Statuses" && r.uiStatus !== statusFilter) return false;

      // Search across entity + raw JSON (any field in screening & results)
      if (!q) return true;

      const blob = JSON.stringify(r.raw ?? {});
      const hay = `${r.entity} ${r.type} ${r.country} ${r.uiStatus} ${r.date} ${blob}`.toLowerCase();
      return hay.includes(q);
    });
  }, [flattened, search, statusFilter, typeFilter]);

  // ---------- Pagination (10) ----------
  const pageSize = 10;
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageSafe = Math.min(page, totalPages);
  const startIdx = (pageSafe - 1) * pageSize;
  const pageRows = filtered.slice(startIdx, startIdx + pageSize);

  // ---------- Mark as Match (manual true positive) ----------
  function markAsMatch(row: ResultRow) {
    // We store manualMatch flag inside raw object where possible; easiest durable is to store in submissionsState
    setSubmissions((prev) =>
      prev.map((s: any) => {
        // SINGLE new structure
        if (s.mode === "SINGLE" && row.id.startsWith(s.id) && s.details?.responses) {
          const key = row.id.replace(`${s.id}_`, "");
          const responses = { ...(s.details.responses ?? {}) };
          if (responses[key]) responses[key] = { ...responses[key], manualMatch: true };
          return { ...s, details: { ...s.details, responses } };
        }
        // BATCH
        if (s.mode === "BATCH" && row.id.startsWith(s.id + "_")) {
          const idx = Number(row.id.replace(`${s.id}_`, ""));
          const items = [...s.items];
          if (items[idx]) items[idx] = { ...items[idx], manualMatch: true };
          return { ...s, items };
        }
        // legacy SINGLE
        if (s.mode === "SINGLE" && s.id === row.id) {
          return { ...s, manualMatch: true };
        }
        return s;
      })
    );
  }

  return (
    <div className="page">
      {/* Tabs row like screenshot */}
      <SummaryCards />
      <div className="tabsRow">
        <button className={mode === "SINGLE" ? "tabBtn active" : "tabBtn"} onClick={() => setMode("SINGLE")} type="button">
          <span className="tabIcon">🔍</span> Single Screening
        </button>
        <button className={mode === "BATCH" ? "tabBtn active" : "tabBtn"} onClick={() => setMode("BATCH")} type="button">
          <span className="tabIcon">📄</span> Batch Screening
        </button>

        <button className="btnGhost" type="button" onClick={clearAll} disabled={submitting} style={{ marginLeft: "auto" }}>
          Clear
        </button>
      </div>

      {/* SINGLE */}
      {mode === "SINGLE" && (
        <div className="card">
          <div className="cardHeader">
            <h2>Single Entity Screening</h2>
          </div>

          <div className="cardBody">
            <form onSubmit={submitSingle}>
              <div className="singleEntityTypeRow">
                <div className="field singleEntityTypeField">
                  <label>Entity Type *</label>
                  <FormSelect
                    value={selectedEntityType}
                    onChange={(uiType) => setEntityTypeForAll(uiType)}
                    options={ENTITY_TYPE_OPTIONS}
                  />
                </div>
              </div>

              {/* Names section with +Add */}
              <div className="sectionRow">
                <div className="sectionTitle">Names</div>
              </div>

              {primaryName ? (
                <div key={primaryName.id} className="nameCard">
                  <div className="nameCardTop">
                    <div className="nameCardLabel">Primary Name</div>
                    <div style={{ display: "flex", gap: 8 }}>
                      {primaryName.uiType === "Individual" ? (
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
                  ) : (
                    <div className="grid2">
                      <div className="field" style={{ gridColumn: "1 / -1" }}>
                        <label>Primary Name *</label>
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

              {singleError ? <div className="errorBox">{singleError}</div> : null}

              <button className="btnRunWide" type="submit" disabled={submitting}>
                {submitting ? "Running..." : "Run OFAC Screening"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* BATCH */}
      {mode === "BATCH" && (
        <div className="card">
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
                <span className="accordionIcon">⬇</span>
                <span>Download Screening Templates</span>
                <span className="badgeCount">5 templates</span>
              </div>
              <span className="chev">{templatesOpen ? "▴" : "▾"}</span>
            </button>

            {/* Accordion content */}
            {templatesOpen && (
              <div className="templateGrid5">
                <TemplateCard
                  title="Individual Screening"
                  desc="Persons, employees, customers, beneficial owners"
                  chips={["entity name", "entity type", "date of birth", "+5 more"]}
                  onCsv={() => downloadTemplate("Individual", "csv")}
                />
                <TemplateCard
                  title="Organization Screening"
                  desc="Companies, vendors, partners, subsidiaries"
                  chips={["entity name", "entity type", "dba name", "+5 more"]}
                  onCsv={() => downloadTemplate("Organization", "csv")}
                />
                <TemplateCard
                  title="Vessel Screening"
                  desc="Ships, tankers, cargo vessels, maritime assets"
                  chips={["entity name", "entity type", "imo number", "+5 more"]}
                  onCsv={() => downloadTemplate("Vessel", "csv")}
                />
                <TemplateCard
                  title="Aircraft Screening"
                  desc="Aircraft, jets, aviation assets"
                  chips={["entity name", "entity type", "tail number", "+5 more"]}
                  onCsv={() => downloadTemplate("Aircraft", "csv")}
                />
                <TemplateCard
                  title="Mixed / Combined"
                  desc="Combined list of individuals and organizations"
                  chips={["entity name", "entity type", "dba name", "+8 more"]}
                  onCsv={() => downloadTemplate("Mixed", "csv")}
                />
              </div>
            )}

            <div className="field" style={{ marginTop: 14 }}>
              <label>Batch Name *</label>
              <input value={batchName} onChange={(e) => setBatchName(e.target.value)} placeholder="e.g., Q1 2024 Vendor Screening" />
            </div>

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
                if (!f) return;
                setBatchFile(f);
                setBatchFileName(f.name);
                setBatchError(null);
              }}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
            >
              <div className="dropIconCircle">⬆</div>
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

              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  if (!f) return;
                  setBatchFile(f);
                  setBatchFileName(f.name);
                  setBatchError(null);
                  e.currentTarget.value = "";
                }}
              />
            </div>

            {batchError ? <div className="errorBox">{batchError}</div> : null}

            <form onSubmit={submitBatch}>
              <button className="btnBatchWide" type="submit" disabled={submitting}>
                {submitting ? "Starting..." : "Start Batch Screening"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Screening Results (under BOTH tabs) */}
      <div className="card" style={{ marginTop: 18 }}>
        <div className="resultsHeader">
          <h2>Screening Results</h2>

          <div className="resultsFilters">
            <div className="searchBox">
              <span className="searchIcon">🔍</span>
              <input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Search entities..."
              />
            </div>

            <select
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
              <option>Match</option>
            </select>

            <select
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
                  <th style={{ width: 220 }}>Entity</th>
                  <th style={{ width: 120 }}>Type</th>
                  <th style={{ width: 120 }}>Country</th>
                  <th style={{ width: 140 }}>Status</th>
                  <th style={{ width: 120 }}>Risk Score</th>
                  <th style={{ width: 120 }}>Date</th>
                  <th style={{ width: 110, textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="emptyRow">
                      No results found.
                    </td>
                  </tr>
                ) : (
                  pageRows.map((r) => (
                    <tr key={r.id}>
                      <td className="entityCell">
                        <span className="entityIcon" aria-hidden="true">
                          {r.type === "Individual" ? "👤" : r.type === "Organization" ? "🏢" : r.type === "Vessel" ? "🛳️" : "✈️"}
                        </span>
                        <span>{r.entity}</span>
                      </td>
                      <td className="muted">{r.type}</td>
                      <td className="muted">{r.country || "—"}</td>
                      <td>{badge(r.uiStatus)}</td>
                      <td>
                        <div className="riskWrap">
                          <div className="riskBar">
                            <div className="riskFill" style={{ width: `${Math.min(100, r.risk * 50)}%` }} />
                          </div>
                          <div className="muted" style={{ width: 34, textAlign: "right" }}>
                            {r.risk}
                          </div>
                        </div>
                      </td>
                      <td className="muted">{r.date}</td>
                      <td style={{ textAlign: "right" }}>
                        <button type="button" className="iconBtn" title="Mark as Match" onClick={() => markAsMatch(r)}>
                          ✓
                        </button>
                      </td>
                    </tr>
                  ))
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
                  ‹
                </button>
                <div className="pagerText">Page {pageSafe} of {totalPages}</div>
                <button className="pagerBtn" disabled={pageSafe >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))} type="button">
                  ›
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function TemplateCard(props: {
  title: string;
  desc: string;
  chips: string[];
  onCsv: () => void;
}) {
  return (
    <div className="templateCard">
      <div className="templateTop">
        <div>
          <div className="templateTitle">{props.title}</div>
          <div className="templateDesc">{props.desc}</div>
        </div>

        <button type="button" className="templateCsvBtn" onClick={props.onCsv}>
          CSV
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
function SummaryCards() {
  const [submissions] = useRecoilState(submissionsState);

  // Count “result rows” the same way your table does (SINGLE multi + BATCH items + legacy)
  const counts = useMemo(() => {
    let total = 0;
    let clear = 0;
    let potential = 0;
    let pending = 0;
    let match = 0;

    const bump = (status: "Clear" | "Potential Match" | "Pending" | "Match") => {
      total += 1;
      if (status === "Clear") clear += 1;
      if (status === "Potential Match") potential += 1;
      if (status === "Pending") pending += 1;
      if (status === "Match") match += 1;
    };

    submissions.forEach((s: any) => {
      // New SINGLE multi
      if (s.mode === "SINGLE" && s.details?.meta && s.details?.responses) {
        const meta = s.details.meta as { key: string }[];
        meta.forEach((m) => {
          const resp = s.details.responses[m.key];
          const manual = Boolean(resp?.manualMatch === true);
          const engine: any = resp ? (resp.results?.some((r: any) => r.match) ? "HIT" : "NO_HIT") : "ERROR";
          const ui = manual ? "Match" : engine === "NO_HIT" ? "Clear" : engine === "HIT" ? "Potential Match" : "Pending";
          bump(ui);
        });
        return;
      }

      // BATCH
      if (s.mode === "BATCH" && Array.isArray(s.items)) {
        s.items.forEach((it: any) => {
          const manual = Boolean(it.manualMatch === true);
          const engine: any = it.result;
          const ui = manual ? "Match" : engine === "NO_HIT" ? "Clear" : engine === "HIT" ? "Potential Match" : "Pending";
          bump(ui);
        });
        return;
      }

      // Legacy SINGLE
      if (s.mode === "SINGLE") {
        const manual = Boolean(s.manualMatch === true);
        const engine: any = s.result;
        const ui = manual ? "Match" : engine === "NO_HIT" ? "Clear" : engine === "HIT" ? "Potential Match" : "Pending";
        bump(ui);
      }
    });

    return { total, clear, potential, match, pending };
  }, [submissions]);

  return (
    <div className="summaryGrid">
      <div className="summaryCard">
        <div className="summaryLabel">TOTAL SCREENED</div>
        <div className="summaryValue">{counts.total}</div>
      </div>

      <div className="summaryCard">
        <div className="summaryLabel">CLEAR</div>
        <div className="summaryValue">{counts.clear}</div>
      </div>

      <div className="summaryCard">
        <div className="summaryLabel">POTENTIAL MATCHES</div>
        <div className="summaryValue">{counts.potential}</div>
      </div>

      <div className="summaryCard">
        <div className="summaryLabel">MATCHES</div>
        <div className="summaryValue">{counts.match}</div>
      </div>

      <div className="summaryCard">
        <div className="summaryLabel">PENDING</div>
        <div className="summaryValue">{counts.pending}</div>
      </div>
    </div>
  );
}

