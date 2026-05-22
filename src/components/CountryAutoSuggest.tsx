import { useEffect, useId, useMemo, useRef, useState } from "react";
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

const POPULAR_ISO3_CODES = ["USA", "GBR", "IND", "SGP", "CAN", "DEU", "JPN", "AUS", "HKG"];
const OPTION_RENDER_LIMIT = 120;

const ISO3_OPTIONS: IsoCountryEntry[] = iso31661
  .map((entry) => ({
    alpha2: normalize(entry.alpha2),
    alpha3: normalize(entry.alpha3),
    name: String(entry.name ?? "").trim(),
  }))
  .filter((entry) => entry.alpha2 && entry.alpha3 && entry.name)
  .sort((left, right) => {
    const byName = left.name.localeCompare(right.name);
    if (byName !== 0) return byName;
    return left.alpha3.localeCompare(right.alpha3);
  });

const ISO3_BY_CODE = new Map<string, IsoCountryEntry>(ISO3_OPTIONS.map((entry) => [entry.alpha3, entry]));

function formatOptionLabel(entry: IsoCountryEntry) {
  return `${entry.alpha3} - ${entry.name}`;
}

function toIso3Code(rawValue: string) {
  const safe = normalize(rawValue);
  if (!safe) return "";
  if (safe.length === 2) {
    return String((iso31661Alpha2ToAlpha3 as Record<string, string>)[safe] ?? safe);
  }
  return safe;
}

export function CountryAutosuggest({ label, value, onChange, placeholder, hint }: Props) {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);

  const normalizedValue = useMemo(() => toIso3Code(value), [value]);
  const selectedOption = useMemo(() => ISO3_BY_CODE.get(normalizedValue) ?? null, [normalizedValue]);
  const selectedDisplayValue = useMemo(
    () => (selectedOption ? formatOptionLabel(selectedOption) : ""),
    [selectedOption]
  );
  const normalizedSelectedDisplayValue = useMemo(
    () => normalize(selectedDisplayValue),
    [selectedDisplayValue]
  );

  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [inputValue, setInputValue] = useState(() => {
    if (selectedOption) return formatOptionLabel(selectedOption);
    return normalizedValue;
  });

  useEffect(() => {
    const nextDisplay = selectedOption ? formatOptionLabel(selectedOption) : normalizedValue;
    setInputValue(nextDisplay);
  }, [selectedOption, normalizedValue]);

  const filteredOptions = useMemo(() => {
    const query = (inputValue ?? "").trim().toLowerCase();
    const normalizedQuery = normalize(inputValue);
    const treatAsEmptyQuery =
      !query || (normalizedSelectedDisplayValue && normalizedQuery === normalizedSelectedDisplayValue);

    if (treatAsEmptyQuery) {
      const merged: IsoCountryEntry[] = [];
      const seen = new Set<string>();
      for (const code of POPULAR_ISO3_CODES) {
        const option = ISO3_BY_CODE.get(code);
        if (!option || seen.has(option.alpha3)) continue;
        seen.add(option.alpha3);
        merged.push(option);
      }
      for (const option of ISO3_OPTIONS) {
        if (seen.has(option.alpha3)) continue;
        seen.add(option.alpha3);
        merged.push(option);
      }
      return merged.slice(0, OPTION_RENDER_LIMIT);
    }

    return ISO3_OPTIONS.filter((entry) => {
      if (entry.alpha3.includes(normalizedQuery)) return true;
      if (entry.alpha2.includes(normalizedQuery)) return true;
      return entry.name.toLowerCase().includes(query);
    }).slice(0, OPTION_RENDER_LIMIT);
  }, [inputValue, normalizedSelectedDisplayValue]);

  useEffect(() => {
    setHighlightedIndex((current) => {
      if (!filteredOptions.length) return 0;
      return Math.min(current, filteredOptions.length - 1);
    });
  }, [filteredOptions]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const root = rootRef.current;
      if (!root) return;
      if (event.target instanceof Node && !root.contains(event.target)) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function selectOption(option: IsoCountryEntry) {
    onChange(option.alpha3);
    setInputValue(formatOptionLabel(option));
    setOpen(false);
  }

  function commitInput(rawValue: string) {
    const iso3 = toIso3Code(rawValue);
    if (!iso3) {
      onChange("");
      setInputValue("");
      setOpen(false);
      return;
    }

    const known = ISO3_BY_CODE.get(iso3);
    if (known) {
      selectOption(known);
      return;
    }

    // Preserve manually typed 3-letter code if not in library.
    if (iso3.length === 3) {
      onChange(iso3);
      setInputValue(iso3);
      setOpen(false);
      return;
    }

    // Revert invalid free text back to current selected value.
    const fallback = selectedOption ? formatOptionLabel(selectedOption) : normalizedValue;
    setInputValue(fallback);
    setOpen(false);
  }

  return (
    <div className="field countryAutosuggest" ref={rootRef}>
      {hint ? (
        <div className="labelRow">
          <label>{label || "\u00A0"}</label>
          <span className="hint">{hint}</span>
        </div>
      ) : (
        <label>{label || "\u00A0"}</label>
      )}

      <div className="countryInputRow">
        <input
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value);
            setOpen(true);
            setHighlightedIndex(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => commitInput(inputValue)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              if (!open) setOpen(true);
              setHighlightedIndex((current) => Math.min(current + 1, Math.max(filteredOptions.length - 1, 0)));
              return;
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              if (!open) setOpen(true);
              setHighlightedIndex((current) => Math.max(current - 1, 0));
              return;
            }
            if (e.key === "Enter") {
              if (open && filteredOptions[highlightedIndex]) {
                e.preventDefault();
                selectOption(filteredOptions[highlightedIndex]);
                return;
              }
              commitInput(inputValue);
              return;
            }
            if (e.key === "Escape") {
              e.preventDefault();
              setOpen(false);
              const fallback = selectedOption ? formatOptionLabel(selectedOption) : normalizedValue;
              setInputValue(fallback);
            }
          }}
          placeholder={placeholder ?? "Search country by code or name (e.g., USA, United States)"}
          aria-label={label || "Country"}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={
            open && filteredOptions[highlightedIndex]
              ? `${listboxId}-option-${filteredOptions[highlightedIndex].alpha3}`
              : undefined
          }
        />
        <button
          type="button"
          className="countryToggleBtn"
          aria-label={open ? "Hide country options" : "Show country options"}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            setOpen((current) => !current);
            setHighlightedIndex(0);
          }}
        >
          <span aria-hidden="true">{open ? "\u25B2" : "\u25BC"}</span>
        </button>
      </div>

      {open ? (
        <div className="countrySuggestions" role="listbox" id={listboxId}>
          {filteredOptions.length ? (
            filteredOptions.map((entry, index) => {
              const isActive = index === highlightedIndex;
              const optionId = `${listboxId}-option-${entry.alpha3}`;
              return (
                <button
                  key={entry.alpha3}
                  id={optionId}
                  type="button"
                  className={`countryOption${isActive ? " active" : ""}`}
                  role="option"
                  aria-selected={isActive}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectOption(entry)}
                >
                  <span className="countryOptionCode">{entry.alpha3}</span>
                  <span className="countryOptionName">{entry.name}</span>
                </button>
              );
            })
          ) : (
            <div className="countryNoResults">No countries match your search.</div>
          )}
        </div>
      ) : null}

      <div className="countryAssistText">
        {selectedOption ? `Selected: ${selectedOption.name} (${selectedOption.alpha3})` : "Use ISO3 code (3 letters)."}
      </div>
    </div>
  );
}
