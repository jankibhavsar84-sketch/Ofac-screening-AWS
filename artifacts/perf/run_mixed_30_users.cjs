const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'https://d3ppga4y8wg1ck.cloudfront.net';
const STEP_TIMEOUT_MS = Number(process.env.STEP_TIMEOUT_MS || 120000);
const FILE_PATH =
  process.env.INPUT_FILE ||
  'C:\\Users\\Tapan Bhavsar\\Documents\\OFAC Screening Project\\sample_generated_populated_2603230040.xlsx';
const CREDENTIALS_PATH =
  process.env.CREDENTIALS_FILE ||
  path.resolve('artifacts', 'perf', 'aws_perf_users_30.json');
const RUN_TAG = new Date().toISOString().replace(/[:.]/g, '-');
const OUTPUT_PATH = path.resolve('artifacts', 'perf', `mixed_screening_30_users_${RUN_TAG}.json`);

function nowIso() {
  return new Date().toISOString();
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function readCredentials() {
  const raw = fs.readFileSync(CREDENTIALS_PATH, 'utf8');
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.length < 30) {
    throw new Error(`Expected at least 30 credentials in ${CREDENTIALS_PATH}`);
  }
  return parsed.slice(0, 30).map((item) => ({
    username: String(item.username || '').trim(),
    password: String(item.password || '').trim(),
  }));
}

function cohortForIndex(index) {
  if (index < 10) return 'batch';
  if (index < 20) return 'schedule';
  return 'single';
}

function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, Math.min(sorted.length - 1, pos))];
}

async function pageWait(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
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
    const nextButton = page.getByRole('button', { name: /next|continue|sign in/i }).first();
    await nextButton.click({ timeout: STEP_TIMEOUT_MS });
  }

  if (!(await passwordInput.isVisible({ timeout: 12000 }).catch(() => false))) {
    const usePassword = page.getByRole('button', { name: /password|use password|try another way/i }).first();
    if (await usePassword.isVisible({ timeout: 4000 }).catch(() => false)) {
      await usePassword.click({ timeout: STEP_TIMEOUT_MS });
    }
  }

  await passwordInput.waitFor({ timeout: STEP_TIMEOUT_MS });
  await passwordInput.fill(cred.password, { timeout: STEP_TIMEOUT_MS });

  const submitButton = page.getByRole('button', { name: /sign in|continue/i }).first();
  await submitButton.click({ timeout: STEP_TIMEOUT_MS });

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
      await page.goto('about:blank', { waitUntil: 'domcontentloaded', timeout: STEP_TIMEOUT_MS }).catch(() => {});
      await pageWait(800 * attempt);
    }
  }
  throw lastError;
}

async function selectFirstBusinessUnit(selectLocator) {
  await selectLocator.waitFor({ timeout: STEP_TIMEOUT_MS });
  const startedAt = Date.now();
  while (Date.now() - startedAt < STEP_TIMEOUT_MS) {
    const details = await selectLocator.evaluate((el) => {
      const select = el;
      const options = Array.from(select.options).map((option) => ({
        value: String(option.value || '').trim(),
        label: String(option.textContent || '').trim(),
      }));
      const selectable = options.find((option) => option.value);
      return {
        disabled: Boolean(select.disabled),
        value: selectable ? selectable.value : '',
        labels: options.map((option) => option.label).filter(Boolean),
      };
    });

    if (!details.disabled && details.value) {
      await selectLocator.selectOption(details.value);
      return details.value;
    }

    await pageWait(1000);
  }

  const finalState = await selectLocator.evaluate((el) => {
    const select = el;
    return {
      disabled: Boolean(select.disabled),
      options: Array.from(select.options).map((option) => ({
        value: String(option.value || '').trim(),
        label: String(option.textContent || '').trim(),
      })),
    };
  });

  throw new Error(
    `No Business Unit option available after waiting ${Math.round(STEP_TIMEOUT_MS / 1000)}s: ${JSON.stringify(finalState)}`
  );
}

async function readErrorBox(page) {
  const errorBox = page.locator('.errorBox').first();
  if (await errorBox.isVisible({ timeout: 2500 }).catch(() => false)) {
    return await errorBox.innerText().catch(() => 'Visible errorBox with unreadable text');
  }
  return null;
}

async function waitForApiResponse(page, expectedPath) {
  const startedAt = Date.now();
  const response = await page.waitForResponse(
    (resp) => resp.url().includes(expectedPath) && resp.request().method() === 'POST',
    { timeout: STEP_TIMEOUT_MS }
  );
  let body = null;
  const text = await response.text().catch(() => null);
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  return {
    http_status: response.status(),
    ok: response.ok(),
    response_ms: Date.now() - startedAt,
    response_body: body,
  };
}

async function cleanupSchedule(page, scheduleId) {
  return page.evaluate(async ({ scheduleId }) => {
    const storages = [window.localStorage, window.sessionStorage];
    let token = '';
    for (const storage of storages) {
      for (let i = 0; i < storage.length; i += 1) {
        const key = storage.key(i);
        if (!key || !key.startsWith('oidc.user:')) continue;
        const raw = storage.getItem(key);
        if (!raw) continue;
        try {
          const parsed = JSON.parse(raw);
          if (parsed?.access_token) {
            token = String(parsed.access_token);
            break;
          }
        } catch {
          // ignore malformed storage entries
        }
      }
      if (token) break;
    }
    if (!token) {
      return { ok: false, status: 0, body: 'No access token found for cleanup' };
    }

    const resp = await fetch(`/api/v1/screenings/daily-schedules/${encodeURIComponent(scheduleId)}`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    const body = await resp.text().catch(() => '');
    return { ok: resp.ok, status: resp.status, body };
  }, { scheduleId });
}

async function runBatch(page, index) {
  const batchTab = page.getByRole('tab', { name: /batch screening/i }).first();
  await batchTab.click({ timeout: STEP_TIMEOUT_MS });
  await page.locator('#panel-batch').first().waitFor({ timeout: STEP_TIMEOUT_MS });

  const batchName = `MIXED_BATCH_${RUN_TAG}_${String(index + 1).padStart(2, '0')}`;
  const batchNameField = page.locator('#panel-batch .field').filter({ has: page.getByText(/Batch Name/i) }).first().locator('input');
  await batchNameField.fill(batchName, { timeout: STEP_TIMEOUT_MS });

  const buSelect = page.locator('#panel-batch select').first();
  const business_unit_code = await selectFirstBusinessUnit(buSelect);

  const fileInput = page.locator('#panel-batch input[type="file"]').first();
  await fileInput.setInputFiles(FILE_PATH);

  const startButton = page.locator('#panel-batch .btnBatchWide').first();
  const responsePromise = waitForApiResponse(page, '/api/v1/screenings/batch-upload').catch(() => null);
  await startButton.click({ timeout: STEP_TIMEOUT_MS });
  const response = await responsePromise;
  const error_box = await readErrorBox(page);

  return {
    action: 'batch',
    batch_name: batchName,
    business_unit_code,
    http_status: response?.http_status ?? null,
    response_ms: response?.response_ms ?? null,
    ok: Boolean(response?.ok) && !error_box,
    response_body: response?.response_body ?? null,
    error_box,
  };
}

function defaultScheduleRunAtValue() {
  const dt = new Date(Date.now() + 6 * 60 * 60 * 1000);
  dt.setSeconds(0, 0);
  const pad = (n) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

async function runSchedule(page, index) {
  const scheduleTab = page.getByRole('tab', { name: /schedule screening/i }).first();
  await scheduleTab.click({ timeout: STEP_TIMEOUT_MS });
  await page.locator('#panel-schedule').first().waitFor({ timeout: STEP_TIMEOUT_MS });

  const scheduleName = `MIXED_SCHEDULE_${RUN_TAG}_${String(index + 1).padStart(2, '0')}`;
  const scheduleNameField = page.locator('#panel-schedule .field').filter({ has: page.getByText(/Schedule Name/i) }).first().locator('input');
  await scheduleNameField.fill(scheduleName, { timeout: STEP_TIMEOUT_MS });

  const buSelect = page.locator('#panel-schedule select').first();
  const business_unit_code = await selectFirstBusinessUnit(buSelect);

  const runAtInput = page.locator('#panel-schedule input[type="datetime-local"]').first();
  await runAtInput.fill(defaultScheduleRunAtValue(), { timeout: STEP_TIMEOUT_MS });

  const fileInput = page.locator('#panel-schedule input[type="file"]').first();
  await fileInput.setInputFiles(FILE_PATH);

  const startButton = page.locator('#panel-schedule .btnBatchWide').first();
  const responsePromise = waitForApiResponse(page, '/api/v1/screenings/batch-upload').catch(() => null);
  await startButton.click({ timeout: STEP_TIMEOUT_MS });
  const response = await responsePromise;
  const error_box = await readErrorBox(page);

  const scheduleId =
    response?.response_body && typeof response.response_body === 'object'
      ? response.response_body.daily_schedule_id ?? null
      : null;
  let cleanup = null;
  if (scheduleId) {
    cleanup = await cleanupSchedule(page, scheduleId).catch((error) => ({
      ok: false,
      status: 0,
      body: String(error?.message || error),
    }));
  }

  return {
    action: 'schedule',
    schedule_name: scheduleName,
    business_unit_code,
    http_status: response?.http_status ?? null,
    response_ms: response?.response_ms ?? null,
    ok: Boolean(response?.ok) && !error_box,
    response_body: response?.response_body ?? null,
    error_box,
    cleanup,
  };
}

async function runSingle(page, index) {
  const singleTab = page.getByRole('tab', { name: /single screening/i }).first();
  await singleTab.click({ timeout: STEP_TIMEOUT_MS });
  await page.locator('#panel-single').first().waitFor({ timeout: STEP_TIMEOUT_MS });

  const buSelect = page.locator('#panel-single select').first();
  const business_unit_code = await selectFirstBusinessUnit(buSelect);

  const mockCheckbox = page.locator('#panel-single .mockModeCheck input[type="checkbox"]').first();
  if (await mockCheckbox.isChecked().catch(() => false)) {
    await mockCheckbox.uncheck({ timeout: STEP_TIMEOUT_MS }).catch(() => {});
  }

  const firstNameInput = page.locator('.nameCard .field').filter({ has: page.getByText(/^First Name$/) }).first().locator('input');
  const lastNameInput = page.locator('.nameCard .field').filter({ has: page.getByText(/^Last Name$/) }).first().locator('input');
  await firstNameInput.fill(`Perf${String(index + 1).padStart(2, '0')}`, { timeout: STEP_TIMEOUT_MS });
  await lastNameInput.fill(`Single${Date.now()}`, { timeout: STEP_TIMEOUT_MS });

  const runButton = page.locator('#panel-single .btnRunWide').first();
  const responsePromise = waitForApiResponse(page, '/api/v1/screenings/match').catch(() => null);
  await runButton.click({ timeout: STEP_TIMEOUT_MS });
  const response = await responsePromise;
  const error_box = await readErrorBox(page);

  return {
    action: 'single',
    business_unit_code,
    http_status: response?.http_status ?? null,
    response_ms: response?.response_ms ?? null,
    ok: Boolean(response?.ok) && !error_box,
    response_body: response?.response_body ?? null,
    error_box,
  };
}

async function runForUser(browser, cred, index, globalStartedAt) {
  const action = cohortForIndex(index);
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const result = {
    username: cred.username,
    action,
    started_at: nowIso(),
    ok: false,
    business_unit_code: null,
    http_status: null,
    response_ms: null,
    response_body: null,
    error_box: null,
    page_error: null,
    cleanup: null,
    final_url: null,
  };

  try {
    await loginWithRetries(page, cred, 3);

    let actionResult;
    if (action === 'batch') {
      actionResult = await runBatch(page, index);
    } else if (action === 'schedule') {
      actionResult = await runSchedule(page, index);
    } else {
      actionResult = await runSingle(page, index);
    }

    Object.assign(result, actionResult);
    result.ok = Boolean(actionResult.ok);
    result.final_url = page.url();
  } catch (error) {
    result.page_error = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    result.final_url = page.url();
  } finally {
    await context.close().catch(() => {});
  }

  result.finished_at = nowIso();
  result.since_global_start_ms = Date.now() - globalStartedAt;
  return result;
}

async function main() {
  if (!fs.existsSync(FILE_PATH)) {
    throw new Error(`Input file not found: ${FILE_PATH}`);
  }

  const credentials = readCredentials();
  ensureDir(path.dirname(OUTPUT_PATH));

  const browser = await chromium.launch({ headless: true });
  const globalStartedAt = Date.now();
  const results = [];
  try {
    const settled = await Promise.allSettled(
      credentials.map((cred, index) => runForUser(browser, cred, index, globalStartedAt))
    );
    for (const entry of settled) {
      if (entry.status === 'fulfilled') {
        results.push(entry.value);
      } else {
        results.push({
          username: null,
          action: 'unknown',
          started_at: null,
          ok: false,
          business_unit_code: null,
          http_status: null,
          response_ms: null,
          response_body: null,
          error_box: null,
          page_error: String(entry.reason?.message || entry.reason),
          cleanup: null,
          final_url: null,
          finished_at: nowIso(),
          since_global_start_ms: Date.now() - globalStartedAt,
        });
      }
    }
  } finally {
    await browser.close().catch(() => {});
  }

  const byAction = {
    batch: results.filter((r) => r.action === 'batch'),
    schedule: results.filter((r) => r.action === 'schedule'),
    single: results.filter((r) => r.action === 'single'),
  };

  const responseTimes = results.map((r) => Number(r.response_ms || 0)).filter((ms) => ms > 0);
  const summary = {
    base_url: BASE_URL,
    input_file: FILE_PATH,
    credentials_file: CREDENTIALS_PATH,
    started_at: new Date(globalStartedAt).toISOString(),
    finished_at: nowIso(),
    total_users: results.length,
    total_success: results.filter((r) => r.ok).length,
    total_failed: results.filter((r) => !r.ok).length,
    response_time_ms: {
      min: responseTimes.length ? Math.min(...responseTimes) : 0,
      p50: Number(percentile(responseTimes, 50).toFixed(2)),
      p90: Number(percentile(responseTimes, 90).toFixed(2)),
      max: responseTimes.length ? Math.max(...responseTimes) : 0,
      avg: responseTimes.length ? Number((responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length).toFixed(2)) : 0,
    },
    cohorts: {
      batch: {
        total: byAction.batch.length,
        success: byAction.batch.filter((r) => r.ok).length,
        failed: byAction.batch.filter((r) => !r.ok).length,
      },
      schedule: {
        total: byAction.schedule.length,
        success: byAction.schedule.filter((r) => r.ok).length,
        failed: byAction.schedule.filter((r) => !r.ok).length,
        cleanup_success: byAction.schedule.filter((r) => r.cleanup?.ok).length,
        cleanup_failed: byAction.schedule.filter((r) => r.cleanup && !r.cleanup.ok).length,
      },
      single: {
        total: byAction.single.length,
        success: byAction.single.filter((r) => r.ok).length,
        failed: byAction.single.filter((r) => !r.ok).length,
      },
    },
    http_status_counts: results.reduce((acc, row) => {
      const key = row.http_status == null ? 'null' : String(row.http_status);
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {}),
    page_errors: results.filter((r) => r.page_error).length,
    error_boxes: results.filter((r) => r.error_box).length,
    results,
  };

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(summary, null, 2));
  console.log(JSON.stringify({ output: OUTPUT_PATH, summary }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
