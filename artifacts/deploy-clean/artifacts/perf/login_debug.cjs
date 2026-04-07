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

  try {
    await page.waitForURL((url) => /amazoncognito\.com/i.test(url.hostname) || !url.href.startsWith('http://localhost:8080'), {
      timeout: 60000,
      waitUntil: 'domcontentloaded',
    });
  } catch (e) {
    console.log('wait hosted sign-in failed', e.message);
    await page.screenshot({ path: 'artifacts/perf/login_fail_before_form.png', fullPage: true });
    throw e;
  }
  console.log('at hosted sign-in', page.url());
  await page.fill('input[name="username"]', 'screening.admin');
  await page.fill('input[name="password"]', 'Admin123!');
  await page.screenshot({ path: 'artifacts/perf/login_filled.png', fullPage: true });
  await page.getByRole('button', { name: /sign in|continue/i }).first().click();
  console.log('submitted hosted sign-in form');
  for (let i=0;i<20;i++) {
    await page.waitForTimeout(1000);
    const u = page.url();
    console.log('url', i, u);
    if (u.includes('localhost:8080')) break;
  }
  await page.screenshot({ path: 'artifacts/perf/login_after_submit.png', fullPage: true });
  await browser.close();
})();
