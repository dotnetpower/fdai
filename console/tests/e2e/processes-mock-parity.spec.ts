import { expect, test } from "@playwright/test";
import { openSurface, routeMocks } from "./settings-mock-page";

test("matches the master mock geometry with the same desktop navigation and sample state", async ({ page, context }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const mockPage = await context.newPage();
  await mockPage.setViewportSize({ width: 1440, height: 900 });
  await mockPage.emulateMedia({ reducedMotion: "reduce" });
  await routeMocks(mockPage);
  const mock = await openSurface(mockPage, "processes.html::workspace", true);
  await expect(mock.locator("[data-console-parity-page]")).toHaveAttribute("data-operator-ready", "true");
  const reference = await mock.locator("main").evaluate((root) => {
    const measure = (selector: string) => {
      const element = root.querySelector(selector);
      if (!element) throw new Error(`Missing mock geometry: ${selector}`);
      const rect = element.getBoundingClientRect();
      return { width: rect.width, height: rect.height, font: getComputedStyle(element).fontSize };
    };
    return {
      width: root.getBoundingClientRect().width,
      summary: measure(".cp-kpis"),
      workspace: measure(".cp-workspace"),
      roster: measure(".cp-workspace-list"),
      panelTitle: measure(".cp-workspace-detail > h3"),
      sectionTitle: measure(".cp-section-head h2"),
      facts: root.querySelectorAll(".cp-workspace-body > .cp-facts > div").length,
      records: root.querySelectorAll("[data-op-record]").length,
      open: root.querySelectorAll(".op-record-section[open]").length,
    };
  });

  const mutations: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/workflows/")) mutations.push(request.url());
  });
  await page.goto("/processes?data=sample&locale=en");
  await expect(page.locator(".process-detail")).toBeVisible();
  await page.locator(".page-header-domain-trigger").click();
  await expect(page.locator("#navigation-explorer")).toBeVisible();
  await page.locator(".navigation-pin-button").click();
  await expect(page.locator(".navigation-shell-pinned")).toBeVisible();
  const consoleWidth = (await page.locator(".process-route").boundingBox())!.width;
  // The shells own different rail/scrollbar widths; compare their real content at equal width.
  await page.setViewportSize({ width: 1440 - (consoleWidth - reference.width), height: 900 });
  const actual = await page.locator(".process-route").evaluate((root) => {
    const measure = (selector: string) => {
      const element = root.querySelector(selector);
      if (!element) throw new Error(`Missing Process geometry: ${selector}`);
      const rect = element.getBoundingClientRect();
      return { width: rect.width, height: rect.height, font: getComputedStyle(element).fontSize };
    };
    return {
      width: root.getBoundingClientRect().width,
      summary: measure(".process-status-summary"),
      workspace: measure(".process-workspace"),
      roster: measure(".process-list"),
      panelTitle: measure(".process-view-header"),
      sectionTitle: measure(".process-workspace-heading h3"),
      facts: root.querySelectorAll(".process-runtime-meta > div").length,
      records: root.querySelectorAll(".process-list-entry").length,
      open: root.querySelectorAll(".process-detail-section[open]").length,
    };
  });
  expect(actual.width).toBeCloseTo(reference.width, 0);
  expect(actual.summary.width).toBeCloseTo(reference.summary.width, 0);
  expect(Math.abs(actual.summary.height - reference.summary.height)).toBeLessThan(2);
  expect(actual.workspace.width).toBeCloseTo(reference.workspace.width, 0);
  expect(actual.roster.width / actual.workspace.width).toBeCloseTo(reference.roster.width / reference.workspace.width, 2);
  expect(actual.panelTitle.font).toBe(reference.panelTitle.font);
  expect(Math.abs(actual.panelTitle.height - reference.panelTitle.height)).toBeLessThan(2);
  expect(actual.sectionTitle.font).toBe(reference.sectionTitle.font);
  expect(actual.facts).toBe(reference.facts);
  expect(actual.records).toBe(reference.records);
  expect(actual.open).toBe(reference.open);
  await expect(page.locator(".process-status-summary strong")).toHaveText(["3", "2", "0", "1"]);
  await page.screenshot({ path: testInfo.outputPath("process-console-desktop.png") });
  await mockPage.screenshot({ path: testInfo.outputPath("process-master-mock-desktop.png") });
  await testInfo.attach("matched-geometry", {
    body: JSON.stringify({ reference, actual }, null, 2),
    contentType: "application/json",
  });

  for (const summary of await page.locator(".process-detail-section > summary").all()) {
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(summary.locator("..")).toHaveAttribute("open", "");
    await page.keyboard.press("Enter");
    await expect(summary.locator("..")).not.toHaveAttribute("open");
  }
  await expect(page.getByRole("button", { name: /Request (resume|cancellation|retry)/ })).toHaveCount(0);
  for (const link of await page.locator(".process-list-entry").all()) {
    const href = await link.getAttribute("href");
    await link.click();
    await expect(page.locator(".process-list-entry[aria-current=page]")).toHaveAttribute("href", href!);
    await expect(page.locator(".process-detail-section[open]")).toHaveCount(0);
  }
  expect(mutations).toEqual([]);
  await mockPage.close();
});

test("opens the containing journal for an event deep link", async ({ page }) => {
  await page.goto("/processes/sample-process-1?data=sample&event=sample-process-event-sample-process-1-1");
  await expect(page.locator(".process-detail-section[open] .process-journal")).toBeVisible();
  await expect(page.locator(".process-event-detail[open]")).toContainText("sample-process-event-sample-process-1-1");
});
