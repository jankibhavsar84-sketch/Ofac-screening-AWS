import { useEffect } from "react";
import { Outlet, createRootRoute, Link, useRouterState } from "@tanstack/react-router";
import { useRecoilState } from "recoil";
import { activeUserIdState, usersState } from "../state/users";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isUserAdministrationPage = pathname.startsWith("/manage-users");
  const [users] = useRecoilState(usersState);
  const [activeUserId, setActiveUserId] = useRecoilState(activeUserIdState);

  useEffect(() => {
    if (users.length === 0) {
      if (activeUserId) setActiveUserId(null);
      return;
    }

    const exists = users.some((u) => u.id === activeUserId);
    if (!exists) setActiveUserId(users[0].id);
  }, [users, activeUserId, setActiveUserId]);

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
          <div className="activeUserPicker">
            <label htmlFor="active-user-select">User</label>
            <select
              id="active-user-select"
              value={activeUserId ?? ""}
              onChange={(e) => setActiveUserId(e.target.value || null)}
              disabled={users.length === 0}
            >
              {users.length === 0 ? <option value="">No users</option> : null}
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      <main className="pageMain">
        <Outlet />
      </main>
    </div>
  );
}
