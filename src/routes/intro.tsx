import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/intro")({
  component: Intro,
});

function Intro() {
  return (
    <div className="page">
      <div className="card">
        <div className="cardHeader">
          <h2>How this application works</h2>
        </div>
        <div className="cardBody">
          <ol className="introList">
            <li><b>Single Screening</b>: add one or more entities and run screening.</li>
            <li><b>Batch Screening</b>: upload CSV/XLSX and screen all rows in one run.</li>
            <li>Results show <b>Clear</b>, <b>Potential Match</b>, <b>Pending</b>, or <b>Match</b> (manual).</li>
          </ol>

          <div style={{ marginTop: 16 }}>
            <Link to="/screening" className="btnPrimary">
              Go to Screening
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
