const { chromium } = require('playwright');
const ExcelJS = require('exceljs');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'https://d3ppga4y8wg1ck.cloudfront.net';
const VUS = Number(process.env.VUS || 20);
const RECORDS_PER_BATCH = Number(process.env.RECORDS_PER_BATCH || 1000);
const STEP_TIMEOUT_MS = Number(process.env.STEP_TIMEOUT_MS || 45000);
const OUT_DIR = path.join('artifacts', 'perf');
const CREDS_FILE = path.join(OUT_DIR, 'aws_perf_users.json');
const SAMPLE_XLSX_PATH = process.env.SAMPLE_XLSX_PATH || 'C:\\Users\\Tapan Bhavsar\\Downloads\\SSB_Sample.xlsx';

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function readCredentials() {
  return JSON.parse(fs.readFileSync(CREDS_FILE, 'utf8')).slice(0, VUS);
}

function isoStamp() {
  return new Date().toISOString();
}

function safeStamp() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

function alphaToken(value) {
  let next = Math.max(Number(value) || 0, 0);
  let out = '';
  do {
    out = String.fromCharCode(65 + (next % 26)) + out;
    next = Math.floor(next / 26) - 1;
  } while (next >= 0);
  return out;
}

function templateValue(row, headerMap, name) {
  const index = headerMap.get(name);
  if (typeof index !== 'number') return '';
  return row[index] ?? '';
}

function buildUniqueRow({ headers, headerMap, templateRow, runTag, vuId, index }) {
  const row = headers.map((headerName, idx) => templateRow[idx] ?? '');
  const seq = index + 1;
  const paddedVu = String(vuId).padStart(2, '0');
  const paddedSeq = String(seq).padStart(4, '0');
  const uniqueToken = `${runTag}${paddedVu}${paddedSeq}`;
  const partyType = String(templateValue(templateRow, headerMap, 'PartyType') || 'U').toUpperCase();
  const partyKey = `AMLP_${partyType}_${uniqueToken}`;
  const letterVu = alphaToken(vuId);
  const letterSeq = alphaToken(seq);
  const isEntity = partyType === 'E';
  const isIndividual = partyType === 'I';

  const firstName = isEntity ? `Acme${letterVu}` : `John${letterVu}`;
  const middleName = isEntity ? `Global${letterSeq}` : `Allen${letterSeq}`;
  const lastName = isEntity ? `Holdings${paddedSeq}` : `Smith${paddedSeq}`;
  const maidenName = isEntity ? `NA${paddedVu}` : `Taylor${paddedVu}`;
  const fullName = isEntity
    ? `Acme ${letterVu} Global Holdings ${paddedSeq}`
    : isIndividual
      ? `${firstName} ${middleName} ${lastName}`
      : `Unknown Subject ${uniqueToken}`;

  const alias1FullName = isEntity ? `Acme Intl Group ${paddedSeq}` : `Jon ${letterVu} ${lastName}`;
  const alias2FullName = isEntity ? `AGH Corp ${letterVu}${paddedSeq}` : `Johnny ${middleName} ${lastName}`;
  const alias3FullName = isEntity ? `Acme Global LLC ${paddedSeq}` : `J ${letterVu} ${lastName}`;

  const updates = new Map([
    ['PartyKey', partyKey],
    ['PartyId1Value', `${partyType}1${uniqueToken}`],
    ['PartyId2Value', `${partyType}2${uniqueToken}`],
    ['PartyId3Value', `${partyType}3${uniqueToken}`],
    ['PrimaryFirstName', firstName],
    ['PrimaryMiddleName', middleName],
    ['PrimaryLastName', lastName],
    ['PrimaryMaidenName', maidenName],
    ['PrimaryFullName', fullName],
    ['Alias1FirstName', `${firstName}A`],
    ['Alias1MiddleName', `${middleName}A`],
    ['Alias1LastName', `${lastName}A`],
    ['Alias1MaidenName', `${maidenName}A`],
    ['Alias1FullName', alias1FullName],
    ['Alias2FirstName', `${firstName}B`],
    ['Alias2MiddleName', `${middleName}B`],
    ['Alias2LastName', `${lastName}B`],
    ['Alias2MaidenName', `${maidenName}B`],
    ['Alias2FullName', alias2FullName],
    ['Alias3FirstName', `${firstName}C`],
    ['Alias3MiddleName', `${middleName}C`],
    ['Alias3LastName', `${lastName}C`],
    ['Alias3MaidenName', `${maidenName}C`],
    ['Alias3FullName', alias3FullName],
    ['Address1Line1', `${100 + seq} Main Street`],
    ['Address1Line2', `Suite ${paddedVu}${paddedSeq}`],
    ['Address1City', isEntity ? 'San Francisco' : 'New York'],
    ['Address1ZipCode', isEntity ? `94${String(seq).padStart(3, '0')}` : `10${String(seq).padStart(3, '0')}`],
    ['Address1stateProvince', isEntity ? 'CA' : 'NY'],
    ['Address2Line1', `${200 + seq} Oak Avenue`],
    ['Address2Line2', `Level ${String((seq % 20) + 1).padStart(2, '0')}`],
    ['Address2City', isEntity ? 'London' : 'Jersey City'],
    ['Address2ZipCode', isEntity ? `EC4N${String(seq).padStart(4, '0')}`.slice(0, 8) : `07${String(seq).padStart(3, '0')}`],
    ['Address3Line1', `${300 + seq} Bay Street`],
    ['Address3Line2', `Floor ${String((seq % 15) + 1).padStart(2, '0')}`],
    ['Address3City', isEntity ? 'Toronto' : 'Boston'],
    ['Address3ZipCode', `M5J${String(seq).padStart(3, '0')}`.slice(0, 6)],
  ]);

  for (const [headerName, value] of updates.entries()) {
    const updateIndex = headerMap.get(headerName);
    if (typeof updateIndex === 'number') {
      row[updateIndex] = value;
    }
  }
  return row;
}

async function loadSampleTemplate() {
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(SAMPLE_XLSX_PATH);
  const worksheet =
    workbook.getWorksheet('Sample Data') ||
    workbook.worksheets.find((candidate) => {
      const firstCell = String(candidate.getRow(1).getCell(1).value || '').trim();
      return firstCell === 'PartyKey';
    }) ||
    workbook.worksheets[0];
  if (!worksheet) {
    throw new Error(`No worksheet found in ${SAMPLE_XLSX_PATH}`);
  }
  const headers = worksheet.getRow(1).values.slice(1).map((value) => String(value ?? '').trim());
  const headerMap = new Map(headers.map((header, index) => [header, index]));
  const templateRows = [];
  worksheet.eachRow((row, rowNumber) => {
    if (rowNumber >= 2) {
      const values = row.values.slice(1);
      if (values.some((value) => String(value ?? '').trim())) {
        templateRows.push(values);
      }
    }
  });
  if (!headers.length || !templateRows.length) {
    throw new Error(`Sample workbook ${SAMPLE_XLSX_PATH} does not contain usable headers and template rows`);
  }
  return { headers, headerMap, templateRows, sheetName: worksheet.name };
}

async function buildBatchWorkbook(template, runTag, vuId, totalRows) {
  const workbook = new ExcelJS.Workbook();
  const worksheet = workbook.addWorksheet(template.sheetName || 'Sample Data');
  worksheet.addRow(template.headers);
  for (let index = 0; index < totalRows; index += 1) {
    const templateRow = template.templateRows[index % template.templateRows.length];
    worksheet.addRow(buildUniqueRow({
      headers: template.headers,
      headerMap: template.headerMap,
      templateRow,
      runTag,
      vuId,
      index,
    }));
  }
  return workbook.xlsx.writeBuffer();
}

async function login(page, cred) {
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: STEP_TIMEOUT_MS });

  const signInButton = page.getByRole('button', { name: /sign in/i }).first();
  if (await signInButton.isVisible({ timeout: 6000 }).catch(() => false)) {
    await signInButton.click({ timeout: STEP_TIMEOUT_MS });
  }

  await page.waitForURL(
    (url) => /amazoncognito\.com/i.test(url.hostname) || !url.href.startsWith(BASE_URL),
    { timeout: STEP_TIMEOUT_MS, waitUntil: 'domcontentloaded' }
  );

  const usernameInput = page.locator('input[name="username"]').first();
  await usernameInput.waitFor({ timeout: STEP_TIMEOUT_MS });
  await usernameInput.fill(cred.username, { timeout: STEP_TIMEOUT_MS });

  const passwordInput = page.locator('input[name="password"]').first();
  if (!(await passwordInput.isVisible({ timeout: 2000 }).catch(() => false))) {
    const nextBtn = page.getByRole('button', { name: /next|continue|sign in/i }).first();
    await nextBtn.click({ timeout: STEP_TIMEOUT_MS });
  }

  if (!(await passwordInput.isVisible({ timeout: 12000 }).catch(() => false))) {
    const usePassword = page.getByRole('button', { name: /password|use password|try another way/i }).first();
    if (await usePassword.isVisible({ timeout: 4000 }).catch(() => false)) {
      await usePassword.click({ timeout: STEP_TIMEOUT_MS });
    }
  }

  await passwordInput.waitFor({ timeout: STEP_TIMEOUT_MS });
  await passwordInput.fill(cred.password, { timeout: STEP_TIMEOUT_MS });

  const signInBtn = page.getByRole('button', { name: /sign in|continue/i }).first();
  await signInBtn.click({ timeout: STEP_TIMEOUT_MS });

  const base = new URL(BASE_URL);
  await page.waitForURL(
    (url) => url.hostname === base.hostname && String(url.port || '') === String(base.port || '') && !url.searchParams.has('code'),
    { timeout: STEP_TIMEOUT_MS, waitUntil: 'domcontentloaded' }
  );

  await page.goto(`${BASE_URL}/screening`, { waitUntil: 'domcontentloaded', timeout: STEP_TIMEOUT_MS });
  await page.getByRole('heading', { name: /Entity Screening Workbench/i }).waitFor({ timeout: STEP_TIMEOUT_MS });
}

async function loginWithRetries(page, cred, maxAttempts = 3) {
  let lastError = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      await login(page, cred);
      return;
    } catch (error) {
      lastError = error;
      if (attempt >= maxAttempts) break;
      await page.context().clearCookies();
      await page.goto('about:blank', { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(700 * attempt);
    }
  }
  throw lastError;
}

async function extractTokenAndBusinessUnits(page) {
  return page.evaluate(async () => {
    let token = '';
    const stores = [window.localStorage, window.sessionStorage];
    for (const store of stores) {
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i);
        if (!key || !key.startsWith('oidc.user:')) continue;
        const raw = store.getItem(key);
        if (!raw) continue;
        try {
          const parsed = JSON.parse(raw);
          if (parsed && parsed.access_token) {
            token = String(parsed.access_token);
            break;
          }
        } catch {
        }
      }
      if (token) break;
    }
    if (!token) throw new Error('No access token found in browser storage');

    const resp = await fetch('/api/v1/business-units', {
      headers: { Authorization: `Bearer ${token}` },
    });
    const text = await resp.text();
    if (!resp.ok) {
      throw new Error(`Failed to load business units: ${resp.status} ${text}`);
    }
    const data = JSON.parse(text);
    return { token, businessUnits: Array.isArray(data) ? data : [] };
  });
}

async function submitBatch(payload) {
  const sleepMs = payload.startAtMs - Date.now();
  if (sleepMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, sleepMs));
  }

  const form = new FormData();
  const file = new File([payload.fileBuffer], payload.fileName, {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  form.set('file', file);
  form.set('screening_types_json', '[]');
  form.set('batch_name', payload.batchName);
  form.set('daily_screening', 'false');
  form.set('business_unit_code', payload.businessUnitCode);
  form.set('mock_screening', 'false');
  form.set('user_name', payload.userName);

  const startedAt = Date.now();
  const resp = await fetch(`${BASE_URL}/api/v1/screenings/batch-upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${payload.token}` },
    body: form,
  });
  const text = await resp.text();
  return {
    startedAt: new Date(startedAt).toISOString(),
    endedAt: new Date().toISOString(),
    responseMs: Date.now() - startedAt,
    statusCode: resp.status,
    ok: resp.ok,
    text,
  };
}

(async () => {
  ensureDir(OUT_DIR);
  const stamp = safeStamp();
  const runTag = stamp.replace(/[^0-9]/g, '').slice(2, 12);
  const credentials = readCredentials();
  const template = await loadSampleTemplate();
  const browser = await chromium.launch({ headless: true });
  const sessions = [];
  const prepFailures = [];

  try {
    await Promise.all(
      credentials.map(async (cred, index) => {
        const vuId = index + 1;
        const context = await browser.newContext({ ignoreHTTPSErrors: true });
        const page = await context.newPage();
        try {
          await loginWithRetries(page, cred, 3);
          const auth = await extractTokenAndBusinessUnits(page);
          const businessUnitCode = String(auth.businessUnits?.[0]?.business_unit_code || '').trim();
          if (!businessUnitCode) {
            throw new Error('No mapped business unit found for user');
          }
          sessions.push({
            vuId,
            cred,
            context,
            token: auth.token,
            businessUnitCode,
          });
        } catch (error) {
          prepFailures.push({
            vuId,
            username: cred.username,
            error: String(error && error.message ? error.message : error),
          });
          await context.close();
        } finally {
          await page.close().catch(() => {});
        }
      })
    );

    if (prepFailures.length) {
      throw new Error(`Preparation failed for ${prepFailures.length} users`);
    }

    const generatedFiles = await Promise.all(
      sessions.map(async (session) => {
        const fileName = `stress_populated_${runTag}_vu_${String(session.vuId).padStart(2, '0')}.xlsx`;
        const batchName = `STRESS_POPULATED_${runTag}_VU_${String(session.vuId).padStart(2, '0')}`;
        const fileBuffer = await buildBatchWorkbook(template, runTag, session.vuId, RECORDS_PER_BATCH);
        return {
          ...session,
          fileName,
          batchName,
          fileBuffer,
        };
      })
    );

    if (generatedFiles.length > 0) {
      const sampleOut = path.join(OUT_DIR, `sample_generated_populated_${runTag}.xlsx`);
      fs.writeFileSync(sampleOut, Buffer.from(generatedFiles[0].fileBuffer));
    }

    const startAtMs = Date.now() + 5000;
    const submissions = await Promise.all(
      generatedFiles.map(async (session) => {
        const result = await submitBatch({
          startAtMs,
          token: session.token,
          fileName: session.fileName,
          fileBuffer: session.fileBuffer,
          batchName: session.batchName,
          businessUnitCode: session.businessUnitCode,
          userName: session.cred.username,
        });

        let parsedBody = null;
        try {
          parsedBody = JSON.parse(result.text);
        } catch {
          parsedBody = null;
        }

        return {
          vuId: session.vuId,
          username: session.cred.username,
          businessUnitCode: session.businessUnitCode,
          fileName: session.fileName,
          batchName: session.batchName,
          rowsSubmitted: RECORDS_PER_BATCH,
          ...result,
          body: parsedBody,
        };
      })
    );

    const report = {
      baseUrl: BASE_URL,
      sampleWorkbookPath: SAMPLE_XLSX_PATH,
      startedAt: isoStamp(),
      plannedStartAt: new Date(startAtMs).toISOString(),
      finishedAt: isoStamp(),
      vus: VUS,
      recordsPerBatch: RECORDS_PER_BATCH,
      totalRecordsPlanned: VUS * RECORDS_PER_BATCH,
      format: 'populated-xlsx-based-on-sample',
      prepFailures,
      submissions,
    };

    const outFile = path.join(OUT_DIR, `aws_batch_stress_submit_20x1000_populated_xlsx_${stamp}.json`);
    fs.writeFileSync(outFile, JSON.stringify(report, null, 2), 'utf8');
    console.log(JSON.stringify({ outFile, report }, null, 2));

    const failed = submissions.filter((item) => !item.ok);
    if (failed.length) process.exitCode = 2;
  } finally {
    await Promise.allSettled(sessions.map((session) => session.context.close()));
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
