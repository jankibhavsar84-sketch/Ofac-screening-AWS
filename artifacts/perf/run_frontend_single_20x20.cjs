const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'https://d2ibkkc5zn6dnw.cloudfront.net';
const STEP_TIMEOUT_MS = Number(process.env.STEP_TIMEOUT_MS || 120000);
const USERS = Number(process.env.USERS || 20);
const REQUESTS_PER_USER = Number(process.env.REQUESTS_PER_USER || 20);
const PREFERRED_BUSINESS_UNIT_CODE = String(process.env.PREFERRED_BUSINESS_UNIT_CODE || 'US_PRU_OPES').trim();
const CREDENTIALS_PATH =
  process.env.CREDENTIALS_FILE ||
  path.resolve('artifacts', 'perf', 'aws_perf_users_30.json');
const RUN_TAG = new Date().toISOString().replace(/[:.]/g, '-');
const OUTPUT_PATH = path.resolve(
  'artifacts',
  'perf',
  `frontend_single_${USERS}u_${REQUESTS_PER_USER}r_${RUN_TAG}.json`
);

function nowIso() {
  return new Date().toISOString();
}

function alphaToken(value) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  let n = Math.max(0, Number(value) || 0);
  let out = '';
  do {
    out = alphabet[n % alphabet.length] + out;
    n = Math.floor(n / alphabet.length) - 1;
  } while (n >= 0);
  return out;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, Math.min(sorted.length - 1, pos))];
}

function readCredentials() {
  const raw = fs.readFileSync(CREDENTIALS_PATH, 'utf8');
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.length < USERS) {
    throw new Error(`Expected at least ${USERS} credentials in ${CREDENTIALS_PATH}`);
  }
  return parsed.slice(0, USERS).map((item) => ({
    username: String(item.username || '').trim(),
    password: String(item.password || '').trim(),
  }));
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

  const usernameInput = page.locator('input[name="username"]:visible').first();
  await usernameInput.waitFor({ timeout: STEP_TIMEOUT_MS });
  await usernameInput.fill(cred.username, { timeout: STEP_TIMEOUT_MS });

  const passwordInput = page.locator('input[name="password"]:visible').first();
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

  const submitButton = page
    .locator('#signInSubmitButton:visible, input[name="signInSubmitButton"]:visible, button[type="submit"]:visible')
    .first();
  await submitButton.click({ timeout: STEP_TIMEOUT_MS });

  const base = new URL(BASE_URL);
  await page.waitForURL(
    (url) =>
      url.hostname === base.hostname &&
      String(url.port || '') === String(base.port || '') &&
      !url.searchParams.has('code'),
    { timeout: STEP_TIMEOUT_MS, waitUntil: 'domcontentloaded' }
  );

  await page.goto(`${BASE_URL}/screening`, {
    waitUntil: 'domcontentloaded',
    timeout: STEP_TIMEOUT_MS,
  });
  await page
    .getByRole('heading', { name: /Entity Screening Workbench/i })
    .waitFor({ timeout: STEP_TIMEOUT_MS });
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
    const details = await selectLocator.evaluate((el, preferredCode) => {
      const select = el;
      const options = Array.from(select.options).map((option) => ({
        value: String(option.value || '').trim(),
        label: String(option.textContent || '').trim(),
      }));
      const preferred = options.find((option) => option.value === preferredCode);
      const selectable = preferred || options.find((option) => option.value);
      return {
        disabled: Boolean(select.disabled),
        value: selectable ? selectable.value : '',
      };
    }, PREFERRED_BUSINESS_UNIT_CODE);

    if (!details.disabled && details.value) {
      await selectLocator.selectOption(details.value);
      return details.value;
    }

    await pageWait(1000);
  }

  throw new Error(`No Business Unit option available after waiting ${Math.round(STEP_TIMEOUT_MS / 1000)}s`);
}

async function readErrorBox(page) {
  const errorBox = page.locator('.errorBox').first();
  if (await errorBox.isVisible({ timeout: 2500 }).catch(() => false)) {
    return await errorBox.innerText().catch(() => 'Visible errorBox with unreadable text');
  }
  return null;
}

async function runSingleOnce(page, userIndex, iteration) {
  const singleTab = page.getByRole('tab', { name: /single screening/i }).first();
  await singleTab.click({ timeout: STEP_TIMEOUT_MS });
  await page.locator('#panel-single').first().waitFor({ timeout: STEP_TIMEOUT_MS });

  const buSelect = page.locator('#panel-single select').first();
  const business_unit_code = await selectFirstBusinessUnit(buSelect);

  const mockCheckbox = page.locator('#panel-single .mockModeCheck input[type="checkbox"]').first();
  if (await mockCheckbox.isChecked().catch(() => false)) {
    await mockCheckbox.uncheck({ timeout: STEP_TIMEOUT_MS }).catch(() => {});
  }

  const firstNameInput = page
    .locator('.nameCard .field')
    .filter({ has: page.getByText(/^First Name$/) })
    .first()
    .locator('input');
  const lastNameInput = page
    .locator('.nameCard .field')
    .filter({ has: page.getByText(/^Last Name$/) })
    .first()
    .locator('input');

  const firstName = `Perf${alphaToken(userIndex + 1)}`;
  const lastName = `Load${alphaToken(iteration + 1)}${alphaToken((userIndex + 1) * 3)}`;

  await firstNameInput.fill(firstName, { timeout: STEP_TIMEOUT_MS });
  await lastNameInput.fill(lastName, {
    timeout: STEP_TIMEOUT_MS,
  });

  const startedAt = Date.now();
  const runButton = page.locator('#panel-single .btnRunWide').first();
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/screenings/match') &&
      response.request().method() === 'POST',
    { timeout: STEP_TIMEOUT_MS }
  );
  await runButton.click({ timeout: STEP_TIMEOUT_MS });

  const response = await responsePromise;
  const responseText = await response.text().catch(() => null);
  let responseBody = null;
  if (responseText) {
    try {
      responseBody = JSON.parse(responseText);
    } catch {
      responseBody = responseText;
    }
  }

  const errorBox = await readErrorBox(page);
  let businessOk = true;
  if (responseBody && typeof responseBody === 'object') {
    const responses = responseBody.responses;
    if (responses && typeof responses === 'object') {
      const rows = Object.values(responses);
      if (rows.length) {
        businessOk = rows.every((row) => {
          if (!row || typeof row !== 'object') return false;
          const status = Number(row.status || 0);
          const errorText = String(row.error_text || '').trim();
          return status === 200 && !errorText;
        });
      }
    }
  }
  return {
    business_unit_code,
    http_status: response.status(),
    ok: response.ok() && !errorBox && businessOk,
    response_ms: Date.now() - startedAt,
    response_body: responseBody,
    error_box: errorBox,
    business_ok: businessOk,
  };
}

async function runForUser(browser, cred, userIndex, globalStartedAt) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const userResult = {
    username: cred.username,
    started_at: nowIso(),
    finished_at: null,
    ok: false,
    requests: [],
    final_url: null,
    page_error: null,
  };

  try {
    await loginWithRetries(page, cred, 3);

    for (let i = 0; i < REQUESTS_PER_USER; i += 1) {
      const requestResult = {
        sequence: i + 1,
        ok: false,
        business_ok: null,
        business_unit_code: null,
        http_status: null,
        response_ms: null,
        response_body: null,
        error_box: null,
        page_error: null,
        started_at: nowIso(),
        finished_at: null,
      };

      try {
        const single = await runSingleOnce(page, userIndex, i);
        requestResult.ok = Boolean(single.ok);
        requestResult.business_unit_code = single.business_unit_code;
        requestResult.http_status = single.http_status;
        requestResult.response_ms = single.response_ms;
        requestResult.response_body = single.response_body;
        requestResult.error_box = single.error_box;
        requestResult.business_ok = single.business_ok;
      } catch (error) {
        requestResult.page_error =
          error instanceof Error ? `${error.name}: ${error.message}` : String(error);
        await page.goto(`${BASE_URL}/screening`, {
          waitUntil: 'domcontentloaded',
          timeout: STEP_TIMEOUT_MS,
        }).catch(() => {});
      }

      requestResult.finished_at = nowIso();
      userResult.requests.push(requestResult);
      await pageWait(120 + Math.floor(Math.random() * 180));
    }

    userResult.ok = userResult.requests.every((r) => r.ok);
    userResult.final_url = page.url();
  } catch (error) {
    userResult.page_error =
      error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    userResult.final_url = page.url();
  } finally {
    await context.close().catch(() => {});
  }

  userResult.finished_at = nowIso();
  userResult.since_global_start_ms = Date.now() - globalStartedAt;
  return userResult;
}

async function main() {
  const credentials = readCredentials();
  ensureDir(path.dirname(OUTPUT_PATH));

  const browser = await chromium.launch({ headless: true });
  const globalStartedAt = Date.now();
  const users = [];

  try {
    const settled = await Promise.allSettled(
      credentials.map((cred, index) => runForUser(browser, cred, index, globalStartedAt))
    );

    for (const entry of settled) {
      if (entry.status === 'fulfilled') {
        users.push(entry.value);
      } else {
        users.push({
          username: null,
          started_at: null,
          finished_at: nowIso(),
          ok: false,
          requests: [],
          final_url: null,
          page_error: String(entry.reason?.message || entry.reason),
          since_global_start_ms: Date.now() - globalStartedAt,
        });
      }
    }
  } finally {
    await browser.close().catch(() => {});
  }

  const requests = users.flatMap((u) => u.requests);
  const responseTimes = requests
    .map((r) => Number(r.response_ms || 0))
    .filter((ms) => ms > 0);

  const summary = {
    base_url: BASE_URL,
    users_configured: USERS,
    requests_per_user_configured: REQUESTS_PER_USER,
    credentials_file: CREDENTIALS_PATH,
    started_at: new Date(globalStartedAt).toISOString(),
    finished_at: nowIso(),
    total_users: users.length,
    users_all_success: users.filter((u) => u.ok).length,
    users_with_any_failure: users.filter((u) => !u.ok).length,
    total_requests_expected: USERS * REQUESTS_PER_USER,
    total_requests_attempted: requests.length,
    total_requests_success: requests.filter((r) => r.ok).length,
    total_requests_failed: requests.filter((r) => !r.ok).length,
    response_time_ms: {
      min: responseTimes.length ? Math.min(...responseTimes) : 0,
      p50: Number(percentile(responseTimes, 50).toFixed(2)),
      p90: Number(percentile(responseTimes, 90).toFixed(2)),
      max: responseTimes.length ? Math.max(...responseTimes) : 0,
      avg: responseTimes.length
        ? Number((responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length).toFixed(2))
        : 0,
    },
    http_status_counts: requests.reduce((acc, row) => {
      const key = row.http_status == null ? 'null' : String(row.http_status);
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {}),
    request_error_boxes: requests.filter((r) => r.error_box).length,
    request_page_errors: requests.filter((r) => r.page_error).length,
    users_with_login_or_fatal_error: users.filter((u) => u.page_error).length,
    users,
  };

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(summary, null, 2));
  console.log(JSON.stringify({ output: OUTPUT_PATH, summary }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
