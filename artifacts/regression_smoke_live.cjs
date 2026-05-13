const { chromium } = require('playwright');
const fs = require('fs');

const BASE = process.env.SMOKE_BASE_URL || 'https://d2ibkkc5zn6dnw.cloudfront.net';
const users = JSON.parse(fs.readFileSync('artifacts/perf/aws_perf_users_30.json', 'utf8'));
const USERNAME = process.env.SMOKE_USER || users?.[0]?.username || 'perf_load_user_01';
const PASSWORD = process.env.SMOKE_PASS || users?.[0]?.password || 'Perf#2026Load!';

function ts() {
  return new Date().toISOString().replace(/[.:]/g, '-');
}

async function parseError(resp) {
  const raw = await resp.text();
  if (!raw) return `${resp.status} ${resp.statusText}`;
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && parsed.detail) {
      return `${resp.status}: ${parsed.detail}`;
    }
  } catch (_) {}
  return `${resp.status}: ${raw.slice(0, 800)}`;
}

async function api(path, options = {}, token = '') {
  const headers = Object.assign({}, options.headers || {});
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${BASE}${path}`, { ...options, headers });
  if (!resp.ok) {
    throw new Error(await parseError(resp));
  }
  const ct = (resp.headers.get('content-type') || '').toLowerCase();
  if (ct.includes('application/json')) {
    return await resp.json();
  }
  return await resp.text();
}

async function run() {
  const out = {};
  const startedAt = new Date().toISOString();

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  const check = async (name, fn) => {
    try {
      const detail = await fn();
      out[name] = { ok: true, detail: String(detail || 'ok') };
    } catch (err) {
      out[name] = { ok: false, detail: err?.message || String(err) };
    }
  };

  await check('health', async () => {
    const h = await api('/health');
    if (!h || h.status !== 'ok') throw new Error(JSON.stringify(h));
    return h.status;
  });

  let token = '';
  let tokenSub = '';
  await check('auth_login', async () => {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });

    const signIn = page.getByRole('button', { name: /sign in/i }).first();
    if (await signIn.isVisible({ timeout: 7000 }).catch(() => false)) {
      await signIn.click();
    }

    await page.waitForURL((url) => /amazoncognito\.com/i.test(url.hostname), {
      timeout: 60000,
      waitUntil: 'domcontentloaded',
    });

    const userInput = page.locator('input[name="username"]:visible').first();
    await userInput.waitFor({ timeout: 60000 });
    await userInput.fill(USERNAME);

    const passInput = page.locator('input[name="password"]:visible').first();
    if (!(await passInput.isVisible({ timeout: 2500 }).catch(() => false))) {
      const nextBtn = page.getByRole('button', { name: /next|continue|sign in/i }).first();
      if (await nextBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await nextBtn.click();
      }
    }

    await passInput.waitFor({ timeout: 60000 });
    await passInput.fill(PASSWORD);
    const submitInput = page.locator('input[name="signInSubmitButton"]:visible').first();
    if (await submitInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await submitInput.click();
    } else {
      await page.getByRole('button', { name: /sign in|continue/i }).first().click();
    }

    await page.waitForURL((url) => {
      return url.hostname === new URL(BASE).hostname && !url.searchParams.has('code');
    }, { timeout: 90000, waitUntil: 'domcontentloaded' });

    await page.goto(`${BASE}/screening`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    token = await page.evaluate(() => {
      let resolved = '';
      for (const store of [window.localStorage, window.sessionStorage]) {
        for (let i = 0; i < store.length; i += 1) {
          const key = store.key(i);
          if (!key || !key.startsWith('oidc.user:')) continue;
          const raw = store.getItem(key);
          if (!raw) continue;
          try {
            const parsed = JSON.parse(raw);
            if (parsed?.access_token && String(parsed.access_token).trim()) {
              resolved = String(parsed.access_token).trim();
              break;
            }
          } catch (_) {}
        }
        if (resolved) break;
      }
      return resolved;
    });

    if (!token) {
      throw new Error('No access token found after login');
    }
    try {
      const parts = token.split('.');
      if (parts.length >= 2) {
        const payloadRaw = Buffer.from(parts[1], 'base64url').toString('utf8');
        const payload = JSON.parse(payloadRaw);
        tokenSub = String(payload?.sub || '').trim();
      }
    } catch (_) {}

    return `user=${USERNAME}${tokenSub ? ` sub=${tokenSub}` : ''}`;
  });

  let buCode = '';
  await check('map_local_user_bu', async () => {
    const buList = await api('/api/v1/admin/business-units?include_inactive=true', {}, token);
    if (!Array.isArray(buList) || buList.length === 0) {
      throw new Error('No business units available');
    }
    buCode = String(buList[0].business_unit_code || '').trim();
    if (!buCode) throw new Error('business_unit_code missing');

    const mapped = await api(`/api/v1/admin/business-unit-mappings/${encodeURIComponent('local-dev-user')}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_name: 'Local Dev User', business_unit_codes: [buCode] }),
    }, token);

    await api(`/api/v1/admin/business-unit-mappings/${encodeURIComponent(USERNAME)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_name: USERNAME, business_unit_codes: [buCode] }),
    }, token);
    if (tokenSub) {
      await api(`/api/v1/admin/business-unit-mappings/${encodeURIComponent(tokenSub)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_name: USERNAME, business_unit_codes: [buCode] }),
      }, token);
    }

    return JSON.stringify(mapped);
  });

  let screeningType = 'SAN-US';
  await check('screening_types', async () => {
    const types = await api('/api/v1/screenings/types', {}, token);
    if (!Array.isArray(types) || types.length === 0) throw new Error('No screening types');
    const sanUs = types.find((t) => String(t?.value || '').trim() === 'SAN-US');
    screeningType = String((sanUs || types[0]).value || 'SAN-US').trim() || 'SAN-US';
    return `count=${types.length} selected=${screeningType}`;
  });

  await check('single_match', async () => {
    const stamp = Date.now();
    const key = `AMLP_REG_SMOKE_SINGLE_${stamp}`;
    const payload = {
      queries: {
        [key]: {
          schema: 'Person',
          properties: {
            country: ['US'],
            fullName: ['Smoke Single'],
            partyKey: key,
            businessUnit: buCode || 'US_PRU_OPES',
          },
        },
      },
      screening_types: [screeningType],
      mock_screening: true,
      business_unit_code: buCode || 'US_PRU_OPES',
      user_id: USERNAME,
      user_name: USERNAME,
    };

    const resp = await api('/api/v1/screenings/match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }, token);

    const first = Object.values(resp?.responses || {})[0] || {};
    const total = first?.total?.value ?? 0;
    const status = first?.status ?? 'n/a';
    const engine = first?.engine_message ?? 'n/a';
    return `status=${status} total=${total} engine=${engine}`;
  });

  let batchJobId = '';
  await check('batch_submit', async () => {
    const stamp = Date.now();
    const q1 = `AMLP_REG_SMOKE_B1_${stamp}`;
    const q2 = `AMLP_REG_SMOKE_B2_${stamp}`;
    const payload = {
      queries: {
        [q1]: {
          schema: 'Person',
          properties: {
            country: ['US'],
            fullName: ['Smoke Batch One'],
            partyKey: q1,
            businessUnit: buCode || 'US_PRU_OPES',
          },
        },
        [q2]: {
          schema: 'Person',
          properties: {
            country: ['US'],
            fullName: ['Smoke Batch Two'],
            partyKey: q2,
            businessUnit: buCode || 'US_PRU_OPES',
          },
        },
      },
      screening_types: [screeningType],
      mock_screening: true,
      business_unit_code: buCode || 'US_PRU_OPES',
      user_id: USERNAME,
      user_name: USERNAME,
    };

    const accepted = await api('/api/v1/screenings/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }, token);

    batchJobId = String(accepted?.job_id || '').trim();
    if (!batchJobId) throw new Error('Missing job_id');
    return `job_id=${batchJobId} status=${accepted?.status || 'n/a'}`;
  });

  await check('batch_poll', async () => {
    if (!batchJobId) throw new Error('No batch job id');
    let progress = null;
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      progress = await api(`/api/v1/screenings/jobs/${encodeURIComponent(batchJobId)}`, {}, token);
      const st = String(progress?.status || '').toUpperCase();
      if (st === 'COMPLETED' || st === 'FAILED') break;
      await new Promise((r) => setTimeout(r, 1000));
    }
    if (!progress) throw new Error('No progress response');
    return `status=${progress.status} completed=${progress.completed_items} failed=${progress.failed_items}`;
  });

  await check('submissions', async () => {
    const rows = await api('/api/v1/screenings/submissions?limit=20', {}, token);
    const count = Array.isArray(rows) ? rows.length : 0;
    return `count=${count}`;
  });

  await check('summary', async () => {
    const s = await api('/api/v1/screenings/summary', {}, token);
    return `total=${s.total} clear=${s.clear} potential=${s.potential} pending=${s.pending} failed=${s.failed}`;
  });

  await check('results', async () => {
    const rows = await api('/api/v1/screenings/results?limit=200', {}, token);
    const count = Array.isArray(rows) ? rows.length : 0;
    return `count=${count}`;
  });

  await check('daily_schedules', async () => {
    const rows = await api('/api/v1/screenings/daily-schedules', {}, token);
    const count = Array.isArray(rows) ? rows.length : 0;
    return `count=${count}`;
  });

  await check('audit_events', async () => {
    const rows = await api('/api/v1/audit-events?limit=20', {}, token);
    const count = Array.isArray(rows) ? rows.length : 0;
    return `count=${count}`;
  });

  await browser.close();

  const summary = {
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    base_url: BASE,
    user: USERNAME,
    results: out,
  };

  const outPath = `artifacts/regression_smoke_live_${ts()}.json`;
  fs.writeFileSync(outPath, JSON.stringify(summary, null, 2));
  console.log(JSON.stringify({ output: outPath, summary }, null, 2));
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
