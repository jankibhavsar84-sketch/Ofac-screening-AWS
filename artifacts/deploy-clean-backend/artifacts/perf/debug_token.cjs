const { chromium } = require('playwright');
(async () => {
  const base='https://d3ppga4y8wg1ck.cloudfront.net';
  const user='perf_load_user_01';
  const pass='Perf#2026Load!';
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({ignoreHTTPSErrors:true});
  const page=await context.newPage();
  await page.goto(base,{waitUntil:'domcontentloaded'});
  const signIn=page.getByRole('button',{name:/sign in/i}).first();
  if (await signIn.isVisible({timeout:5000}).catch(()=>false)) await signIn.click();
  await page.waitForURL(url=>/amazoncognito\.com/i.test(url.hostname),{timeout:45000,waitUntil:'domcontentloaded'});
  const u=page.locator('input[name="username"]').first();
  await u.waitFor({timeout:45000});
  await u.fill(user);
  const p=page.locator('input[name="password"]').first();
  if (!(await p.isVisible({timeout:2000}).catch(()=>false))) {
    await page.getByRole('button',{name:/next|continue|sign in/i}).first().click();
  }
  if (!(await p.isVisible({timeout:12000}).catch(()=>false))) {
    const usePass = page.getByRole('button',{name:/password|use password|try another way/i}).first();
    if (await usePass.isVisible({timeout:3000}).catch(()=>false)) await usePass.click();
  }
  await p.waitFor({timeout:45000});
  await p.fill(pass);
  await page.getByRole('button',{name:/sign in|continue/i}).first().click();
  await page.waitForURL(url=>url.hostname==='d3ppga4y8wg1ck.cloudfront.net' && !url.searchParams.has('code'),{timeout:45000,waitUntil:'domcontentloaded'});
  await page.goto(base+'/screening',{waitUntil:'domcontentloaded'});
  await page.waitForTimeout(3000);

  const data = await page.evaluate(async () => {
    const keys = [];
    for (let i=0;i<localStorage.length;i++) keys.push(localStorage.key(i));
    for (let i=0;i<sessionStorage.length;i++) keys.push(sessionStorage.key(i));
    let token = '';
    const stores=[localStorage,sessionStorage];
    for (const st of stores){
      for (let i=0;i<st.length;i++){
        const k=st.key(i);
        if (!k || !k.startsWith('oidc.user:')) continue;
        const raw=st.getItem(k);
        if (!raw) continue;
        try { const parsed=JSON.parse(raw); if (parsed?.access_token){ token=parsed.access_token; break; }} catch{}
      }
      if (token) break;
    }
    const result={tokenFound:!!token, keysCount:keys.length, keys:keys.slice(0,10)};
    if (!token) return result;
    const buResp = await fetch('/api/v1/admin/business-units', { headers: { Authorization: `Bearer ${token}` }});
    result['buStatus']=buResp.status;
    result['buText']=await buResp.text();
    return result;
  });

  console.log(JSON.stringify(data,null,2));
  await browser.close();
})();
