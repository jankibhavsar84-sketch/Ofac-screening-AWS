import { useEffect, useMemo, useState } from "react";
import { useAuth } from "react-oidc-context";
import { buildIdentity, hasPermission } from "../auth/claims";
import {
  createAdminBusinessUnit,
  deleteAdminBusinessUnit,
  listAdminUsers,
  listAdminBusinessUnits,
  listBusinessUnitMappings,
  updateAdminBusinessUnit,
  updateBusinessUnitMapping,
  type BusinessUnit,
  type UserBusinessUnitMapping,
} from "../api/openSanctions";
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

function normalizeBusinessUnitCode(value: string): string {
  return readString(value).toUpperCase();
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

  const [auditUserOptions, setAuditUserOptions] = useState<AuditUserOption[]>([]);
  const [businessUnits, setBusinessUnits] = useState<BusinessUnit[]>([]);
  const [businessUnitMappings, setBusinessUnitMappings] = useState<UserBusinessUnitMapping[]>([]);
  const [businessUnitLoading, setBusinessUnitLoading] = useState(false);
  const [businessUnitError, setBusinessUnitError] = useState<string | null>(null);
  const [businessUnitCodeInput, setBusinessUnitCodeInput] = useState("");
  const [businessUnitNameInput, setBusinessUnitNameInput] = useState("");
  const [editingBusinessUnitCode, setEditingBusinessUnitCode] = useState<string | null>(null);
  const [businessUnitSaving, setBusinessUnitSaving] = useState(false);
  const [selectedMappingUserId, setSelectedMappingUserId] = useState("");
  const [selectedMappingCodes, setSelectedMappingCodes] = useState<string[]>([]);
  const [mappingSaving, setMappingSaving] = useState(false);

  const activeBusinessUnits = useMemo(
    () =>
      [...businessUnits]
        .filter((row) => row.is_active)
        .sort((a, b) => `${a.business_unit_name}`.localeCompare(`${b.business_unit_name}`)),
    [businessUnits]
  );
  const businessUnitMappingsByUser = useMemo(() => {
    const map = new Map<string, UserBusinessUnitMapping>();
    for (const row of businessUnitMappings) {
      const id = readString(row.user_id);
      if (!id) continue;
      map.set(id, row);
    }
    return map;
  }, [businessUnitMappings]);
  const mappingUserOptions = useMemo(() => {
    const merged = new Map<string, string>();
    for (const option of auditUserOptions) {
      const id = readString(option.userId);
      if (!id) continue;
      merged.set(id, readString(option.displayName) || id);
    }
    for (const mapping of businessUnitMappings) {
      const id = readString(mapping.user_id);
      if (!id) continue;
      const name = readString(mapping.user_name) || merged.get(id) || id;
      merged.set(id, name);
    }
    if (identity?.id) {
      const id = readString(identity.id);
      if (id && !merged.has(id)) merged.set(id, readString(identity.name) || id);
    }
    return Array.from(merged.entries())
      .map(([userId, displayName]) => ({ userId, displayName }))
      .sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [auditUserOptions, businessUnitMappings, identity?.id, identity?.name]);

  async function loadAdminUserOptions() {
    try {
      const rows = await listAdminUsers();

      setAuditUserOptions((prev) => {
        const merged = new Map<string, string>(prev.map((item) => [item.userId, item.displayName]));
        for (const row of rows) {
          const userId = readString(row.user_id);
          if (!userId) continue;
          const displayName = readString(row.display_name) || userId;
          const existing = merged.get(userId);
          if (!existing || existing === userId) {
            merged.set(userId, displayName || userId);
          }
        }
        return Array.from(merged.entries()).map(([userId, displayName]) => ({ userId, displayName }));
      });
    } catch {
      // best-effort source for user options
    }
  }

  async function loadBusinessUnitAdminData() {
    setBusinessUnitError(null);
    setBusinessUnitLoading(true);
    try {
      const [units, mappings] = await Promise.all([listAdminBusinessUnits(true), listBusinessUnitMappings()]);
      setBusinessUnits(units);
      setBusinessUnitMappings(mappings);
      setAuditUserOptions((prev) => {
        const merged = new Map<string, string>(prev.map((item) => [item.userId, item.displayName]));
        for (const row of mappings) {
          const userId = readString(row.user_id);
          if (!userId) continue;
          const userName = readString(row.user_name) || userId;
          if (!merged.has(userId)) merged.set(userId, userName);
        }
        return Array.from(merged.entries()).map(([userId, displayName]) => ({ userId, displayName }));
      });
    } catch (err: any) {
      setBusinessUnitError(err?.message ?? "Failed to load Business Unit administration data.");
    } finally {
      setBusinessUnitLoading(false);
    }
  }

  useEffect(() => {
    if (!allowed) return;
    void loadBusinessUnitAdminData();
    void loadAdminUserOptions();
  }, [allowed]);

  useEffect(() => {
    if (selectedMappingUserId) return;
    const first = mappingUserOptions[0]?.userId ?? "";
    if (first) setSelectedMappingUserId(first);
  }, [mappingUserOptions, selectedMappingUserId]);

  useEffect(() => {
    const safeUserId = readString(selectedMappingUserId);
    if (!safeUserId) {
      setSelectedMappingCodes([]);
      return;
    }
    const mapped = businessUnitMappingsByUser.get(safeUserId);
    const codes = Array.isArray(mapped?.business_unit_codes)
      ? mapped.business_unit_codes.map((code) => normalizeBusinessUnitCode(String(code))).filter(Boolean)
      : [];
    setSelectedMappingCodes(Array.from(new Set(codes)));
  }, [selectedMappingUserId, businessUnitMappingsByUser]);

  function resetBusinessUnitForm() {
    setEditingBusinessUnitCode(null);
    setBusinessUnitCodeInput("");
    setBusinessUnitNameInput("");
  }

  function toggleMappingCode(code: string) {
    const safeCode = normalizeBusinessUnitCode(code);
    if (!safeCode) return;
    setSelectedMappingCodes((prev) => (prev.includes(safeCode) ? prev.filter((value) => value !== safeCode) : [...prev, safeCode]));
  }

  async function saveBusinessUnit() {
    const code = normalizeBusinessUnitCode(businessUnitCodeInput);
    const name = readString(businessUnitNameInput);
    if (!code || !name) {
      setBusinessUnitError("Business Unit code and name are required.");
      return;
    }

    setBusinessUnitError(null);
    setBusinessUnitSaving(true);
    try {
      if (editingBusinessUnitCode) {
        await updateAdminBusinessUnit(editingBusinessUnitCode, code, name);
      } else {
        await createAdminBusinessUnit(code, name);
      }
      await loadBusinessUnitAdminData();
      resetBusinessUnitForm();
    } catch (err: any) {
      setBusinessUnitError(err?.message ?? "Failed to save Business Unit.");
    } finally {
      setBusinessUnitSaving(false);
    }
  }

  async function removeBusinessUnit(code: string) {
    const safeCode = normalizeBusinessUnitCode(code);
    if (!safeCode) return;
    if (!window.confirm(`Delete Business Unit ${safeCode}?`)) return;

    setBusinessUnitError(null);
    setBusinessUnitSaving(true);
    try {
      await deleteAdminBusinessUnit(safeCode);
      await loadBusinessUnitAdminData();
      if (editingBusinessUnitCode === safeCode) {
        resetBusinessUnitForm();
      }
      setSelectedMappingCodes((prev) => prev.filter((value) => value !== safeCode));
    } catch (err: any) {
      setBusinessUnitError(err?.message ?? "Failed to delete Business Unit.");
    } finally {
      setBusinessUnitSaving(false);
    }
  }

  async function saveUserBusinessUnitMapping() {
    const userId = readString(selectedMappingUserId);
    if (!userId) {
      setBusinessUnitError("Select a user to map Business Units.");
      return;
    }
    const userName = mappingUserOptions.find((row) => row.userId === userId)?.displayName || userId;

    setBusinessUnitError(null);
    setMappingSaving(true);
    try {
      const saved = await updateBusinessUnitMapping(userId, {
        userName,
        businessUnitCodes: selectedMappingCodes,
      });
      setBusinessUnitMappings((prev) => {
        const next = prev.filter((row) => readString(row.user_id) !== userId);
        next.push(saved);
        return next;
      });
    } catch (err: any) {
      setBusinessUnitError(err?.message ?? "Failed to save user mapping.");
    } finally {
      setMappingSaving(false);
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
            <p className="muted">Administrator access is required (`screening.admin` or `screening.useradmin`).</p>
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
            Business Unit Administration
          </h2>
        </div>
        <div className="cardBody buAdminBody">
          {businessUnitError ? <div className="errorBox" role="alert" aria-live="assertive">{businessUnitError}</div> : null}
          <div className="buAdminHeader">
            <div className="buAdminIntro">
              <p className="buAdminIntroTitle">Business Unit Catalog and User Mapping</p>
              <p className="buAdminIntroSub">Create business units, maintain names/codes, and control user-level BU access.</p>
            </div>
            <div className="buAdminStats">
              <div className="buStatCard">
                <div className="buStatLabel">Active Business Units</div>
                <div className="buStatValue">{activeBusinessUnits.length}</div>
              </div>
              <div className="buStatCard">
                <div className="buStatLabel">Mapped Users</div>
                <div className="buStatValue">{businessUnitMappings.length}</div>
              </div>
            </div>
            <button type="button" className="btnGhostSmall buRefreshBtn" onClick={() => void loadBusinessUnitAdminData()} disabled={businessUnitLoading || businessUnitSaving || mappingSaving}>
              {businessUnitLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          <div className="buAdminGrid">
            <div className="buAdminPanel">
              <div className="buPanelHeading">
                <h3>Add / Edit Business Unit</h3>
                <p>Use consistent BU code format. Editing updates mapped references automatically.</p>
              </div>
              <div className="field">
                <label>Business Unit Code <span className="requiredMark">*</span></label>
                <input
                  className="buCodeInput"
                  value={businessUnitCodeInput}
                  onChange={(e) => setBusinessUnitCodeInput(normalizeBusinessUnitCode(e.target.value))}
                  placeholder="e.g., US_PRU_OSGLI"
                />
              </div>
              <div className="field buFieldSpacing">
                <label>Business Unit Name <span className="requiredMark">*</span></label>
                <input
                  value={businessUnitNameInput}
                  onChange={(e) => setBusinessUnitNameInput(e.target.value)}
                  placeholder="e.g., OSGLI"
                />
              </div>
              <div className="buActionRow">
                <button type="button" className="buPrimaryBtn" onClick={() => void saveBusinessUnit()} disabled={businessUnitSaving}>
                  {businessUnitSaving ? "Saving..." : editingBusinessUnitCode ? "Update Business Unit" : "Add Business Unit"}
                </button>
                {editingBusinessUnitCode ? (
                  <button type="button" className="btnGhostSmall" onClick={resetBusinessUnitForm} disabled={businessUnitSaving}>
                    Cancel
                  </button>
                ) : null}
              </div>
            </div>
            <div className="buAdminPanel">
              <div className="buPanelHeading">
                <h3>Business Unit Catalog</h3>
                <p>Review existing Business Units and manage updates.</p>
              </div>
              <div className="tableWrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col" className="buColCode">Code</th>
                      <th scope="col">Name</th>
                      <th scope="col" className="buColActions">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {businessUnits.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="emptyRow">
                          {businessUnitLoading ? "Loading business units..." : "No Business Units found."}
                        </td>
                      </tr>
                    ) : (
                      businessUnits
                        .slice()
                        .sort((a, b) => `${a.business_unit_name}`.localeCompare(`${b.business_unit_name}`))
                        .map((row) => (
                          <tr key={row.business_unit_code}>
                            <td>{row.business_unit_code}</td>
                            <td>{row.business_unit_name}</td>
                            <td className="buCellActions">
                              <div className="buTableActions">
                                <button
                                  type="button"
                                  className="btnGhostSmall"
                                  onClick={() => {
                                    setEditingBusinessUnitCode(row.business_unit_code);
                                    setBusinessUnitCodeInput(normalizeBusinessUnitCode(row.business_unit_code));
                                    setBusinessUnitNameInput(readString(row.business_unit_name));
                                  }}
                                  disabled={businessUnitSaving}
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  className="btnGhostSmall"
                                  onClick={() => void removeBusinessUnit(row.business_unit_code)}
                                  disabled={businessUnitSaving}
                                >
                                  Delete
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

          <div className="buAdminPanel buMappingPanel">
            <div className="buPanelHeading">
              <h3>User to Business Unit Mapping</h3>
              <p>Select a user and assign one or more Business Units.</p>
            </div>
            <div className="buMappingUserSelect">
              <div className="field">
                <label>User (select existing)</label>
                <select
                  value={selectedMappingUserId}
                  onChange={(e) => setSelectedMappingUserId(e.target.value)}
                >
                  <option value="">Select user</option>
                  {mappingUserOptions.map((option) => (
                    <option key={option.userId} value={option.userId}>
                      {option.displayName}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="field buFieldSpacing">
              <div className="buMappingHeaderRow">
                <span className="buMappingLabel">Mapped Business Units</span>
                <span className="buMappingCount">{selectedMappingCodes.length} selected</span>
              </div>
              <div className="buCheckboxGrid">
                {activeBusinessUnits.length === 0 ? (
                  <div className="emptyRow buEmptyState">No active Business Units available.</div>
                ) : (
                  activeBusinessUnits.map((row) => {
                    const code = normalizeBusinessUnitCode(row.business_unit_code);
                    const checked = selectedMappingCodes.includes(code);
                    return (
                      <label key={code} className="mockModeCheck">
                        <input type="checkbox" checked={checked} onChange={() => toggleMappingCode(code)} />
                        <span>{row.business_unit_name} ({code})</span>
                      </label>
                    );
                  })
                )}
              </div>
            </div>

            <div className="buActionRow">
              <button type="button" className="buPrimaryBtn" onClick={() => void saveUserBusinessUnitMapping()} disabled={mappingSaving || businessUnitSaving}>
                {mappingSaving ? "Saving Mapping..." : "Save User Mapping"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
