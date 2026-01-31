type Tab = "INTRO" | "SCREEN" | "RESULTS";

export function AppTabs({
  active,
  onChange,
}: {
  active: Tab;
  onChange: (t: Tab) => void;
}) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "INTRO", label: "Introduction" },
    { key: "SCREEN", label: "Screening" },
    { key: "RESULTS", label: "Results & Queue" },
  ];

  return (
    <div style={{ display: "flex", gap: 16, borderBottom: "1px solid #e2e8f0" }}>
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          style={{
            padding: "10px 16px",
            border: "none",
            background: "none",
            borderBottom: active === t.key ? "3px solid #1e40af" : "3px solid transparent",
            fontWeight: active === t.key ? 700 : 500,
            cursor: "pointer",
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
