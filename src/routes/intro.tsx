import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/intro")({
  component: Intro,
});

type AppRole = "Admin" | "Compliance Officer" | "Analyst" | "Viewer";

const ROLE_OPTIONS: AppRole[] = ["Admin", "Compliance Officer", "Analyst", "Viewer"];

const roleDescriptions: Record<AppRole, string> = {
  Admin: "Single, batch, daily scheduling, and User Administration access",
  "Compliance Officer": "Single and batch screening, including daily schedule enable/disable",
  Analyst: "Single and batch screening (no daily scheduling)",
  Viewer: "Single screening in mock mode only",
};

function IntroIcon({
  type,
}: {
  type: "flow" | "single" | "batch" | "daily" | "clear" | "hit" | "pending" | "match";
}) {
  if (type === "single") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
    );
  }
  if (type === "batch") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 4h16v4H4zM4 10h16v4H4zM4 16h10v4H4z" />
      </svg>
    );
  }
  if (type === "daily") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <polyline points="12 7 12 12 15 14" />
      </svg>
    );
  }
  if (type === "clear") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <polyline points="8 12 11 15 16 9" />
      </svg>
    );
  }
  if (type === "hit") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3l9 16H3z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <circle cx="12" cy="17" r="1" />
      </svg>
    );
  }
  if (type === "pending") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <line x1="12" y1="7" x2="12" y2="12" />
        <line x1="12" y1="12" x2="15" y2="14" />
      </svg>
    );
  }
  if (type === "match") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3l7 3v6c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6l7-3z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  );
}

function RoleIcon({ role }: { role: AppRole }) {
  if (role === "Admin") {
    return (
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="m12 4 2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.6-4.8 2.6.9-5.4-3.9-3.8 5.4-.8z" />
      </svg>
    );
  }
  if (role === "Compliance Officer") {
    return (
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3l7 3v6c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6l7-3z" />
      </svg>
    );
  }
  if (role === "Analyst") {
    return (
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <line x1="4" y1="20" x2="20" y2="20" />
        <line x1="7" y1="17" x2="7" y2="10" />
        <line x1="12" y1="17" x2="12" y2="6" />
        <line x1="17" y1="17" x2="17" y2="13" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="2.5" />
    </svg>
  );
}

function Intro() {
  const screeningTypes = [
    {
      key: "sanction",
      icon: "match" as const,
      name: "Sanction",
      meaning: "US sanctions list only.",
    },
    {
      key: "pep",
      icon: "single" as const,
      name: "PEP",
      meaning: "Politically Exposed Persons outside the US.",
    },
    {
      key: "ame",
      icon: "hit" as const,
      name: "AME",
      meaning: "Adverse Media and negative news coverage.",
    },
    {
      key: "global-sanction",
      icon: "batch" as const,
      name: "Global Sanction",
      meaning: "Sanctions lists published worldwide.",
    },
  ];

  return (
    <div className="page introPage">
      <section className="pageHero" aria-label="Introduction">
        <div className="pageHeroMain">
          <div className="pageHeroHead">
            <span className="pageHeroIcon" aria-hidden="true">
              <IntroIcon type="flow" />
            </span>
            <div>
              <p className="pageHeroEyebrow">Introduction</p>
              <h1 className="pageHeroTitle">Screening Platform Overview</h1>
            </div>
          </div>
          <p className="pageHeroSub">Understand screening types, workflow steps, and result statuses before running real-time or queued screening.</p>
        </div>
        <div className="pageHeroMeta" aria-hidden="true">
          <span className="pageHeroPill">4 Screening Types</span>
          <span className="pageHeroPill">Real-time + Queued</span>
          <span className="pageHeroPill">Role-based Access</span>
        </div>
      </section>

      <div className="card">
        <div className="cardHeader">
          <h2>Screening Types</h2>
        </div>
        <div className="cardBody">
          <div className="introFlowGrid">
            {screeningTypes.map((item) => (
              <div key={item.key} className="introFlowCard">
                <div className="introFlowHead">
                  <IntroIcon type={item.icon} />
                  <strong>{item.name}</strong>
                </div>
                <p>{item.meaning}</p>
              </div>
            ))}
          </div>
          <div className="muted" style={{ marginTop: 10 }}>
            Select one or more screening types at request time based on your compliance objective.
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="cardHeader">
          <h2>Role Permissions</h2>
        </div>
        <div className="cardBody">
          <div className="rolePermissionGrid">
            {ROLE_OPTIONS.map((role) => (
              <div key={role} className={`rolePermissionCard rolePermissionCard--${role.replace(/\s+/g, "").toLowerCase()}`}>
                <div className="rolePermissionHead">
                  <RoleIcon role={role} />
                  <span>{role}</span>
                </div>
                <div className="rolePermissionDesc">{roleDescriptions[role]}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="cardHeader">
          <h2>How It Works</h2>
        </div>
        <div className="cardBody">
          <div className="introFlowGrid">
            <div className="introFlowCard">
              <div className="introFlowStep">Step 1</div>
              <div className="introFlowHead">
                <IntroIcon type="single" />
                <strong>Submit Request</strong>
              </div>
              <p>Run a single entity check immediately or submit a batch file for queued processing.</p>
            </div>
            <div className="introFlowCard">
              <div className="introFlowStep">Step 2</div>
              <div className="introFlowHead">
                <IntroIcon type="batch" />
                <strong>Engine Processing</strong>
              </div>
              <p>Each selected screening type is executed as a separate screening call and results are normalized.</p>
            </div>
            <div className="introFlowCard">
              <div className="introFlowStep">Step 3</div>
              <div className="introFlowHead">
                <IntroIcon type="daily" />
                <strong>Track + Re-screen</strong>
              </div>
              <p>Monitor progress in Screening Results and optionally enable daily re-screening for supported roles.</p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid2" style={{ marginTop: 18 }}>
        <div className="card">
          <div className="cardHeader">
            <h2>Execution Modes</h2>
          </div>
          <div className="cardBody">
            <div className="introModeCard introModeCardSync">
              <div className="introModeHead">
                <IntroIcon type="single" />
                <strong>Single Screening (Real-time)</strong>
              </div>
              <p>Use for immediate, interactive decisions with direct response in the same session.</p>
            </div>
            <div className="introModeCard introModeCardAsync">
              <div className="introModeHead">
                <IntroIcon type="batch" />
                <strong>Batch Screening (Queued)</strong>
              </div>
              <p>Use for volume processing. Submission returns fast with in-progress tracking until completion.</p>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="cardHeader">
            <h2>Result Status Guide</h2>
          </div>
          <div className="cardBody">
            <div className="introStatusList">
              <div className="introStatusRow">
                <span className="introStatusIcon introStatusIconClear"><IntroIcon type="clear" /></span>
                <div><strong>Clear</strong><p>No match found for current criteria.</p></div>
              </div>
              <div className="introStatusRow">
                <span className="introStatusIcon introStatusIconHit"><IntroIcon type="hit" /></span>
                <div><strong>Potential Match</strong><p>Engine found one or more candidate hits to review.</p></div>
              </div>
              <div className="introStatusRow">
                <span className="introStatusIcon introStatusIconPending"><IntroIcon type="pending" /></span>
                <div><strong>Pending</strong><p>Processing is still running or waiting in queue.</p></div>
              </div>
              <div className="introStatusRow">
                <span className="introStatusIcon introStatusIconMatch"><IntroIcon type="match" /></span>
                <div><strong>Match</strong><p>Final reviewed match status for operational handling.</p></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="cardHeader">
          <h2>Ready To Start</h2>
        </div>
        <div className="cardBody introCtaRow">
          <p className="muted">Open the Screening tab to run single or batch workflows with role-based controls.</p>
          <Link to="/screening" className="btnPrimary">
            Go to Screening
          </Link>
        </div>
      </div>
    </div>
  );
}
