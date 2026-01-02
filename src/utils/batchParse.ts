import * as XLSX from "xlsx";

export type BatchRow = {
  customerType: "Person" | "Entity";
  firstName?: string;
  middleName?: string;
  lastName?: string;
  fullName?: string;
  aliasName?: string;

  addressLine1?: string;
  addressLine2?: string;
  city?: string;
  state?: string;
  zip?: string;
  country?: string;

  idCode?: string;
  idNumber?: string;
  idIssueCountry?: string;

  countryOfBirth?: string;
  dateOfBirth?: string;
  countryOfCitizenship?: string;
};

function normalizeCustomerType(v: any): "Person" | "Entity" {
  const s = String(v ?? "").trim().toLowerCase();
  return s === "entity" ? "Entity" : "Person";
}

function getStr(v: any): string {
  return String(v ?? "").trim();
}

// Case-insensitive getter
function getCI(map: Record<string, any>, key: string) {
  return map[key.toLowerCase()];
}

export async function parseCsv(file: File): Promise<BatchRow[]> {
  const text = await file.text();
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) return [];

  const headers = splitCsvLine(lines[0]).map((h) => h.trim().toLowerCase());

  const idx = (name: string) => headers.indexOf(name.toLowerCase());

  const rows: BatchRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = splitCsvLine(lines[i]);
    const get = (name: string) => {
      const j = idx(name);
      return j >= 0 ? cols[j] : "";
    };

    rows.push({
      customerType: normalizeCustomerType(get("customerType")),
      firstName: getStr(get("firstName")),
      middleName: getStr(get("middleName")),
      lastName: getStr(get("lastName")),
      fullName: getStr(get("fullName")),
      aliasName: getStr(get("aliasName")),

      addressLine1: getStr(get("addressLine1")),
      addressLine2: getStr(get("addressLine2")),
      city: getStr(get("city")),
      state: getStr(get("state")),
      zip: getStr(get("zip")),
      country: getStr(get("country")),

      idCode: getStr(get("idCode")),
      idNumber: getStr(get("idNumber")),
      idIssueCountry: getStr(get("idIssueCountry")),

      countryOfBirth: getStr(get("countryOfBirth")),
      dateOfBirth: getStr(get("dateOfBirth")),
      countryOfCitizenship: getStr(get("countryOfCitizenship")),
    });
  }

  return rows;
}

export async function parseExcel(file: File): Promise<BatchRow[]> {
  const buf = await file.arrayBuffer();
  const wb = XLSX.read(buf, { type: "array" });
  const sheetName = wb.SheetNames[0];
  const ws = wb.Sheets[sheetName];

  const json = XLSX.utils.sheet_to_json<Record<string, any>>(ws, { defval: "" });

  const rows: BatchRow[] = json.map((r) => {
    const map = Object.fromEntries(Object.entries(r).map(([k, v]) => [k.trim().toLowerCase(), v]));
    return {
      customerType: normalizeCustomerType(getCI(map, "customerType")),

      firstName: getStr(getCI(map, "firstName")),
      middleName: getStr(getCI(map, "middleName")),
      lastName: getStr(getCI(map, "lastName")),
      fullName: getStr(getCI(map, "fullName")),
      aliasName: getStr(getCI(map, "aliasName")),

      addressLine1: getStr(getCI(map, "addressLine1")),
      addressLine2: getStr(getCI(map, "addressLine2")),
      city: getStr(getCI(map, "city")),
      state: getStr(getCI(map, "state")),
      zip: getStr(getCI(map, "zip")),
      country: getStr(getCI(map, "country")),

      idCode: getStr(getCI(map, "idCode")),
      idNumber: getStr(getCI(map, "idNumber")),
      idIssueCountry: getStr(getCI(map, "idIssueCountry")),

      countryOfBirth: getStr(getCI(map, "countryOfBirth")),
      dateOfBirth: getStr(getCI(map, "dateOfBirth")),
      countryOfCitizenship: getStr(getCI(map, "countryOfCitizenship")),
    };
  });

  return rows;
}

// CSV splitter with support for quoted fields
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i++) {
    const ch = line[i];

    if (ch === '"' && line[i + 1] === '"') {
      cur += '"';
      i++;
      continue;
    }
    if (ch === '"') {
      inQuotes = !inQuotes;
      continue;
    }
    if (ch === "," && !inQuotes) {
      out.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }

  out.push(cur);
  return out.map((s) => s.trim());
}
