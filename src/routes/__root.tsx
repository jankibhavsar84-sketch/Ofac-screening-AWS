import React from "react";
import { Outlet, createRootRoute, Link, useRouterState } from "@tanstack/react-router";

function PrudentialMark() {
  // Simple inline mark (enterprise-safe). Replace later with a real SVG in /public if needed.
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span
        aria-hidden
        style={{
          width: 28,
          height: 28,
          borderRadius: 10,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          background: "rgba(148,163,184,.16)",
          border: "1px solid rgba(148,163,184,.18)",
          fontWeight: 800,
        }}
      >
        P
      </span>
      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.05 }}>
        <span style={{ fontWeight: 800, letterSpacing: 0.2 }}>Prudential</span>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>OFAC Screening Console</span>
      </div>
    </div>
  );
}

function Tabs() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  const items = [
    { to: "/", label: "Introduction" },
    { to: "/screening", label: "Screening" },
    { to: "/results", label: "Results & Queue" },
  ];

  return (
    <div
      style={{
        display: "flex",
        gap: 14,
        borderBottom: "1px solid rgba(148,163,184,.14)",
        marginTop: 14,
      }}
    >
      {items.map((it) => {
        const active = pathname === it.to;
        return (
          <Link
            key={it.to}
            to={it.to}
            className="tabLink"
            style={{
              padding: "10px 12px",
              borderBottom: active ? "3px solid rgba(147,197,253,.95)" : "3px solid transparent",
              color: active ? "rgba(226,232,240,1)" : "rgba(148,163,184,1)",
              fontWeight: active ? 800 : 600,
              textDecoration: "none",
            }}
          >
            {it.label}
          </Link>
        );
      })}
    </div>
  );
}

export const Route = createRootRoute({
  component: function RootLayout() {
    return (
      <div style={{ padding: 18, maxWidth: 1280, margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <PrudentialMark />
          <div className="pill">Prudential</div>
        </div>

        <Tabs />

        <div style={{ marginTop: 16 }}>
          <Outlet />
        </div>
      </div>
    );
  },
});
