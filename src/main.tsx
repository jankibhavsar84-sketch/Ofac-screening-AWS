import React from "react";
import ReactDOM from "react-dom/client";
import { RecoilRoot } from "recoil";
import {
  RouterProvider,
  createRouter,
  createRootRoute,
  createRoute,
  Outlet,
} from "@tanstack/react-router";
import "./styles.css";
import { ScreeningDetailPage } from "./screens/ScreeningDetailPage";
import { ResultsPage } from "./screens/ResultsPage";

const rootRoute = createRootRoute({
  component: () => (
    <div className="app">
      <div className="header">
        <div className="headerInner">
          <div className="brand">
            <div className="logo" />
            <div className="brandText">
              <h1>OFAC Screening</h1>
              <p>Banking/FinTech • Customer screening intake</p>
            </div>
          </div>

          {/* Top-right title */}
          <div className="headerMeta">
            <span className="pill">Tapan Inc.</span>
          </div>
        </div>
      </div>

      <div className="main">
        <Outlet />
      </div>
    </div>
  ),
});

const detailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: ScreeningDetailPage,
});

const resultsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/results",
  component: ResultsPage,
});

const routeTree = rootRoute.addChildren([detailRoute, resultsRoute]);
const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RecoilRoot>
      <RouterProvider router={router} />
    </RecoilRoot>
  </React.StrictMode>
);
