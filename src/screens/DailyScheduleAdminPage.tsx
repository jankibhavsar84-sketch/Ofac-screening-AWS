import { useEffect, useMemo, useState } from "react";
import { useAuth } from "react-oidc-context";
import { buildIdentity, hasPermission } from "../auth/claims";
import { listDailySchedules, removeDailySchedule, type DailySchedule } from "../api/openSanctions";

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

  const [schedules, setSchedules] = useState<DailySchedule[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

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

  useEffect(() => {
    if (!allowed) return;
    void loadSchedules();
  }, [allowed]);

  const sorted = useMemo(
    () => [...schedules].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")),
    [schedules]
  );

  async function removeSchedule(schedule: DailySchedule) {
    if (!identity) return;
    setRemovingId(schedule.schedule_id);
    setError(null);
    try {
      await removeDailySchedule(schedule.schedule_id, { id: identity.id, name: identity.name });
      setSchedules((prev) => prev.filter((s) => s.schedule_id !== schedule.schedule_id));
    } catch (err: any) {
      setError(err?.message ?? "Failed to remove schedule.");
    } finally {
      setRemovingId(null);
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
      <div className="card">
        <div className="cardHeader">
          <div className="adminScheduleHeader">
            <h2>Daily Screening Schedules</h2>
            <button type="button" className="btnGhost" onClick={() => void loadSchedules()} disabled={loading}>
              {loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>
        <div className="cardBody">
          <p className="muted" style={{ marginTop: 0 }}>
            Compliance/Admin users can remove batch files from daily screening here.
          </p>
          {error ? <div className="errorBox">{error}</div> : null}

          <div className="tableWrap" style={{ marginTop: 10 }}>
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 220 }}>Batch Name</th>
                  <th style={{ width: 220 }}>Screening Types</th>
                  <th style={{ width: 150 }}>Items</th>
                  <th style={{ width: 180 }}>Next Run</th>
                  <th style={{ width: 180 }}>Created</th>
                  <th style={{ width: 140, textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sorted.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="emptyRow">
                      {loading ? "Loading schedules..." : "No active daily schedules found."}
                    </td>
                  </tr>
                ) : (
                  sorted.map((row) => (
                    <tr key={row.schedule_id}>
                      <td>{row.batch_name}</td>
                      <td className="muted">{row.screening_types.join(", ") || "-"}</td>
                      <td className="muted">{row.total_items}</td>
                      <td className="muted">{formatDateTime(row.next_run_at)}</td>
                      <td className="muted">{formatDateTime(row.created_at)}</td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className="btnGhostSmall"
                          disabled={removingId === row.schedule_id}
                          onClick={() => void removeSchedule(row)}
                        >
                          {removingId === row.schedule_id ? "Removing..." : "Remove"}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
