import { useMemo } from "react";
import { iso31661, iso31661Alpha2ToAlpha3 } from "iso-3166";

type Props = {
  label: string;
  value: string;
  onChange: (iso3: string) => void;
  placeholder?: string;
  hint?: string;
};

function normalize(s: string) {
  return (s ?? "").trim().toUpperCase();
}

type IsoCountryEntry = {
  alpha2: string;
  alpha3: string;
  name: string;
};

const ISO3_OPTIONS: IsoCountryEntry[] = iso31661
  .map((entry) => ({
    alpha2: normalize(entry.alpha2),
    alpha3: normalize(entry.alpha3),
    name: String(entry.name ?? "").trim(),
  }))
  .filter((entry) => entry.alpha2 && entry.alpha3 && entry.name)
  .sort((left, right) => left.alpha3.localeCompare(right.alpha3));

export function CountryAutosuggest({ label, value, onChange, placeholder, hint }: Props) {
  const normalizedValue = useMemo(() => {
    const raw = normalize(value);
    if (!raw) return "";
    if (raw.length === 2) return String((iso31661Alpha2ToAlpha3 as Record<string, string>)[raw] ?? raw);
    return raw;
  }, [value]);

  const isKnownCountry = useMemo(
    () => ISO3_OPTIONS.some((entry) => entry.alpha3 === normalizedValue),
    [normalizedValue]
  );

  function handleChange(raw: string) {
    onChange(normalize(raw));
  }

  return (
    <div className="field">
      {hint ? (
        <div className="labelRow">
          <label>{label || "\u00A0"}</label>
          <span className="hint">{hint}</span>
        </div>
      ) : (
        <label>{label || "\u00A0"}</label>
      )}

      <select
        value={normalizedValue}
        onChange={(e) => handleChange(e.target.value)}
        aria-label={label || "Country"}
      >
        <option value="">{placeholder ?? "Select ISO3 country code"}</option>
        {!isKnownCountry && normalizedValue ? <option value={normalizedValue}>{normalizedValue}</option> : null}
        {ISO3_OPTIONS.map((entry) => (
          <option key={entry.alpha3} value={entry.alpha3}>
            {entry.alpha3} - {entry.name}
          </option>
        ))}
      </select>
    </div>
  );
}
