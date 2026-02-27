import type { AuthProviderProps } from "react-oidc-context";
import { WebStorageStateStore } from "oidc-client-ts";
import { appEnv } from "../config/env";

function env(name: string, fallback = ""): string {
  return appEnv(name, fallback);
}

function envInt(name: string, fallback: number): number {
  const raw = env(name, String(fallback));
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0) return fallback;
  return Math.floor(parsed);
}

function envBool(name: string, fallback: boolean): boolean {
  const raw = env(name, fallback ? "true" : "false").toLowerCase();
  if (["1", "true", "yes", "y", "on"].includes(raw)) return true;
  if (["0", "false", "no", "n", "off"].includes(raw)) return false;
  return fallback;
}

export const oidcAuthEnabled = envBool("VITE_AUTH_ENABLED", true);

const authority = env(
  "VITE_OIDC_AUTHORITY",
  oidcAuthEnabled ? "http://localhost:8081/realms/screening-local" : "http://127.0.0.1/oidc-disabled"
);
const clientId = env("VITE_OIDC_CLIENT_ID", "screening-frontend");

const redirectUri = env("VITE_OIDC_REDIRECT_URI", `${window.location.origin}/`);
const postLogoutRedirectUri = env("VITE_OIDC_POST_LOGOUT_REDIRECT_URI", `${window.location.origin}/`);
// Cognito does not support `roles` default scope. Use standard OIDC scopes by default.
const defaultScope = authority.includes("amazoncognito.com") ? "openid profile email" : "openid profile email roles";
const scope = env("VITE_OIDC_SCOPE", defaultScope);
export const oidcIdleTimeoutMs = envInt("VITE_OIDC_IDLE_TIMEOUT_MS", 15 * 60 * 1000);
export const oidcClearSessionOnClose = envBool("VITE_OIDC_CLEAR_SESSION_ON_CLOSE", true);

export const oidcConfig: AuthProviderProps = {
  authority,
  client_id: clientId,
  redirect_uri: redirectUri,
  post_logout_redirect_uri: postLogoutRedirectUri,
  response_type: "code",
  scope,
  automaticSilentRenew: oidcAuthEnabled,
  loadUserInfo: oidcAuthEnabled,
  monitorSession: oidcAuthEnabled,
  userStore: new WebStorageStateStore({
    store: oidcClearSessionOnClose ? window.sessionStorage : window.localStorage,
  }),
  stateStore: new WebStorageStateStore({
    store: oidcClearSessionOnClose ? window.sessionStorage : window.localStorage,
  }),
};

if (oidcAuthEnabled && !appEnv("VITE_OIDC_AUTHORITY", "").trim()) {
  console.warn("VITE_OIDC_AUTHORITY is not set. Using local default authority:", authority);
}
if (oidcAuthEnabled && !appEnv("VITE_OIDC_CLIENT_ID", "").trim()) {
  console.warn("VITE_OIDC_CLIENT_ID is not set. Using local default client_id:", clientId);
}

export function clearSigninQueryParams(): void {
  const url = new URL(window.location.href);
  const hadParams =
    url.searchParams.has("code") ||
    url.searchParams.has("state") ||
    url.searchParams.has("session_state");
  if (!hadParams) return;
  url.searchParams.delete("code");
  url.searchParams.delete("state");
  url.searchParams.delete("session_state");
  window.history.replaceState({}, document.title, `${url.pathname}${url.search}${url.hash}`);
}
