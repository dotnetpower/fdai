import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const shell = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;

async function openDashboard(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`${shell}#mocks/ui/dashboard-v2.html`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("#resource-count")).toContainText("24 resources shown");
  return frame;
}

test.describe("Dashboard type autocomplete", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop before responsive checks.");
  });

  test("searches a many-type catalog by label, alias and native type without changing draft scope", async ({ page }, testInfo) => {
    const frame = await openDashboard(page);
    const input = frame.getByRole("combobox", { name: "Type", exact: true });
    await input.click();
    await expect(frame.locator("#resource-type-results")).toHaveText("12 of 36 matching types. Keep typing to narrow.");
    await expect(frame.locator("#resource-type-options").getByRole("option")).toHaveCount(12);
    await input.fill("vm");
    await expect(frame.locator("#resource-type-options").getByRole("option")).toHaveCount(2);
    await expect(frame.locator("#resource-count")).toContainText("24 resources shown");
    await expect(frame.locator("#resource-type-option-vm")).toContainText("8 observed");
    await page.keyboard.press("Enter");
    await expect(frame.locator("#resource-count")).toContainText("24 resources shown");
    await expect(frame.locator("#resource-type-results")).toContainText("filter has not changed");
    await page.keyboard.press("ArrowDown");
    await expect(input).toHaveAttribute("aria-activedescendant", "resource-type-option-vm");
    await page.keyboard.press("Enter");
    await expect(input).toHaveValue("Virtual machine");
    await expect(input).toHaveAttribute("data-value", "vm");
    await expect(input).toHaveAttribute("aria-expanded", "false");
    await expect(frame.locator("#resource-count")).toHaveText("8 resources shown / 8 match filters / 24 received");
    await input.fill("Microsoft.DBforPostgreSQL/flexibleServers");
    await expect(frame.locator("#resource-type-options").getByRole("option")).toHaveCount(1);
    await expect(frame.locator("#resource-count")).toContainText("8 resources shown");
    await frame.locator("#resource-type-options").getByRole("option").click();
    await expect(frame.locator("#resource-count")).toContainText("3 resources shown");
    await input.fill("vault");
    await expect(frame.locator("#resource-type-options").getByRole("option")).toHaveCount(2);
    await page.screenshot({ path: testInfo.outputPath("dashboard-type-desktop.png") });
    await page.keyboard.press("Escape");
    await expect(input).toHaveValue("PostgreSQL");
    await expect(frame.locator("#resource-count")).toContainText("3 resources shown");
    await frame.getByRole("button", { name: "Clear type filter", exact: true }).click();
    await expect(input).toHaveValue("All types");
    await expect(frame.locator("#resource-count")).toContainText("24 resources shown");
    await input.fill("Microsoft.RecoveryServices/vaults");
    await expect(frame.locator("#resource-type-options").getByRole("option")).toHaveCount(1);
    await expect(frame.locator("#resource-type-option-recovery-vault")).toContainText("Recovery Services vault");
  });

  test("distinguishes no catalog match, zero observed records and partial inventory", async ({ page }) => {
    const frame = await openDashboard(page);
    const input = frame.getByRole("combobox", { name: "Type", exact: true });
    await input.fill("not-a-type");
    await expect(frame.locator("#resource-type-results")).toContainText("No matching types");
    await expect(frame.locator("#resource-count")).toContainText("24 resources shown");
    await input.fill("managed disk");
    await expect(frame.locator("#resource-type-option-disk")).toContainText("0 observed");
    await frame.locator("#resource-type-options").getByRole("option").click();
    await expect(input).toHaveValue("Managed disk");
    await expect(frame.locator("#resource-empty")).toBeVisible();
    await expect(frame.locator("#resource-count")).toHaveText("0 resources shown / 0 match filters / 24 received");
    await input.fill("<img src=x onerror=alert(1)>");
    await expect(frame.locator("#resource-type-popup img")).toHaveCount(0);
    await frame.getByLabel("Find resource", { exact: true }).click();
    await expect(input).toHaveValue("Managed disk");
    await frame.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(input).toHaveValue("All types");
    await frame.locator(".dr-preview-controls > summary").click();
    await frame.getByLabel("Inventory example", { exact: true }).selectOption("partial");
    await input.fill("storage");
    await expect(frame.locator("#resource-type-help")).toContainText("partial inventory; full coverage is unknown");
  });

  test("handles IME and keyboard dismissal while applying counts over the full 10000-record snapshot", async ({ page }) => {
    const frame = await openDashboard(page);
    const requests: string[] = [];
    page.on("request", (request) => requests.push(request.url()));
    await frame.locator(".dr-preview-controls > summary").click();
    await frame.getByLabel("Example resources", { exact: true }).selectOption("10000");
    await frame.locator(".dr-preview-controls > summary").click();
    const input = frame.getByRole("combobox", { name: "Type", exact: true });
    await input.fill("VM");
    await page.keyboard.press("ArrowDown");
    await input.dispatchEvent("compositionstart");
    await input.dispatchEvent("keydown", { key: "Enter", isComposing: true });
    await expect(input).toHaveAttribute("data-value", "all");
    await input.evaluate((element: HTMLInputElement) => { element.value = "가상 머신"; });
    await input.dispatchEvent("compositionend");
    await expect(frame.locator("#resource-type-options").getByRole("option")).toHaveCount(1);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(input).toHaveValue("Virtual machine");
    await expect(frame.locator("#resource-count")).toContainText("3334 match filters / 10000 received");
    await input.click();
    await expect(frame.locator("#resource-type-option-vm")).toContainText("3,334 observed");
    await page.keyboard.press("ArrowUp");
    const active = await input.getAttribute("aria-activedescendant");
    expect(active).not.toBeNull();
    await expect(frame.locator(`[id="${active}"]`)).toBeInViewport({ ratio: 1 });
    await page.keyboard.press("Tab");
    await expect(input).toHaveValue("Virtual machine");
    await expect(input).toHaveAttribute("aria-expanded", "false");
    await expect(input).not.toHaveAttribute("aria-activedescendant");
    expect(requests).toEqual([]);
  });

  test("keeps selected type and facet counts aligned with other scope filters", async ({ page }) => {
    const frame = await openDashboard(page);
    const input = frame.getByRole("combobox", { name: "Type", exact: true });
    await input.fill("VM");
    await frame.locator("#resource-type-option-vm").click();
    await frame.getByLabel("Group", { exact: true }).selectOption("data");
    await expect(frame.locator("#resource-count")).toContainText("2 resources shown");
    await input.click();
    await expect(frame.locator("#resource-type-option-vm")).toContainText("2 observed");
    await page.keyboard.press("Escape");
    await frame.getByLabel("Find resource", { exact: true }).fill("db-orders-01");
    await expect(frame.locator("#resource-empty")).toBeVisible();
    await input.click();
    await expect(frame.locator("#resource-type-option-vm")).toContainText("0 observed");
    await expect(frame.locator("#resource-type-option-database")).toContainText("1 observed");
    await page.keyboard.press("Escape");
    await expect(input).toHaveValue("Virtual machine");
    await frame.getByRole("button", { name: "Clear type filter", exact: true }).click();
    await expect(frame.getByLabel("Group", { exact: true })).toHaveValue("data");
    await expect(frame.getByLabel("Find resource", { exact: true })).toHaveValue("db-orders-01");
    await expect(frame.locator("#resource-count")).toContainText("1 resources shown");
  });

  test("stays dismissed after background clicks, restored focus and late IME completion", async ({ page }) => {
    const frame = await openDashboard(page);
    const input = frame.getByRole("combobox", { name: "Type", exact: true });
    const popup = frame.locator("#resource-type-popup");
    await input.fill("VM");
    await frame.locator("#resource-type-option-vm").click();
    await input.fill("postgres");
    await frame.locator(".db-page-subtitle").click();
    await expect(popup).toBeHidden();
    await expect(input).toHaveValue("Virtual machine");
    await expect(frame.locator("#resource-count")).toContainText("8 resources shown");
    await input.focus();
    await input.dispatchEvent("focus");
    await expect(popup).toBeHidden();
    await page.keyboard.press("ArrowDown");
    await expect(popup).toBeVisible();
    await input.dispatchEvent("compositionstart");
    await frame.locator(".db-page-subtitle").dispatchEvent("pointerdown");
    await expect(popup).toBeHidden();
    await input.dispatchEvent("compositionend");
    await expect(popup).toBeHidden();
    await input.evaluate((element) => element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertCompositionText" })));
    await expect(popup).toBeHidden();
    await expect(input).toHaveValue("Virtual machine");
    await input.click();
    await expect(popup).toBeVisible();
    await input.dispatchEvent("compositionstart");
    await input.evaluate((element: HTMLInputElement) => { element.value = "가상 머신"; });
    await input.dispatchEvent("compositionend");
    await expect(frame.locator("#resource-type-option-vm")).toBeVisible();
    await frame.locator("body").evaluate(() => window.dispatchEvent(new Event("blur")));
    await input.dispatchEvent("focus");
    await expect(popup).toBeHidden();
    await frame.locator(".db-page-subtitle").click();
    await frame.locator(".db-page-subtitle").click();
    await expect(input).toHaveAttribute("aria-expanded", "false");
    await expect(input).not.toHaveAttribute("aria-activedescendant");
    await input.fill("postgres");
    await expect(frame.locator("#resource-type-option-database")).toBeVisible();
    await frame.locator(".db-page-subtitle").evaluate((element: HTMLElement) => element.click());
    await expect(popup).toBeHidden();
    await expect(input).toHaveValue("Virtual machine");
  });

  test("clamps the popup on constrained screens and supports touch selection", async ({ page, browser }, testInfo) => {
    const frame = await openDashboard(page);
    await page.setViewportSize({ width: 993, height: 641 });
    await frame.getByRole("combobox", { name: "Type", exact: true }).fill("network");
    await expect(frame.getByRole("combobox", { name: "Type", exact: true })).toHaveValue("network");
    const popup = frame.locator("#resource-type-popup");
    await expect(popup).toBeVisible();
    await expect.poll(() => popup.evaluate((element) => {
      const box = element.getBoundingClientRect();
      return box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight;
    })).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("dashboard-type-993x641.png") });
    const context = await browser.newContext({ hasTouch: true });
    const touchPage = await context.newPage();
    try {
      const touchFrame = await openDashboard(touchPage);
      await touchPage.setViewportSize({ width: 390, height: 844 });
      const input = touchFrame.getByRole("combobox", { name: "Type", exact: true });
      await input.tap();
      await input.fill("postgres");
      const option = touchFrame.locator("#resource-type-option-database");
      await expect(option).toBeVisible();
      expect(await touchFrame.locator("#resource-type-popup").evaluate((element) => {
        const box = element.getBoundingClientRect();
        return box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight;
      })).toBe(true);
      expect((await option.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await touchPage.screenshot({ path: testInfo.outputPath("dashboard-type-mobile.png") });
      await option.tap();
      await expect(input).toHaveValue("PostgreSQL");
      await expect(input).toHaveAttribute("aria-expanded", "false");
      await expect(touchFrame.locator("#resource-count")).toContainText("3 resources shown");
      expect(await touchFrame.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    } finally {
      await context.close();
    }
  });
});
