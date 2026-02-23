import { type FormEvent, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useRecoilState } from "recoil";
import { z } from "zod";
import { usersState, type UserRole } from "../state/users";

const ROLE_OPTIONS: UserRole[] = ["Admin", "Compliance Officer", "Analyst", "Viewer"];

const roleDescriptions: Record<UserRole, string> = {
  Admin: "Full access - manage users, settings, all screenings",
  "Compliance Officer": "Can run screenings, review results, manage batch jobs",
  Analyst: "Can run single screenings and view results",
  Viewer: "Read-only access to screening results",
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

export function ManageUsersPage() {
  const [users, setUsers] = useRecoilState(usersState);
  const [inviteFullName, setInviteFullName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<UserRole>("Analyst");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const sortedUsers = useMemo(
    () => [...users].sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
    [users]
  );

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

  function updateRole(userId: string, role: UserRole) {
    setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, role } : u)));
  }

  return (
    <div className="page">
      <div className="userAdminHero">
        <div className="userAdminHeroLeft">
          <div className="userAdminHeroIcon" aria-hidden="true">
            <SectionIcon kind="shield" />
          </div>
          <div>
            <h1 className="userAdminTitle">User Administration</h1>
            <div className="userAdminSub">Manage team members and their access levels</div>
          </div>
        </div>
        <Link to="/screening" className="btnGhost userAdminBackBtn">
          <span aria-hidden="true"><SectionIcon kind="back" /></span>
          Back to Dashboard
        </Link>
      </div>

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
                    <select
                      className="teamRoleSelect"
                      value={user.role}
                      onChange={(e) => updateRole(user.id, e.target.value as UserRole)}
                    >
                      {ROLE_OPTIONS.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
