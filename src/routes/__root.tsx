import { useEffect } from "react";
import { Outlet, createRootRoute, Link, useRouterState } from "@tanstack/react-router";
import { useAuth } from "react-oidc-context";
import { buildIdentity, hasRole, hasScope } from "../auth/claims";
import { oidcAuthEnabled } from "../auth/oidc";
import { setAccessToken } from "../auth/session";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isUserAdministrationPage = pathname.startsWith("/manage-users");
  const isDailySchedulePage = pathname.startsWith("/daily-schedules");
  const auth = useAuth();
  const identity = buildIdentity(auth.user);
  const canManageUsers = hasRole(identity, "admin", "screening.admin") || hasScope(identity, "screening.admin");

  useEffect(() => {
    setAccessToken(oidcAuthEnabled ? auth.user?.access_token ?? null : null);
  }, [auth.user]);

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
            {canManageUsers ? (
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
                className="btnGhost"
                onClick={() => void auth.signoutRedirect()}
                title="Sign out"
              >
                Sign Out
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
