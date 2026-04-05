import React from "react";
import ReactDOM from "react-dom/client";
import { RecoilRoot } from "recoil";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { AuthProvider } from "react-oidc-context";
import { routeTree } from "./routeTree.gen";
import { AuthGate } from "./components/AuthGate";
import { clearSigninQueryParams, oidcConfig } from "./auth/oidc";
import "./styles.css";

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider {...oidcConfig} onSigninCallback={clearSigninQueryParams}>
      <AuthGate>
        <RecoilRoot>
          <RouterProvider router={router} />
        </RecoilRoot>
      </AuthGate>
    </AuthProvider>
  </React.StrictMode>
);
