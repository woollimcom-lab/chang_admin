const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

function ensure(condition, message) {
  if (!condition) throw new Error(message);
}

async function loginIfNeeded(context, targetUrl, useAuth) {
  if (!useAuth) return;

  const loginId = process.env.CHANG_ADMIN_ID;
  const loginPw = process.env.CHANG_ADMIN_PW;
  ensure(loginId && loginPw, "CHANG_ADMIN_ID and CHANG_ADMIN_PW are required");

  const url = new URL(targetUrl);
  const baseUrl = `${url.protocol}//${url.host}`;
  const response = await context.request.post(`${baseUrl}/api/auth/token`, {
    form: { username: loginId, password: loginPw },
  });

  if (!response.ok()) {
    const body = await response.text();
    throw new Error(`login failed: ${response.status()} ${body}`);
  }

  const data = await response.json();
  ensure(data.access_token, "access_token missing");

  await context.addCookies([{
    name: "access_token",
    value: `Bearer ${data.access_token}`,
    domain: url.hostname,
    path: "/",
    httpOnly: false,
    secure: url.protocol === "https:",
  }]);
}

async function launchBrowser(spec) {
  const attempts = [];
  if (spec.channel) {
    attempts.push({ name: `channel:${spec.channel}`, options: { channel: spec.channel, headless: spec.headless !== false } });
  } else {
    attempts.push({ name: "default chromium", options: { headless: spec.headless !== false } });
    attempts.push({ name: "chrome channel", options: { channel: "chrome", headless: spec.headless !== false } });
    attempts.push({ name: "msedge channel", options: { channel: "msedge", headless: spec.headless !== false } });
  }

  let lastError;
  for (const attempt of attempts) {
    try {
      console.log(`browser attempt: ${attempt.name}`);
      return await chromium.launch(attempt.options);
    } catch (error) {
      lastError = error;
      console.error(`browser attempt failed: ${attempt.name}`);
      console.error(error && error.stack ? error.stack : String(error));
    }
  }

  throw lastError || new Error("browser launch failed");
}

async function runStep(page, step, defaultShotPath) {
  switch (step.action) {
    case "goto":
      await page.goto(step.url || page.url(), {
        waitUntil: step.waitUntil || "networkidle",
        timeout: step.timeout || 30000,
      });
      return;
    case "waitFor":
      if (step.selector) {
        await page.waitForSelector(step.selector, {
          state: step.state || "visible",
          timeout: step.timeout || 15000,
        });
      } else {
        await page.waitForTimeout(step.timeout || 1000);
      }
      return;
    case "click":
      await page.locator(step.selector).click({ timeout: step.timeout || 15000 });
      return;
    case "fill":
      await page.locator(step.selector).fill(step.value || "", { timeout: step.timeout || 15000 });
      return;
    case "press":
      await page.locator(step.selector).press(step.key || "Enter", { timeout: step.timeout || 15000 });
      return;
    case "select":
      await page.locator(step.selector).selectOption(step.value, { timeout: step.timeout || 15000 });
      return;
    case "expectVisible":
      await page.locator(step.selector).waitFor({ state: "visible", timeout: step.timeout || 15000 });
      return;
    case "expectHidden":
      await page.locator(step.selector).waitFor({ state: "hidden", timeout: step.timeout || 15000 });
      return;
    case "expectText": {
      const text = await page.locator(step.selector).innerText({ timeout: step.timeout || 15000 });
      ensure(text.includes(step.text), `expected text not found: ${step.text}`);
      return;
    }
    case "expectUrlIncludes":
      ensure(page.url().includes(step.text), `url does not include expected text: ${step.text}`);
      return;
    case "evaluate": {
      const result = await page.evaluate(step.expression);
      if (Object.prototype.hasOwnProperty.call(step, "expect")) {
        ensure(
          JSON.stringify(result) === JSON.stringify(step.expect),
          `evaluate result mismatch. actual=${JSON.stringify(result)} expected=${JSON.stringify(step.expect)}`
        );
      }
      return;
    }
    case "screenshot": {
      const shotPath = path.resolve(step.path || defaultShotPath);
      fs.mkdirSync(path.dirname(shotPath), { recursive: true });
      await page.screenshot({ path: shotPath, fullPage: !!step.fullPage });
      return;
    }
    default:
      throw new Error(`unsupported action: ${step.action}`);
  }
}

async function main() {
  const specPath = process.argv[2];
  ensure(specPath, "verification spec path is required");

  const rawSpec = fs.readFileSync(specPath, "utf8").replace(/^\uFEFF/, "");
  const spec = JSON.parse(rawSpec);
  ensure(spec.url, "verification url is required");

  const projectRoot = path.resolve(__dirname, "..");
  const defaultShotPath = spec.outputPath
    ? path.resolve(spec.outputPath)
    : path.join(projectRoot, "output", "playwright", "task-check.png");

  fs.mkdirSync(path.dirname(defaultShotPath), { recursive: true });

  const browser = await launchBrowser(spec);
  const context = await browser.newContext();
  const page = await context.newPage();
  const dialogs = [];
  const pageErrors = [];
  const consoleErrors = [];

  page.on("dialog", async (dialog) => {
    dialogs.push({ type: dialog.type(), message: dialog.message() });
    if (spec.autoDismissDialogs !== false) {
      await dialog.dismiss();
    }
  });
  page.on("pageerror", (error) => {
    pageErrors.push(error && error.message ? error.message : String(error));
  });
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });

  try {
    await loginIfNeeded(context, spec.url, spec.useAuth !== false);
    await page.goto(spec.url, {
      waitUntil: spec.initialWaitUntil || "networkidle",
      timeout: spec.initialTimeout || 30000,
    });

    const steps = Array.isArray(spec.steps) ? spec.steps : [];
    for (const step of steps) {
      await runStep(page, step, defaultShotPath);
    }

    if (spec.forbidDialogs && dialogs.length > 0) {
      throw new Error(`unexpected dialogs detected: ${JSON.stringify(dialogs)}`);
    }

    if (spec.forbidPageErrors !== false && pageErrors.length > 0) {
      throw new Error(`page errors detected: ${JSON.stringify(pageErrors)}`);
    }

    if (spec.forbidConsoleErrors && consoleErrors.length > 0) {
      throw new Error(`console errors detected: ${JSON.stringify(consoleErrors)}`);
    }

    if (Array.isArray(spec.requiredTexts)) {
      const bodyText = await page.locator("body").innerText();
      for (const text of spec.requiredTexts) {
        ensure(bodyText.includes(text), `required text missing: ${text}`);
      }
    }

    if (Array.isArray(spec.forbiddenTexts)) {
      const bodyText = await page.locator("body").innerText();
      for (const text of spec.forbiddenTexts) {
        ensure(!bodyText.includes(text), `forbidden text detected: ${text}`);
      }
    }

    if (!steps.some((step) => step.action === "screenshot")) {
      await page.screenshot({ path: defaultShotPath, fullPage: true });
    }

    console.log(defaultShotPath);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
