import React from "react";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  component: IntroRoute,
});

function IntroRoute() {
  return (
    <div className="panel">
      <div className="panelHeader">
        <div>
          <h2>Introduction</h2>
          <p>How the Prudential OFAC Screening app works</p>
        </div>
      </div>

      <div className="panelBody" style={{ lineHeight: 1.7 }}>
        <div className="helpBox">
          <b>Overview</b>
          <ul style={{ marginTop: 10 }}>
            <li>Use <b>Screening</b> tab for on-demand (single) screening or batch upload.</li>
            <li>Single screening requires names based on customer type: <b>Person</b> (First + Last), <b>Entity</b> (Full Name).</li>
            <li>Batch screening uses CSV/XLSX template; upload the file, then click <b>Submit Screening</b>.</li>
            <li>Results classify as <b>HIT</b> or <b>NO_HIT</b>. History is stored locally and visible in <b>Results & Queue</b>.</li>
          </ul>
        </div>

        <div style={{ marginTop: 14 }} className="helpBox">
          <b>Notes</b>
          <ul style={{ marginTop: 10 }}>
            <li>Country fields support autosuggest and store ISO2 codes (US, IN, GB).</li>
            <li>Date of Birth is validated (YYYY-MM-DD, not future, not older than 100 years).</li>
            <li>This UI is a screening console; production use usually adds server-side audit logging.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
