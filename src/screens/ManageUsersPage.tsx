import { useEffect, useMemo, useState } from "react";
import { useAuth } from "react-oidc-context";
import { buildIdentity, hasPermission } from "../auth/claims";
import { listAuditEvents, type AuditEvent } from "../api/openSanctions";
import type { UserRole } from "../state/users";

const ROLE_OPTIONS: UserRole[] = ["Admin", "Compliance Officer", "Analyst", "Viewer"];

const roleDescriptions: Record<UserRole, string> = {
  Admin: "Single, batch, daily scheduling, and User Administration access",
  "Compliance Officer": "Single and batch screening, including daily schedule enable/disable",
  Analyst: "Single and batch screening (no daily scheduling)",
  Viewer: "Single screening in mock mode only",
};

type AuditUserOption = {
  userId: string;
  displayName: string;
};

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || "").trim()).filter(Boolean);
}

function toTitleCaseWords(input: string): string {
  const normalized = input.replace(/[_-]+/g, " ").trim();
  if (!normalized) return "";
  return normalized
    .split(/\s+/g)
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1).toLowerCase() : ""))
    .join(" ");
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function readErrorFromDetails(details: Record<string, unknown> | undefined): string {
  if (!details) return "";
  const candidates = [details.error, details.error_text, details.message, details.detail];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  return "";
}

function isTechnicalIdentifier(value: string): boolean {
  const raw = value.trim();
  if (!raw) return true;
  if (/^\d+$/.test(raw)) return true;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(raw)) return true;
  return false;
}

function resolveAuditUserName(event: AuditEvent): string {
  const details = (event.details as Record<string, unknown> | undefined) || undefined;
  const candidates = [
    readString(event.user_name),
    readString(event.user_id).includes("@") ? readString(event.user_id) : "",
    readString(details?.user_email),
    readString(details?.user_name),
    readString(details?.disabled_by),
    readString(details?.actor_name),
  ];
  for (const candidate of candidates) {
    if (candidate && !isTechnicalIdentifier(candidate)) return candidate;
  }
  for (const candidate of candidates) {
    if (candidate) return candidate;
  }
  return readString(event.user_id) || "-";
}

function formatActionLabel(action: string): string {
  const normalized = readString(action);
  return normalized ? toTitleCaseWords(normalized) : "-";
}

function shortId(value: string): string {
  const trimmed = readString(value);
  if (!trimmed) return "";
  if (trimmed.length <= 12) return trimmed;
  return `${trimmed.slice(0, 8)}...`;
}

function resolveEntityLabel(event: AuditEvent): string {
  const details = (event.details as Record<string, unknown> | undefined) || undefined;
  const entityType = readString(event.entity_type).toLowerCase();
  const entityId = readString(event.entity_id);
  const action = readString(event.action).toUpperCase();

  if (entityType === "screening_job" || action.includes("SCREENING_JOB")) {
    const batchName = readString(details?.batch_name);
    const totalItemsRaw = Number(details?.total_items);
    const screeningTypes = toStringArray(details?.screening_types);
    const base = batchName ? `Batch "${batchName}"` : "Batch screening job";
    const parts: string[] = [];
    if (Number.isFinite(totalItemsRaw) && totalItemsRaw > 0) parts.push(`${totalItemsRaw} items`);
    if (screeningTypes.length) parts.push(screeningTypes.join(", "));
    if (entityId) parts.push(`job ${shortId(entityId)}`);
    return parts.length ? `${base} (${parts.join(" | ")})` : base;
  }

  if (entityType === "sync_screening") {
    const totalItemsRaw = Number(details?.total_items);
    const screeningTypes = toStringArray(details?.screening_types);
    const parts: string[] = [];
    if (Number.isFinite(totalItemsRaw) && totalItemsRaw > 0) parts.push(`${totalItemsRaw} item${totalItemsRaw > 1 ? "s" : ""}`);
    if (screeningTypes.length) parts.push(screeningTypes.join(", "));
    return parts.length ? `Single screening (${parts.join(" | ")})` : "Single screening";
  }

  if (entityType === "screening_item") {
    const itemKey = readString(details?.item_key) || (entityId.includes(":") ? entityId.split(":")[1] : "");
    const jobId = readString(details?.job_id) || (entityId.includes(":") ? entityId.split(":")[0] : "");
    const base = itemKey ? `Batch item ${itemKey}` : "Batch item";
    return jobId ? `${base} (job ${shortId(jobId)})` : base;
  }

  if (entityType === "sync_screening_item") {
    const itemKey = readString(details?.item_key) || entityId;
    return itemKey ? `Single screening item ${itemKey}` : "Single screening item";
  }

  if (entityType === "daily_schedule") {
    const batchName = readString(details?.batch_name);
    const base = batchName ? `Daily schedule "${batchName}"` : "Daily schedule";
    return entityId ? `${base} (${shortId(entityId)})` : base;
  }

  const fallbackType = entityType ? toTitleCaseWords(entityType) : toTitleCaseWords(action);
  if (fallbackType && entityId) return `${fallbackType} (${entityId})`;
  if (fallbackType) return fallbackType;
  if (entityId) return entityId;
  return "-";
}

function SectionIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3l7 3v6c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6l7-3z" />
    </svg>
  );
}

function RoleIcon({ role }: { role: UserRole }) {
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

export function ManageUsersPage() {
  const auth = useAuth();
  const identity = buildIdentity(auth.user);
  const allowed = hasPermission(identity, "screening.admin", "screening.useradmin");
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditUserFilter, setAuditUserFilter] = useState("all");
  const [auditErrorsOnly, setAuditErrorsOnly] = useState(false);
  const [auditUserOptions, setAuditUserOptions] = useState<AuditUserOption[]>([]);

  const sortedAuditUserOptions = useMemo(
    () => [...auditUserOptions].sort((a, b) => a.displayName.localeCompare(b.displayName)),
    [auditUserOptions]
  );
  const auditUserNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const option of auditUserOptions) {
      const id = option.userId.trim();
      const name = option.displayName.trim();
      if (!id || !name) continue;
      if (!map.has(id) || isTechnicalIdentifier(map.get(id) || "")) {
        map.set(id, name);
      }
    }
    return map;
  }, [auditUserOptions]);

  async function loadAuditEvents(userId?: string) {
    setAuditError(null);
    setAuditLoading(true);
    try {
      const rows = await listAuditEvents(500, userId);
      setAuditEvents(rows);
      setAuditUserOptions((prev) => {
        const merged = new Map<string, string>(prev.map((item) => [item.userId, item.displayName]));
        for (const row of rows) {
          const rowUserId = readString(row.user_id);
          if (!rowUserId) continue;
          const resolvedName = resolveAuditUserName(row);
          const existing = merged.get(rowUserId);
          if (!existing || existing === rowUserId) {
            merged.set(rowUserId, resolvedName || rowUserId);
          }
        }
        if (identity?.id) {
          const id = identity.id.trim();
          if (id && !merged.has(id)) {
            merged.set(id, (identity.name || identity.email || identity.id).trim());
          }
        }
        return Array.from(merged.entries()).map(([userIdValue, displayName]) => ({
          userId: userIdValue,
          displayName: displayName || userIdValue,
        }));
      });
    } catch (err: any) {
      setAuditError(err?.message ?? "Failed to load audit events.");
    } finally {
      setAuditLoading(false);
    }
  }

  useEffect(() => {
    if (!allowed) return;
    const userId = auditUserFilter === "all" ? undefined : auditUserFilter;
    void loadAuditEvents(userId);
  }, [allowed, auditUserFilter]);

  const filteredAuditEvents = useMemo(() => {
    if (!auditErrorsOnly) return auditEvents;
    return auditEvents.filter((event) => {
      const action = (event.action || "").toUpperCase();
      const details = event.details as Record<string, unknown> | undefined;
      return action.includes("FAILED") || Boolean(readErrorFromDetails(details));
    });
  }, [auditEvents, auditErrorsOnly]);

  if (!allowed) {
    return (
      <div className="page">
        <div className="card">
          <div className="cardHeader">
            <h2>Access Denied</h2>
          </div>
          <div className="cardBody">
            <p className="muted">Administrator access is required (`admin` or `screening.admin`).</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="card">
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
          <h2 className="userAdminSectionTitle">
            <span className="userAdminInlineIcon" aria-hidden="true">
              <SectionIcon />
            </span>
            User Audit Logs
          </h2>
        </div>
        <div className="cardBody">
          <div className="adminScheduleHeader" style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <div className="field" style={{ minWidth: 220 }}>
                <label>User Filter</label>
                <select value={auditUserFilter} onChange={(e) => setAuditUserFilter(e.target.value)}>
                  <option value="all">All users</option>
                  {sortedAuditUserOptions.map((option) => (
                    <option key={option.userId} value={option.userId}>
                      {option.displayName}
                    </option>
                  ))}
                </select>
              </div>
              <label className="mockModeCheck" style={{ marginTop: 18 }}>
                <input
                  type="checkbox"
                  checked={auditErrorsOnly}
                  onChange={(e) => setAuditErrorsOnly(e.target.checked)}
                />
                <span>Show errors only</span>
              </label>
            </div>
            <button
              type="button"
              className="btnGhost"
              onClick={() => void loadAuditEvents(auditUserFilter === "all" ? undefined : auditUserFilter)}
              disabled={auditLoading}
            >
              {auditLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          {auditError ? <div className="errorBox">{auditError}</div> : null}

          <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 180 }}>Time</th>
                  <th style={{ width: 220 }}>User</th>
                  <th style={{ width: 220 }}>Action</th>
                  <th style={{ width: 360 }}>Entity</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {filteredAuditEvents.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="emptyRow">
                      {auditLoading ? "Loading audit events..." : "No audit events found."}
                    </td>
                  </tr>
                ) : (
                  filteredAuditEvents.map((event) => {
                    const details = event.details as Record<string, unknown> | undefined;
                    const errorText = readErrorFromDetails(details);
                    const rowUserId = readString(event.user_id);
                    const resolvedUserName = (rowUserId ? auditUserNameById.get(rowUserId) : "") || resolveAuditUserName(event);
                    return (
                      <tr key={event.event_id}>
                        <td className="muted">{formatDateTime(event.created_at)}</td>
                        <td>{resolvedUserName}</td>
                        <td>
                          <span className="statusPill statusPending">{formatActionLabel(event.action)}</span>
                        </td>
                        <td className="muted">{resolveEntityLabel(event)}</td>
                        <td className="muted">{errorText || "-"}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
