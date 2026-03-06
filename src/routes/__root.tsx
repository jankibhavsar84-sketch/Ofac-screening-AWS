import { useEffect, useState } from "react";
import { Outlet, createRootRoute, Link } from "@tanstack/react-router";
import { useAuth } from "react-oidc-context";
import { buildIdentity, hasPermission } from "../auth/claims";
import { oidcAuthEnabled, oidcUseRpInitiatedLogout, redirectToSignedOutPage } from "../auth/oidc";
import { setAccessToken } from "../auth/session";

type ThemeMode = "light" | "dark";
const THEME_STORAGE_KEY = "ws-theme-mode";

function getInitialThemeMode(): ThemeMode {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => getInitialThemeMode());
  const auth = useAuth();
  const identity = buildIdentity(auth.user);
  const canManageUsers = hasPermission(identity, "screening.admin", "screening.useradmin");
  const canViewAuditLogs = hasPermission(identity, "screening.admin");
  const canManageDailySchedules = hasPermission(identity, "screening.daily", "screening.admin");

  useEffect(() => {
    setAccessToken(oidcAuthEnabled ? auth.user?.access_token ?? null : null);
  }, [auth.user]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", themeMode);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
    } catch {
      // Ignore storage errors (private mode/browser policy).
    }
  }, [themeMode]);

  const handleSignOut = async () => {
    if (isSigningOut) return;
    setIsSigningOut(true);
    try {
      await auth.removeUser();
      if (!oidcUseRpInitiatedLogout) {
        redirectToSignedOutPage();
      } else {
        try {
          await auth.signoutRedirect();
        } catch {
          redirectToSignedOutPage();
        }
      }
    } catch {
      redirectToSignedOutPage();
    } finally {
      setIsSigningOut(false);
    }
  };

  return (
    <div className="appShell">
      <a href="#main-content" className="skipLink">Skip to main content</a>
      <header className="topHeader">
        <div className="topHeaderInner page">
          <div className="brandRow">
            <div className="brandIcon" aria-hidden="true">
              <img src="/Circle_Pru_Rrock.avif" className="brandIconImg" alt="" />
            </div>
            <div className="brandText">
              <div className="brandTitle">Watchlist Screening</div>
              <div className="brandSub">AML Screening Platform</div>
            </div>
          </div>

          <nav className="topNav" aria-label="Primary">
            <Link to="/intro" className="navLink" activeProps={{ className: "navLink active" }}>
              Introduction
            </Link>
            <Link to="/screening" className="navLink" activeProps={{ className: "navLink active" }}>
              Screening
            </Link>
            {canManageDailySchedules ? (
              <Link to="/daily-schedules" className="navLink" activeProps={{ className: "navLink active" }}>
                Daily Schedules
              </Link>
            ) : null}
            {canManageUsers ? (
              <Link to="/manage-users" className="navLink" activeProps={{ className: "navLink active" }}>
                User Administration
              </Link>
            ) : null}
            {canViewAuditLogs ? (
              <Link to="/audit-logs" className="navLink" activeProps={{ className: "navLink active" }}>
                Audit Log
              </Link>
            ) : null}
          </nav>
          <div className="authUserPanel">
            <label className="themeToggle" title={`Switch to ${themeMode === "light" ? "dark" : "light"} mode`}>
              <input
                className="themeToggleInput"
                type="checkbox"
                checked={themeMode === "dark"}
                onChange={(e) => setThemeMode(e.target.checked ? "dark" : "light")}
                aria-label="Toggle light and dark mode"
              />
              <span className="themeToggleTrack" aria-hidden="true">
                <span className="themeToggleThumb" />
              </span>
              <span className="themeToggleText">{themeMode === "dark" ? "Dark" : "Light"}</span>
            </label>
            <div className="authUserMeta">
              <div className="authUserName">{identity?.name ?? "Unknown User"}</div>
              <div className="authUserEmail">{identity?.email || identity?.id || ""}</div>
            </div>
            {oidcAuthEnabled ? (
              <button
                type="button"
                className="btnGhost btnSignOut"
                onClick={() => void handleSignOut()}
                title="Sign out"
                disabled={isSigningOut}
              >
                <span className="btnSignOutIcon" aria-hidden="true">
                  <svg viewBox="0 0 20 20" width="14" height="14" focusable="false">
                    <path d="M3 10h8M8 6l4 4-4 4M12 3h3a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-3" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <span>{isSigningOut ? "Signing Out..." : "Sign Out"}</span>
              </button>
            ) : (
              <span className="chip chipWarning">Auth Disabled</span>
            )}
          </div>
        </div>
      </header>

      <main id="main-content" className="pageMain" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
