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
} from "../api/screeningApi";

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
  const [mappingSearch, setMappingSearch] = useState("");
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
  const filteredBusinessUnits = useMemo(() => {
    const term = readString(mappingSearch).toLowerCase();
    const ranked = [...activeBusinessUnits].sort((a, b) => {
      const aCode = normalizeBusinessUnitCode(a.business_unit_code);
      const bCode = normalizeBusinessUnitCode(b.business_unit_code);
      const aSelected = selectedMappingCodes.includes(aCode) ? 0 : 1;
      const bSelected = selectedMappingCodes.includes(bCode) ? 0 : 1;
      if (aSelected !== bSelected) return aSelected - bSelected;
      return `${a.business_unit_name}`.localeCompare(`${b.business_unit_name}`);
    });
    if (!term) return ranked;
    return ranked.filter((row) => {
      const code = normalizeBusinessUnitCode(row.business_unit_code);
      const name = readString(row.business_unit_name).toLowerCase();
      return code.toLowerCase().includes(term) || name.includes(term);
    });
  }, [activeBusinessUnits, mappingSearch, selectedMappingCodes]);
  const selectedBusinessUnitRows = useMemo(() => {
    const byCode = new Map(activeBusinessUnits.map((row) => [normalizeBusinessUnitCode(row.business_unit_code), row]));
    return selectedMappingCodes
      .map((code) => {
        const row = byCode.get(code);
        if (!row) return null;
        return { code, name: readString(row.business_unit_name) || code };
      })
      .filter((row): row is { code: string; name: string } => Boolean(row))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [activeBusinessUnits, selectedMappingCodes]);
  const savedMappingCodes = useMemo(() => {
    const safeUserId = readString(selectedMappingUserId);
    if (!safeUserId) return [];
    const mapped = businessUnitMappingsByUser.get(safeUserId);
    const codes = Array.isArray(mapped?.business_unit_codes)
      ? mapped.business_unit_codes.map((code) => normalizeBusinessUnitCode(String(code))).filter(Boolean)
      : [];
    return Array.from(new Set(codes)).sort();
  }, [selectedMappingUserId, businessUnitMappingsByUser]);
  const mappingHasChanges = useMemo(() => {
    if (savedMappingCodes.length !== selectedMappingCodes.length) return true;
    const selectedSet = new Set(selectedMappingCodes);
    return savedMappingCodes.some((code) => !selectedSet.has(code));
  }, [savedMappingCodes, selectedMappingCodes]);

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

  function setAllMappingCodes() {
    const all = activeBusinessUnits.map((row) => normalizeBusinessUnitCode(row.business_unit_code)).filter(Boolean);
    setSelectedMappingCodes(Array.from(new Set(all)));
  }

  function clearAllMappingCodes() {
    setSelectedMappingCodes([]);
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
      <section className="pageHero" aria-label="User Administration">
        <div className="pageHeroMain">
          <div className="pageHeroHead">
            <span className="pageHeroIcon" aria-hidden="true">
              <SectionIcon />
            </span>
            <div>
              <p className="pageHeroEyebrow">User Administration</p>
              <h1 className="pageHeroTitle">Access and Business Unit Controls</h1>
            </div>
          </div>
          <p className="pageHeroSub">Maintain the Business Unit catalog and map user-level Business Unit access for screening workflows.</p>
        </div>
        <div className="pageHeroMeta" aria-hidden="true">
          <span className="pageHeroPill">{activeBusinessUnits.length} Active Business Units</span>
          <span className="pageHeroPill">{businessUnitMappings.length} Mapped Users</span>
        </div>
      </section>

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
              <p>Select a user, pick Business Units, and save. Left side shows selected units, right side shows available units.</p>
            </div>
            <div className="buMappingTop">
              <div className="field buMappingUserSelect">
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
              <div className="field buMappingSearchField">
                <label>Find Business Unit</label>
                <input
                  className="buMappingSearchInput"
                  value={mappingSearch}
                  onChange={(e) => setMappingSearch(e.target.value)}
                  placeholder="Search by BU name or code"
                  aria-label="Search business units"
                />
              </div>
              <div className="buMappingQuickActions">
                <button type="button" className="btnGhostSmall" onClick={setAllMappingCodes} disabled={activeBusinessUnits.length === 0}>
                  Select All
                </button>
                <button type="button" className="btnGhostSmall" onClick={clearAllMappingCodes} disabled={selectedMappingCodes.length === 0}>
                  Clear All
                </button>
              </div>
            </div>

            <div className="buMappingHeaderRow buFieldSpacing">
              <span className="buMappingLabel">Mapping Overview</span>
              <div className="buMappingMeta">
                <span className="buMappingCount">{selectedMappingCodes.length} selected</span>
                <span className="buMappingCount">{filteredBusinessUnits.length} visible</span>
                {mappingHasChanges ? <span className="buMappingBadgeChanged">Unsaved changes</span> : <span className="buMappingBadgeSaved">Saved</span>}
              </div>
            </div>

            <div className="buMappingWorkspace">
              <div className="buMappingSelectedPanel">
                <div className="buMappingPanelTitle">
                  <span>Selected for User</span>
                  <span className="buMappingCount">{selectedBusinessUnitRows.length}</span>
                </div>
                <div className="buMappingSelectedChips" aria-live="polite">
                  {selectedBusinessUnitRows.length === 0 ? (
                    <div className="buEmptyState">No Business Units selected for this user.</div>
                  ) : (
                    selectedBusinessUnitRows.map((row) => (
                      <button key={row.code} type="button" className="buMappingChip" onClick={() => toggleMappingCode(row.code)} title="Remove from mapping">
                        <span>{row.name}</span>
                        <strong>{row.code}</strong>
                        <span className="buMappingChipX" aria-hidden="true">
                          ×
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>
              <div className="buMappingAvailablePanel">
                <div className="buMappingPanelTitle">
                  <span>Available Business Units</span>
                  <span className="buMappingCount">{activeBusinessUnits.length}</span>
                </div>
                <div className="buCheckboxGrid">
                  {filteredBusinessUnits.length === 0 ? (
                    <div className="emptyRow buEmptyState">No active Business Units available.</div>
                  ) : (
                    filteredBusinessUnits.map((row) => {
                      const code = normalizeBusinessUnitCode(row.business_unit_code);
                      const checked = selectedMappingCodes.includes(code);
                      return (
                        <label key={code} className={`buMappingOption ${checked ? "active" : ""}`}>
                          <input type="checkbox" checked={checked} onChange={() => toggleMappingCode(code)} />
                          <span className="buMappingOptionText">
                            <span className="buMappingOptionName">{row.business_unit_name}</span>
                            <span className="buMappingOptionCode">{code}</span>
                          </span>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>
            </div>

            <div className="buActionRow">
              <button
                type="button"
                className="buPrimaryBtn"
                onClick={() => void saveUserBusinessUnitMapping()}
                disabled={mappingSaving || businessUnitSaving || !mappingHasChanges}
              >
                {mappingSaving ? "Saving Mapping..." : "Save User Mapping"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

