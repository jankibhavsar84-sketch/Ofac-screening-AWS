import React, { useMemo, useState } from "react";
import * as XLSX from "xlsx";
import { Link } from "@tanstack/react-router";
import { useRecoilState, useSetRecoilState } from "recoil";
import { z } from "zod";
import { latestResultState, submissionsState, type BatchSubmission, type SingleSubmission } from "../state/submissions";
import { parseCsv, parseExcel, type BatchRow } from "../utils/batchParse";
import { matchBatch, type EntityExample } from "../api/openSanctions";
import { CountryAutosuggest } from "../components/CountryAutosuggest";

type CustomerType = "Person" | "Entity";

type FormState = {
  customerType: CustomerType;
  firstName: string;
  lastName: string;
  middleName: string;
  fullName: string;
  aliasName: string;

  addressLine1: string;
  addressLine2: string;
  city: string;
  state: string;
  zip: string;
  country: string;

  idCode: string;
  idNumber: string;
  idIssueCountry: string;

  countryOfBirth: string;
  dateOfBirth: string;
  countryOfCitizenship: string;
};

const defaultState: FormState = {
  customerType: "Person",
  firstName: "",
  lastName: "",
  middleName: "",
  fullName: "",
  aliasName: "",
  addressLine1: "",
  addressLine2: "",
  city: "",
  state: "",
  zip: "",
  country: "",
  idCode: "",
  idNumber: "",
  idIssueCountry: "",
  countryOfBirth: "",
  dateOfBirth: "",
  countryOfCitizenship: "",
};

function safeTrim(v: string) {
  return (v ?? "").trim();
}

function parseISODate(s: string): Date | null {
  const v = safeTrim(s);
  if (!v) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;

  const d = new Date(v + "T00:00:00");
  if (Number.isNaN(d.getTime())) return null;

  // ensure it matches exactly (prevents 2024-02-31 rolling)
  const [yy, mm, dd] = v.split("-").map(Number);
  if (d.getUTCFullYear() !== yy || d.getUTCMonth() + 1 !== mm || d.getUTCDate() !== dd) return null;

  return d;
}

function uuid() {
  return crypto?.randomUUID?.() ?? `${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
function displayNameFor(form: { customerType: CustomerType; firstName: string; lastName: string; fullName: string }) {
  return form.customerType === "Person"
    ? [safeTrim(form.firstName), safeTrim(form.lastName)].filter(Boolean).join(" ")
    : safeTrim(form.fullName);
}

/**
 * OpenSanctions examples show nationality like "us" and datasets like "us_ofac_sdn". :contentReference[oaicite:4]{index=4}
 * If you pass full country names, matching may be weaker.
 * Best practice: use ISO-2 codes (US, IN, AE, etc). You can enter those in the UI.
 */
function toCountryCode(input: string) {
  const v = safeTrim(input).toLowerCase();
  if (!v) return "";
  // Accept already-typed ISO2
  if (v.length === 2) return v;
  // Minimal helpful map (you can extend later)
  const map: Record<string, string> = {
    "united states": "us",
    usa: "us",
    america: "us",
    india: "in",
    "united kingdom": "gb",
    uk: "gb",
    canada: "ca",
  };
  return map[v] ?? v; // fallback
}

function buildEntityExampleFromForm(form: FormState): EntityExample {
  if (form.customerType === "Person") {
    const name = [safeTrim(form.firstName), safeTrim(form.middleName), safeTrim(form.lastName)].filter(Boolean).join(" ");
    const props: Record<string, any> = {
      name: [name],
    };

    if (safeTrim(form.aliasName)) props.alias = [safeTrim(form.aliasName)];
    if (safeTrim(form.dateOfBirth)) props.birthDate = [safeTrim(form.dateOfBirth)];
    if (safeTrim(form.countryOfCitizenship)) props.nationality = [toCountryCode(form.countryOfCitizenship)];
    if (safeTrim(form.idNumber)) props.idNumber = [safeTrim(form.idNumber)];

    const addressBits = [form.addressLine1, form.addressLine2, form.city, form.state, form.zip, form.country]
      .map(safeTrim)
      .filter(Boolean)
      .join(", ");
    if (addressBits) props.address = [addressBits];

    return { schema: "Person", properties: props };
  }

  // Entity
  const props: Record<string, any> = { name: [safeTrim(form.fullName)] };
  if (safeTrim(form.aliasName)) props.alias = [safeTrim(form.aliasName)];
  if (safeTrim(form.country)) props.country = [toCountryCode(form.country)];
  if (safeTrim(form.idNumber)) props.registrationNumber = [safeTrim(form.idNumber)];
  const addressBits = [form.addressLine1, form.addressLine2, form.city, form.state, form.zip, form.country]
    .map(safeTrim)
    .filter(Boolean)
    .join(", ");
  if (addressBits) props.address = [addressBits];

  return { schema: "Company", properties: props };
}

function buildEntityExampleFromBatchRow(r: BatchRow & Partial<FormState>): EntityExample {
  if (r.customerType === "Person") {
    const name = [safeTrim(r.firstName || ""), safeTrim(r.middleName || ""), safeTrim(r.lastName || "")].filter(Boolean).join(" ");
    const props: Record<string, any> = { name: [name] };
    if (safeTrim(r.aliasName || "")) props.alias = [safeTrim(r.aliasName || "")];
    if (safeTrim((r as any).dateOfBirth || r.dateOfBirth || "")) props.birthDate = [safeTrim((r as any).dateOfBirth || r.dateOfBirth || "")];
    if (safeTrim((r as any).countryOfCitizenship || r.countryOfCitizenship || "")) props.nationality = [toCountryCode(safeTrim((r as any).countryOfCitizenship || r.countryOfCitizenship || ""))];
    if (safeTrim((r as any).idNumber || "")) props.idNumber = [safeTrim((r as any).idNumber || "")];

    const addressBits = [(r as any).addressLine1, (r as any).addressLine2, (r as any).city, (r as any).state, (r as any).zip, (r as any).country]
      .map(safeTrim)
      .filter(Boolean)
      .join(", ");
    if (addressBits) props.address = [addressBits];

    return { schema: "Person", properties: props };
  }

  const props: Record<string, any> = { name: [safeTrim((r as any).fullName || r.fullName || "")] };
  if (safeTrim((r as any).aliasName || "")) props.alias = [safeTrim((r as any).aliasName || "")];
  if (safeTrim((r as any).country || "")) props.country = [toCountryCode(safeTrim((r as any).country || ""))];
  if (safeTrim((r as any).idNumber || "")) props.registrationNumber = [safeTrim((r as any).idNumber || "")];

  const addressBits = [(r as any).addressLine1, (r as any).addressLine2, (r as any).city, (r as any).state, (r as any).zip, (r as any).country]
    .map(safeTrim)
    .filter(Boolean)
    .join(", ");
  if (addressBits) props.address = [addressBits];

  return { schema: "Company", properties: props };
}

function classifyHit(results: { match: boolean }[]) {
  // ScoredEntityResponse has boolean "match" in the spec. :contentReference[oaicite:5]{index=5}
  return results?.some((r) => r.match) ? "HIT" : "NO_HIT";
}

export function ScreeningDetailPage() {
  const [form, setForm] = useState<FormState>(defaultState);
  const [submissions, setSubmissions] = useRecoilState(submissionsState);
  const setLatest = useSetRecoilState(latestResultState);

  const [error, setError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [batchSubmitting, setBatchSubmitting] = useState(false);

  const isPerson = form.customerType === "Person";

  const schema = useMemo(() => {
    const base = z.object({
      customerType: z.enum(["Person", "Entity"]),
      firstName: z.string(),
      lastName: z.string(),
      fullName: z.string(),
      dateOfBirth: z.string(), // ✅ add
    });
    return base.superRefine((data, ctx) => {
      if (data.customerType === "Person") {
        if (!safeTrim(data.firstName)) ctx.addIssue({ code: "custom", path: ["firstName"], message: "First Name is required for Person." });
        if (!safeTrim(data.lastName)) ctx.addIssue({ code: "custom", path: ["lastName"], message: "Last Name is required for Person." });
      } else {
        if (!safeTrim(data.fullName)) ctx.addIssue({ code: "custom", path: ["fullName"], message: "Full Name (Organization) is required for Entity." });
      }
      const dob = safeTrim((data as any).dateOfBirth ?? "");
      if (dob) {
        const d = parseISODate(dob);
        if (!d) {
          ctx.addIssue({ code: "custom", path: ["dateOfBirth"], message: "DOB must be a valid date in YYYY-MM-DD format." });
        } else {
          const now = new Date();
          const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
          if (d > today) {
            ctx.addIssue({ code: "custom", path: ["dateOfBirth"], message: "DOB cannot be a future date." });
          }
          const oldest = new Date(today);
          oldest.setFullYear(oldest.getFullYear() - 100);
          if (d < oldest) {
            ctx.addIssue({ code: "custom", path: ["dateOfBirth"], message: "DOB cannot be more than 100 years old." });
          }
        }
      }  
    });
  }, []);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((p) => ({ ...p, [key]: value }));
  }

  function downloadCsvTemplate() {
    const headers = [
      "customerType",
      "firstName",
      "middleName",
      "lastName",
      "fullName",
      "aliasName",
      "addressLine1",
      "addressLine2",
      "city",
      "state",
      "zip",
      "country",
      "idCode",
      "idNumber",
      "idIssueCountry",
      "countryOfBirth",
      "dateOfBirth",
      "countryOfCitizenship",
    ];

    const sample = [
      [
        "Person",
        "John",
        "",
        "Doe",
        "",
        "Johnny",
        "123 Main St",
        "",
        "New York",
        "NY",
        "10001",
        "US",
        "SSN",
        "123-45-6789",
        "US",
        "US",
        "1980-01-01",
        "US",
      ],
      [
        "Entity",
        "",
        "",
        "",
        "ACME Holdings LLC",
        "",
        "200 Business Rd",
        "Suite 10",
        "Newark",
        "NJ",
        "07102",
        "US",
        "EIN",
        "12-3456789",
        "US",
        "",
        "",
        "US",
      ],
    ];

    const lines = [headers.join(","), ...sample.map((r) => r.map(csvEscape).join(","))].join("\n");
    downloadBlob(new Blob([lines], { type: "text/csv;charset=utf-8" }), "tapan_ofac_template.csv");
  }

  function downloadExcelTemplate() {
    const rows = [
      {
        customerType: "Person",
        firstName: "John",
        middleName: "",
        lastName: "Doe",
        fullName: "",
        aliasName: "Johnny",
        addressLine1: "123 Main St",
        addressLine2: "",
        city: "New York",
        state: "NY",
        zip: "10001",
        country: "US",
        idCode: "SSN",
        idNumber: "123-45-6789",
        idIssueCountry: "US",
        countryOfBirth: "US",
        dateOfBirth: "1980-01-01",
        countryOfCitizenship: "US",
      },
      {
        customerType: "Entity",
        firstName: "",
        middleName: "",
        lastName: "",
        fullName: "ACME Holdings LLC",
        aliasName: "",
        addressLine1: "200 Business Rd",
        addressLine2: "Suite 10",
        city: "Newark",
        state: "NJ",
        zip: "07102",
        country: "US",
        idCode: "EIN",
        idNumber: "12-3456789",
        idIssueCountry: "US",
        countryOfBirth: "",
        dateOfBirth: "",
        countryOfCitizenship: "US",
      },
    ];

    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Template");
    const out = XLSX.write(wb, { type: "array", bookType: "xlsx" });

    downloadBlob(new Blob([out], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), "tapan_ofac_template.xlsx");
  }

  async function onSubmitSingle(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const parsed = schema.safeParse(form);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Fix validation errors.");
      return;
    }

    setSubmitting(true);
    try {
      const key = "single";
      const example = buildEntityExampleFromForm(form);

      // One query in the batch request.
      // Request format is "queries": { "entity1": { schema, properties } } :contentReference[oaicite:6]{index=6}
      const resp = await matchBatch({ [key]: example });
      const matches = resp.responses[key];
      const result = classifyHit(matches?.results ?? []);

      const entry: SingleSubmission = {
        id: uuid(),
        createdAt: new Date().toISOString(),
        mode: "SINGLE",
        customerType: form.customerType,
        displayName: displayNameFor(form),
        result,
        message: matches?.results?.[0]?.caption ? `Top match: ${matches.results[0].caption}` : undefined,
        details: matches,
      };

      const next = [entry, ...submissions].slice(0, 200);
      setSubmissions(next);
      setLatest(entry);
    } catch (err: any) {
      setError(err?.message ?? "Failed to screen.");
      const entry: SingleSubmission = {
        id: uuid(),
        createdAt: new Date().toISOString(),
        mode: "SINGLE",
        customerType: form.customerType,
        displayName: displayNameFor(form) || "(Unknown)",
        result: "ERROR",
        message: err?.message ?? "ERROR",
      };
      const next = [entry, ...submissions].slice(0, 200);
      setSubmissions(next);
      setLatest(entry);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleBatchFile(file: File) {
    setFileError(null);
    setBatchSubmitting(true);

    try {
      const name = file.name.toLowerCase();
      let rows: any[] = [];

      if (name.endsWith(".csv")) rows = await parseCsv(file);
      else if (name.endsWith(".xlsx") || name.endsWith(".xls")) rows = await parseExcel(file);
      else throw new Error("Only CSV or Excel files are allowed.");

      if (rows.length === 0) throw new Error("No rows found in the file.");

      // Build queries map (ONE API CALL)
      const queries: Record<string, EntityExample> = {};
      const rowMeta: { key: string; displayName: string; customerType: CustomerType }[] = [];

      rows.forEach((r, idx) => {
        const customerType = r.customerType === "Entity" ? "Entity" : "Person";

        const display =
          customerType === "Person"
            ? [safeTrim(r.firstName || ""), safeTrim(r.lastName || "")].filter(Boolean).join(" ")
            : safeTrim(r.fullName || "");

        const key = `row_${idx + 1}`;
        rowMeta.push({ key, displayName: display || `(Row ${idx + 1})`, customerType });

        // validate name requirements
        if (customerType === "Person" && (!safeTrim(r.firstName || "") || !safeTrim(r.lastName || ""))) return;
        if (customerType === "Entity" && !safeTrim(r.fullName || "")) return;

        queries[key] = buildEntityExampleFromBatchRow(r);
      });

      if (Object.keys(queries).length === 0) throw new Error("All rows are invalid (missing required names).");

      const resp = await matchBatch(queries);

      const items: BatchSubmission["items"] = rowMeta.map((m) => {
        const matches = resp.responses[m.key];
        if (!matches) {
          return { customerType: m.customerType, displayName: m.displayName, result: "ERROR", message: "Invalid row (missing required name)" };
        }
        const result = classifyHit(matches.results ?? []);
        return {
          customerType: m.customerType,
          displayName: m.displayName,
          result,
          message: matches?.results?.[0]?.caption ? `Top match: ${matches.results[0].caption}` : undefined,
          details: matches,
        };
      });

      const overall: BatchSubmission["overallResult"] =
        items.some((i) => i.result === "HIT") ? "HIT" : items.some((i) => i.result === "ERROR") ? "ERROR" : "NO_HIT";

      const entry: BatchSubmission = {
        id: uuid(),
        createdAt: new Date().toISOString(),
        mode: "BATCH",
        fileName: file.name,
        overallResult: overall,
        items,
      };

      const next = [entry, ...submissions].slice(0, 200);
      setSubmissions(next);
      setLatest(entry);
    } catch (err: any) {
      setFileError(err?.message ?? "Batch processing failed.");
    } finally {
      setBatchSubmitting(false);
    }
  }

  return (
    <div className="workspace">
      {/* LEFT: form + batch + templates */}
      <form onSubmit={onSubmitSingle} className="panel">
        <div className="panelHeader">
          <div>
            <h2>OFAC Screening Detail</h2>
            <p>Single customer screening or batch upload (CSV/XLSX).</p>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <Link to="/results" className="pill">
              View Results
            </Link>
          </div>
        </div>

        <div className="panelBody">
          {/* Customer section */}
          <div className="section">
            <div className="sectionTitle">
              <h3>Customer</h3>
              <span>Names required by type</span>
            </div>

            <div className="grid">
              <div className="field col-12">
                <div className="labelRow">
                  <label>Customer Type</label>
                  <span className="hint">Person / Entity</span>
                </div>
                <select value={form.customerType} onChange={(e) => update("customerType", e.target.value as CustomerType)}>
                  <option value="Person">Person</option>
                  <option value="Entity">Entity</option>
                </select>
              </div>

              {isPerson ? (
                <>
                  <div className="field col-6">
                    <div className="labelRow">
                      <label>
                        First Name <span className="req">*</span>
                      </label>
                    </div>
                    <input value={form.firstName} onChange={(e) => update("firstName", e.target.value)} placeholder="First name" />
                  </div>

                  <div className="field col-6">
                    <div className="labelRow">
                      <label>
                        Last Name <span className="req">*</span>
                      </label>
                    </div>
                    <input value={form.lastName} onChange={(e) => update("lastName", e.target.value)} placeholder="Last name" />
                  </div>

                  <div className="field col-12">
                    <div className="labelRow">
                      <label>Middle Name</label>
                      <span className="hint">Optional</span>
                    </div>
                    <input value={form.middleName} onChange={(e) => update("middleName", e.target.value)} placeholder="Middle name" />
                  </div>
                </>
              ) : (
                <div className="field col-12">
                  <div className="labelRow">
                    <label>
                      Full Name (Organization) <span className="req">*</span>
                    </label>
                  </div>
                  <input value={form.fullName} onChange={(e) => update("fullName", e.target.value)} placeholder="Organization name" />
                </div>
              )}

              <div className="field col-12">
                <div className="labelRow">
                  <label>Alias Name</label>
                  <span className="hint">Optional</span>
                </div>
                <input value={form.aliasName} onChange={(e) => update("aliasName", e.target.value)} placeholder="AKA / alternate spelling" />
              </div>
            </div>
          </div>

          {/* Demographics */}
          <div className="section">
            <div className="sectionTitle">
              <h3>Demographics</h3>
              <span>Improves match quality</span>
            </div>

            <div className="grid">
              <div className="field col-6">
                <div className="labelRow">
                  <label>Date of Birth</label>
                  <span className="hint">YYYY-MM-DD</span>
                </div>
                <input value={form.dateOfBirth} onChange={(e) => update("dateOfBirth", e.target.value)} placeholder="1980-01-01" />
              </div>

              <CountryAutosuggest
                label="Country of Citizenship"
                value={form.countryOfCitizenship}
                onChange={(v) => update("countryOfCitizenship", v)}
                hint="Type country name or ISO2 (US, IN)"
              />


              <CountryAutosuggest
                label="Country of Birth"
                value={form.countryOfBirth}
                onChange={(v) => update("countryOfBirth", v)}
                hint="Type country name or ISO2"
              />


            </div>
          </div>

          {/* Address + ID */}
          <div className="section">
            <div className="sectionTitle">
              <h3>Address & ID</h3>
              <span>Optional</span>
            </div>

            <div className="grid">
              <div className="field col-12">
                <label>Address Line 1</label>
                <input value={form.addressLine1} onChange={(e) => update("addressLine1", e.target.value)} />
              </div>
              <div className="field col-12">
                <label>Address Line 2</label>
                <input value={form.addressLine2} onChange={(e) => update("addressLine2", e.target.value)} />
              </div>
              <div className="field col-4">
                <label>City</label>
                <input value={form.city} onChange={(e) => update("city", e.target.value)} />
              </div>
              <div className="field col-4">
                <label>State</label>
                <input value={form.state} onChange={(e) => update("state", e.target.value)} />
              </div>
              <div className="field col-4">
                <label>Zip</label>
                <input value={form.zip} onChange={(e) => update("zip", e.target.value)} />
              </div>
              <CountryAutosuggest
                label="Country"
                value={form.country}
                onChange={(v) => update("country", v)}
                hint="Type country name or ISO2"
              />

              <div className="field col-4">
                <label>ID Code</label>
                <input value={form.idCode} onChange={(e) => update("idCode", e.target.value)} placeholder="SSN / EIN / Passport" />
              </div>
              <div className="field col-4">
                <label>ID Number</label>
                <input value={form.idNumber} onChange={(e) => update("idNumber", e.target.value)} />
              </div>
              <div className="field col-4">
                <label>ID Issue Country</label>
                <input value={form.idIssueCountry} onChange={(e) => update("idIssueCountry", e.target.value)} placeholder="US" />
              </div>
            </div>
          </div>

          {/* Batch upload + templates */}
          <div className="section">
            <div className="sectionTitle">
              <h3>Batch Processing</h3>
              <span>CSV / Excel</span>
            </div>

            <div className="grid">
              <div className="field col-12">
                <div className="labelRow">
                  <label>Upload File</label>
                  <span className="hint">Allowed: .csv, .xlsx, .xls</span>
                </div>
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void handleBatchFile(f);
                    e.currentTarget.value = "";
                  }}
                />
                {fileError && (
                  <div className="alert alertError">
                    <b>Batch Error:</b> {fileError}
                  </div>
                )}
                {batchSubmitting && <div className="alert">Processing batch (single API call)…</div>}
              </div>

              <div className="field col-12">
                <div className="labelRow">
                  <label>Template</label>
                  <span className="hint">Download and fill required name fields</span>
                </div>

                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button type="button" className="btnGhost" onClick={downloadCsvTemplate}>
                    Download CSV Template
                  </button>
                  <button type="button" className="btnGhost" onClick={downloadExcelTemplate}>
                    Download Excel Template
                  </button>
                </div>

                <div className="helpBox" style={{ marginTop: 12 }}>
                  <b>How to use the template</b>
                  <ul style={{ marginTop: 8, lineHeight: 1.6 }}>
                    <li><b>Person</b>: set <code>customerType</code>=Person and fill <code>firstName</code> + <code>lastName</code></li>
                    <li><b>Entity</b>: set <code>customerType</code>=Entity and fill <code>fullName</code></li>
                    <li>Best results: use ISO2 for <code>country</code> / <code>countryOfCitizenship</code> (US, IN, GB)</li>
                    <li>Save as CSV or XLSX and upload</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>

          {error && (
            <div className="alert alertError">
              <b>Error:</b> {error}
            </div>
          )}

          <div className="actions">
            <button type="button" className="btnGhost" onClick={() => setForm(defaultState)} disabled={submitting || batchSubmitting}>
              Clear
            </button>
            <button type="submit" className="btnPrimary" disabled={submitting || batchSubmitting}>
              {submitting ? "Submitting..." : "Submit Screening"}
            </button>
          </div>
        </div>
      </form>

      {/* RIGHT: Latest result panel */}
      <LatestResultPanel />
    </div>
  );
}

function LatestResultPanel() {
  const [latest] = useRecoilState(latestResultState);

  return (
    <div className="panel">
      <div className="panelHeader">
        <div>
          <h2>Latest Screening Result</h2>
          <p>Most recent single/batch submission.</p>
        </div>
        <span className="pill">Tapan Inc.</span>
      </div>

      <div className="panelBody">
        {!latest && <div className="alert" style={{ color: "var(--muted)" }}>No results yet. Submit a screening or upload a file.</div>}

        {latest && latest.mode === "SINGLE" && (
          <div className={`alert ${latest.result === "HIT" ? "alertError" : latest.result === "NO_HIT" ? "alertSuccess" : "alertError"}`}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
              <div>
                <b>{latest.displayName}</b>
                <div style={{ marginTop: 6, opacity: 0.9 }}>
                  Result: <b>{latest.result}</b>
                  {latest.message ? <div style={{ marginTop: 6 }}>{latest.message}</div> : null}
                </div>
              </div>
              <span className={`pill ${latest.result === "HIT" ? "resultPillHit" : "resultPillNoHit"}`}>{latest.result}</span>
            </div>
            {latest.message ? <div className="wrapText" style={{ marginTop: 6 }}>{latest.message}</div> : null}
          </div>
        )}

        {latest && latest.mode === "BATCH" && (
          <div className={`alert ${latest.overallResult === "HIT" ? "alertError" : latest.overallResult === "NO_HIT" ? "alertSuccess" : "alertError"}`}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
              <div>
                <b>Batch: {latest.fileName}</b>
                <div style={{ marginTop: 6 }}>
                  Overall Result: <b>{latest.overallResult}</b> • Items: <b>{latest.items.length}</b>
                </div>
              </div>
              <span className={`pill ${latest.overallResult === "HIT" ? "resultPillHit" : "resultPillNoHit"}`}>{latest.overallResult}</span>
            </div>

            <div style={{ marginTop: 12 }}>
              {latest.items.slice(0, 50).map((it, idx) => (
                <div key={idx} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid rgba(148,163,184,.12)" }}>
                  <span>{it.displayName}</span>
                  <span>{it.result}</span>
                </div>
              ))}
              {latest.items.length > 50 && <div style={{ marginTop: 10, color: "var(--muted)" }}>Showing first 50. View full history on Results page.</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function csvEscape(v: any) {
  const s = String(v ?? "");
  if (/[,"\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
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
