import { useState, type FormEvent } from "react";
import { useRecoilState } from "recoil";
import { z } from "zod";
import { usersState, type UserRole, type UserStatus } from "../state/users";

type UserForm = {
  firstName: string;
  lastName: string;
  email: string;
  role: UserRole;
  status: UserStatus;
};

const defaultForm: UserForm = {
  firstName: "",
  lastName: "",
  email: "",
  role: "Analyst",
  status: "Active",
};

const roles: UserRole[] = ["Admin", "Analyst", "Reviewer"];
const statuses: UserStatus[] = ["Active", "Inactive"];

const userSchema = z.object({
  firstName: z.string().trim().min(1, "First name is required."),
  lastName: z.string().trim().min(1, "Last name is required."),
  email: z.string().trim().email("Enter a valid email address."),
  role: z.enum(["Admin", "Analyst", "Reviewer"]),
  status: z.enum(["Active", "Inactive"]),
});

function uuid() {
  return crypto?.randomUUID?.() ?? `${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function formatCreatedAt(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function ManageUsersPage() {
  const [users, setUsers] = useRecoilState(usersState);
  const [form, setForm] = useState<UserForm>(defaultForm);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  function update<K extends keyof UserForm>(key: K, value: UserForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function resetForm() {
    setForm(defaultForm);
    setError(null);
    setSuccess(null);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    const parsed = userSchema.safeParse(form);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Please fix validation errors.");
      return;
    }

    const normalizedEmail = parsed.data.email.toLowerCase();
    const exists = users.some((u) => u.email.toLowerCase() === normalizedEmail);
    if (exists) {
      setError("A user with this email already exists.");
      return;
    }

    setUsers((prev) => [
      {
        id: uuid(),
        firstName: parsed.data.firstName,
        lastName: parsed.data.lastName,
        email: normalizedEmail,
        role: parsed.data.role,
        status: parsed.data.status,
        createdAt: new Date().toISOString(),
      },
      ...prev,
    ]);

    setSuccess("User added successfully.");
    setForm(defaultForm);
  }

  return (
    <div className="page">
      <div className="card">
        <div className="cardHeader">
          <h2>Manage Users</h2>
        </div>

        <div className="cardBody">
          <p className="manageUsersSub">Add a new user in the system.</p>

          <form onSubmit={onSubmit}>
            <div className="manageFormGrid">
              <div className="field">
                <label>First Name *</label>
                <input value={form.firstName} onChange={(e) => update("firstName", e.target.value)} />
              </div>

              <div className="field">
                <label>Last Name *</label>
                <input value={form.lastName} onChange={(e) => update("lastName", e.target.value)} />
              </div>

              <div className="field manageFieldWide">
                <label>Email *</label>
                <input type="email" value={form.email} onChange={(e) => update("email", e.target.value)} />
              </div>

              <div className="field">
                <label>Role *</label>
                <select value={form.role} onChange={(e) => update("role", e.target.value as UserRole)}>
                  {roles.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label>Status *</label>
                <select value={form.status} onChange={(e) => update("status", e.target.value as UserStatus)}>
                  {statuses.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="manageActions">
              <button type="button" className="btnGhost" onClick={resetForm}>
                Clear
              </button>
              <button type="submit" className="btnAdd">
                Add User
              </button>
            </div>

            {error ? <div className="errorBox">{error}</div> : null}
            {success ? <div className="successBox">{success}</div> : null}
          </form>

          <div className="sectionRow" style={{ marginTop: 18 }}>
            <div className="sectionTitle">System Users</div>
            <div className="muted">{users.length} total</div>
          </div>

          <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {users.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="emptyRow">
                      No users added yet.
                    </td>
                  </tr>
                ) : (
                  users.map((user) => (
                    <tr key={user.id}>
                      <td>{`${user.firstName} ${user.lastName}`}</td>
                      <td>{user.email}</td>
                      <td>{user.role}</td>
                      <td>{user.status}</td>
                      <td>{formatCreatedAt(user.createdAt)}</td>
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
