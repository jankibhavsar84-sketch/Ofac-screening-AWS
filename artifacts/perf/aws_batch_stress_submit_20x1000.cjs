const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'https://d3ppga4y8wg1ck.cloudfront.net';
const VUS = Number(process.env.VUS || 20);
const RECORDS_PER_BATCH = Number(process.env.RECORDS_PER_BATCH || 1000);
const STEP_TIMEOUT_MS = Number(process.env.STEP_TIMEOUT_MS || 45000);
const OUT_DIR = path.join('artifacts', 'perf');
const CREDS_FILE = path.join(OUT_DIR, 'aws_perf_users.json');

function readCredentials() {
  return JSON.parse(fs.readFileSync(CREDS_FILE, 'utf8')).slice(0, VUS);
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
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

function buildBatchCsv(runTag, vuId, totalRows) {
  const header = 'PartyKey,CustomerType,PrimaryFullName,Address1Country';
  const rows = [header];
  for (let index = 0; index < totalRows; index += 1) {
    const partyKey = `S${runTag}${String(vuId).padStart(2, '0')}${String(index + 1).padStart(4, '0')}`;
    const name = `STRESSCO${alphaToken(vuId)}${alphaToken(index + 1)}`;
    rows.push(`${partyKey},Entity,${name},US`);
  }
  return rows.join('\n');
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
          // ignore malformed storage entries
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

async function submitBatch(page, args) {
  return page.evaluate(async (payload) => {
    const sleepMs = payload.startAtMs - Date.now();
    if (sleepMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, sleepMs));
    }

    const form = new FormData();
    const file = new File([payload.csv], payload.fileName, { type: 'text/csv' });
    form.set('file', file);
    form.set('screening_types_json', '[]');
    form.set('batch_name', payload.batchName);
    form.set('daily_screening', 'false');
    form.set('business_unit_code', payload.businessUnitCode);
    form.set('mock_screening', 'false');
    form.set('user_name', payload.userName);

    const startedAt = Date.now();
    const resp = await fetch('/api/v1/screenings/batch-upload', {
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
  }, args);
}

(async () => {
  ensureDir(OUT_DIR);
  const stamp = safeStamp();
  const runTag = stamp.replace(/[^0-9]/g, '').slice(2, 12);
  const credentials = readCredentials();
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
            page,
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
        }
      })
    );

    if (prepFailures.length) {
      throw new Error(`Preparation failed for ${prepFailures.length} users`);
    }

    const startAtMs = Date.now() + 5000;
    const submissions = await Promise.all(
      sessions.map(async (session) => {
        const fileName = `stress_${runTag}_vu_${String(session.vuId).padStart(2, '0')}.csv`;
        const batchName = `STRESS_${runTag}_VU_${String(session.vuId).padStart(2, '0')}`;
        const csv = buildBatchCsv(runTag, session.vuId, RECORDS_PER_BATCH);
        const result = await submitBatch(session.page, {
          startAtMs,
          token: session.token,
          fileName,
          csv,
          batchName,
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
          fileName,
          batchName,
          rowsSubmitted: RECORDS_PER_BATCH,
          ...result,
          body: parsedBody,
        };
      })
    );

    const report = {
      baseUrl: BASE_URL,
      startedAt: isoStamp(),
      plannedStartAt: new Date(startAtMs).toISOString(),
      finishedAt: isoStamp(),
      vus: VUS,
      recordsPerBatch: RECORDS_PER_BATCH,
      totalRecordsPlanned: VUS * RECORDS_PER_BATCH,
      prepFailures,
      submissions,
    };

    const outFile = path.join(OUT_DIR, `aws_batch_stress_submit_20x1000_${stamp}.json`);
    fs.writeFileSync(outFile, JSON.stringify(report, null, 2), 'utf8');
    console.log(JSON.stringify({ outFile, report }, null, 2));

    const failed = submissions.filter((item) => !item.ok);
    if (failed.length) process.exitCode = 2;
  } finally {
    await Promise.allSettled(sessions.map((session) => session.context.close()));
    await browser.close();
  }
})();
