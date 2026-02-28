import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/intro")({
  component: Intro,
});

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

function Intro() {
  return (
    <div className="page introPage">
      <div className="introHero card">
        <div className="cardBody introHeroBody">
          <div className="introHeroLeft">
            <div className="introHeroIcon" aria-hidden="true">
              <IntroIcon type="flow" />
            </div>
            <div>
              <h1 className="introTitle">Watchlist Screening Overview</h1>
              <p className="introSubtitle">
                AML Screening Platform for single, batch, and daily watchlist checks with full audit visibility.
              </p>
            </div>
          </div>
          <div className="introHeroStats">
            <div className="introStat">
              <div className="introStatLabel">Design Throughput</div>
              <div className="introStatValue">32 TPS</div>
            </div>
            <div className="introStat">
              <div className="introStatLabel">Target Users</div>
              <div className="introStatValue">80</div>
            </div>
            <div className="introStat">
              <div className="introStatLabel">Parallel Sessions</div>
              <div className="introStatValue">15</div>
            </div>
          </div>
        </div>
      </div>

      <div className="card">
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
              <p>Run a single entity check immediately or submit a batch file for asynchronous processing.</p>
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
                <strong>Single Screening (Sync)</strong>
              </div>
              <p>Use for immediate, interactive decisions with direct response in the same session.</p>
            </div>
            <div className="introModeCard introModeCardAsync">
              <div className="introModeHead">
                <IntroIcon type="batch" />
                <strong>Batch Screening (Async)</strong>
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
