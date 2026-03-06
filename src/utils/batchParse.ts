import * as XLSX from "xlsx";

export type BatchRow = {
  partyKey?: string;
  customerType: "Person" | "Entity";
  customerTypeRaw?: string;
  partyType?: string;
  gender?: string;
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
  countries?: string;
  addresses?: string;
  idType?: string;
  idCountry?: string;
};

function normalizeCustomerType(v: any): "Person" | "Entity" {
  const s = String(v ?? "").trim().toLowerCase();
  if (s === "entity" || s === "organization" || s === "company" || s === "e") return "Entity";
  return "Person";
}

function getStr(v: any): string {
  return String(v ?? "").trim();
}

function normalizeHeaderKey(value: string): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function getByAliases(map: Record<string, any>, aliases: string[]): string {
  for (const alias of aliases) {
    const value = map[normalizeHeaderKey(alias)];
    const text = getStr(value);
    if (text) return text;
  }
  return "";
}

function mapParsedRow(map: Record<string, any>): BatchRow {
  const customerTypeRaw = getByAliases(map, ["customerType"]);
  return {
    partyKey: getByAliases(map, ["partyKey", "party_key", "party key"]),
    customerType: normalizeCustomerType(customerTypeRaw || getByAliases(map, ["partyType", "party type", "party_type"])),
    customerTypeRaw,
    partyType: getByAliases(map, ["partyType", "party type", "party_type", "partyTypeCode", "party type code"]),
    gender: getByAliases(map, ["gender", "genderCode", "gender code", "gender_code"]),

    firstName: getByAliases(map, ["firstName", "primaryFirstName", "first name"]),
    middleName: getByAliases(map, ["middleName", "primaryMiddleName", "middle name"]),
    lastName: getByAliases(map, ["lastName", "primaryLastName", "last name"]),
    fullName: getByAliases(map, ["fullName", "primaryFullName", "primary name", "name"]),
    aliasName: getByAliases(map, ["aliasName", "alias1FullName", "alias", "aka"]),

    addressLine1: getByAliases(map, ["addressLine1", "address1Line1", "address line 1"]),
    addressLine2: getByAliases(map, ["addressLine2", "address1Line2", "address line 2"]),
    city: getByAliases(map, ["city", "address1City"]),
    state: getByAliases(map, ["state", "address1stateProvince", "stateProvince"]),
    zip: getByAliases(map, ["zip", "zipCode", "address1ZipCode"]),
    country: getByAliases(map, ["country", "address1Country", "nationalityCountry1", "birthCountry"]),
    addresses: getByAliases(map, ["addresses"]),
    countries: getByAliases(map, ["countries"]),

    idType: getByAliases(map, ["idType", "partyId1Type", "id code", "idCode"]),
    idCode: getByAliases(map, ["idCode", "partyId1Type", "id type"]),
    idNumber: getByAliases(map, ["idNumber", "partyId1Value", "id value"]),
    idCountry: getByAliases(map, ["idCountry", "partyId1IDCountry", "id issue country"]),
    idIssueCountry: getByAliases(map, ["idIssueCountry", "partyId1IDCountry", "id country"]),

    countryOfBirth: getByAliases(map, ["countryOfBirth", "birthCountry"]),
    dateOfBirth: getByAliases(map, ["dateOfBirth", "DateOfBirth"]),
    countryOfCitizenship: getByAliases(map, ["countryOfCitizenship", "nationalityCountry1"]),
  };
}

export async function parseCsv(file: File): Promise<BatchRow[]> {
  const text = await file.text();
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) return [];

  const headers = splitCsvLine(lines[0]).map((h) => normalizeHeaderKey(h));

  const rows: BatchRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = splitCsvLine(lines[i]);
    const map: Record<string, string> = {};
    headers.forEach((h, idx) => {
      if (!h) return;
      map[h] = getStr(cols[idx] ?? "");
    });
    rows.push(mapParsedRow(map));
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
    const map = Object.fromEntries(Object.entries(r).map(([k, v]) => [normalizeHeaderKey(k), v]));
    return mapParsedRow(map);
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
