import { useMemo, useRef } from "react";

type IsoDateInputProps = {
  value: string;
  onChange: (value: string) => void;
  id?: string;
  name?: string;
  disabled?: boolean;
  required?: boolean;
  placeholder?: string;
  onBlur?: () => void;
};

function isValidIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const d = new Date(value + "T00:00:00Z");
  if (Number.isNaN(d.getTime())) return false;
  const [yy, mm, dd] = value.split("-").map(Number);
  return d.getUTCFullYear() === yy && d.getUTCMonth() + 1 === mm && d.getUTCDate() === dd;
}

export function IsoDateInput({
  value,
  onChange,
  id,
  name,
  disabled,
  required,
  placeholder = "YYYY-MM-DD",
  onBlur,
}: IsoDateInputProps) {
  const pickerRef = useRef<HTMLInputElement | null>(null);

  const pickerValue = useMemo(() => {
    const trimmed = value.trim();
    return isValidIsoDate(trimmed) ? trimmed : "";
  }, [value]);

  function openCalendar() {
    const picker = pickerRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    if (!picker || disabled) return;
    if (typeof picker.showPicker === "function") {
      picker.showPicker();
      return;
    }
    picker.focus();
    picker.click();
  }

  return (
    <div className="isoDateWrap">
      <input
        id={id}
        name={name}
        className="isoDateText"
        type="text"
        inputMode="numeric"
        maxLength={10}
        placeholder={placeholder}
        pattern="\d{4}-\d{2}-\d{2}"
        title="Use YYYY-MM-DD format"
        autoComplete="bday"
        value={value}
        onBlur={onBlur}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        required={required}
      />

      <button
        type="button"
        className="isoDateBtn"
        onClick={openCalendar}
        disabled={disabled}
        aria-label="Open calendar"
        title="Open calendar"
      >
        <svg
          className="isoDateIcon"
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      </button>

      <input
        ref={pickerRef}
        type="date"
        className="isoDatePickerInput"
        tabIndex={-1}
        aria-hidden="true"
        value={pickerValue}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      />
    </div>
  );
}
