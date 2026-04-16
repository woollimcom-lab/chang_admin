const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

async function main() {
  const targetUrl = process.argv[2];
  if (!targetUrl) throw new Error("target url is required");
  const outputArg = process.argv[3];

  const loginId = process.env.CHANG_ADMIN_ID;
  const loginPw = process.env.CHANG_ADMIN_PW;
  if (!loginId || !loginPw) {
    throw new Error("CHANG_ADMIN_ID and CHANG_ADMIN_PW are required");
  }

  const projectRoot = path.resolve(__dirname, "..");
  const outputDir = path.join(projectRoot, "output", "playwright");
  const shotPath = outputArg ? path.resolve(outputArg) : path.join(outputDir, "smoke.png");
  const shotDir = path.dirname(shotPath);
  fs.mkdirSync(shotDir, { recursive: true });

  const url = new URL(targetUrl);
  const baseUrl = `${url.protocol}//${url.host}`;

  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext();

  try {
    const response = await context.request.post(`${baseUrl}/api/auth/token`, {
      form: {
        username: loginId,
        password: loginPw,
      },
    });

    if (!response.ok()) {
      const body = await response.text();
      throw new Error(`login failed: ${response.status()} ${body}`);
    }

    const data = await response.json();
    if (!data.access_token) {
      throw new Error("login failed: access_token missing");
    }

    await context.addCookies([{
      name: "access_token",
      value: `Bearer ${data.access_token}`,
      domain: url.hostname,
      path: "/",
      httpOnly: false,
      secure: url.protocol === "https:",
    }]);

    const page = await context.newPage();
    await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 30000 });
    await page.screenshot({ path: shotPath, fullPage: true });
    console.log(shotPath);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
