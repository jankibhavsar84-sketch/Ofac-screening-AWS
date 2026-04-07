const { chromium } = require('playwright');
(async () => {
 const browser = await chromium.launch({headless:true});
 const page = await (await browser.newContext()).newPage();
 await page.goto('http://localhost:8080');
 await page.getByRole('button',{name:/sign in/i}).click();
 await page.fill('input[name="username"]','screening.admin');
 await page.fill('input[name="password"]','Admin123!');
 await page.getByRole('button',{name:/sign in|continue/i}).first().click();
 for (let i=0;i<30;i++){
  await page.waitForTimeout(1000);
  console.log(i,page.url());
 }
 await browser.close();
})();
