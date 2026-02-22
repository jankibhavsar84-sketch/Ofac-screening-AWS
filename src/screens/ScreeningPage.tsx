import React, { useMemo, useState } from "react";
import { z } from "zod";
import { IsoDateInput } from "../components/IsoDateInput";

type CustomerType = "Person" | "Entity";

type FormState = {
  customerType: CustomerType;

  firstName: string;
  middleName: string;
  lastName: string;

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
  dateOfBirth: string; // yyyy-mm-dd
  countryOfCitizenship: string;
};

const defaultState: FormState = {
  customerType: "Person",
  firstName: "",
  middleName: "",
  lastName: "",
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

type ApiResponse = {
  result: "HIT" | "NO_HIT";
  message?: string;
  details?: unknown;
};

const COUNTRIES = [
  "Afghanistan","Albania","Algeria","Andorra","Angola","Antigua and Barbuda","Argentina","Armenia","Australia","Austria","Azerbaijan",
  "Bahamas","Bahrain","Bangladesh","Barbados","Belarus","Belgium","Belize","Benin","Bhutan","Bolivia","Bosnia and Herzegovina","Botswana","Brazil","Brunei","Bulgaria","Burkina Faso","Burundi",
  "Cabo Verde","Cambodia","Cameroon","Canada","Central African Republic","Chad","Chile","China","Colombia","Comoros","Congo (Congo-Brazzaville)","Costa Rica","Côte d’Ivoire","Croatia","Cuba","Cyprus","Czechia",
  "Denmark","Djibouti","Dominica","Dominican Republic",
  "Ecuador","Egypt","El Salvador","Equatorial Guinea","Eritrea","Estonia","Eswatini","Ethiopia",
  "Fiji","Finland","France",
  "Gabon","Gambia","Georgia","Germany","Ghana","Greece","Grenada","Guatemala","Guinea","Guinea-Bissau","Guyana",
  "Haiti","Honduras","Hungary",
  "Iceland","India","Indonesia","Iran","Iraq","Ireland","Israel","Italy",
  "Jamaica","Japan","Jordan",
  "Kazakhstan","Kenya","Kiribati","Kuwait","Kyrgyzstan",
  "Laos","Latvia","Lebanon","Lesotho","Liberia","Libya","Liechtenstein","Lithuania","Luxembourg",
  "Madagascar","Malawi","Malaysia","Maldives","Mali","Malta","Marshall Islands","Mauritania","Mauritius","Mexico","Micronesia","Moldova","Monaco","Mongolia","Montenegro","Morocco","Mozambique","Myanmar (Burma)",
  "Namibia","Nauru","Nepal","Netherlands","New Zealand","Nicaragua","Niger","Nigeria","North Korea","North Macedonia","Norway",
  "Oman",
  "Pakistan","Palau","Panama","Papua New Guinea","Paraguay","Peru","Philippines","Poland","Portugal",
  "Qatar",
  "Romania","Russia","Rwanda",
  "Saint Kitts and Nevis","Saint Lucia","Saint Vincent and the Grenadines","Samoa","San Marino","Sao Tome and Principe","Saudi Arabia","Senegal","Serbia","Seychelles","Sierra Leone","Singapore","Slovakia","Slovenia","Solomon Islands","Somalia","South Africa","South Korea","South Sudan","Spain","Sri Lanka","Sudan","Suriname","Sweden","Switzerland","Syria",
  "Taiwan","Tajikistan","Tanzania","Thailand","Timor-Leste","Togo","Tonga","Trinidad and Tobago","Tunisia","Turkey","Turkmenistan","Tuvalu",
  "Uganda","Ukraine","United Arab Emirates","United Kingdom","United States","Uruguay","Uzbekistan",
  "Vanuatu","Vatican City","Venezuela","Vietnam",
  "Yemen",
  "Zambia","Zimbabwe"
];

function safeTrim(v: string) {
  return (v ?? "").trim();
}

function CountryInput(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  hint?: string;
  listId: string;
}) {
  return (
    <div className="field col-4">
      <div className="labelRow">
        <label>
          {props.label}
          {props.required ? <span className="req">*</span> : null}
        </label>
        <span className="hint">{props.hint ?? "Type to search"}</span>
      </div>

      {/* datalist provides auto-suggestions */}
      <input
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder ?? "Start typing..."}
        list={props.listId}
      />
    </div>
  );
}

export function ScreeningPage() {
  const [form, setForm] = useState<FormState>(defaultState);
  const [submitting, setSubmitting] = useState(false);
  const [apiResult, setApiResult] = useState<ApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isPerson = form.customerType === "Person";

  const schema = useMemo(() => {
    const base = z.object({
      customerType: z.enum(["Person", "Entity"]),
      firstName: z.string(),
      middleName: z.string(),
      lastName: z.string(),
      fullName: z.string(),
      aliasName: z.string(),

      addressLine1: z.string(),
      addressLine2: z.string(),
      city: z.string(),
      state: z.string(),
      zip: z.string(),
      country: z.string(),

      idCode: z.string(),
      idNumber: z.string(),
      idIssueCountry: z.string(),

      countryOfBirth: z.string(),
      dateOfBirth: z.string(),
      countryOfCitizenship: z.string(),
    });

    return base.superRefine((data, ctx) => {
      if (data.customerType === "Person") {
        if (!safeTrim(data.firstName)) {
          ctx.addIssue({ code: "custom", path: ["firstName"], message: "First Name is required for Person." });
        }
        if (!safeTrim(data.lastName)) {
          ctx.addIssue({ code: "custom", path: ["lastName"], message: "Last Name is required for Person." });
        }
      } else {
        if (!safeTrim(data.fullName)) {
          ctx.addIssue({ code: "custom", path: ["fullName"], message: "Full Name (Organization Name) is required for Entity." });
        }
      }
    });
  }, []);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function resetForm() {
    setError(null);
    setApiResult(null);
    setForm(defaultState);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setApiResult(null);

    const parsed = schema.safeParse(form);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Please fix the highlighted fields.");
      return;
    }

    setSubmitting(true);
    try {
      const url = import.meta.env.VITE_OFAC_API_URL as string;
      if (!url) throw new Error("Missing VITE_OFAC_API_URL in .env.local");

      const payload = {
        customerType: form.customerType,
        name:
          form.customerType === "Person"
            ? {
                firstName: safeTrim(form.firstName),
                middleName: safeTrim(form.middleName),
                lastName: safeTrim(form.lastName),
              }
            : { fullName: safeTrim(form.fullName) },
        aliasName: safeTrim(form.aliasName),
        address: {
          addressLine1: safeTrim(form.addressLine1),
          addressLine2: safeTrim(form.addressLine2),
          city: safeTrim(form.city),
          state: safeTrim(form.state),
          zip: safeTrim(form.zip),
          country: safeTrim(form.country),
        },
        id: {
          idCode: safeTrim(form.idCode),
          idNumber: safeTrim(form.idNumber),
          idIssueCountry: safeTrim(form.idIssueCountry),
        },
        demographics: {
          countryOfBirth: safeTrim(form.countryOfBirth),
          dateOfBirth: form.dateOfBirth,
          countryOfCitizenship: safeTrim(form.countryOfCitizenship),
        },
      };

      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`API error ${resp.status}: ${text}`);
      }

      const data = (await resp.json()) as ApiResponse;
      if (data.result !== "HIT" && data.result !== "NO_HIT") {
        throw new Error("Unexpected API response. Expected result: HIT or NO_HIT.");
      }

      setApiResult(data);
    } catch (err: any) {
      setError(err?.message ?? "Something went wrong calling the API.");
    } finally {
      setSubmitting(false);
    }
  }

  const countryListId = "country-list";

  return (
    <div className="workspace">
      {/* LEFT PANEL: Customer + minimum fields */}
      <form onSubmit={onSubmit} className="panel">
        <div className="panelHeader">
          <div>
            <h2>Customer Profile</h2>
            <p>Enter required name fields and optionally add alias.</p>
          </div>
          <span className="pill">Step 1</span>
        </div>

        <div className="panelBody">
          <div className="section">
            <div className="sectionTitle">
              <h3>Identity</h3>
              <span>Required fields marked *</span>
            </div>

            <div className="grid">
              <div className="field col-12">
                <div className="labelRow">
                  <label>Customer Type</label>
                  <span className="hint">Person or Entity</span>
                </div>
                <select value={form.customerType} onChange={(e) => update("customerType", e.target.value as CustomerType)}>
                  <option value="Person">Person</option>
                  <option value="Entity">Entity</option>
                </select>
              </div>

              <div className="field col-12">
                <div className="labelRow">
                  <label>Alias Name</label>
                  <span className="hint">Optional</span>
                </div>
                <input
                  value={form.aliasName}
                  onChange={(e) => update("aliasName", e.target.value)}
                  placeholder="Alternate spelling / AKA"
                />
              </div>

              {isPerson ? (
                <>
                  <div className="field col-12">
                    <div className="labelRow">
                      <label>
                        First Name <span className="req">*</span>
                      </label>
                      <span className="hint">Required</span>
                    </div>
                    <input value={form.firstName} onChange={(e) => update("firstName", e.target.value)} placeholder="First name" />
                  </div>

                  <div className="field col-12">
                    <div className="labelRow">
                      <label>Middle Name</label>
                      <span className="hint">Optional</span>
                    </div>
                    <input value={form.middleName} onChange={(e) => update("middleName", e.target.value)} placeholder="Middle name" />
                  </div>

                  <div className="field col-12">
                    <div className="labelRow">
                      <label>
                        Last Name <span className="req">*</span>
                      </label>
                      <span className="hint">Required</span>
                    </div>
                    <input value={form.lastName} onChange={(e) => update("lastName", e.target.value)} placeholder="Last name" />
                  </div>
                </>
              ) : (
                <div className="field col-12">
                  <div className="labelRow">
                    <label>
                      Full Name (Organization) <span className="req">*</span>
                    </label>
                    <span className="hint">Required</span>
                  </div>
                  <input value={form.fullName} onChange={(e) => update("fullName", e.target.value)} placeholder="Organization name" />
                </div>
              )}
            </div>
          </div>

          {error && (
            <div className="alert alertError">
              <b>Error:</b> {error}
            </div>
          )}

          <div className="actions">
            <button type="button" className="btnGhost" onClick={resetForm} disabled={submitting}>
              Clear
            </button>
            <button type="submit" className="btnPrimary" disabled={submitting}>
              {submitting ? "Screening..." : "Submit Screening"}
            </button>
          </div>
        </div>
      </form>

      {/* RIGHT PANEL: details + results */}
      <div className="panel">
        <div className="panelHeader">
          <div>
            <h2>Additional Details</h2>
            <p>Optional data that improves match quality and reduces false positives.</p>
          </div>
          <span className="pill">Step 2</span>
        </div>

        <div className="panelBody">
          {/* shared datalist for country autosuggest */}
          <datalist id={countryListId}>
            {COUNTRIES.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>

          <div className="section">
            <div className="sectionTitle">
              <h3>Address</h3>
              <span>Optional</span>
            </div>

            <div className="grid">
              <div className="field col-6">
                <label>Address Line 1</label>
                <input value={form.addressLine1} onChange={(e) => update("addressLine1", e.target.value)} />
              </div>
              <div className="field col-6">
                <label>Address Line 2</label>
                <input value={form.addressLine2} onChange={(e) => update("addressLine2", e.target.value)} />
              </div>
              <div className="field col-3">
                <label>City</label>
                <input value={form.city} onChange={(e) => update("city", e.target.value)} />
              </div>
              <div className="field col-3">
                <label>State</label>
                <input value={form.state} onChange={(e) => update("state", e.target.value)} />
              </div>
              <div className="field col-3">
                <label>Zip</label>
                <input value={form.zip} onChange={(e) => update("zip", e.target.value)} />
              </div>

              {/* Country autosuggest */}
              <CountryInput
                label="Country"
                value={form.country}
                onChange={(v) => update("country", v)}
                listId={countryListId}
                hint="Auto-suggest"
              />
            </div>
          </div>

          <div className="section">
            <div className="sectionTitle">
              <h3>Identification</h3>
              <span>Optional</span>
            </div>

            <div className="grid">
              <div className="field col-4">
                <label>ID Code</label>
                <input value={form.idCode} onChange={(e) => update("idCode", e.target.value)} />
              </div>
              <div className="field col-4">
                <label>ID Number</label>
                <input value={form.idNumber} onChange={(e) => update("idNumber", e.target.value)} />
              </div>

              {/* Country autosuggest */}
              <CountryInput
                label="ID Issue Country"
                value={form.idIssueCountry}
                onChange={(v) => update("idIssueCountry", v)}
                listId={countryListId}
                hint="Auto-suggest"
              />
            </div>
          </div>

          <div className="section">
            <div className="sectionTitle">
              <h3>Demographics</h3>
              <span>Optional</span>
            </div>

            <div className="grid">
              {/* Country autosuggest */}
              <CountryInput
                label="Country of Birth"
                value={form.countryOfBirth}
                onChange={(v) => update("countryOfBirth", v)}
                listId={countryListId}
                hint="Auto-suggest"
              />

              <div className="field col-4">
                <div className="labelRow">
                  <label>Date of Birth</label>
                  <span className="hint">Optional</span>
                </div>
                <IsoDateInput value={form.dateOfBirth} onChange={(value) => update("dateOfBirth", value)} />
              </div>

              {/* Country autosuggest */}
              <CountryInput
                label="Country of Citizenship"
                value={form.countryOfCitizenship}
                onChange={(v) => update("countryOfCitizenship", v)}
                listId={countryListId}
                hint="Auto-suggest"
              />
            </div>
          </div>

          {apiResult && (
            <div className={`alert ${apiResult.result === "HIT" ? "alertError" : "alertSuccess"}`}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                <div>
                  <b>Result:</b> {apiResult.result === "HIT" ? "HIT" : "NO HIT"}
                  {apiResult.message ? <div style={{ marginTop: 6, color: "inherit" }}>{apiResult.message}</div> : null}
                </div>
                <span
                  className={`pill ${apiResult.result === "HIT" ? "resultPillHit" : "resultPillNoHit"}`}
                >
                  {apiResult.result}
                </span>
              </div>

              {apiResult.details && <pre>{JSON.stringify(apiResult.details, null, 2)}</pre>}
            </div>
          )}

          {!apiResult && (
            <div className="alert" style={{ color: "var(--muted)" }}>
              Submit screening on the left. Results will appear here.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
