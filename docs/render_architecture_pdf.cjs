const path = require("path");
const { chromium } = require("playwright");

async function main() {
  const repoRoot = path.resolve(__dirname, "..");
  const htmlPath = path.join(repoRoot, "docs", "architecture-api-flow.html");
  const pdfPath = path.join(repoRoot, "docs", "architecture-api-flow.pdf");

  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1600, height: 1000 },
      deviceScaleFactor: 1.5,
    });

    await page.goto(`file:///${htmlPath.replace(/\\/g, "/")}`, {
      waitUntil: "load",
    });
    await page.emulateMedia({ media: "print" });
    await page.pdf({
      path: pdfPath,
      printBackground: true,
      preferCSSPageSize: true,
      margin: {
        top: "0mm",
        right: "0mm",
        bottom: "0mm",
        left: "0mm",
      },
    });
    console.log(`Rendered ${pdfPath}`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
