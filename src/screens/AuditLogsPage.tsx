import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "react-oidc-context";
import { buildIdentity, hasPermission } from "../auth/claims";
import {
  listAdminUsers,
  listAuditEventPage,
  type AdminUserOption,
  type AuditEvent,
} from "../api/screeningApi";

type AuditUserOption = {
  userId: string;
  displayName: string;
};

const pageSizeOptions = [100, 200, 300] as const;
const AUDIT_WORKSPACE_STORAGE_KEY = "ofac-screening:audit-workspace";
const AUDIT_CACHE_STORAGE_KEY = "ofac-screening:audit-cache";
const AUDIT_CACHE_TTL_MS = 60 * 1000;

type AuditWorkspaceState = {
  userFilter: string;
  errorsOnly: boolean;
  page: number;
  pageSize: (typeof pageSizeOptions)[number];
};

type AuditCacheState = {
  ownerUserId: string | null;
  queryKey: string | null;
  scopeKey: string | null;
  items: AuditEvent[];
  total: number;
  lastRefreshedAt: string | null;
  userOptions: AuditUserOption[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function defaultAuditWorkspaceState(): AuditWorkspaceState {
  return {
    userFilter: "all",
    errorsOnly: false,
    page: 1,
    pageSize: 100,
  };
}

function defaultAuditCacheState(): AuditCacheState {
  return {
    ownerUserId: null,
    queryKey: null,
    scopeKey: null,
    items: [],
    total: 0,
    lastRefreshedAt: null,
    userOptions: [],
  };
}

function parseAuditUserOption(value: unknown): AuditUserOption | null {
  if (!isRecord(value)) return null;
  const userId = typeof value.userId === "string" ? value.userId.trim() : "";
  const displayName = typeof value.displayName === "string" ? value.displayName.trim() : "";
  if (!userId) return null;
  return {
    userId,
    displayName: displayName || userId,
  };
}

function parseAuditEvent(value: unknown): AuditEvent | null {
  if (!isRecord(value)) return null;
  const eventId = typeof value.event_id === "number" && Number.isFinite(value.event_id) ? Math.trunc(value.event_id) : NaN;
  const createdAt = typeof value.created_at === "string" ? value.created_at : "";
  const action = typeof value.action === "string" ? value.action : "";
  if (!Number.isFinite(eventId) || !createdAt || !action) return null;
  return {
    event_id: eventId,
    created_at: createdAt,
    user_id: typeof value.user_id === "string" ? value.user_id : null,
    user_name: typeof value.user_name === "string" ? value.user_name : null,
    action,
    entity_type: typeof value.entity_type === "string" ? value.entity_type : null,
    entity_id: typeof value.entity_id === "string" ? value.entity_id : null,
    details: isRecord(value.details) ? value.details : {},
  };
}

function parseAuditWorkspaceState(value: unknown): AuditWorkspaceState | null {
  if (!isRecord(value)) return null;
  const page = typeof value.page === "number" && Number.isFinite(value.page) ? Math.max(1, Math.floor(value.page)) : 1;
  const userFilter = typeof value.userFilter === "string" && value.userFilter.trim() ? value.userFilter.trim() : "all";
  const errorsOnly = Boolean(value.errorsOnly);
  const pageSizeRaw = typeof value.pageSize === "number" ? value.pageSize : NaN;
  const pageSize = pageSizeRaw === 100 || pageSizeRaw === 200 || pageSizeRaw === 300 ? pageSizeRaw : 100;
  return { userFilter, errorsOnly, page, pageSize };
}

function parseAuditCacheState(value: unknown): AuditCacheState | null {
  if (!isRecord(value)) return null;
  const ownerUserId =
    value.ownerUserId === null || typeof value.ownerUserId === "string" ? value.ownerUserId : null;
  const queryKey = value.queryKey === null || typeof value.queryKey === "string" ? value.queryKey : null;
  const scopeKey = value.scopeKey === null || typeof value.scopeKey === "string" ? value.scopeKey : null;
  const total = typeof value.total === "number" && Number.isFinite(value.total) ? Math.max(0, Math.floor(value.total)) : 0;
  const lastRefreshedAt =
    value.lastRefreshedAt === null || typeof value.lastRefreshedAt === "string" ? value.lastRefreshedAt : null;
  const items = Array.isArray(value.items) ? value.items.map(parseAuditEvent).filter((item): item is AuditEvent => item !== null) : [];
  const userOptions = Array.isArray(value.userOptions)
    ? value.userOptions.map(parseAuditUserOption).filter((item): item is AuditUserOption => item !== null)
    : [];
  return {
    ownerUserId,
    queryKey,
    scopeKey,
    items,
    total,
    lastRefreshedAt,
    userOptions,
  };
}

function loadStoredState<T>(storageKey: string, parse: (value: unknown) => T | null, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw == null) return fallback;
    const parsed = parse(JSON.parse(raw));
    if (parsed != null) return parsed;
    window.localStorage.removeItem(storageKey);
  } catch {
    window.localStorage.removeItem(storageKey);
  }
  return fallback;
}

function persistStoredState(storageKey: string, value: unknown): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // Ignore browser storage limitations.
  }
}

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

function mergeAuditUserOptions(
  current: AuditUserOption[],
  adminRows: AdminUserOption[] = [],
  events: AuditEvent[] = [],
  selfUserId?: string,
  selfDisplayName?: string,
): AuditUserOption[] {
  const merged = new Map<string, string>();
  for (const option of current) {
    const userId = readString(option.userId);
    if (!userId) continue;
    merged.set(userId, readString(option.displayName) || userId);
  }
  for (const row of adminRows) {
    const userId = readString(row.user_id);
    if (!userId) continue;
    const displayName = readString(row.display_name) || userId;
    const existing = merged.get(userId);
    const shouldUpgradeWithEmail = displayName.includes("@") && !readString(existing).includes("@");
    if (!existing || existing === userId || shouldUpgradeWithEmail) {
      merged.set(userId, displayName || userId);
    }
  }
  for (const row of events) {
    const rowUserId = readString(row.user_id);
    if (!rowUserId) continue;
    const resolvedName = resolveAuditUserName(row);
    const existing = merged.get(rowUserId);
    if (!existing || existing === rowUserId || isTechnicalIdentifier(existing)) {
      merged.set(rowUserId, resolvedName || rowUserId);
    }
  }
  if (selfUserId) {
    merged.set(selfUserId, readString(selfDisplayName) || merged.get(selfUserId) || selfUserId);
  }
  return Array.from(merged.entries()).map(([userId, displayName]) => ({
    userId,
    displayName: displayName || userId,
  }));
}

function buildAuditQueryKey(workspace: AuditWorkspaceState): string {
  return JSON.stringify({
    userFilter: workspace.userFilter,
    errorsOnly: workspace.errorsOnly,
    pageSize: workspace.pageSize,
    page: workspace.page,
  });
}

function buildAuditScopeKey(workspace: AuditWorkspaceState): string {
  return JSON.stringify({
    userFilter: workspace.userFilter,
    errorsOnly: workspace.errorsOnly,
    pageSize: workspace.pageSize,
  });
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

export function AuditLogsPage() {
  const auth = useAuth();
  const identity = buildIdentity(auth.user);
  const allowed = hasPermission(identity, "screening.admin");
  const selfUserId = readString(identity?.id) || undefined;
  const selfDisplayName = readString(identity?.name || identity?.email || identity?.id) || undefined;
  const [auditWorkspace, setAuditWorkspace] = useState<AuditWorkspaceState>(() =>
    loadStoredState(AUDIT_WORKSPACE_STORAGE_KEY, parseAuditWorkspaceState, defaultAuditWorkspaceState())
  );
  const [auditCache, setAuditCache] = useState<AuditCacheState>(() =>
    loadStoredState(AUDIT_CACHE_STORAGE_KEY, parseAuditCacheState, defaultAuditCacheState())
  );
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const latestAuditRequestRef = useRef("");

  const auditQueryKey = useMemo(() => buildAuditQueryKey(auditWorkspace), [auditWorkspace]);
  const auditScopeKey = useMemo(() => buildAuditScopeKey(auditWorkspace), [auditWorkspace]);
  const auditOffset = Math.max(0, (auditWorkspace.page - 1) * auditWorkspace.pageSize);
  const hasCachedAuditScope =
    (auditCache.ownerUserId || null) === (selfUserId || null) &&
    auditCache.scopeKey === auditScopeKey;
  const hasCachedAuditPage =
    hasCachedAuditScope &&
    auditCache.queryKey === auditQueryKey;
  const auditEvents = hasCachedAuditPage ? auditCache.items : [];
  const auditTotal = hasCachedAuditScope ? auditCache.total : 0;

  const sortedAuditUserOptions = useMemo(
    () => [...auditCache.userOptions].sort((a, b) => a.displayName.localeCompare(b.displayName)),
    [auditCache.userOptions]
  );
  const auditUserNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const option of auditCache.userOptions) {
      const id = option.userId.trim();
      const name = option.displayName.trim();
      if (!id || !name) continue;
      if (!map.has(id) || isTechnicalIdentifier(map.get(id) || "")) {
        map.set(id, name);
      }
    }
    return map;
  }, [auditCache.userOptions]);

  const loadAuditUserOptions = useCallback(
    async (force = false) => {
      const existingOptions = auditCache.userOptions;
      if (!force && existingOptions.length > 0) return;
      try {
        const rows = await listAdminUsers();
        setAuditCache((prev) => ({
          ...prev,
          ownerUserId: selfUserId || null,
          userOptions: mergeAuditUserOptions(prev.userOptions, rows, [], selfUserId, selfDisplayName),
        }));
      } catch {
        // Best effort only. Audit rows can still populate names.
      }
    },
    [auditCache.userOptions, selfDisplayName, selfUserId]
  );

  const loadAuditPage = useCallback(
    async (force = false) => {
      const requestKey = auditQueryKey;
      const userId = auditWorkspace.userFilter === "all" ? undefined : auditWorkspace.userFilter;
      const isFresh =
        hasCachedAuditPage &&
        auditCache.lastRefreshedAt != null &&
        Date.now() - Date.parse(auditCache.lastRefreshedAt) < AUDIT_CACHE_TTL_MS;
      if (!force && isFresh) return;

      latestAuditRequestRef.current = requestKey;
      setAuditError(null);
      setAuditLoading(true);
      try {
        const page = await listAuditEventPage(
          auditWorkspace.pageSize,
          userId,
          auditOffset,
          auditWorkspace.errorsOnly
        );
        if (latestAuditRequestRef.current !== requestKey) return;
        setAuditCache((prev) => ({
          ...prev,
          ownerUserId: selfUserId || null,
          queryKey: requestKey,
          scopeKey: auditScopeKey,
          items: page.items,
          total: page.total,
          lastRefreshedAt: new Date().toISOString(),
          userOptions: mergeAuditUserOptions(prev.userOptions, [], page.items, selfUserId, selfDisplayName),
        }));
      } catch (err: any) {
        if (latestAuditRequestRef.current !== requestKey) return;
        setAuditError(err?.message ?? "Failed to load audit events.");
      } finally {
        if (latestAuditRequestRef.current === requestKey) {
          setAuditLoading(false);
        }
      }
    },
    [
      auditCache.lastRefreshedAt,
      auditOffset,
      auditQueryKey,
      auditScopeKey,
      auditWorkspace.errorsOnly,
      auditWorkspace.pageSize,
      auditWorkspace.userFilter,
      hasCachedAuditPage,
      selfDisplayName,
      selfUserId,
    ]
  );

  useEffect(() => {
    persistStoredState(AUDIT_WORKSPACE_STORAGE_KEY, auditWorkspace);
  }, [auditWorkspace]);

  useEffect(() => {
    persistStoredState(AUDIT_CACHE_STORAGE_KEY, auditCache);
  }, [auditCache]);

  useEffect(() => {
    if ((auditCache.ownerUserId || null) === (selfUserId || null)) return;
    setAuditCache({
      ...defaultAuditCacheState(),
      ownerUserId: selfUserId || null,
    });
    setAuditWorkspace((prev) => ({
      ...prev,
      userFilter: "all",
      page: 1,
    }));
  }, [auditCache.ownerUserId, selfUserId]);

  useEffect(() => {
    if (!allowed) return;
    void loadAuditUserOptions();
  }, [allowed, loadAuditUserOptions]);

  useEffect(() => {
    if (!allowed) return;
    void loadAuditPage();
  }, [allowed, loadAuditPage]);

  const totalAuditPages = Math.max(1, Math.ceil(auditTotal / auditWorkspace.pageSize));
  const auditPageSafe = Math.min(auditWorkspace.page, totalAuditPages);
  const auditStartIdx = auditTotal === 0 ? 0 : (auditPageSafe - 1) * auditWorkspace.pageSize;
  const pagedAuditEvents = auditEvents;

  useEffect(() => {
    if (auditWorkspace.page === auditPageSafe) return;
    setAuditWorkspace((prev) => ({ ...prev, page: auditPageSafe }));
  }, [auditPageSafe, auditWorkspace.page]);

  if (!allowed) {
    return (
      <div className="page">
        <div className="card">
          <div className="cardHeader">
            <h2>Access Denied</h2>
          </div>
          <div className="cardBody">
            <p className="muted">Admin access is required (`screening.admin`).</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <section className="pageHero" aria-label="Audit Log">
        <div className="pageHeroMain">
          <div className="pageHeroHead">
            <span className="pageHeroIcon" aria-hidden="true">
              <SectionIcon />
            </span>
            <div>
              <p className="pageHeroEyebrow">Audit Log</p>
              <h1 className="pageHeroTitle">Enterprise Activity Monitoring</h1>
            </div>
          </div>
          <p className="pageHeroSub">Track system and user actions across screening, scheduling, notifications, and administration to support compliance traceability.</p>
        </div>
        <div className="pageHeroMeta" aria-hidden="true">
          <span className="pageHeroPill">{auditTotal} Events</span>
          <span className="pageHeroPill">Admin Scope</span>
          <span className="pageHeroPill">Paginated View</span>
        </div>
      </section>

      <div className="card">
        <div className="cardHeader">
          <h2 className="userAdminSectionTitle">
            <span className="userAdminInlineIcon" aria-hidden="true">
              <SectionIcon />
            </span>
            Audit Log
          </h2>
        </div>
        <div className="cardBody">
          <div className="adminScheduleHeader" style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <div className="field" style={{ minWidth: 220 }}>
                <label>User Filter</label>
                <select
                  value={auditWorkspace.userFilter}
                  onChange={(e) => {
                    setAuditWorkspace((prev) => ({
                      ...prev,
                      userFilter: e.target.value,
                      page: 1,
                    }));
                  }}
                >
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
                  checked={auditWorkspace.errorsOnly}
                  onChange={(e) => {
                    setAuditWorkspace((prev) => ({
                      ...prev,
                      errorsOnly: e.target.checked,
                      page: 1,
                    }));
                  }}
                />
                <span>Show errors only</span>
              </label>
            </div>
            <button
              type="button"
              className="btnGhost"
              onClick={() => {
                void loadAuditUserOptions(true);
                void loadAuditPage(true);
              }}
              disabled={auditLoading}
            >
              {auditLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          {auditError ? <div className="errorBox" role="alert" aria-live="assertive">{auditError}</div> : null}

          <div className="auditPagerRow">
            <div className="pagerText">
              Showing {auditTotal === 0 ? 0 : auditStartIdx + 1} to {Math.min(auditTotal, auditStartIdx + auditWorkspace.pageSize)} of {auditTotal} audit events
            </div>
            <div className="auditPagerRight">
              <div className="field auditPagerSizeField">
                <label>Records per page</label>
                <select
                  value={auditWorkspace.pageSize}
                  onChange={(e) => {
                    const next = Number(e.target.value);
                    if (next === 100 || next === 200 || next === 300) {
                      setAuditWorkspace((prev) => ({
                        ...prev,
                        pageSize: next,
                        page: 1,
                      }));
                    }
                  }}
                >
                  {pageSizeOptions.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </div>
              <div className="auditPagerNav">
                <button
                  className="auditPagerArrow"
                  disabled={auditPageSafe <= 1}
                  onClick={() =>
                    setAuditWorkspace((prev) => ({
                      ...prev,
                      page: Math.max(1, prev.page - 1),
                    }))
                  }
                  type="button"
                  aria-label="Previous page"
                  title="Previous page"
                >
                  <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
                    <path d="M12.5 4.5 7 10l5.5 5.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
                <div className="auditPagerMeta">Page {auditPageSafe} of {totalAuditPages}</div>
                <button
                  className="auditPagerArrow"
                  disabled={auditPageSafe >= totalAuditPages}
                  onClick={() =>
                    setAuditWorkspace((prev) => ({
                      ...prev,
                      page: Math.min(totalAuditPages, prev.page + 1),
                    }))
                  }
                  type="button"
                  aria-label="Next page"
                  title="Next page"
                >
                  <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
                    <path d="m7.5 4.5 5.5 5.5-5.5 5.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col" style={{ width: 180 }}>Time</th>
                  <th scope="col" style={{ width: 220 }}>User</th>
                  <th scope="col" style={{ width: 220 }}>Action</th>
                  <th scope="col" style={{ width: 360 }}>Entity</th>
                  <th scope="col">Error</th>
                </tr>
              </thead>
              <tbody>
                {pagedAuditEvents.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="emptyRow">
                      {auditLoading ? "Loading audit events..." : "No audit events found."}
                    </td>
                  </tr>
                ) : (
                  pagedAuditEvents.map((event) => {
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
