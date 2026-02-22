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
        Cal
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
