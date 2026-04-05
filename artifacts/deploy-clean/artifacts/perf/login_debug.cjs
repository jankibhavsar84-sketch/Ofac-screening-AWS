const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext()).newPage();
  await page.goto('http://localhost:8080', { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('after goto', page.url());
  const signIn = page.getByRole('button', { name: /sign in/i }).first();
  try {
    if (await signIn.isVisible({ timeout: 8000 })) {
      console.log('click sign in');
      await signIn.click({ timeout: 8000 });
    }
  } catch (e) {
    console.log('no sign in button visible', e.message);
  }
  await page.waitForTimeout(2000);
  console.log('after sign-in attempt', page.url());
  await page.screenshot({ path: 'artifacts/perf/login_step1.png', fullPage: true });

  if (!/realms\/screening-local/i.test(page.url())) {
    try {
      await page.waitForURL(/realms\/screening-local/i, { timeout: 60000, waitUntil: 'domcontentloaded' });
    } catch (e) {
      console.log('wait keycloak failed', e.message);
      await page.screenshot({ path: 'artifacts/perf/login_fail_before_form.png', fullPage: true });
      throw e;
    }
  }
  console.log('at keycloak', page.url());
  await page.fill('#username', 'screening.admin');
  await page.fill('#password', 'Admin123!');
  await page.screenshot({ path: 'artifacts/perf/login_filled.png', fullPage: true });
  await page.click('#kc-login');
  console.log('clicked kc login');
  for (let i=0;i<20;i++) {
    await page.waitForTimeout(1000);
    const u = page.url();
    console.log('url', i, u);
    if (u.includes('localhost:8080')) break;
  }
  await page.screenshot({ path: 'artifacts/perf/login_after_submit.png', fullPage: true });
  await browser.close();
})();
