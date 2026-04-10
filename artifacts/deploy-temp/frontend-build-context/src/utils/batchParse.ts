import ExcelJS from "exceljs";

export type BatchRow = {
  partyKey?: string;
  customerType: "Person" | "Entity";
  customerTypeRaw?: string;
  partyType?: string;
  title?: string;
  gender?: string;

  primaryFirstName?: string;
  primaryMiddleName?: string;
  primaryLastName?: string;
  primaryMaidenName?: string;
  primaryFullName?: string;
  primaryIsBrokenName?: string;

  alias1FirstName?: string;
  alias1MiddleName?: string;
  alias1LastName?: string;
  alias1MaidenName?: string;
  alias1FullName?: string;
  alias1IsBrokenName?: string;
  alias2FirstName?: string;
  alias2MiddleName?: string;
  alias2LastName?: string;
  alias2MaidenName?: string;
  alias2FullName?: string;
  alias2IsBrokenName?: string;
  alias3FirstName?: string;
  alias3MiddleName?: string;
  alias3LastName?: string;
  alias3MaidenName?: string;
  alias3FullName?: string;
  alias3IsBrokenName?: string;

  partyId1Type?: string;
  partyId1Value?: string;
  partyId1IDCountry?: string;
  partyId2Type?: string;
  partyId2Value?: string;
  partyId2IDCountry?: string;
  partyId3Type?: string;
  partyId3Value?: string;
  partyId3IDCountry?: string;

  address1Line1?: string;
  address1Line2?: string;
  address1City?: string;
  address1ZipCode?: string;
  address1Country?: string;
  address1stateProvince?: string;
  address2Line1?: string;
  address2Line2?: string;
  address2City?: string;
  address2ZipCode?: string;
  address2Country?: string;
  address2stateProvince?: string;
  address3Line1?: string;
  address3Line2?: string;
  address3City?: string;
  address3ZipCode?: string;
  address3Country?: string;
  address3stateProvince?: string;

  birthCountry?: string;
  birthLocation?: string;
  nationalityCountry1?: string;
  nationalityCountry2?: string;
  nationalityCountry3?: string;
  yearOfBirth?: string;

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
    title: getByAliases(map, ["title"]),
    gender: getByAliases(map, ["gender", "genderCode", "gender code", "gender_code"]),

    primaryFirstName: getByAliases(map, ["primaryFirstName"]),
    primaryMiddleName: getByAliases(map, ["primaryMiddleName"]),
    primaryLastName: getByAliases(map, ["primaryLastName"]),
    primaryMaidenName: getByAliases(map, ["primaryMaidenName"]),
    primaryFullName: getByAliases(map, ["primaryFullName"]),
    primaryIsBrokenName: getByAliases(map, ["primaryIsBrokenName"]),

    alias1FirstName: getByAliases(map, ["alias1FirstName"]),
    alias1MiddleName: getByAliases(map, ["alias1MiddleName"]),
    alias1LastName: getByAliases(map, ["alias1LastName"]),
    alias1MaidenName: getByAliases(map, ["alias1MaidenName"]),
    alias1FullName: getByAliases(map, ["alias1FullName"]),
    alias1IsBrokenName: getByAliases(map, ["alias1IsBrokenName"]),
    alias2FirstName: getByAliases(map, ["alias2FirstName"]),
    alias2MiddleName: getByAliases(map, ["alias2MiddleName"]),
    alias2LastName: getByAliases(map, ["alias2LastName"]),
    alias2MaidenName: getByAliases(map, ["alias2MaidenName"]),
    alias2FullName: getByAliases(map, ["alias2FullName"]),
    alias2IsBrokenName: getByAliases(map, ["alias2IsBrokenName"]),
    alias3FirstName: getByAliases(map, ["alias3FirstName"]),
    alias3MiddleName: getByAliases(map, ["alias3MiddleName"]),
    alias3LastName: getByAliases(map, ["alias3LastName"]),
    alias3MaidenName: getByAliases(map, ["alias3MaidenName"]),
    alias3FullName: getByAliases(map, ["alias3FullName"]),
    alias3IsBrokenName: getByAliases(map, ["alias3IsBrokenName"]),

    partyId1Type: getByAliases(map, ["partyId1Type"]),
    partyId1Value: getByAliases(map, ["partyId1Value"]),
    partyId1IDCountry: getByAliases(map, ["partyId1IDCountry"]),
    partyId2Type: getByAliases(map, ["partyId2Type"]),
    partyId2Value: getByAliases(map, ["partyId2Value"]),
    partyId2IDCountry: getByAliases(map, ["partyId2IDCountry"]),
    partyId3Type: getByAliases(map, ["partyId3Type"]),
    partyId3Value: getByAliases(map, ["partyId3Value"]),
    partyId3IDCountry: getByAliases(map, ["partyId3IDCountry"]),

    address1Line1: getByAliases(map, ["address1Line1"]),
    address1Line2: getByAliases(map, ["address1Line2"]),
    address1City: getByAliases(map, ["address1City"]),
    address1ZipCode: getByAliases(map, ["address1ZipCode"]),
    address1Country: getByAliases(map, ["address1Country"]),
    address1stateProvince: getByAliases(map, ["address1stateProvince"]),
    address2Line1: getByAliases(map, ["address2Line1"]),
    address2Line2: getByAliases(map, ["address2Line2"]),
    address2City: getByAliases(map, ["address2City"]),
    address2ZipCode: getByAliases(map, ["address2ZipCode"]),
    address2Country: getByAliases(map, ["address2Country"]),
    address2stateProvince: getByAliases(map, ["address2stateProvince"]),
    address3Line1: getByAliases(map, ["address3Line1"]),
    address3Line2: getByAliases(map, ["address3Line2"]),
    address3City: getByAliases(map, ["address3City"]),
    address3ZipCode: getByAliases(map, ["address3ZipCode"]),
    address3Country: getByAliases(map, ["address3Country"]),
    address3stateProvince: getByAliases(map, ["address3stateProvince"]),

    birthCountry: getByAliases(map, ["birthCountry"]),
    birthLocation: getByAliases(map, ["birthLocation"]),
    nationalityCountry1: getByAliases(map, ["nationalityCountry1"]),
    nationalityCountry2: getByAliases(map, ["nationalityCountry2"]),
    nationalityCountry3: getByAliases(map, ["nationalityCountry3"]),
    yearOfBirth: getByAliases(map, ["yearOfBirth"]),

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
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(buf);
  const worksheet = workbook.worksheets[0];
  if (!worksheet) return [];

  const headerRow = worksheet.getRow(1);
  const headers = Array.from({ length: headerRow.cellCount }, (_, index) =>
    normalizeHeaderKey(headerRow.getCell(index + 1).text)
  );
  if (!headers.some(Boolean)) return [];

  const rows: BatchRow[] = [];
  for (let rowNumber = 2; rowNumber <= worksheet.rowCount; rowNumber++) {
    const row = worksheet.getRow(rowNumber);
    const map: Record<string, string> = {};
    let hasValue = false;
    headers.forEach((header, index) => {
      if (!header) return;
      const value = getStr(row.getCell(index + 1).text);
      if (value) hasValue = true;
      map[header] = value;
    });
    if (!hasValue) continue;
    rows.push(mapParsedRow(map));
  }
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
