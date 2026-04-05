import { useEffect, useId, useMemo, useRef, useState } from "react";
import { getData } from "country-list";

type Props = {
  label: string;
  value: string; // we will store ISO2 like "US"
  onChange: (iso2: string) => void;
  placeholder?: string;
  hint?: string;
};

function normalize(s: string) {
  return (s ?? "").trim();
}

export function CountryAutosuggest({ label, value, onChange, placeholder, hint }: Props) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const inputId = useId();
  const listboxId = `${inputId}-listbox`;

  // [{ code: 'US', name: 'United States' }, ...]
  const countries = useMemo(() => getData(), []);

  // display text for input (show ISO2 + name)
  const displayValue = useMemo(() => {
    const iso = normalize(value).toUpperCase();
    const found = countries.find((c) => c.code.toUpperCase() === iso);
    return found ? `${found.code} - ${found.name}` : value;
  }, [value, countries]);

  const suggestions = useMemo(() => {
    const q = normalize(displayValue).toLowerCase();
    if (!q) return countries.slice(0, 12);
    return countries
      .filter((c) => c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q))
      .slice(0, 12);
  }, [countries, displayValue]);

  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (!rootRef.current) return;
      if (e.target instanceof Node && !rootRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  function handleInput(raw: string) {
    const txt = normalize(raw);

    // user typed ISO2
    if (/^[A-Za-z]{2}$/.test(txt)) {
      onChange(txt.toUpperCase());
      return;
    }

    // user selected "US - United States"
    const dashIdx = txt.indexOf(" - ");
    if (dashIdx > 0) {
      const maybeCode = txt.slice(0, dashIdx).trim();
      if (/^[A-Za-z]{2}$/.test(maybeCode)) {
        onChange(maybeCode.toUpperCase());
        return;
      }
    }

    // user typed a country name -> map by name
    const foundByName = countries.find((c) => c.name.toLowerCase() === txt.toLowerCase());
    if (foundByName) {
      onChange(foundByName.code.toUpperCase());
      return;
    }

    // fallback: keep raw (won't block user)
    onChange(txt);
  }

  return (
    <div ref={rootRef} className="field countryAutosuggest">
      {hint ? (
        <div className="labelRow">
          <label htmlFor={inputId}>{label}</label>
          <span className="hint">{hint}</span>
        </div>
      ) : (
        <label htmlFor={inputId}>{label}</label>
      )}

      <input
        id={inputId}
        value={displayValue}
        onChange={(e) => handleInput(e.target.value)}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder={placeholder ?? "Type country name or ISO2 (US, IN)"}
        autoComplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listboxId}
      />

      {open && suggestions.length > 0 ? (
        <div id={listboxId} className="countrySuggestions" role="listbox" aria-label="Country suggestions">
          {suggestions.map((c) => (
            <button
              key={c.code}
              type="button"
              className="countryOption"
              role="option"
              aria-selected={c.code.toUpperCase() === normalize(value).toUpperCase()}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(c.code.toUpperCase());
                setOpen(false);
              }}
            >
              {c.code} - {c.name}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
