import * as React from "react";

export default function IntroPage() {
  return (
    <div className="page">
      <div className="card">
        <div className="cardHeader">
          <h1>How this application works</h1>
          <p>Prudential OFAC screening — on-demand and batch screening in one UI.</p>
        </div>

        <div className="cardBody prose">
          <ol>
            <li>
              Go to <b>Screening</b> tab.
            </li>
            <li>
              Choose <b>Customer Type</b>:
              <ul>
                <li><b>Person</b>: First Name + Last Name are required</li>
                <li><b>Entity</b>: Full Name (Organization) is required</li>
              </ul>
            </li>
            <li>
              Optional fields (DOB, citizenship, address, ID) improve match quality.
            </li>
            <li>
              For <b>Batch</b>:
              <ul>
                <li>Download the CSV/XLSX template</li>
                <li>Fill rows (required name fields)</li>
                <li>Select the file — it will <b>not</b> screen yet</li>
                <li>Click <b>Submit Screening</b> to run the batch</li>
              </ul>
            </li>
            <li>
              Results appear:
              <ul>
                <li>Immediately in the <b>Latest Screening Result</b> panel</li>
                <li>In <b>Results & Queue</b> tab (history with pagination)</li>
              </ul>
            </li>
          </ol>

          <div className="note">
            <b>Tip:</b> Citizenship / Birth / Country fields support autosuggest. You can also type ISO2 (US, IN, GB).
          </div>
        </div>
      </div>
    </div>
  );
}
