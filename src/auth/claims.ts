import type { User } from "oidc-client-ts";

export type AuthIdentity = {
  id: string;
  name: string;
  email: string;
  scopes: Set<string>;
  roles: Set<string>;
};

function toStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((v) => String(v).trim()).filter(Boolean);
  }
  return [];
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

  const realmAccess = profile.realm_access;
  if (realmAccess && typeof realmAccess === "object" && !Array.isArray(realmAccess)) {
    const realmRoles = toStringArray((realmAccess as Record<string, unknown>).roles);
    realmRoles.forEach((r) => roles.add(r));
  }

  const resourceAccess = profile.resource_access;
  if (resourceAccess && typeof resourceAccess === "object" && !Array.isArray(resourceAccess)) {
    Object.values(resourceAccess as Record<string, unknown>).forEach((clientAccess) => {
      if (clientAccess && typeof clientAccess === "object" && !Array.isArray(clientAccess)) {
        const clientRoles = toStringArray((clientAccess as Record<string, unknown>).roles);
        clientRoles.forEach((r) => roles.add(r));
      }
    });
  }

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

export function buildIdentity(user: User | null | undefined): AuthIdentity | null {
  const profile = (user?.profile ?? {}) as Record<string, unknown>;
  const accessTokenClaims = decodeJwtPayload(user?.access_token);

  const id = firstNonEmpty(
    profile.sub,
    profile.preferred_username,
    profile.email,
    accessTokenClaims?.sub,
    accessTokenClaims?.preferred_username,
    accessTokenClaims?.email
  );
  const authEnabledRaw = String(import.meta.env.VITE_AUTH_ENABLED ?? "true").trim().toLowerCase();
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
  const name = firstNonEmpty(
    profile.name,
    profile.preferred_username,
    accessTokenClaims?.name,
    accessTokenClaims?.preferred_username,
    email,
    id
  );

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

export function hasRole(identity: AuthIdentity | null, ...roleNames: string[]): boolean {
  if (!identity) return false;
  const required = roleNames.map((r) => r.trim().toLowerCase()).filter(Boolean);
  if (!required.length) return true;
  const actual = new Set<string>(Array.from(identity.roles).map((r) => r.toLowerCase()));
  return required.some((r) => actual.has(r));
}

export function hasScope(identity: AuthIdentity | null, ...scopeNames: string[]): boolean {
  if (!identity) return false;
  const required = scopeNames.map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!required.length) return true;
  const actual = new Set<string>(Array.from(identity.scopes).map((s) => s.toLowerCase()));
  return required.some((s) => actual.has(s));
}
