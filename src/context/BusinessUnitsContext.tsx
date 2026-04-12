import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "react-oidc-context";
import { buildIdentity } from "../auth/claims";
import { oidcAuthEnabled } from "../auth/oidc";
import { getAccessToken, setAccessToken } from "../auth/session";
import { listMyBusinessUnits, type BusinessUnit } from "../api/screeningApi";

const BUSINESS_UNITS_CACHE_MS = 15 * 60 * 1000;
const BUSINESS_UNITS_STORAGE_KEY_PREFIX = "ofac-screening:business-units:";
const BUSINESS_UNIT_EMPTY_RETRY_DELAYS_MS = [1000, 2500, 5000];
const BUSINESS_UNIT_ERROR_RETRY_DELAYS_MS = [1500, 3500, 7000];

type BusinessUnitOption = {
  code: string;
  name: string;
};

type BusinessUnitsContextValue = {
  businessUnits: BusinessUnit[];
  businessUnitOptions: BusinessUnitOption[];
  businessUnitsError: string | null;
  businessUnitsLoading: boolean;
  businessUnitsResolved: boolean;
  businessUnitsPending: boolean;
  businessUnitsAvailable: boolean;
  reloadBusinessUnits: () => Promise<void>;
};

const BusinessUnitsContext = createContext<BusinessUnitsContextValue | null>(null);

function safeTrim(value: string): string {
  return (value ?? "").trim();
}

function readLocalStorageJson<T>(storageKey: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeLocalStorageJson(storageKey: string, value: unknown) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // Ignore storage quota and browser policy errors.
  }
}

function businessUnitsStorageKey(userId: string): string {
  return `${BUSINESS_UNITS_STORAGE_KEY_PREFIX}${safeTrim(userId)}`;
}

function normalizeBusinessUnits(rows: BusinessUnit[]): BusinessUnit[] {
  return Array.isArray(rows)
    ? rows.map((row) => ({
        business_unit_code: safeTrim(String(row.business_unit_code || "")).toUpperCase(),
        business_unit_name: safeTrim(String(row.business_unit_name || "")),
        is_active: Boolean(row.is_active),
        created_at: row.created_at ?? null,
        updated_at: row.updated_at ?? null,
      }))
    : [];
}

function readCachedBusinessUnits(userId: string): BusinessUnit[] {
  const safeUserId = safeTrim(userId);
  if (!safeUserId) return [];
  const cached = readLocalStorageJson<{ loadedAt?: string; rows?: BusinessUnit[] } | null>(
    businessUnitsStorageKey(safeUserId),
    null
  );
  const loadedAt = safeTrim(String(cached?.loadedAt ?? ""));
  const rows = normalizeBusinessUnits(Array.isArray(cached?.rows) ? cached.rows : []);
  if (!loadedAt || !rows.length) return [];
  const parsed = new Date(loadedAt);
  if (Number.isNaN(parsed.getTime())) return [];
  if (Date.now() - parsed.getTime() > BUSINESS_UNITS_CACHE_MS) return [];
  return rows;
}

function writeCachedBusinessUnits(userId: string, rows: BusinessUnit[]) {
  const safeUserId = safeTrim(userId);
  if (!safeUserId || !rows.length) return;
  writeLocalStorageJson(businessUnitsStorageKey(safeUserId), {
    loadedAt: new Date().toISOString(),
    rows: normalizeBusinessUnits(rows),
  });
}

function toFriendlyBusinessUnitError(error: unknown): string {
  const text = safeTrim(String((error as { message?: string } | null)?.message ?? ""));
  if (!text) return "Failed to load Business Units.";
  if (text.includes("502") || text.includes("503") || text.includes("504")) {
    return "Business Unit service is temporarily unavailable. Please retry in a moment.";
  }
  return text;
}

export function BusinessUnitsProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const identity = useMemo(() => buildIdentity(auth.user), [auth.user]);
  const [bootstrapToken, setBootstrapToken] = useState<string>(() => getAccessToken() ?? "");
  const effectiveAccessToken = safeTrim(auth.user?.access_token || bootstrapToken || "");
  const authReady = !oidcAuthEnabled || Boolean(effectiveAccessToken) || Boolean(identity);
  const requestSeqRef = useRef(0);
  const retryTimerRef = useRef<number | null>(null);
  const [businessUnits, setBusinessUnits] = useState<BusinessUnit[]>([]);
  const [businessUnitsError, setBusinessUnitsError] = useState<string | null>(null);
  const [businessUnitsLoading, setBusinessUnitsLoading] = useState(false);
  const [businessUnitsResolved, setBusinessUnitsResolved] = useState(false);

  useEffect(() => {
    if (!oidcAuthEnabled) {
      setBootstrapToken("");
      return;
    }
    if (auth.user?.access_token) {
      const next = safeTrim(auth.user.access_token);
      if (next && next !== bootstrapToken) {
        setBootstrapToken(next);
      }
      return;
    }
    if (bootstrapToken) return;

    const timer = window.setInterval(() => {
      const token = safeTrim(getAccessToken() || "");
      if (!token) return;
      setBootstrapToken(token);
      window.clearInterval(timer);
    }, 500);

    return () => window.clearInterval(timer);
  }, [auth.user?.access_token, bootstrapToken]);

  useEffect(() => {
    setAccessToken(oidcAuthEnabled ? effectiveAccessToken || null : null);
  }, [effectiveAccessToken]);

  const cacheKey = useMemo(() => {
    const profile = auth.user?.profile as Record<string, unknown> | undefined;
    const fallback = profile?.sub ?? profile?.email ?? profile?.preferred_username ?? "";
    return safeTrim(String(identity?.id || fallback || ""));
  }, [auth.user?.profile, identity?.id]);

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const reloadBusinessUnits = useCallback(
    async (attempt = 1, silent = false) => {
      if (!authReady) return;
      clearRetry();
      const requestSeq = requestSeqRef.current + 1;
      requestSeqRef.current = requestSeq;
      if (!silent) {
        setBusinessUnitsLoading(true);
      }
      if (attempt === 1) {
        setBusinessUnitsError(null);
        setBusinessUnitsResolved(false);
      }

      let willRetry = false;
      try {
        const rows = normalizeBusinessUnits(await listMyBusinessUnits());
        if (requestSeq !== requestSeqRef.current) return;
        if (rows.length > 0) {
          setBusinessUnits(rows);
          setBusinessUnitsError(null);
          setBusinessUnitsResolved(true);
          if (cacheKey) {
            writeCachedBusinessUnits(cacheKey, rows);
          }
          return;
        }

        const cachedRows = cacheKey ? readCachedBusinessUnits(cacheKey) : [];
        if (cachedRows.length > 0) {
          setBusinessUnits(cachedRows);
          setBusinessUnitsError(null);
          setBusinessUnitsResolved(true);
          return;
        }

        const retryDelay = BUSINESS_UNIT_EMPTY_RETRY_DELAYS_MS[attempt - 1];
        if (retryDelay) {
          willRetry = true;
          retryTimerRef.current = window.setTimeout(() => {
            void reloadBusinessUnits(attempt + 1, true);
          }, retryDelay);
          return;
        }

        setBusinessUnits([]);
        setBusinessUnitsResolved(true);
      } catch (error: unknown) {
        if (requestSeq !== requestSeqRef.current) return;
        const cachedRows = cacheKey ? readCachedBusinessUnits(cacheKey) : [];
        if (cachedRows.length > 0) {
          setBusinessUnits(cachedRows);
          setBusinessUnitsResolved(true);
        }

        const retryDelay = BUSINESS_UNIT_ERROR_RETRY_DELAYS_MS[attempt - 1];
        if (retryDelay) {
          willRetry = true;
          retryTimerRef.current = window.setTimeout(() => {
            void reloadBusinessUnits(attempt + 1, true);
          }, retryDelay);
          return;
        }

        setBusinessUnitsError(toFriendlyBusinessUnitError(error));
        setBusinessUnitsResolved(true);
      } finally {
        if (requestSeq === requestSeqRef.current && !willRetry) {
          setBusinessUnitsLoading(false);
        }
      }
    },
    [authReady, cacheKey, clearRetry]
  );

  useEffect(() => {
    clearRetry();
    setBusinessUnitsError(null);
    if (!authReady) {
      setBusinessUnits([]);
      setBusinessUnitsResolved(false);
      setBusinessUnitsLoading(true);
      return;
    }

    const cachedRows = cacheKey ? readCachedBusinessUnits(cacheKey) : [];
    if (cachedRows.length > 0) {
      setBusinessUnits(cachedRows);
      setBusinessUnitsResolved(true);
      setBusinessUnitsLoading(false);
      void reloadBusinessUnits(1, true);
      return;
    }

    setBusinessUnits([]);
    setBusinessUnitsResolved(false);
    void reloadBusinessUnits(1, false);
  }, [authReady, cacheKey, clearRetry, reloadBusinessUnits]);

  useEffect(() => () => {
    clearRetry();
  }, [clearRetry]);

  const businessUnitOptions = useMemo(
    () =>
      [...normalizeBusinessUnits(businessUnits)]
        .map((row) => ({
          code: safeTrim(String(row.business_unit_code || "")).toUpperCase(),
          name: safeTrim(String(row.business_unit_name || "")),
        }))
        .filter((row) => row.code && row.name)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [businessUnits]
  );

  const businessUnitsAvailable = businessUnitOptions.length > 0;
  const businessUnitsPending = !authReady || businessUnitsLoading || (!businessUnitsResolved && !businessUnitsAvailable);

  const value = useMemo<BusinessUnitsContextValue>(
    () => ({
      businessUnits,
      businessUnitOptions,
      businessUnitsError,
      businessUnitsLoading,
      businessUnitsResolved,
      businessUnitsPending,
      businessUnitsAvailable,
      reloadBusinessUnits: async () => {
        await reloadBusinessUnits(1, false);
      },
    }),
    [
      businessUnitOptions,
      businessUnits,
      businessUnitsAvailable,
      businessUnitsError,
      businessUnitsLoading,
      businessUnitsPending,
      businessUnitsResolved,
      reloadBusinessUnits,
    ]
  );

  return <BusinessUnitsContext.Provider value={value}>{children}</BusinessUnitsContext.Provider>;
}

export function useBusinessUnits(): BusinessUnitsContextValue {
  const context = useContext(BusinessUnitsContext);
  if (!context) {
    throw new Error("useBusinessUnits must be used within a BusinessUnitsProvider");
  }
  return context;
}
