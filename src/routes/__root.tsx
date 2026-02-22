import * as React from "react";
import { Outlet, createRootRoute, Link } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  return (
    <div className="appShell">
      <header className="topHeader">
        <div className="topHeaderInner page">
          <div className="brandRow">
            <div className="brandIcon" aria-hidden="true">{"\u{1F6E1}\uFE0F"}</div>
            <div className="brandText">
              <div className="brandTitle">OFAC Screening</div>
              <div className="brandSub">Sanctions compliance screening platform</div>
            </div>
          </div>

          <nav className="topNav">
            <Link to="/intro" className="navLink" activeProps={{ className: "navLink active" }}>
              Introduction
            </Link>
            <Link to="/screening" className="navLink" activeProps={{ className: "navLink active" }}>
              Screening
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
