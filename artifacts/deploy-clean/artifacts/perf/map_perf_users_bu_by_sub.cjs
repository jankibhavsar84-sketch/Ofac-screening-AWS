const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const base='https://d3ppga4y8wg1ck.cloudfront.net';
  const adminUser='perf_load_user_01';
  const adminPass='Perf#2026Load!';
  const users=JSON.parse(fs.readFileSync('artifacts/perf/aws_perf_users_with_sub.json','utf8'));

  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({ignoreHTTPSErrors:true});
  const page=await context.newPage();
  await page.goto(base,{waitUntil:'domcontentloaded'});
  const signIn=page.getByRole('button',{name:/sign in/i}).first();
  if (await signIn.isVisible({timeout:5000}).catch(()=>false)) await signIn.click();
  await page.waitForURL(url=>/amazoncognito\.com/i.test(url.hostname),{timeout:45000,waitUntil:'domcontentloaded'});
  const u=page.locator('input[name="username"]').first();
  await u.waitFor({timeout:45000});
  await u.fill(adminUser);
  const p=page.locator('input[name="password"]').first();
  if (!(await p.isVisible({timeout:2000}).catch(()=>false))) {
    await page.getByRole('button',{name:/next|continue|sign in/i}).first().click();
  }
  await p.waitFor({timeout:45000});
  await p.fill(adminPass);
  await page.getByRole('button',{name:/sign in|continue/i}).first().click();
  await page.waitForURL(url=>url.hostname==='d3ppga4y8wg1ck.cloudfront.net' && !url.searchParams.has('code'),{timeout:45000,waitUntil:'domcontentloaded'});
  await page.goto(base+'/screening',{waitUntil:'domcontentloaded'});
  await page.waitForTimeout(1200);

  const result = await page.evaluate(async ({users}) => {
    let token='';
    for (const st of [localStorage,sessionStorage]) {
      for (let i=0;i<st.length;i++) {
        const key=st.key(i);
        if (!key || !key.startsWith('oidc.user:')) continue;
        const raw=st.getItem(key);
        if (!raw) continue;
        try { const parsed=JSON.parse(raw); if (parsed?.access_token) { token=parsed.access_token; break; } } catch {}
      }
      if (token) break;
    }
    if (!token) throw new Error('No access token found');
    const headers={ 'Authorization': `Bearer ${token}`, 'Content-Type':'application/json' };
    const buResp=await fetch('/api/v1/admin/business-units',{headers});
    const buList=await buResp.json();
    const codes=(Array.isArray(buList)?buList:[]).map((x)=>String(x.business_unit_code||'').trim()).filter(Boolean);
    if (!codes.length) throw new Error('No business units available');
    const targetCodes=[codes[0]];
    let ok=0;
    const failed=[];
    for (const row of users) {
      const userId=String(row.user_id||'').trim();
      const userName=String(row.username||'').trim();
      const resp=await fetch(`/api/v1/admin/business-unit-mappings/${encodeURIComponent(userId)}`, {
        method:'PUT',
        headers,
        body: JSON.stringify({ user_name: userName, business_unit_codes: targetCodes }),
      });
      if (resp.ok) ok+=1;
      else failed.push({userId,userName,status:resp.status,body:await resp.text()});
    }
    return {mapped:ok, failed, targetCodes};
  }, { users });

  console.log(JSON.stringify(result,null,2));
  await browser.close();
})();
