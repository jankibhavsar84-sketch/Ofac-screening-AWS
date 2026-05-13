import { useEffect, useMemo, useState } from "react";
import { useAuth } from "react-oidc-context";
import { buildIdentity, hasPermission } from "../auth/claims";
import {
  listDailyScheduleBatchRuns,
  listDailySchedules,
  removeDailySchedule,
  rerunDailySchedule,
  type DailySchedule,
  type DailyScheduleBatchRunStatus,
} from "../api/screeningApi";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function DailyScheduleAdminPage() {
  const auth = useAuth();
  const identity = buildIdentity(auth.user);
  const allowed = hasPermission(identity, "screening.daily", "screening.admin");
  const isAdmin = hasPermission(identity, "screening.admin");

  const [schedules, setSchedules] = useState<DailySchedule[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [batchRuns, setBatchRuns] = useState<DailyScheduleBatchRunStatus[]>([]);
  const [batchRunsLoading, setBatchRunsLoading] = useState(false);
  const [batchRunsError, setBatchRunsError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [rerunningId, setRerunningId] = useState<string | null>(null);

  async function loadSchedules() {
    setError(null);
    setLoading(true);
    try {
      const rows = await listDailySchedules();
      setSchedules(rows);
    } catch (err: any) {
      setError(err?.message ?? "Failed to load daily schedules.");
    } finally {
      setLoading(false);
    }
  }

  async function loadBatchRuns() {
    if (!isAdmin) {
      setBatchRuns([]);
      setBatchRunsError(null);
      return;
    }
    setBatchRunsError(null);
    setBatchRunsLoading(true);
    try {
      const rows = await listDailyScheduleBatchRuns(300);
      setBatchRuns(rows);
    } catch (err: any) {
      setBatchRunsError(err?.message ?? "Failed to load batch run status.");
    } finally {
      setBatchRunsLoading(false);
    }
  }

  useEffect(() => {
    if (!allowed) return;
    void loadSchedules();
    void loadBatchRuns();
  }, [allowed, isAdmin]);

  const sorted = useMemo(
    () => [...schedules].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")),
    [schedules]
  );

  const sortedBatchRuns = useMemo(
    () => [...batchRuns].sort((a, b) => (b.submitted_at || "").localeCompare(a.submitted_at || "")),
    [batchRuns]
  );

  function renderRunStatus(status: string) {
    const safe = String(status || "").trim().toUpperCase();
    if (safe === "COMPLETED") return <span className="statusPill statusClear">Completed</span>;
    if (safe === "PARTIAL") return <span className="statusPill statusPotential">Partial</span>;
    if (safe === "PROCESSING" || safe === "QUEUED") return <span className="statusPill statusPending">Processing</span>;
    if (safe === "FAILED") return <span className="statusPill statusFailed">Failed</span>;
    return <span className="statusPill statusMatch">{safe || "Unknown"}</span>;
  }

  async function refreshAll() {
    await Promise.all([loadSchedules(), loadBatchRuns()]);
  }

  async function refreshBatchRuns() {
    await loadBatchRuns();
  }

  async function removeSchedule(schedule: DailySchedule) {
    if (!identity) return;
    setRemovingId(schedule.schedule_id);
    setError(null);
    setNotice(null);
    try {
      await removeDailySchedule(schedule.schedule_id, { id: identity.id, name: identity.name });
      setSchedules((prev) => prev.filter((s) => s.schedule_id !== schedule.schedule_id));
    } catch (err: any) {
      setError(err?.message ?? "Failed to remove schedule.");
    } finally {
      setRemovingId(null);
    }
  }

  async function rerunSchedule(schedule: DailySchedule) {
    if (!identity) return;
    setRerunningId(schedule.schedule_id);
    setError(null);
    setNotice(null);
    try {
      const accepted = await rerunDailySchedule(schedule.schedule_id);
      setNotice(`Ad-hoc re-run submitted for ${schedule.batch_name}. Job ID: ${accepted.job_id}`);
      await loadSchedules();
      await loadBatchRuns();
    } catch (err: any) {
      setError(err?.message ?? "Failed to re-run daily schedule.");
    } finally {
      setRerunningId(null);
    }
  }

  if (!allowed) {
    return (
      <div className="page">
        <div className="card">
          <div className="cardHeader">
            <h2>Access Denied</h2>
          </div>
          <div className="cardBody">
            <p className="muted">Compliance/Admin access is required (`screening.daily` or `screening.admin`).</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <section className="pageHero" aria-label="Daily Schedule">
        <div className="pageHeroMain">
          <div className="pageHeroHead">
            <span className="pageHeroIcon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="18" rx="3" />
                <line x1="8" y1="2.5" x2="8" y2="6.5" />
                <line x1="16" y1="2.5" x2="16" y2="6.5" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
            </span>
            <div>
              <p className="pageHeroEyebrow">Daily Schedule</p>
              <h1 className="pageHeroTitle">Recurring Screening Administration</h1>
            </div>
          </div>
          <p className="pageHeroSub">Review active schedules, monitor next-run timing, and remove scheduled batch jobs when business changes require it.</p>
        </div>
        <div className="pageHeroMeta">
          <span className="pageHeroPill">{sorted.length} Active Schedules</span>
          <button type="button" className="btnGhost" onClick={() => void refreshAll()} disabled={loading || batchRunsLoading}>
            {loading || batchRunsLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </section>

      <div className="card">
        <div className="cardHeader">
          <h2>Configured Daily Screening Schedules</h2>
        </div>
        <div className="cardBody">
          <p className="muted" style={{ marginTop: 0 }}>
            Compliance/Admin users can remove batch files from daily screening here.
          </p>
          {notice ? <div className="successBox" role="status" aria-live="polite">{notice}</div> : null}
          {error ? <div className="errorBox" role="alert" aria-live="assertive">{error}</div> : null}

          <div className="tableWrap scheduleTableWrap" style={{ marginTop: 10 }}>
            <table className="table scheduleTable">
              <thead>
                <tr>
                  <th scope="col" style={{ width: 220 }}>Batch Name</th>
                  <th scope="col" style={{ width: 120 }}>Frequency</th>
                  <th scope="col" style={{ width: 220 }}>Screening Types</th>
                  <th scope="col" style={{ width: 220 }}>Source File</th>
                  <th scope="col" style={{ width: 150 }}>Items</th>
                  <th scope="col" style={{ width: 180 }}>Next Run</th>
                  <th scope="col" style={{ width: 180 }}>Created</th>
                  <th scope="col" style={{ width: 220, textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sorted.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="emptyRow">
                      {loading ? "Loading schedules..." : "No active daily schedules found."}
                    </td>
                  </tr>
                ) : (
                  sorted.map((row) => (
                    <tr key={row.schedule_id}>
                      <td>{row.batch_name}</td>
                      <td className="muted">{row.schedule_frequency || "DAILY"}</td>
                      <td className="muted">{row.screening_types.join(", ") || "-"}</td>
                      <td className="muted">{row.source_file_name || "-"}</td>
                      <td className="muted">{row.total_items}</td>
                      <td className="muted">{formatDateTime(row.next_run_at)}</td>
                      <td className="muted">{formatDateTime(row.created_at)}</td>
                      <td style={{ textAlign: "right" }}>
                        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
                          <button
                            type="button"
                            className="btnGhostSmall"
                            disabled={rerunningId === row.schedule_id || removingId === row.schedule_id}
                            onClick={() => void rerunSchedule(row)}
                          >
                            {rerunningId === row.schedule_id ? "Re-running..." : "Re-run"}
                          </button>
                          <button
                            type="button"
                            className="btnGhostSmall"
                            disabled={removingId === row.schedule_id || rerunningId === row.schedule_id}
                            onClick={() => void removeSchedule(row)}
                          >
                            {removingId === row.schedule_id ? "Removing..." : "Remove"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {isAdmin ? (
        <div className="card">
          <div className="cardHeader" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <h2>Batch Run Status (Admin)</h2>
            <button
              type="button"
              className="btnGhostSmall"
              onClick={() => void refreshBatchRuns()}
              disabled={batchRunsLoading}
            >
              {batchRunsLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
          <div className="cardBody">
            <p className="muted" style={{ marginTop: 0 }}>
              Recent scheduled and ad-hoc schedule runs across all users.
            </p>
            {batchRunsError ? <div className="errorBox" role="alert" aria-live="assertive">{batchRunsError}</div> : null}
            <div className="tableWrap scheduleTableWrap" style={{ marginTop: 10 }}>
              <table className="table scheduleTable" style={{ minWidth: 1650 }}>
                <thead>
                  <tr>
                    <th scope="col" style={{ width: 180 }}>Submitted</th>
                    <th scope="col" style={{ width: 210 }}>Batch Name</th>
                    <th scope="col" style={{ width: 180 }}>Schedule ID</th>
                    <th scope="col" style={{ width: 180 }}>Job ID</th>
                    <th scope="col" style={{ width: 130 }}>Run Status</th>
                    <th scope="col" style={{ width: 90 }}>Total</th>
                    <th scope="col" style={{ width: 90 }}>Completed</th>
                    <th scope="col" style={{ width: 90 }}>Failed</th>
                    <th scope="col" style={{ width: 90 }}>Pending</th>
                    <th scope="col" style={{ width: 90 }}>Processing</th>
                    <th scope="col" style={{ width: 220 }}>Source File</th>
                    <th scope="col" style={{ width: 140 }}>Frequency</th>
                    <th scope="col" style={{ width: 170 }}>Triggered By</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedBatchRuns.length === 0 ? (
                    <tr>
                      <td colSpan={13} className="emptyRow">
                        {batchRunsLoading ? "Loading batch runs..." : "No daily schedule batch runs found."}
                      </td>
                    </tr>
                  ) : (
                    sortedBatchRuns.map((run) => (
                      <tr key={`${run.job_id}:${run.schedule_id}`}>
                        <td className="muted">{formatDateTime(run.submitted_at)}</td>
                        <td>{run.batch_name || "-"}</td>
                        <td className="muted">{run.schedule_id || "-"}</td>
                        <td className="muted">{run.job_id}</td>
                        <td>{renderRunStatus(run.run_status)}</td>
                        <td className="muted">{run.total_items}</td>
                        <td className="muted">{run.completed_items}</td>
                        <td className="muted">{run.failed_items}</td>
                        <td className="muted">{run.pending_items}</td>
                        <td className="muted">{run.processing_items}</td>
                        <td className="muted">{run.source_file_name || "-"}</td>
                        <td className="muted">{run.schedule_frequency || "-"}</td>
                        <td className="muted">{run.user_name || run.user_id || "-"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
