const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'http://localhost:8080';
const VUS = Number(process.env.VUS || 20);
const ITERATIONS = Number(process.env.ITERATIONS || 3);
const TIMEOUT_MS = Number(process.env.STEP_TIMEOUT_MS || 30000);

const DEFAULT_CREDENTIALS = [
  { username: 'screening.admin', password: 'Admin123!' },
  { username: 'screening.analyst', password: 'Analyst123!' },
  { username: 'screening.viewer', password: 'Viewer123!' },
];

const CREDENTIALS = (() => {
  const raw = String(process.env.CREDENTIALS_JSON || '').trim();
  if (!raw) return DEFAULT_CREDENTIALS;
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length) {
      const normalized = parsed
        .map((row) => ({
          username: String(row?.username || '').trim(),
          password: String(row?.password || '').trim(),
        }))
        .filter((row) => row.username && row.password);
      if (normalized.length) return normalized;
    }
  } catch {
    // fallback to defaults
  }
  return DEFAULT_CREDENTIALS;
})();

function nowIso() {
  return new Date().toISOString();
}

function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[idx];
}

async function clickIfEnabled(locator) {
  try {
    if (await locator.isEnabled({ timeout: 1500 })) {
      await locator.click({ timeout: 5000 });
      return true;
    }
  } catch {
    return false;
  }
  return false;
}

async function login(page, cred) {
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS });

  if (!/realms\/screening-local/i.test(page.url())) {
    const signInButton = page.getByRole('button', { name: /sign in/i }).first();
    try {
      if (await signInButton.isVisible({ timeout: 6000 })) {
        await signInButton.click({ timeout: 6000 });
      }
    } catch {
      // optional, app may auto-redirect to IdP
    }
  }

  await page.waitForURL(
    (url) => /realms\/screening-local/i.test(url.href) || /amazoncognito\.com/i.test(url.hostname),
    { timeout: TIMEOUT_MS, waitUntil: 'domcontentloaded' }
  );

  if (/realms\/screening-local/i.test(page.url())) {
    await page.fill('#username', cred.username, { timeout: TIMEOUT_MS });
    await page.fill('#password', cred.password, { timeout: TIMEOUT_MS });
    await page.click('#kc-login', { timeout: TIMEOUT_MS });
  } else {
    const usernameField = page.locator('input[name="username"]').first();
    await usernameField.waitFor({ timeout: TIMEOUT_MS });
    await usernameField.fill(cred.username, { timeout: TIMEOUT_MS });

    const nextButton = page.getByRole('button', { name: /next|continue|sign in/i }).first();
    await nextButton.click({ timeout: TIMEOUT_MS });

    const passwordField = page.locator('input[name="password"]').first();
    const passwordVisible = await passwordField.isVisible({ timeout: 12000 }).catch(() => false);
    if (!passwordVisible) {
      const usePasswordButton = page.getByRole('button', { name: /password|use password|try another way/i }).first();
      if (await usePasswordButton.isVisible({ timeout: 4000 }).catch(() => false)) {
        await usePasswordButton.click({ timeout: TIMEOUT_MS });
      }
    }

    await passwordField.waitFor({ timeout: TIMEOUT_MS });
    await passwordField.fill(cred.password, { timeout: TIMEOUT_MS });

    const signInButton = page.getByRole('button', { name: /sign in|continue/i }).first();
    await signInButton.click({ timeout: TIMEOUT_MS });
  }

  const base = new URL(BASE_URL);
  await page.waitForURL(
    (url) => url.hostname === base.hostname && String(url.port || '') === String(base.port || '') && !url.searchParams.has('code'),
    { timeout: TIMEOUT_MS, waitUntil: 'domcontentloaded' }
  );
  if (!/\/screening(?:\/|$)/i.test(page.url())) {
    await page.goto(`${BASE_URL}/screening`, { waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS });
  }
  await page.getByRole('heading', { name: /Entity Screening Workbench/i }).waitFor({ timeout: TIMEOUT_MS });
}

async function runScenario(vuId, cred) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  const stepLatencies = [];
  const errors = [];
  const scenarioStart = Date.now();

  const recordStep = (name, startedAt, ok, errText) => {
    const ms = Date.now() - startedAt;
    stepLatencies.push({ name, ms, ok });
    if (!ok) errors.push({ step: name, error: errText || 'unknown' });
  };

  try {
    const loginStart = Date.now();
    try {
      await login(page, cred);
      recordStep('login', loginStart, true);
    } catch (err) {
      recordStep('login', loginStart, false, String(err?.message || err));
      throw err;
    }

    for (let i = 0; i < ITERATIONS; i += 1) {
      const refreshStart = Date.now();
      try {
        const refreshButton = page.getByRole('button', { name: /refreshing? screening results/i }).first();
        const visible = await refreshButton.isVisible({ timeout: 3000 }).catch(() => false);
        if (visible) {
          const disabled = await refreshButton.isDisabled();
          if (!disabled) {
            await refreshButton.click({ timeout: 10000 });
          }
        }
        recordStep('refresh_results', refreshStart, true);
      } catch (err) {
        recordStep('refresh_results', refreshStart, false, String(err?.message || err));
      }

      const searchStart = Date.now();
      try {
        const search = page.getByLabel(/search screening results/i);
        await search.fill(`vu_${vuId}_iter_${i}`, { timeout: 8000 });
        await page.waitForTimeout(150);
        await search.fill('', { timeout: 8000 });
        recordStep('search_results', searchStart, true);
      } catch (err) {
        recordStep('search_results', searchStart, false, String(err?.message || err));
      }

      const tabsStart = Date.now();
      try {
        const batchTab = page.getByRole('tab', { name: /batch screening/i });
        const scheduleTab = page.getByRole('tab', { name: /schedule screening/i });
        const singleTab = page.getByRole('tab', { name: /single screening/i });
        await clickIfEnabled(batchTab);
        await page.waitForTimeout(80);
        await clickIfEnabled(scheduleTab);
        await page.waitForTimeout(80);
        await clickIfEnabled(singleTab);
        recordStep('switch_tabs', tabsStart, true);
      } catch (err) {
        recordStep('switch_tabs', tabsStart, false, String(err?.message || err));
      }

      const cardStart = Date.now();
      try {
        const cards = page.locator('.summaryCard');
        await cards.first().waitFor({ timeout: 8000 });
        const count = await cards.count();
        if (count < 4) throw new Error(`Unexpected summary card count: ${count}`);
        recordStep('read_dashboard_cards', cardStart, true);
      } catch (err) {
        recordStep('read_dashboard_cards', cardStart, false, String(err?.message || err));
      }
    }
  } finally {
    await context.close();
    await browser.close();
  }

  return {
    vuId,
    username: cred.username,
    startedAt: new Date(scenarioStart).toISOString(),
    finishedAt: nowIso(),
    totalMs: Date.now() - scenarioStart,
    steps: stepLatencies,
    errors,
  };
}

(async () => {
  const startedAt = Date.now();
  const tasks = [];
  for (let i = 0; i < VUS; i += 1) {
    tasks.push(runScenario(i + 1, CREDENTIALS[i % CREDENTIALS.length]));
  }

  const settled = await Promise.allSettled(tasks);
  const completed = [];
  const fatalErrors = [];

  for (const result of settled) {
    if (result.status === 'fulfilled') completed.push(result.value);
    else fatalErrors.push(String(result.reason?.message || result.reason));
  }

  const allSteps = completed.flatMap((x) => x.steps);
  const allStepMs = allSteps.map((s) => s.ms);
  const successfulVus = completed.filter((x) => x.errors.length === 0).length;
  const failedVus = completed.length - successfulVus + fatalErrors.length;

  const summary = {
    baseUrl: BASE_URL,
    vus: VUS,
    iterationsPerVu: ITERATIONS,
    startedAt: new Date(startedAt).toISOString(),
    finishedAt: nowIso(),
    durationMs: Date.now() - startedAt,
    completedVus: completed.length,
    successfulVus,
    failedVus,
    fatalErrors,
    totalSteps: allSteps.length,
    avgStepMs: allStepMs.length ? Number((allStepMs.reduce((a, b) => a + b, 0) / allStepMs.length).toFixed(2)) : 0,
    p95StepMs: Number(percentile(allStepMs, 95).toFixed(2)),
    p99StepMs: Number(percentile(allStepMs, 99).toFixed(2)),
    maxStepMs: allStepMs.length ? Math.max(...allStepMs) : 0,
  };

  const outDir = path.join('artifacts', 'perf');
  fs.mkdirSync(outDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outFile = path.join(outDir, `ui_stress_20_users_${stamp}.json`);
  fs.writeFileSync(outFile, JSON.stringify({ summary, completed }, null, 2), 'utf8');

  console.log('Stress test summary:');
  console.log(JSON.stringify(summary, null, 2));
  console.log(`Report: ${outFile}`);

  if (failedVus > 0) {
    process.exitCode = 2;
  }
})();
