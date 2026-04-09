const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'https://d3ppga4y8wg1ck.cloudfront.net';
const STEP_TIMEOUT_MS = Number(process.env.STEP_TIMEOUT_MS || 90000);
const FILE_PATH =
  process.env.INPUT_FILE ||
  'C:\\Users\\Tapan Bhavsar\\Documents\\OFAC Screening Project\\sample_generated_populated_2603230040.xlsx';
const CREDENTIALS_PATH =
  process.env.CREDENTIALS_FILE ||
  path.resolve('artifacts', 'deploy-clean-backend', 'artifacts', 'perf', 'aws_perf_users.json');
const RUN_TAG = new Date().toISOString().replace(/[:.]/g, '-');
const OUTPUT_PATH = path.resolve('artifacts', 'perf', `batch_upload_same_file_20_users_${RUN_TAG}.json`);

function readCredentials() {
  const raw = fs.readFileSync(CREDENTIALS_PATH, 'utf8');
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.length < 20) {
    throw new Error(`Expected at least 20 credentials in ${CREDENTIALS_PATH}`);
  }
  return parsed.slice(0, 20).map((item) => ({
    username: String(item.username || '').trim(),
    password: String(item.password || '').trim(),
  }));
}

function nowIso() {
  return new Date().toISOString();
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
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

async function selectFirstBusinessUnit(selectLocator) {
  await selectLocator.waitFor({ timeout: STEP_TIMEOUT_MS });
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    const value = await selectLocator.evaluate((el) => {
      const select = el;
      const option = Array.from(select.options).find((o) => String(o.value || '').trim());
      return option ? String(option.value) : '';
    });
    if (value) {
      await selectLocator.selectOption(value);
      return value;
    }
    await pageWait(750);
  }
  throw new Error('No Business Unit option available');
}

async function pageWait(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function uploadBatchForUser(browser, cred, index, startedAt) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const result = {
    username: cred.username,
    started_at: nowIso(),
    batch_name: `BULK_SHARED_FILE_${RUN_TAG}_${String(index + 1).padStart(2, '0')}`,
    business_unit_code: null,
    http_status: null,
    response_ms: null,
    ok: false,
    response_body: null,
    page_error: null,
    error_box: null,
    final_url: null,
  };

  try {
    await login(page, cred);

    const batchTab = page.getByRole('tab', { name: /batch screening/i }).first();
    await batchTab.click({ timeout: STEP_TIMEOUT_MS });
    await page.locator('#panel-batch').first().waitFor({ timeout: STEP_TIMEOUT_MS });

    const batchNameField = page.locator('#panel-batch .field').filter({ has: page.getByText(/Batch Name/i) }).first().locator('input');
    await batchNameField.fill(result.batch_name, { timeout: STEP_TIMEOUT_MS });

    const buSelect = page.locator('#panel-batch select').first();
    result.business_unit_code = await selectFirstBusinessUnit(buSelect);

    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles(FILE_PATH);

    const startButton = page.locator('#panel-batch .btnBatchWide').first();
    await startButton.waitFor({ timeout: STEP_TIMEOUT_MS });

    const clickStartedAt = Date.now();
    const responsePromise = page
      .waitForResponse(
        (response) =>
          response.url().includes('/api/v1/screenings/batch-upload') &&
          response.request().method() === 'POST',
        { timeout: STEP_TIMEOUT_MS }
      )
      .catch(() => null);

    await startButton.click({ timeout: STEP_TIMEOUT_MS });

    const response = await responsePromise;
    result.response_ms = Date.now() - clickStartedAt;

    if (response) {
      result.http_status = response.status();
      const text = await response.text().catch(() => null);
      if (text) {
        try {
          result.response_body = JSON.parse(text);
        } catch {
          result.response_body = text;
        }
      }
      result.ok = response.ok();
    }

    const errorBox = page.locator('.errorBox').first();
    if (await errorBox.isVisible({ timeout: 3000 }).catch(() => false)) {
      result.error_box = await errorBox.innerText().catch(() => 'Visible errorBox with unreadable text');
      result.ok = false;
    }

    result.final_url = page.url();
  } catch (error) {
    result.page_error = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    result.final_url = page.url();
  } finally {
    await context.close().catch(() => {});
  }

  result.finished_at = nowIso();
  result.since_global_start_ms = Date.now() - startedAt;
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
  const summary = {
    base_url: BASE_URL,
    input_file: FILE_PATH,
    credentials_file: CREDENTIALS_PATH,
    started_at: nowIso(),
    results: [],
  };

  try {
    summary.results = await Promise.all(
      credentials.map((cred, index) => uploadBatchForUser(browser, cred, index, globalStartedAt))
    );
  } finally {
    await browser.close().catch(() => {});
  }

  summary.finished_at = nowIso();
  summary.total_users = summary.results.length;
  summary.http_200 = summary.results.filter((r) => r.http_status === 200).length;
  summary.http_non_200 = summary.results.filter((r) => r.http_status && r.http_status !== 200).length;
  summary.page_errors = summary.results.filter((r) => r.page_error).length;
  summary.error_boxes = summary.results.filter((r) => r.error_box).length;
  summary.successful_submissions = summary.results.filter((r) => r.ok).length;
  summary.failed_submissions = summary.results.filter((r) => !r.ok).length;

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(summary, null, 2));
  console.log(JSON.stringify({ output: OUTPUT_PATH, summary }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
