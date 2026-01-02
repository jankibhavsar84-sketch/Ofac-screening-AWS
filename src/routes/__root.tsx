import { Outlet, createRootRoute } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: () => (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: 16 }}>
      <h1>OFAC Screening</h1>
      <Outlet />
    </div>
  ),
});
