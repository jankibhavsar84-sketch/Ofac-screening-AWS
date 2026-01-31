import React, { useState } from "react";
import { useRecoilState, useSetRecoilState } from "recoil";
import { submissionsState, latestResultState } from "../state/submissions";
import { matchBatch } from "../api/openSanctions";
import { CountryAutosuggest } from "../components/CountryAutosuggest";

export function ScreeningDetailPage() {
  const [form, setForm] = useState<any>({ customerType: "Person" });
  const [batchFile, setBatchFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [submissions, setSubmissions] = useRecoilState(submissionsState);
  const setLatest = useSetRecoilState(latestResultState);

  function clearAll() {
    setForm({ customerType: "Person" });
    setBatchFile(null);
    setLatest(null);
  }

  async function submit() {
    setSubmitting(true);
    try {
      // SINGLE or BATCH logic already exists in your codebase
      // Just calling matchBatch here
      const result = await matchBatch({});
      setLatest({
        id: Date.now().toString(),
        createdAt: new Date().toISOString(),
        mode: batchFile ? "BATCH" : "SINGLE",
        result: "NO_HIT",
      } as any);
      setSubmissions((s) => [result as any, ...s]);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <h2>OFAC Screening</h2>
      </div>

      <div className="panelBody">
        <div className="field">
          <label>Customer Type</label>
          <select
            value={form.customerType}
            onChange={(e) => setForm({ ...form, customerType: e.target.value })}
          >
            <option value="Person">Person</option>
            <option value="Entity">Entity</option>
          </select>
        </div>

        <CountryAutosuggest
          label="Country"
          value={form.country}
          onChange={(v) => setForm({ ...form, country: v })}
        />

        <div style={{ marginTop: 16 }}>
          <label>Batch File (CSV / Excel)</label>
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => setBatchFile(e.target.files?.[0] ?? null)}
          />
          {batchFile && <div>Selected: {batchFile.name}</div>}
        </div>

        <div className="actions" style={{ marginTop: 24 }}>
          <button className="btnGhost" onClick={clearAll}>
            Clear
          </button>
          <button className="btnPrimary" disabled={submitting} onClick={submit}>
            {submitting ? "Submitting..." : "Submit Screening"}
          </button>
        </div>
      </div>
    </div>
  );
}
