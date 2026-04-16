const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

function text(value, fallback = "") {
  const rendered = String(value ?? "").trim();
  return rendered || fallback;
}

function parseCliArgs(argv) {
  const args = Array.from(argv || []);
  const baseUrl = args.shift() || "http://127.0.0.1:8001";
  let outputDirArg = path.join("output", "playwright", "codex-chat-bridge");
  const submitCommand = args.includes("--submit");
  if (submitCommand) {
    args.splice(args.indexOf("--submit"), 1);
  }
  const outputDirFlagIndex = args.findIndex((arg) => arg === "--output-dir");
  if (outputDirFlagIndex >= 0) {
    const flaggedOutputDir = text(args[outputDirFlagIndex + 1]);
    if (flaggedOutputDir) {
      outputDirArg = flaggedOutputDir;
    }
    args.splice(outputDirFlagIndex, flaggedOutputDir ? 2 : 1);
  }
  const message = text(args.join(" "), "브리지 검증 명령");
  return { baseUrl: baseUrl.replace(/\/$/, ""), message, outputDirArg, submitCommand };
}

async function main() {
  const { baseUrl, message, outputDirArg, submitCommand } = parseCliArgs(process.argv.slice(2));
  const loginId = process.env.CHANG_ADMIN_ID;
  const loginPw = process.env.CHANG_ADMIN_PW;
  if (!loginId || !loginPw) {
    throw new Error("CHANG_ADMIN_ID and CHANG_ADMIN_PW are required");
  }

  const projectRoot = path.resolve(__dirname, "..");
  const outputDir = path.resolve(projectRoot, outputDirArg);
  fs.mkdirSync(outputDir, { recursive: true });
  const resultPath = path.join(outputDir, "bridge_verify.json");
  const shotPath = path.join(outputDir, "bridge_verify.png");
  const result = {
    ok: false,
    baseUrl,
    targetUrl: `${baseUrl}/codex-chat`,
    message,
    submitCommand,
    loginStatus: 0,
    stateApiStatus: 0,
    bridgeMode: "",
    bridgeGoal: "",
    viewKind: "",
    serviceModule: "",
    serviceBoundary: "",
    commandPresent: false,
    runStatePresent: false,
    summaryPresent: false,
    publicProjectsEmpty: false,
    publicRecentTasksEmpty: false,
    publicSummaryCountsEmpty: false,
    publicStarterPromptsEmpty: false,
    inputVisible: false,
    inputEditable: false,
    visibleTextareaCount: 0,
    visibleCommandButtonCount: 0,
    visibleLegacyFocusableCount: 0,
    rootBridgeMode: "",
    statusVisible: false,
    statusDetailsHidden: false,
    resultVisible: false,
    resultLabels: [],
    goalCriteria: {
      oneLineInput: false,
      minimalStatus: false,
      lastResult: false,
      localCodexBridge: false,
      legacyHidden: false,
    },
    legacyVisible: {},
    legacyHiddenOk: false,
    sent: false,
    postSendNotice: "",
    screenshot: shotPath,
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const loginResponse = await context.request.post(`${baseUrl}/api/auth/token`, {
      form: { username: loginId, password: loginPw },
    });
    result.loginStatus = loginResponse.status();
    if (!loginResponse.ok()) {
      result.loginBody = await loginResponse.text();
      throw new Error(`login failed: ${loginResponse.status()}`);
    }
    const auth = await loginResponse.json();
    if (!auth.access_token) {
      throw new Error("login failed: access_token missing");
    }
    const hostname = new URL(baseUrl).hostname;
    await context.addCookies([
      {
        name: "access_token",
        value: auth.access_token,
        domain: hostname,
        path: "/",
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);

    const page = await context.newPage();
    await page.goto(result.targetUrl, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForSelector("#chatInput", { timeout: 15000 });

    const stateProbe = await page.evaluate(async () => {
      const response = await fetch("/api/codex-chat/state", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      return { status: response.status, payload };
    });
    const payload = stateProbe.payload || {};
    result.stateApiStatus = stateProbe.status;
    result.bridgeMode = text(payload.bridge_mode);
    result.bridgeGoal = text(payload.bridge_goal);
    result.viewKind = text(payload.view_kind);
    result.serviceModule = text(payload.service_module);
    result.serviceBoundary = text(payload.service_boundary);
    result.commandPresent = Boolean(text(payload.command));
    result.runStatePresent = Boolean(text(payload.run_state));
    result.summaryPresent = Boolean(text(payload.summary));
    result.publicProjectsEmpty = Array.isArray(payload.projects) && payload.projects.length === 0;
    result.publicRecentTasksEmpty = Array.isArray(payload.recent_tasks) && payload.recent_tasks.length === 0;
    result.publicSummaryCountsEmpty = Array.isArray(payload.summary_counts) && payload.summary_counts.length === 0;
    result.publicStarterPromptsEmpty = Array.isArray(payload.starter_prompts) && payload.starter_prompts.length === 0;

    const input = page.locator("#chatInput");
    result.inputVisible = await input.isVisible().catch(() => false);
    result.inputEditable = await input.isEditable().catch(() => false);
    result.visibleTextareaCount = await page
      .locator("textarea")
      .evaluateAll((els) => els.filter((el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      }).length)
      .catch(() => 0);
    result.visibleCommandButtonCount = await page
      .locator("button")
      .evaluateAll((els) => els.filter((el) => {
        const label = String(el.textContent || "").trim();
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        const visible = style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
        return visible && /명령 보내기|맞아요, 진행/.test(label);
      }).length)
      .catch(() => 0);
    result.rootBridgeMode = text(await page.locator("#codexChatApp").getAttribute("data-bridge-mode").catch(() => ""));
    result.statusVisible = await page.locator("#autonomyBanner").isVisible().catch(() => false);
    result.statusDetailsHidden = await page
      .locator("#autonomyBannerCopy, #autonomyBannerMeta, #autonomyBannerStatusRow, #autonomyBannerProgressTrack")
      .evaluateAll((els) => els.every((el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display === "none" || style.visibility === "hidden" || rect.width === 0 || rect.height === 0;
      }))
      .catch(() => false);
    result.resultVisible = await page.locator("#taskWorkspacePanel").isVisible().catch(() => false);
    result.resultLabels = await page
      .locator("#taskCard .task-card-label")
      .evaluateAll((els) => els.map((el) => String(el.textContent || "").trim()).filter(Boolean))
      .catch(() => []);

    const legacyKeys = [
      "summary",
      "project",
      "project-toggle",
      "project-drawer",
      "project-overlay",
      "composer-mode",
      "composer-context",
      "starter-prompts",
      "send-and-run",
      "reset-task",
      "primary-action",
      "queue-panel",
      "queue-toggle",
      "queue-overlay",
    ];
    for (const key of legacyKeys) {
      result.legacyVisible[key] = await page
        .locator(`[data-bridge-legacy="${key}"]`)
        .first()
        .isVisible()
        .catch(() => false);
    }
    result.visibleLegacyFocusableCount = await page
      .locator("[data-bridge-legacy] button, [data-bridge-legacy] input, [data-bridge-legacy] textarea, button[data-bridge-legacy], input[data-bridge-legacy], textarea[data-bridge-legacy]")
      .evaluateAll((els) => els.filter((el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0 && !el.disabled;
      }).length)
      .catch(() => 0);
    result.legacyHiddenOk = Object.values(result.legacyVisible).every((visible) => visible === false);
    result.goalCriteria.oneLineInput = Boolean(
      result.inputVisible &&
      result.inputEditable &&
      result.visibleTextareaCount === 1 &&
      result.visibleCommandButtonCount === 1
    );
    result.goalCriteria.minimalStatus = Boolean(result.statusVisible && result.statusDetailsHidden);
    result.goalCriteria.lastResult = Boolean(
      result.resultVisible &&
      result.resultLabels.includes("상태") &&
      result.resultLabels.includes("명령") &&
      result.resultLabels.includes("요약") &&
      result.resultLabels.every((label) => ["상태", "명령", "요약", "오류"].includes(label))
    );
    result.goalCriteria.localCodexBridge = Boolean(
      result.stateApiStatus === 200 &&
      (result.bridgeMode === "thin-bridge" || result.viewKind === "codex-max-minimal") &&
      result.serviceModule === "services.codex_chat_active_service" &&
      result.serviceBoundary === "active-service-owns-mobile-control-adapter"
    );
    result.goalCriteria.legacyHidden = result.legacyHiddenOk && result.visibleLegacyFocusableCount === 0;

    if (submitCommand && result.inputVisible && result.inputEditable) {
      await input.fill(message);
      await page.locator("#sendButton").click();
      result.sent = true;
      const confirmRunButton = page.locator('[data-confirm-command="run"]').first();
      if (await confirmRunButton.isVisible().catch(() => false)) {
        await confirmRunButton.click();
      }
      await page.waitForTimeout(1200);
      result.postSendNotice = text(await page.locator("#pageNotice").textContent().catch(() => ""));
    }

    await page.screenshot({ path: shotPath, fullPage: true }).catch(() => {});
    const bridgeModeOk = result.bridgeMode === "thin-bridge" || result.viewKind === "codex-max-minimal";
    const bridgeFieldsOk = result.bridgeMode === "thin-bridge"
      ? (result.runStatePresent && result.summaryPresent)
      : (result.resultLabels.includes("상태") && result.resultLabels.includes("명령") && result.resultLabels.includes("요약"));
    const publicDataOk = result.bridgeMode === "thin-bridge"
      ? (
        result.publicProjectsEmpty &&
        result.publicRecentTasksEmpty &&
        result.publicSummaryCountsEmpty &&
        result.publicStarterPromptsEmpty
      )
      : true;
    result.ok = Boolean(
      result.loginStatus === 200 &&
      result.stateApiStatus === 200 &&
      bridgeModeOk &&
      result.rootBridgeMode === "thin-bridge" &&
      result.goalCriteria.oneLineInput &&
      result.goalCriteria.minimalStatus &&
      result.goalCriteria.lastResult &&
      result.goalCriteria.localCodexBridge &&
      bridgeFieldsOk &&
      publicDataOk &&
      result.goalCriteria.legacyHidden &&
      (!submitCommand || result.sent)
    );
  } finally {
    fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), "utf8");
    await browser.close();
  }

  console.log(`bridge_verify_json=${resultPath}`);
  console.log(`ok=${result.ok}`);
  console.log(
    `bridge_summary=mode=${result.bridgeMode || result.viewKind}, input=${result.goalCriteria.oneLineInput ? "ok" : "fail"}, status=${result.goalCriteria.minimalStatus ? "ok" : "fail"}, result=${result.goalCriteria.lastResult ? "ok" : "fail"}, localBridge=${result.goalCriteria.localCodexBridge ? "ok" : "fail"}, legacy=${result.goalCriteria.legacyHidden ? "ok" : "fail"}, submit=${submitCommand ? "on" : "off"}, sent=${result.sent ? "ok" : "skipped"}`
  );
  process.exit(result.ok ? 0 : 1);
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
