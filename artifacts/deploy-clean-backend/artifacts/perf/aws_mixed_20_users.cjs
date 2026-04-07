const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'https://d3ppga4y8wg1ck.cloudfront.net';
const VUS = Number(process.env.VUS || 20);
const STEP_TIMEOUT_MS = Number(process.env.STEP_TIMEOUT_MS || 45000);
const REFRESH_LOOPS = Number(process.env.REFRESH_LOOPS || 8);
const IDLE_MS = Number(process.env.IDLE_MS || 20000);
const SOAK_MINUTES = Number(process.env.SOAK_MINUTES || 0);
const SOAK_DURATION_MS = Math.max(0, Math.floor(SOAK_MINUTES * 60 * 1000));
const ACTION_PAUSE_MS = Number(process.env.ACTION_PAUSE_MS || 700);

const DEFAULT_CREDS = [
  { username: 'perf_load_user_01', password: 'Perf#2026Load!' },
];

function loadCredentials() {
  const raw = String(process.env.CREDENTIALS_JSON || '').trim();
  if (!raw) return DEFAULT_CREDS;
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length) {
      const normalized = parsed
        .map((r) => ({ username: String(r?.username || '').trim(), password: String(r?.password || '').trim() }))
        .filter((r) => r.username && r.password);
      if (normalized.length) return normalized;
    }
  } catch {
    // ignore parse error
  }
  return DEFAULT_CREDS;
}

const CREDENTIALS = loadCredentials();

function nowIso() {
  return new Date().toISOString();
}

function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[index];
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function cohortForVu(vuId) {
  if (vuId <= 10) return 'mixed_single_batch';
  if (vuId <= 15) return 'refresh_only';
  return 'idle_only';
}

function batchCsvFor(vuId) {
  const dir = path.join('artifacts', 'perf', 'tmp_batch');
  ensureDir(dir);
  const partyKey = `A${String(8000000 + vuId).padStart(7, '0')}`;
  const content = [
    'PartyKey,PartyType,PrimaryFirstName,PrimaryLastName,PrimaryFullName,PartyId1Type,PartyId1Value,PartyId1IDCountry,Address1Country,Gender',
    `${partyKey},I,Perf${vuId},User${vuId},Perf${vuId} User${vuId},PASSPORT,P${700000 + vuId},US,US,M`,
  ].join('\n');
  const filePath = path.join(dir, `batch_vu_${String(vuId).padStart(2, '0')}.csv`);
  fs.writeFileSync(filePath, content, 'utf8');
  return path.resolve(filePath);
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

async function waitForEnabled(locator, timeoutMs = STEP_TIMEOUT_MS) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const visible = await locator.isVisible({ timeout: 1000 }).catch(() => false);
    if (visible) {
      const disabled = await locator.isDisabled().catch(() => false);
      if (!disabled) return;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error('Timed out waiting for enabled control');
}

async function selectFirstBusinessUnit(selectLocator) {
  await selectLocator.waitFor({ timeout: STEP_TIMEOUT_MS });
  for (let attempt = 1; attempt <= 8; attempt += 1) {
    const value = await selectLocator.evaluate((el) => {
      const select = el;
      const option = Array.from(select.options).find((o) => String(o.value || '').trim());
      return option ? String(option.value) : '';
    });
    if (value) {
      await selectLocator.selectOption(value);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 900));
  }
  throw new Error('No Business Unit option available');
}

async function runSingleScreening(page, vuId) {
  const singleTab = page.getByRole('tab', { name: /single screening/i }).first();
  await singleTab.click({ timeout: STEP_TIMEOUT_MS });
  await page.locator('#panel-single').first().waitFor({ timeout: STEP_TIMEOUT_MS });

  const buSelect = page.locator('#panel-single select').first();
  await selectFirstBusinessUnit(buSelect);

  const firstNameInput = page.locator('.nameCard .field').filter({ has: page.getByText(/^First Name$/) }).first().locator('input');
  const lastNameInput = page.locator('.nameCard .field').filter({ has: page.getByText(/^Last Name$/) }).first().locator('input');
  await firstNameInput.fill(`Perf${vuId}`, { timeout: STEP_TIMEOUT_MS });
  await lastNameInput.fill(`Single${vuId}`, { timeout: STEP_TIMEOUT_MS });

  const runButton = page.locator('#panel-single .btnRunWide').first();
  await waitForEnabled(runButton, 30000);
  await runButton.click({ timeout: STEP_TIMEOUT_MS });

  const submitOutcome = await Promise.race([
    page.locator('.errorBox').first().isVisible({ timeout: 6000 }).then((v) => (v ? 'error' : 'ok')).catch(() => 'ok'),
    page.waitForTimeout(2500).then(() => 'ok'),
  ]);
  if (submitOutcome === 'error') {
    const msg = await page.locator('.errorBox').first().innerText().catch(() => 'Single screening failed');
    throw new Error(`Single screening error: ${msg}`);
  }
}

async function runBatchScreening(page, vuId) {
  const batchTab = page.getByRole('tab', { name: /batch screening/i }).first();
  await batchTab.click({ timeout: STEP_TIMEOUT_MS });
  await page.locator('#panel-batch').first().waitFor({ timeout: STEP_TIMEOUT_MS });

  const batchNameField = page.locator('#panel-batch .field').filter({ has: page.getByText(/Batch Name/i) }).first().locator('input');
  await batchNameField.fill(`PERF_BATCH_VU_${vuId}_${Date.now()}`, { timeout: STEP_TIMEOUT_MS });

  const buSelect = page.locator('#panel-batch select').first();
  await selectFirstBusinessUnit(buSelect);

  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles(batchCsvFor(vuId));

  const startButton = page.locator('#panel-batch .btnBatchWide').first();
  await waitForEnabled(startButton, 45000);
  await startButton.click({ timeout: STEP_TIMEOUT_MS });

  const submitOutcome = await Promise.race([
    page.locator('.errorBox').first().isVisible({ timeout: 8000 }).then((v) => (v ? 'error' : 'ok')).catch(() => 'ok'),
    page.waitForTimeout(3000).then(() => 'ok'),
  ]);
  if (submitOutcome === 'error') {
    const msg = await page.locator('.errorBox').first().innerText().catch(() => 'Batch screening failed');
    throw new Error(`Batch screening error: ${msg}`);
  }
}

async function runRefreshLoop(page) {
  await page.goto(`${BASE_URL}/screening`, { waitUntil: 'domcontentloaded', timeout: STEP_TIMEOUT_MS });
  const refreshBtn = page.getByRole('button', { name: /refreshing? screening results/i }).first();
  const search = page.getByLabel(/search screening results/i).first();

  for (let i = 0; i < REFRESH_LOOPS; i += 1) {
    if (await refreshBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      if (!(await refreshBtn.isDisabled().catch(() => false))) {
        await refreshBtn.click({ timeout: STEP_TIMEOUT_MS });
      }
    }
    await search.fill(`perf_refresh_${i}`, { timeout: STEP_TIMEOUT_MS });
    await search.fill('', { timeout: STEP_TIMEOUT_MS });
    await page.waitForTimeout(350);
  }
}

async function runUser(browser, vuId, cred) {
  const cohort = cohortForVu(vuId);
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const steps = [];
  const errors = [];

  const mark = (name, startMs, ok, errorText = '') => {
    steps.push({ name, ms: Date.now() - startMs, ok });
    if (!ok) errors.push({ step: name, error: errorText });
  };

  const start = Date.now();
  try {
    const tLogin = Date.now();
    try {
      await loginWithRetries(page, cred, 3);
      mark('login', tLogin, true);
    } catch (error) {
      mark('login', tLogin, false, String(error?.message || error));
      throw error;
    }

    const endAt = SOAK_DURATION_MS > 0 ? Date.now() + SOAK_DURATION_MS : 0;

    if (cohort === 'mixed_single_batch') {
      if (SOAK_DURATION_MS > 0) {
        while (Date.now() < endAt) {
          const tSingle = Date.now();
          try {
            await runSingleScreening(page, vuId);
            mark('single_screening_submit', tSingle, true);
          } catch (error) {
            mark('single_screening_submit', tSingle, false, String(error?.message || error));
          }

          const tBatch = Date.now();
          try {
            await runBatchScreening(page, vuId);
            mark('batch_screening_submit', tBatch, true);
          } catch (error) {
            mark('batch_screening_submit', tBatch, false, String(error?.message || error));
          }

          if (Date.now() < endAt) await page.waitForTimeout(ACTION_PAUSE_MS);
        }
      } else {
        const tSingle = Date.now();
        try {
          await runSingleScreening(page, vuId);
          mark('single_screening_submit', tSingle, true);
        } catch (error) {
          mark('single_screening_submit', tSingle, false, String(error?.message || error));
        }

        const tBatch = Date.now();
        try {
          await runBatchScreening(page, vuId);
          mark('batch_screening_submit', tBatch, true);
        } catch (error) {
          mark('batch_screening_submit', tBatch, false, String(error?.message || error));
        }
      }
    } else if (cohort === 'refresh_only') {
      if (SOAK_DURATION_MS > 0) {
        while (Date.now() < endAt) {
          const tRefresh = Date.now();
          try {
            await runRefreshLoop(page);
            mark('results_refresh_loop', tRefresh, true);
          } catch (error) {
            mark('results_refresh_loop', tRefresh, false, String(error?.message || error));
          }
          if (Date.now() < endAt) await page.waitForTimeout(ACTION_PAUSE_MS);
        }
      } else {
        const tRefresh = Date.now();
        try {
          await runRefreshLoop(page);
          mark('results_refresh_loop', tRefresh, true);
        } catch (error) {
          mark('results_refresh_loop', tRefresh, false, String(error?.message || error));
        }
      }
    } else {
      const tIdle = Date.now();
      const waitMs = SOAK_DURATION_MS > 0 ? SOAK_DURATION_MS : IDLE_MS;
      await page.waitForTimeout(waitMs);
      mark('idle_wait', tIdle, true);
    }
  } finally {
    await context.close();
  }

  return {
    vuId,
    cohort,
    username: cred.username,
    totalMs: Date.now() - start,
    steps,
    errors,
    startedAt: new Date(start).toISOString(),
    finishedAt: nowIso(),
  };
}

(async () => {
  const started = Date.now();
  const browser = await chromium.launch({ headless: true });
  const jobs = [];
  for (let i = 0; i < VUS; i += 1) {
    jobs.push(runUser(browser, i + 1, CREDENTIALS[i % CREDENTIALS.length]));
  }

  const settled = await Promise.allSettled(jobs);
  await browser.close();
  const completed = [];
  const fatalErrors = [];
  for (const item of settled) {
    if (item.status === 'fulfilled') completed.push(item.value);
    else fatalErrors.push(String(item.reason?.message || item.reason));
  }

  const allSteps = completed.flatMap((u) => u.steps || []);
  const allStepMs = allSteps.map((s) => s.ms);
  const successfulUsers = completed.filter((u) => (u.errors || []).length === 0).length;
  const failedUsers = completed.length - successfulUsers + fatalErrors.length;

  const byCohort = {
    mixed_single_batch: completed.filter((u) => u.cohort === 'mixed_single_batch').length,
    refresh_only: completed.filter((u) => u.cohort === 'refresh_only').length,
    idle_only: completed.filter((u) => u.cohort === 'idle_only').length,
  };

  const summary = {
    baseUrl: BASE_URL,
    vus: VUS,
    soakMinutes: SOAK_MINUTES,
    cohortDistribution: byCohort,
    startedAt: new Date(started).toISOString(),
    finishedAt: nowIso(),
    durationMs: Date.now() - started,
    completedUsers: completed.length,
    successfulUsers,
    failedUsers,
    fatalErrors,
    totalSteps: allSteps.length,
    avgStepMs: allStepMs.length ? Number((allStepMs.reduce((a, b) => a + b, 0) / allStepMs.length).toFixed(2)) : 0,
    p95StepMs: Number(percentile(allStepMs, 95).toFixed(2)),
    p99StepMs: Number(percentile(allStepMs, 99).toFixed(2)),
    maxStepMs: allStepMs.length ? Math.max(...allStepMs) : 0,
  };

  const outDir = path.join('artifacts', 'perf');
  ensureDir(outDir);
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outFile = path.join(outDir, `aws_mixed_20_users_${stamp}.json`);
  fs.writeFileSync(outFile, JSON.stringify({ summary, completed }, null, 2), 'utf8');

  console.log('Mixed workload stress summary:');
  console.log(JSON.stringify(summary, null, 2));
  console.log(`Report: ${outFile}`);

  if (failedUsers > 0) process.exitCode = 2;
})();
