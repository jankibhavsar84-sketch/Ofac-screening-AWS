import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useRecoilState } from "recoil";
import { useAuth } from "react-oidc-context";
import { z } from "zod";
import { buildIdentity, hasPermission } from "../auth/claims";
import { listAuditEvents, type AuditEvent } from "../api/openSanctions";
import { usersState, type UserRole } from "../state/users";

const ROLE_OPTIONS: UserRole[] = ["Admin", "Compliance Officer", "Analyst", "Viewer"];

const roleDescriptions: Record<UserRole, string> = {
  Admin: "Single, batch, daily scheduling, and User Administration access",
  "Compliance Officer": "Single and batch screening, including daily schedule enable/disable",
  Analyst: "Single and batch screening (no daily scheduling)",
  Viewer: "Single screening in mock mode only",
};

const inviteSchema = z.object({
  fullName: z.string().trim().min(1, "Full name is required."),
  email: z.string().trim().email("Enter a valid email address."),
  role: z.enum(["Admin", "Compliance Officer", "Analyst", "Viewer"]),
});

function uuid() {
  return crypto?.randomUUID?.() ?? `${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function toTitleCase(input: string): string {
  return input
    .split(" ")
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1).toLowerCase() : ""))
    .join(" ")
    .trim();
}

function userInitial(name: string): string {
  return (name.trim().charAt(0) || "U").toUpperCase();
}

function SectionIcon({ kind }: { kind: "shield" | "users" | "invite" | "back" }) {
  if (kind === "shield") {
    return (
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3l7 3v6c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6l7-3z" />
      </svg>
    );
  }
  if (kind === "invite") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M22 6 12 13 2 6" />
        <rect x="2" y="5" width="20" height="14" rx="2" />
      </svg>
    );
  }
  if (kind === "users") {
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="9" cy="8" r="3" />
        <circle cx="17" cy="10" r="2.5" />
        <path d="M3 19c0-3.3 2.7-6 6-6s6 2.7 6 6" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
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

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="3 6 5 6 21 6" />
      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
      <path d="M19 6l-1 14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1L5 6" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </svg>
  );
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function readErrorFromDetails(details: Record<string, unknown> | undefined): string {
  if (!details) return "";
  const candidates = [
    details.error,
    details.error_text,
    details.message,
    details.detail,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  return "";
}

export function ManageUsersPage() {
  const auth = useAuth();
  const identity = buildIdentity(auth.user);
  const allowed = hasPermission(identity, "screening.admin", "screening.useradmin");
  const [users, setUsers] = useRecoilState(usersState);
  const [inviteFullName, setInviteFullName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<UserRole>("Analyst");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditUserFilter, setAuditUserFilter] = useState("all");
  const [auditErrorsOnly, setAuditErrorsOnly] = useState(false);

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

  const sortedUsers = useMemo(
    () => [...users].sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
    [users]
  );

  async function loadAuditEvents(userId?: string) {
    setAuditError(null);
    setAuditLoading(true);
    try {
      const rows = await listAuditEvents(500, userId);
      setAuditEvents(rows);
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

  function submitInvite(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    const parsed = inviteSchema.safeParse({ fullName: inviteFullName, email: inviteEmail, role: inviteRole });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Please fix validation errors.");
      return;
    }

    const email = parsed.data.email.toLowerCase();
    const exists = users.some((u) => u.email.toLowerCase() === email);
    if (exists) {
      setError("A user with this email already exists.");
      return;
    }

    setUsers((prev) => [
      {
        id: uuid(),
        name: toTitleCase(parsed.data.fullName),
        email,
        role: parsed.data.role,
        createdAt: new Date().toISOString(),
      },
      ...prev,
    ]);

    setInviteFullName("");
    setInviteEmail("");
    setInviteRole("Analyst");
    setSuccess("User added successfully.");
  }

  function removeUser(userId: string) {
    setUsers((prev) => prev.filter((u) => u.id !== userId));
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
              <SectionIcon kind="invite" />
            </span>
            Add New User
          </h2>
        </div>
        <div className="cardBody">
          <form onSubmit={submitInvite} className="inviteGrid">
            <div className="field inviteNameField">
              <label>Full Name</label>
              <input
                type="text"
                placeholder="e.g. John Smith"
                value={inviteFullName}
                onChange={(e) => setInviteFullName(e.target.value)}
              />
            </div>
            <div className="field inviteEmailField">
              <label>Email Address</label>
              <input
                type="email"
                placeholder="colleague@company.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
              />
            </div>
            <div className="field inviteRoleField">
              <label>Role</label>
              <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value as UserRole)}>
                {ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </div>
            <div className="inviteActionField">
              <button type="submit" className="btnInvite">
                <span className="btnInviteIcon" aria-hidden="true">
                  <SectionIcon kind="invite" />
                </span>
                Add User
              </button>
            </div>
          </form>
          {error ? <div className="errorBox">{error}</div> : null}
          {success ? <div className="successBox">{success}</div> : null}
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="cardHeader">
          <h2 className="userAdminSectionTitle">
            <span className="userAdminInlineIcon" aria-hidden="true">
              <SectionIcon kind="users" />
            </span>
            Team Members
            <span className="userCount">({sortedUsers.length})</span>
          </h2>
        </div>
        <div className="cardBody">
          {sortedUsers.length === 0 ? (
            <div className="emptyTeam">No team members yet. Invite a user to get started.</div>
          ) : (
            <div className="teamMemberList">
              {sortedUsers.map((user) => (
                <div key={user.id} className="teamMemberRow">
                  <div className="teamMemberLeft">
                    <div className="teamAvatar">{userInitial(user.name)}</div>
                    <div>
                      <div className="teamName">{user.name}</div>
                      <div className="teamEmail">{user.email}</div>
                    </div>
                  </div>
                  <div className="teamMemberRight">
                    <span className={`teamRoleBadge teamRoleBadge--${user.role.replace(/\s+/g, "").toLowerCase()}`}>
                      <RoleIcon role={user.role} />
                      {user.role}
                    </span>
                    <button
                      type="button"
                      className="teamRemoveBtn"
                      onClick={() => removeUser(user.id)}
                      aria-label={`Remove ${user.name}`}
                      title="Remove user"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="cardHeader">
          <h2 className="userAdminSectionTitle">
            <span className="userAdminInlineIcon" aria-hidden="true">
              <SectionIcon kind="shield" />
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
                  {sortedUsers.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.name} ({user.email})
                    </option>
                  ))}
                  {identity?.id ? (
                    <option value={identity.id}>
                      {identity.name || identity.id} (current token user)
                    </option>
                  ) : null}
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
                  <th style={{ width: 200 }}>User</th>
                  <th style={{ width: 210 }}>Action</th>
                  <th style={{ width: 180 }}>Entity</th>
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
                    return (
                      <tr key={event.event_id}>
                        <td className="muted">{formatDateTime(event.created_at)}</td>
                        <td>
                          <div>{event.user_name || "-"}</div>
                          <div className="muted">{event.user_id || "-"}</div>
                        </td>
                        <td>
                          <span className="statusPill statusPending">{event.action}</span>
                        </td>
                        <td className="muted">
                          {event.entity_type || "-"}
                          {event.entity_id ? ` / ${event.entity_id}` : ""}
                        </td>
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
