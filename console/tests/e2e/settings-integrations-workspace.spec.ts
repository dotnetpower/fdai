import { expect, test, type FrameLocator } from "@playwright/test";
import { openSurface, routeMocks } from "./settings-mock-page";

const tabs = [
  { name: "Overview", id: "overview" },
  { name: "Teams Workflows", id: "teams-workflows" },
  { name: "Diagnostics", id: "diagnostics" },
  { name: "Email template", id: "email-template" },
];

async function navigationStyle(frame: FrameLocator) {
  return frame.locator(".cs-settings-workspace-nav").evaluate((nav) => {
    const tab = nav.querySelector('[aria-selected="true"]')!;
    const style = getComputedStyle(tab);
    return {
      height: tab.getBoundingClientRect().height,
      weight: style.fontWeight,
      background: style.backgroundColor,
      color: style.color,
      border: style.borderTopColor,
      padding: getComputedStyle(nav).padding,
      gap: getComputedStyle(nav.querySelector('[role="tablist"]')!).gap,
    };
  });
}

test.describe("Integrations task workspace", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await routeMocks(page);
  });

  for (const viewport of [
    { label: "wide", width: 1440, height: 900, master: false },
    { label: "session-sized", width: 1070, height: 918, master: false },
    { label: "constrained", width: 993, height: 641, master: true },
    { label: "compact", width: 840, height: 760, master: true },
    { label: "mobile", width: 390, height: 844, master: true },
  ]) {
    test(`${viewport.label} tabs keep the primary task visible and details reachable`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const frame = await openSurface(page, "settings-integrations.html", viewport.master);
      const geometry = await frame.getByRole("tab").evaluateAll((elements) =>
        elements.map((element) => ({ x: element.getBoundingClientRect().x, width: element.getBoundingClientRect().width })),
      );
      for (const tab of tabs) {
        await frame.getByRole("tab", { name: tab.name, exact: true }).click();
        await expect(frame.getByRole("tabpanel")).toHaveCount(1);
        await expect(frame.getByRole("tab", { name: tab.name, exact: true })).toHaveAttribute("aria-selected", "true");
        await expect(page).toHaveURL(new RegExp(`settings-integrations\\.html::${tab.id}$`));
        expect(await frame.locator("body").evaluate(() => scrollY)).toBe(0);
        expect(await frame.getByRole("tab").evaluateAll((elements) =>
          elements.map((element) => ({ x: element.getBoundingClientRect().x, width: element.getBoundingClientRect().width })),
        )).toEqual(geometry);
        expect(await frame.getByRole("tabpanel").evaluate((element) =>
          element.scrollWidth <= element.clientWidth && document.documentElement.scrollWidth <= innerWidth,
        )).toBe(true);
        if (tab.id === "overview") {
          await expect(frame.locator(".integration-state-cell button")).toHaveCount(0);
          await expect(frame.locator(".integration-action-cell button")).toHaveCount(2);
          await expect(frame.locator(".integrations-table")).toHaveCSS("display",
            viewport.label === "compact" || viewport.label === "mobile" ? "block" : "table",
          );
        }
        if (tab.id === "diagnostics" && viewport.width >= 993) {
          expect(await frame.locator(".integration-action-row").evaluate((row) =>
            Math.abs(row.getBoundingClientRect().right - row.querySelector("button")!.getBoundingClientRect().right),
          )).toBeLessThanOrEqual(1);
        }
        if (tab.id === "teams-workflows") {
          await expect(frame.locator("[data-teams-workflow-preview]")).toHaveAttribute("data-teams-workflow-ready", "true");
          const workspace = frame.locator(".tw-workspace");
          await expect(workspace.locator("details[open]")).toHaveCount(0);
          if (viewport.label !== "mobile") {
            expect(await workspace.getByRole("button", { name: "Save and send test" }).evaluate((element) =>
              element.getBoundingClientRect().bottom <= innerHeight - 16,
            )).toBe(true);
          }
          if (viewport.label === "wide" || viewport.label === "session-sized") {
            expect(await workspace.locator(".tw-receipt").evaluate((element) =>
              element.getBoundingClientRect().bottom <= innerHeight - 16,
            )).toBe(true);
          }
          await page.screenshot({ path: testInfo.outputPath(`tab-${tab.id}.png`) });
          await workspace.locator(".tw-guide > summary").click();
          await workspace.locator(".tw-guide img").last().scrollIntoViewIfNeeded();
          await expect(workspace.locator(".tw-guide")).toHaveAttribute("open", "");
        } else {
          await page.screenshot({ path: testInfo.outputPath(`tab-${tab.id}.png`) });
        }
      }
      if (viewport.label === "mobile") {
        for (const tab of await frame.getByRole("tab").all()) {
          expect(await tab.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
        }
      }
    });
  }

  test("desktop shares IAM navigation and disclosure presentation", async ({ page }) => {
    await page.setViewportSize({ width: 1070, height: 918 });
    const integrations = await openSurface(page, "settings-integrations.html::teams-workflows");
    await expect(integrations.locator(".tw-guide")).toBeVisible();
    const style = await navigationStyle(integrations);
    const disclosure = await integrations.locator(".tw-guide > summary").evaluate((element) => ({
      gap: getComputedStyle(element).gap,
      height: element.getBoundingClientRect().height,
      marker: getComputedStyle(element, "::before").content,
      rotation: getComputedStyle(element, "::before").transform,
    }));
    const iam = await openSurface(page, "settings-iam.html");
    expect(await navigationStyle(iam)).toEqual(style);
    expect(await iam.locator(".iam-identity-details > summary").evaluate((element) => ({
      gap: getComputedStyle(element).gap,
      height: element.getBoundingClientRect().height,
      marker: getComputedStyle(element, "::before").content,
      rotation: getComputedStyle(element, "::before").transform,
    }))).toEqual(disclosure);
  });

  test("desktop keyboard, direct links, history and same-tab context stay coherent", async ({ page }) => {
    await page.setViewportSize({ width: 1070, height: 918 });
    const frame = await openSurface(page, "settings-integrations.html");
    await frame.getByRole("button", { name: "View setup", exact: true }).click();
    const teams = frame.getByRole("tab", { name: "Teams Workflows", exact: true });
    await expect(teams).toBeFocused();
    await frame.locator(".tw-accounts > summary").click();
    await frame.locator("body").evaluate(() => scrollTo(0, 180));
    await teams.click();
    expect(await frame.locator("body").evaluate(() => scrollY)).toBeGreaterThan(0);
    await expect(frame.locator(".tw-accounts")).toHaveAttribute("open", "");
    await teams.focus();
    await teams.press("ArrowRight");
    await expect(frame.getByRole("tab", { name: "Diagnostics", exact: true })).toBeFocused();
    expect(await frame.locator("body").evaluate(() => scrollY)).toBe(0);
    await page.goBack();
    await expect(frame.getByRole("tab", { name: "Teams Workflows", exact: true })).toHaveAttribute("aria-selected", "true");
    await page.goForward();
    await expect(frame.getByRole("tab", { name: "Diagnostics", exact: true })).toHaveAttribute("aria-selected", "true");
    await frame.getByRole("tab", { name: "Diagnostics", exact: true }).focus();
    await page.keyboard.press("End");
    await expect(frame.getByRole("tab", { name: "Email template", exact: true })).toBeFocused();
    await page.keyboard.press("Home");
    await expect(frame.getByRole("tab", { name: "Overview", exact: true })).toBeFocused();
    await expect(frame.getByRole("tab", { name: "Overview", exact: true })).toHaveCSS("outline-width", "2px");
  });

  test("unknown tab routes show an explicit recovery instead of healthy content", async ({ page }) => {
    const frame = await openSurface(page, "settings-integrations.html::unknown-view");
    await expect(frame.getByRole("alert")).toContainText("Integration view unavailable");
    await expect(frame.getByRole("tabpanel")).toHaveCount(0);
    await frame.getByRole("button", { name: "Return to overview" }).click();
    await expect(frame.getByRole("tabpanel", { name: "Overview", exact: true })).toBeVisible();
    await expect(page).toHaveURL(/settings-integrations\.html::overview$/);
  });
});
