import React, { useId, useMemo } from "react";
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
  const id = useId();
  const listId = `${id}-countries`;

  // [{ code: 'US', name: 'United States' }, ...]
  const countries = useMemo(() => getData(), []);

  // display text for input (show ISO2 + name)
  const displayValue = useMemo(() => {
    const iso = normalize(value).toUpperCase();
    const found = countries.find((c) => c.code.toUpperCase() === iso);
    return found ? `${found.code} - ${found.name}` : value;
  }, [value, countries]);

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
    <div className="field col-6">
      <div className="labelRow">
        <label>{label}</label>
        {hint ? <span className="hint">{hint}</span> : null}
      </div>

      <input
        list={listId}
        value={displayValue}
        onChange={(e) => handleInput(e.target.value)}
        placeholder={placeholder ?? "Type country name or ISO2 (US, IN)"}
      />

      <datalist id={listId}>
        {countries.map((c) => (
          <option key={c.code} value={`${c.code} - ${c.name}`} />
        ))}
      </datalist>
    </div>
  );
}
