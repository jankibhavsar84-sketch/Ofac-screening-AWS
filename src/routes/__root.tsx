import { useEffect, useState } from "react";
import { Outlet, createRootRoute, Link, useRouterState } from "@tanstack/react-router";
import { useAuth } from "react-oidc-context";
import { buildIdentity, hasPermission } from "../auth/claims";
import { oidcAuthEnabled, oidcUseRpInitiatedLogout, redirectToSignedOutPage } from "../auth/oidc";
import { setAccessToken } from "../auth/session";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const [isSigningOut, setIsSigningOut] = useState(false);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isUserAdministrationPage = pathname.startsWith("/manage-users");
  const isDailySchedulePage = pathname.startsWith("/daily-schedules");
  const auth = useAuth();
  const identity = buildIdentity(auth.user);
  const canManageUsers = hasPermission(identity, "screening.admin", "screening.useradmin");
  const canManageDailySchedules = hasPermission(identity, "screening.daily", "screening.admin");

  useEffect(() => {
    setAccessToken(oidcAuthEnabled ? auth.user?.access_token ?? null : null);
  }, [auth.user]);

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
      <header className="topHeader">
        <div className="topHeaderInner page">
          <div className="brandRow">
            <div className="brandIcon" aria-hidden="true">{"\u{1F6E1}\uFE0F"}</div>
            <div className="brandText">
              <div className="brandTitle">
                {isUserAdministrationPage
                  ? "User Administration"
                  : isDailySchedulePage
                    ? "Daily Schedule Administration"
                    : "OFAC Screening"}
              </div>
              <div className="brandSub">
                {isUserAdministrationPage
                  ? "Manage team members and access levels"
                  : isDailySchedulePage
                    ? "Remove batch files from daily screening schedules"
                    : "Sanctions compliance screening platform"}
              </div>
            </div>
          </div>

          <nav className="topNav">
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
          </nav>
          <div className="authUserPanel">
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

      <main className="pageMain">
        <Outlet />
      </main>
    </div>
  );
}
