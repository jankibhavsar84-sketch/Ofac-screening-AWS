import type { User } from "oidc-client-ts";
import { appEnv } from "../config/env";

export type AuthIdentity = {
  id: string;
  name: string;
  email: string;
  scopes: Set<string>;
  roles: Set<string>;
};

export type AppRole = "admin" | "compliance" | "analyst" | "viewer";

const ROLE_PERMISSION_MAP: Record<AppRole, string[]> = {
  viewer: ["screening.read", "screening.single.mock"],
  analyst: ["screening.read", "screening.write"],
  compliance: ["screening.read", "screening.write", "screening.daily"],
  admin: ["screening.read", "screening.write", "screening.daily", "screening.admin", "screening.useradmin", "screening.single.mock"],
};

function toStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((v) => String(v).trim()).filter(Boolean);
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }
  return [];
}

function normalizeRole(role: string): string {
  const normalized = role.trim().toLowerCase().replace(/[\s_-]+/g, " ");
  if (!normalized) return "";
  if (["admin", "screening admin", "screening.admin", "screening-admin"].includes(normalized)) return "admin";
  if (["compliance", "compliance officer"].includes(normalized)) return "compliance";
  if (normalized === "analyst") return "analyst";
  if (normalized === "viewer") return "viewer";
  return role.trim().toLowerCase();
}

function parseScopes(profile: Record<string, unknown>): Set<string> {
  const scopes = new Set<string>();

  const scope = profile.scope;
  if (typeof scope === "string") {
    scope
      .split(" ")
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((s) => scopes.add(s));
  }

  toStringArray(profile.scp).forEach((s) => scopes.add(s));
  return scopes;
}

function parseRoles(profile: Record<string, unknown>): Set<string> {
  const roles = new Set<string>();

  toStringArray(profile.roles).forEach((r) => roles.add(normalizeRole(r)));
  toStringArray(profile.groups).forEach((r) => roles.add(normalizeRole(r)));
  toStringArray(profile["cognito:groups"]).forEach((r) => roles.add(normalizeRole(r)));
  toStringArray(profile["custom:roles"]).forEach((r) => roles.add(normalizeRole(r)));

  return roles;
}

function decodeJwtPayload(token: string | null | undefined): Record<string, unknown> | null {
  const raw = String(token ?? "").trim();
  if (!raw) return null;
  const parts = raw.split(".");
  if (parts.length < 2) return null;

  try {
    const payloadPart = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payloadPart + "=".repeat((4 - (payloadPart.length % 4)) % 4);
    const json = atob(padded);
    const parsed = JSON.parse(json);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // ignore malformed token payloads
  }
  return null;
}

function firstNonEmpty(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
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

export function buildIdentity(user: User | null | undefined): AuthIdentity | null {
  const profile = (user?.profile ?? {}) as Record<string, unknown>;
  const accessTokenClaims = decodeJwtPayload(user?.access_token);

  const id = firstNonEmpty(
    profile.sub,
    profile.preferred_username,
    profile["cognito:username"],
    profile.username,
    profile.email,
    accessTokenClaims?.sub,
    accessTokenClaims?.preferred_username,
    accessTokenClaims?.["cognito:username"],
    accessTokenClaims?.username,
    accessTokenClaims?.email
  );
  const authEnabledRaw = appEnv("VITE_AUTH_ENABLED", "true").toLowerCase();
  const authEnabled = !["0", "false", "no", "off"].includes(authEnabledRaw);
  if (!id && !authEnabled) {
    return {
      id: "local-admin",
      name: "Local Admin",
      email: "local-admin@screening.internal",
      scopes: new Set<string>(["screening.read", "screening.write", "screening.admin"]),
      roles: new Set<string>(["admin", "screening.admin"]),
    };
  }
  if (!id) return null;

  const email = firstNonEmpty(profile.email, accessTokenClaims?.email);
  const preferredName = firstNonEmpty(
    profile.name,
    profile.preferred_username,
    profile["cognito:username"],
    profile.username,
    accessTokenClaims?.name,
    accessTokenClaims?.preferred_username,
    accessTokenClaims?.["cognito:username"],
    accessTokenClaims?.username,
    email,
    id,
  );
  const name = isTechnicalIdentifier(preferredName) ? firstNonEmpty(email, profile["cognito:username"], profile.username, preferredName) : preferredName;

  const scopes = parseScopes(profile);
  const roles = parseRoles(profile);
  if (accessTokenClaims) {
    parseScopes(accessTokenClaims).forEach((scope) => scopes.add(scope));
    parseRoles(accessTokenClaims).forEach((role) => roles.add(role));
  }

  return {
    id,
    name,
    email,
    scopes,
    roles,
  };
}

function permissionSet(identity: AuthIdentity | null): Set<string> {
  if (!identity) return new Set<string>();

  const perms = new Set<string>(Array.from(identity.scopes).map((s) => s.toLowerCase()));
  const normalizedRoles = new Set<string>(Array.from(identity.roles).map((r) => normalizeRole(r)));

  normalizedRoles.forEach((role) => {
    if (role in ROLE_PERMISSION_MAP) {
      ROLE_PERMISSION_MAP[role as AppRole].forEach((perm) => perms.add(perm));
    }
    if (role.startsWith("screening.")) {
      perms.add(role);
    }
  });

  if (perms.has("screening.admin")) {
    ROLE_PERMISSION_MAP.admin.forEach((perm) => perms.add(perm));
  } else if (perms.has("screening.write")) {
    perms.add("screening.read");
  }

  return perms;
}

export function hasPermission(identity: AuthIdentity | null, ...permissionNames: string[]): boolean {
  const required = permissionNames.map((p) => p.trim().toLowerCase()).filter(Boolean);
  if (!required.length) return true;
  const actual = permissionSet(identity);
  return required.some((p) => actual.has(p));
}

export function getPrimaryRole(identity: AuthIdentity | null): AppRole | null {
  if (!identity) return null;
  const roles = new Set<string>(Array.from(identity.roles).map((r) => normalizeRole(r)));
  if (roles.has("admin")) return "admin";
  if (roles.has("compliance")) return "compliance";
  if (roles.has("analyst")) return "analyst";
  if (roles.has("viewer")) return "viewer";

  const perms = permissionSet(identity);
  if (perms.has("screening.admin")) return "admin";
  if (perms.has("screening.daily")) return "compliance";
  if (perms.has("screening.write")) return "analyst";
  if (perms.has("screening.single.mock") || perms.has("screening.read")) return "viewer";
  return null;
}

export function hasRole(identity: AuthIdentity | null, ...roleNames: string[]): boolean {
  if (!identity) return false;
  const required = roleNames.map((r) => normalizeRole(r)).filter(Boolean);
  if (!required.length) return true;
  const actual = new Set<string>(Array.from(identity.roles).map((r) => normalizeRole(r)));
  return required.some((r) => actual.has(r));
}

export function hasScope(identity: AuthIdentity | null, ...scopeNames: string[]): boolean {
  if (!identity) return false;
  const required = scopeNames.map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!required.length) return true;
  const actual = permissionSet(identity);
  return required.some((s) => actual.has(s));
}
