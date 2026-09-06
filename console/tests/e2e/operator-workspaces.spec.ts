import { readFileSync } from "node:fs";
import ts from "typescript";
import { expect, test, type Page } from "@playwright/test";
import { routeMocks } from "./settings-mock-page";

const routes = [
  ["overview", "dashboard", "dashboard.html"],
  ["overview", "dashboard-v2", "dashboard-v2.html"],
  ["overview", "operating-outcomes", "operating-outcomes.html"],
  ["overview", "control-assurance", "control-assurance.html"],
  ["overview", "verticals", "verticals.html"],
  ["overview", "trust-routing", "trust-routing.html"],
  ["overview", "llm-cost", "llm-cost.html"],
  ["overview", "cost-governance", "cost-governance.html"],
  ["operations", "live", "live.html"],
  ["operations", "incidents", "incidents.html"],
  ["operations", "hil-queue", "hil.html"],
  ["operations", "provision", "provision.html"],
  ["operations", "onboarding", "onboarding.html"],
  ["operations", "detection-readiness", "detection-readiness.html"],
  ["operations", "configuration-baselines", "configuration-baselines.html"],
  ["operations", "processes", "processes.html"],
  ["operations", "workflow-apps", "workflow-apps.html"],
  ["operations", "scheduler-runs", "scheduler-runs.html"],
  ["operations", "background-tasks", "background-tasks.html"],
  ["operations", "automation-blueprints", "automation-blueprints.html"],
  ["operations", "scheduled-continuations", "scheduled-continuations.html"],
  ["operations", "conversation-delivery", "conversation-delivery.html"],
  ["agents", "agents", "agents.html"],
  ["agents", "pantheon", "agents-constellation.html"],
  ["agents", "agent-activity", "agent-activity.html"],
] as const;
const recordPages = new Set<string>(routes.slice(13, 22).map((route) => route[2]));

async function openOperator(page: Page, file: string, master = false) {
  const baseFile = file.replace(/[?:].*$/, "");
  await page.goto(`http://127.0.0.1:5373/${master ? `#mocks/ui/${file}` : `mocks/ui/#${file}`}`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("body")).toHaveClass(/cs-embedded/);
  await expect(frame.locator("body")).toHaveClass(/cs-operator-neutral/);
  if (recordPages.has(baseFile)) {
    await expect(frame.locator("[data-console-parity-page]")).toHaveAttribute("data-operator-ready", "true");
  }
  if (baseFile === "live.html") {
    await expect(frame.locator(".cs-tile[data-event-id]").first()).toBeVisible();
    await frame.getByRole("button", { name: "Freeze view", exact: true }).click();
  }
  if (baseFile === "provision.html") {
    await expect(frame.locator(".pv-workspace")).toHaveAttribute("data-operator-ready", "true");
    await frame.getByRole("button", { name: "Pause replay", exact: true }).click();
  }
  return frame;
}

for (const file of recordPages) {
  test(`desktop interactions: ${file} views records and source states`, async ({ page }) => {
    await page.setViewportSize({ width: 1070, height: 918 });
    const errors: string[] = [];
    const unsafeRequests: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.method() !== "GET" || new URL(request.url()).origin !== "http://127.0.0.1:5373") unsafeRequests.push(request.url());
    });
    let frame = await openOperator(page, file);
    const views = await frame.locator("[data-op-tab]").evaluateAll((tabs) => tabs.map((tab) => tab.getAttribute("data-op-tab")!));
    let recordView = "";
    for (const view of views) {
      await frame.locator(`[data-op-tab="${view}"]`).click();
      const panel = frame.locator(`[data-op-panel="${view}"]`);
      await expect(panel).toBeVisible();
      await expect(frame.locator("[data-op-panel]:visible")).toHaveCount(1);
      for (const button of await panel.locator("[data-op-record]").all()) {
        recordView = view;
        const id = await button.getAttribute("data-op-record");
        const label = await button.locator("strong").textContent();
        await button.click();
        await expect(button).toHaveAttribute("aria-pressed", "true");
        await expect(panel.locator("[data-op-record-detail] > h3").first()).toHaveText(label!);
        await expect(page).toHaveURL(new RegExp(`record=${id}`));
        for (const summary of await panel.locator(".op-record-section > summary").all()) {
          if (await summary.isVisible()) await summary.click();
        }
      }
      expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    }
    const state = frame.locator(".op-preview-state select");
    for (const mode of ["loading", "unavailable", "error", "empty"]) {
      await state.selectOption(mode);
      await expect(frame.locator("[data-op-content]")).toBeHidden();
      await expect(frame.locator(".op-state")).toBeVisible();
      await expect(frame.locator(".op-state")).toHaveAttribute("role", mode === "error" ? "alert" : "status");
      await expect(frame.locator(".op-state")).toHaveAttribute("aria-busy", String(mode === "loading"));
    }
    await state.selectOption("sample-data");
    await expect(frame.locator("[data-op-content]")).toBeVisible();
    if (recordView) {
      frame = await openOperator(page, `${file}?record=not-retained::${recordView}`);
      await expect(frame.locator("[data-op-record-detail]:visible")).toContainText("not in this collection");
      await expect(frame.locator('[data-op-record][aria-pressed="true"]')).toHaveCount(0);
      await frame.locator("[data-op-record]:visible").first().click();
      await expect(frame.locator("[data-op-record-detail]:visible > h3")).toBeVisible();
    }
    expect(unsafeRequests).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("desktop interactions: scheduler exact lookup never retains unrelated metrics", async ({ page }) => {
  const frame = await openOperator(page, "scheduler-runs.html");
  const input = frame.locator("#scheduler-query input");
  await input.fill("not-retained");
  await frame.getByRole("button", { name: "Load history", exact: true }).click();
  await expect(frame.locator("#scheduler-dispatch-history tbody tr:visible")).toHaveCount(0);
  await expect(frame.locator(".cp-kpis")).toBeHidden();
  await input.fill("example-scheduled-readiness");
  await frame.locator("#scheduler-query select").selectOption("Published");
  await frame.getByRole("button", { name: "Load history", exact: true }).click();
  await expect(frame.locator("#scheduler-dispatch-history tbody tr:visible")).toHaveCount(1);
  await expect(frame.locator(".cp-kpis")).toBeHidden();
  await frame.locator("#scheduler-query select").selectOption("All statuses");
  await frame.getByRole("button", { name: "Load history", exact: true }).click();
  await expect(frame.locator("#scheduler-dispatch-history tbody tr:visible")).toHaveCount(4);
  await expect(frame.locator(".cp-kpis")).toBeVisible();
});

test("desktop interactions: approval search preserves expiry and read-only boundaries", async ({ page }) => {
  const frame = await openOperator(page, "hil.html");
  await frame.getByRole("searchbox", { name: "Search proposals" }).fill("certificate");
  await expect(frame.locator("[data-approval]:visible")).toHaveCount(1);
  await expect(frame.locator("[data-approval]:visible")).toContainText("Expired approval");
  await frame.locator("[data-approval]:visible summary").click();
  await expect(frame.locator("[data-approval]:visible dl")).toBeVisible();
  await expect(frame.getByRole("button", { name: /approve|reject|execute/i })).toHaveCount(0);
  await frame.getByRole("searchbox", { name: "Search proposals" }).fill("no-match");
  await expect(frame.locator("[data-approval]:visible")).toHaveCount(0);
  await expect(frame.locator("[data-approval-count]")).toHaveText("0 of 3 shown");
});

test("desktop interactions: onboarding distinguishes unknown from observed gaps", async ({ page }) => {
  const frame = await openOperator(page, "onboarding.html");
  for (const mode of ["unconfigured", "failed"]) {
    await frame.locator("#onboarding-preview-state").selectOption(mode);
    await expect(frame.locator("#onboarding-readiness")).toHaveText("Unavailable");
    await expect(frame.locator("#onboarding-resources")).toHaveText("Unavailable");
    await expect(frame.locator("#checked-at")).toHaveText("Not measured");
    await expect(frame.locator("#missing-resources-title")).toHaveText("Required resources");
  }
  await frame.locator("#onboarding-preview-state").selectOption("ready");
  await expect(frame.locator("#onboarding-readiness")).toHaveText("Ready");
  await expect(frame.locator("#onboarding-resource-list")).toBeHidden();
  await frame.getByRole("button", { name: "Reset preview" }).click();
  await expect(frame.locator("#onboarding-readiness")).toHaveText("Blocked");
  await expect(frame.getByRole("link", { name: "Review access" })).toHaveAttribute("href", "settings-iam.html#requests");
});

test("desktop interactions: incident filters and confirmation do not fabricate an effect", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => { if (request.method() !== "GET") requests.push(request.method()); });
  const frame = await openOperator(page, "incidents.html");
  await frame.locator("[data-incident-severity]").selectOption("medium");
  await expect(frame.locator("[data-incident]:visible")).toHaveCount(1);
  await expect(frame.locator("[data-incident]:visible")).toHaveAttribute("data-incident", "inc-cost-spike");
  await frame.locator("[data-incident-search]").fill("not-present");
  await expect(frame.locator("[data-incident-detail]:visible")).toHaveCount(0);
  await frame.locator("[data-clear-incident-scope]").click();
  const detail = frame.locator('[data-incident-detail="inc-api-latency"]');
  const lifecycle = await detail.locator("[data-lifecycle-value]").textContent();
  const events = await detail.locator(".in-event").count();
  await frame.locator("[data-open-intervention]").click();
  await frame.locator('input[name="intervention-action"][value="close"]').check();
  await frame.getByRole("textbox", { name: "Operator comment" }).fill("Synthetic review only; no actual request.");
  await frame.getByRole("button", { name: "Review request", exact: true }).click();
  await frame.getByRole("button", { name: "Confirm intervention", exact: true }).click();
  await expect(detail.locator("[data-lifecycle-value]")).toHaveText(lifecycle!);
  await expect(detail.locator(".in-event")).toHaveCount(events);
  await expect(frame.locator('[data-incident="inc-api-latency"]')).toHaveAttribute("data-status", "active");
  await expect(frame.locator("[data-intervention-summary]")).toContainText(/queued|acceptance/i);
  expect(requests).toEqual([]);
});

test("desktop interactions: Live retains five filters and presentation-only freeze", async ({ page }) => {
  const frame = await openOperator(page, "live.html");
  await expect(frame.locator("[data-live-filter]:visible")).toHaveCount(5);
  await expect(frame.locator('[data-attention-filter="abstain"]')).toBeHidden();
  await frame.getByRole("button", { name: "Queue", exact: true }).click();
  await expect(frame.locator("#queue-view")).toBeVisible();
  await expect(frame.locator("#flow-view")).toBeHidden();
  await frame.locator('[data-live-filter="hil"]').click();
  await expect(page).toHaveURL(/filter=hil/);
  await expect(frame.getByRole("button", { name: "Resume view", exact: true })).toBeVisible();
  await frame.getByRole("button", { name: "Flow", exact: true }).click();
  await expect(frame.locator("#flow-view")).toBeVisible();
});

test("desktop interactions: provisioning exposes every section and independently verified example", async ({ page }) => {
  await page.clock.install();
  const frame = await openOperator(page, "provision.html");
  await expect(frame.locator("[data-op-tab]")).toHaveCount(5);
  for (const id of ["readiness", "runtime", "resources", "events", "stages"]) {
    await frame.locator(`[data-op-tab="${id}"]`).click();
    await expect(frame.locator(`[data-op-panel="${id}"]`)).toBeVisible();
    await expect(frame.locator("[data-op-panel]:visible")).toHaveCount(1);
  }
  await frame.getByRole("button", { name: "Resume replay" }).click();
  await page.clock.runFor(30_000);
  await frame.locator('[data-op-tab="readiness"]').click();
  await expect(frame.locator(".pv-readiness-grid > div")).toHaveCount(6);
  await expect(frame.locator("#pv-progress-track")).toHaveAttribute("aria-valuenow", "15");
  await expect(frame.locator("#pv-progress-track")).toHaveAttribute("aria-valuemax", "15");
  await expect(frame.getByRole("link", { name: "Review onboarding readiness" })).toHaveAttribute("href", "onboarding.html");
});

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1070, height: 918 });
  await routeMocks(page);
});

for (const file of ["operating-outcomes.html", "trust-routing.html", "cost-governance.html"]) {
  test(`desktop interactions: ${file} exposes every evidence view`, async ({ page }) => {
    const frame = await openOperator(page, file);
    const ids = await frame.locator("[data-overview-tab]").evaluateAll((tabs) => tabs.map((tab) => tab.getAttribute("data-overview-tab")!));
    for (const id of ids) {
      await frame.locator(`[data-overview-tab="${id}"]`).click();
      await expect(frame.locator(`[data-overview-panel="${id}"]`)).toBeVisible();
      await expect(frame.locator("[data-overview-panel]:visible")).toHaveCount(1);
      expect(await frame.locator("main").evaluate((main) => main.scrollWidth <= main.clientWidth + 1)).toBe(true);
    }
  });
}

test("desktop interactions: Cost governance keeps recommendations separate from effects", async ({ page }) => {
  const frame = await openOperator(page, "cost-governance.html");
  await frame.getByRole("tab", { name: "Resource efficiency", exact: true }).click();
  await frame.locator('[data-cost-candidate="example-storage"]').first().click();
  await expect(frame.locator("#cost-inspector")).toContainText("Unavailable");
  await expect(frame.locator("#cost-inspector")).toContainText("Recommendation only");
  await frame.locator("#cost-search").fill("not-present");
  await expect(frame.locator("#cost-candidate-rows tr")).toHaveCount(0);
  await expect(frame.locator("#cost-inspector")).toContainText("outside the current filter");
  await frame.getByText("Evidence and preview settings", { exact: true }).click();
  for (const mode of ["loading", "unavailable", "denied", "error", "empty"]) {
    await frame.locator("#cost-scenario").selectOption(mode);
    await expect(frame.locator("#cost-data")).toBeHidden();
    await expect(frame.locator("#cost-read-state")).toBeVisible();
  }
  await frame.locator("#cost-scenario").selectOption("partial");
  await expect(frame.locator("#cost-coverage")).toContainText(/incomplete|partial/i);
});

test("desktop interactions: resource dashboard distinguishes failed inventory from zero", async ({ page }) => {
  const frame = await openOperator(page, "dashboard-v2.html");
  await frame.getByText("Preview scenarios", { exact: true }).click();
  for (const mode of ["loading", "error"]) {
    await frame.locator("#resource-example-state").selectOption(mode);
    await expect(frame.locator("#resource-data")).toBeHidden();
    await expect(frame.locator("#resource-read-state")).toBeVisible();
  }
  await frame.locator("#resource-example-state").selectOption("empty");
  await expect(frame.locator("#count-resources")).toHaveText("0");
  await frame.locator("#resource-example-state").selectOption("complete");
  await expect(frame.locator("#count-resources")).toHaveText("24");
  for (const name of ["List", "Groups", "Honeycomb"]) {
    await frame.getByRole("button", { name, exact: true }).click();
    await expect(frame.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
  }
});

test("desktop interactions: Fleet distinguishes unobserved agents from healthy idle", async ({ page }) => {
  const frame = await openOperator(page, "agents.html");
  await expect(frame.locator("#fleetGrid article")).toHaveCount(15);
  await frame.locator("#fleetSearch").fill("Odin");
  await expect(frame.locator("#fleetGrid article")).toHaveCount(1);
  await frame.locator("#fleetClear").click();
  await frame.locator("#previewState").selectOption("unobserved");
  await expect(frame.locator("#fleetResults")).toContainText("0 observed");
  for (const mode of ["loading", "error"]) {
    await frame.locator("#previewState").selectOption(mode);
    await expect(frame.locator("#previewSourceState")).toBeVisible();
  }
});

test("desktop interactions: Org preserves fixed reporting and keyboard focus", async ({ page }) => {
  const frame = await openOperator(page, "agents-constellation.html");
  await expect(frame.locator("#orgTree [data-agent]")).toHaveCount(15);
  await frame.locator('#orgTree [data-agent="thor"]').click();
  await expect(frame.locator("#agentFocus")).toContainText("Thor");
  await expect(page).toHaveURL(/agent=Thor/);
  await frame.locator('#orgTree [data-agent="odin"]').focus();
  await frame.locator('#orgTree [data-agent="odin"]').press("ArrowDown");
  await expect(frame.locator('#orgTree [data-agent="thor"]')).toBeFocused();
});

test("desktop interactions: activity operational lanes never invent audit traces", async ({ page }) => {
  const frame = await openOperator(page, "agent-activity.html");
  await frame.getByRole("button", { name: /^Inventory scan/ }).click();
  await expect(frame.locator("#activityRows tr")).toHaveCount(1);
  await expect(frame.locator('#activityRows a[href*="rule-trace"]')).toHaveCount(0);
  await expect(frame.locator("#activityFollow")).toHaveAttribute("aria-pressed", "true");
  await frame.locator("#activityFollow").click();
  await expect(frame.locator("#activityFollow")).toHaveAttribute("aria-pressed", "false");
  await frame.getByText("Columns", { exact: true }).click();
  await frame.getByRole("checkbox", { name: "Type", exact: true }).check();
  await expect(frame.locator('th[data-column="type"]')).toBeVisible();
  await frame.getByRole("button", { name: "Waterfall", exact: true }).click();
  await expect(frame.locator("#activityWaterfallView")).toBeVisible();
  await expect(frame.locator("#activityJournal")).toBeHidden();
});

test("desktop inventory includes every current Overview Operations and Agents panel", async ({ page }) => {
  const source = ts.createSourceFile("panels.tsx", readFileSync(new URL("../../src/panels.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const registered: string[] = [];
  function visit(node: ts.Node) {
    if (ts.isObjectLiteralExpression(node)) {
      const fields = new Map<string, string>();
      for (const property of node.properties) {
        if (ts.isPropertyAssignment(property) && ts.isIdentifier(property.name) && ts.isStringLiteral(property.initializer)) {
          fields.set(property.name.text, property.initializer.text);
        }
      }
      if (["overview", "operations", "agents"].includes(fields.get("group") || "") && fields.has("id")) registered.push(fields.get("id")!);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  expect(registered.sort()).toEqual(routes.map((route) => route[1]).sort());
  await openOperator(page, "dashboard.html");
  const listed = await page.locator("a[data-page]").evaluateAll((links) => links.map((link) => link.getAttribute("data-page")));
  for (const route of routes) expect(listed).toContain(route[2]);
});

for (const [group, id, file] of routes) {
  test(`desktop route: ${group}/${id}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1070, height: 918 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const frame = await openOperator(page, file);
    await expect(frame.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(frame.locator("body")).toHaveCSS("color", "rgb(38, 38, 38)");
    await expect(frame.locator("body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
    await expect(frame.locator("body")).toContainText(/synthetic|illustrative|preview/i);
    const geometry = await frame.locator("main").evaluate((main) => ({
      document: document.documentElement.scrollWidth <= innerWidth,
      main: main.scrollWidth <= main.clientWidth + 1,
      heading: getComputedStyle(main.querySelector("h1")!).fontSize,
    }));
    await testInfo.attach("geometry.json", { body: JSON.stringify(geometry), contentType: "application/json" });
    await page.screenshot({ path: testInfo.outputPath(`${id}-desktop.png`) });
    expect(geometry).toEqual({ document: true, main: true, heading: "24px" });
    expect(errors).toEqual([]);
  });
}

for (const [width, height] of [[993, 641], [390, 844]] as const) {
  for (const [, id, file] of routes) {
    test(`responsive ${width}: ${id} and internal views`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height });
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const frame = await openOperator(page, file, true);
      async function checkGeometry() {
        const geometry = await frame.locator("main").evaluate((main) => ({
          document: document.documentElement.scrollWidth <= innerWidth,
          main: main.scrollWidth <= main.clientWidth + 1,
        }));
        expect(geometry).toEqual({ document: true, main: true });
      }
      await checkGeometry();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`${id}-${width}.png`) });
      for (const tab of await frame.locator("[data-op-tab], [data-overview-tab]").all()) {
        await tab.click();
        await checkGeometry();
      }
      if (width === 390) {
        const shortControls = await frame.locator('button:visible, select:visible, input:not([type="checkbox"]):not([type="radio"]):visible').evaluateAll((controls) =>
          controls.filter((control) => control.getBoundingClientRect().height < 43).map((control) => control.getAttribute("aria-label") || control.textContent?.trim() || control.id));
        expect(shortControls).toEqual([]);
      }
      expect(errors).toEqual([]);
    });
  }
}

test("desktop navigation preserves encoded scope in master kit and direct entry", async ({ page }) => {
  const value = "example A&B+1/%";
  const query = `q=${encodeURIComponent(value)}`;
  for (const master of [false, true]) {
    const frame = await openOperator(page, `processes.html?${query}`, master);
    expect(await frame.locator("body").evaluate(() => new URL(location.href).searchParams.get("q"))).toBe(value);
    const direct = await page.locator("#now-open").getAttribute("href");
    expect(new URL(direct!, page.url()).searchParams.get("q")).toBe(value);
    await expect(page.locator('a[data-page$="processes.html"][aria-current="page"]')).toHaveCount(1);
    if (master) {
      const count = await page.locator("a[data-page]").count();
      await expect(page.getByRole("searchbox", { name: "Filter design mocks" })).toHaveAttribute("placeholder", `Filter ${count} design mocks`);
    }
  }
  await page.goto(`http://127.0.0.1:5373/mocks/ui/processes.html?${query}`);
  await expect(page.locator("#preview-frame")).toBeVisible();
  expect(await page.frameLocator("#preview-frame").locator("body").evaluate(() => new URL(location.href).searchParams.get("q"))).toBe(value);
});

test("desktop interactions: guard filtering retains simulated posture", async ({ page }) => {
  const frame = await openOperator(page, "control-assurance.html");
  await frame.locator("[data-guard-filter]").selectOption("fpr");
  await expect(frame.locator("[data-guard-key]:visible")).toHaveCount(1);
  await expect(frame.locator("[data-guard-key]:visible")).toHaveAttribute("data-guard-key", "fpr");
  await expect(frame.locator("[data-guard-key]:visible")).toContainText("Simulated");
  await expect(page).toHaveURL(/guard=fpr/);
  await expect(frame.locator(".cs-readonly-banner")).toContainText("Posture unknown");
});

test("desktop interactions: LLM usage exports only the disclosed visible subset", async ({ page }) => {
  const frame = await openOperator(page, "llm-cost.html");
  await frame.locator('[data-range="24h"]').click();
  await expect(frame.locator('[data-range="24h"]')).toHaveAttribute("aria-pressed", "true");
  await expect(frame.locator("#ledger-note")).toContainText("6 visible records");
  const downloaded = page.waitForEvent("download");
  await frame.getByRole("button", { name: "Export visible CSV" }).click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe("fdai-synthetic-llm-invocations.csv");
  const csv = readFileSync((await download.path())!, "utf8");
  expect(csv.trim().split("\r\n")).toHaveLength(7);
  expect(csv).toMatch(/token/i);
});
