import { Outlet, createRootRoute, Link, useRouterState } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isUserAdministrationPage = pathname.startsWith("/manage-users");

  return (
    <div className="appShell">
      <header className="topHeader">
        <div className="topHeaderInner page">
          <div className="brandRow">
            <div className="brandIcon" aria-hidden="true">{"\u{1F6E1}\uFE0F"}</div>
            <div className="brandText">
              <div className="brandTitle">
                {isUserAdministrationPage ? "User Administration" : "OFAC Screening"}
              </div>
              <div className="brandSub">
                {isUserAdministrationPage
                  ? "Manage team members and access levels"
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
            <Link to="/manage-users" className="navLink" activeProps={{ className: "navLink active" }}>
              User Administration
            </Link>
          </nav>
        </div>
      </header>

      <main className="pageMain">
        <Outlet />
      </main>
    </div>
  );
}
