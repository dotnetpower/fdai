import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const shell = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;

async function openDense(page: Page, dense = true) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`${shell}#mocks/ui/dashboard.html`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("#count-resources")).toHaveText("24");
  await frame.locator(".dr-preview-controls > summary").click();
  await frame.getByLabel("Example resources", { exact: true }).selectOption("10000");
  await frame.locator(".dr-preview-controls > summary").click();
  if (dense) await expect(frame.locator("#resource-honeycomb")).toHaveClass(/is-dense/);
  return frame;
}

test.describe("Dense resource honeycomb", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop gate precedes responsive scenarios.");
  });

  test("shows hundreds of accurately spaced cells without pre-rendering other pages", async ({ page }, testInfo) => {
    const frame = await openDense(page);
    const geometry = await frame.locator("#resource-honeycomb").evaluate((map) => {
      const cells = [...map.querySelectorAll(".dr-cell")];
      const boxes = cells.map((cell) => cell.getBoundingClientRect());
      return {
        count: cells.length,
        visible: boxes.filter((box) => box.top >= 0 && box.bottom <= innerHeight).length,
        columns: Number(map.getAttribute("data-columns")),
        dimensions: boxes.every((box) => box.width === 24 && box.height === 28),
        map: map.scrollWidth <= map.clientWidth,
        page: document.documentElement.scrollWidth <= innerWidth,
      };
    });
    expect(geometry.count).toBeGreaterThanOrEqual(300);
    expect(geometry.count).toBeLessThanOrEqual(476);
    expect(geometry.count).toBe(geometry.columns * 14);
    expect(geometry.visible).toBeGreaterThanOrEqual(200);
    expect(geometry.dimensions && geometry.map && geometry.page).toBe(true);
    await expect(frame.locator(".dr-cell-name").first()).toBeHidden();
    await expect(frame.locator(".dr-cell[tabindex='0']")).toHaveCount(1);
    await expect(frame.locator("#resource-list tbody tr,.dr-group")).toHaveCount(0);
    await expect(frame.getByRole("button", { name: "Dense", exact: true })).toHaveAttribute("aria-pressed", "true");
    await frame.locator('[data-resource-lens="availability"]').click();
    await expect(frame.locator(".dr-cell[data-resource-id='app-web-01']")).toHaveAttribute("data-tone", "negative");
    await expect(frame.locator(".dr-cell[data-resource-id='platform-ca-02'] polygon")).toHaveCSS("fill", /dr-unknown-pattern/);
    await page.screenshot({ path: testInfo.outputPath("dense-dashboard-desktop.png") });
    const ids = await frame.locator(".dr-cell").evaluateAll((cells) => cells.map((cell) => cell.getAttribute("data-resource-id")));
    await frame.getByRole("button", { name: "Next page", exact: true }).click();
    expect(await frame.locator(".dr-cell").evaluateAll((cells) => cells.map((cell) => cell.getAttribute("data-resource-id")))).not.toEqual(ids);
    await frame.getByRole("button", { name: "Previous page", exact: true }).click();
    expect(await frame.locator(".dr-cell").evaluateAll((cells) => cells.map((cell) => cell.getAttribute("data-resource-id")))).toEqual(ids);
    await frame.getByRole("button", { name: "Comfortable", exact: true }).click();
    await expect(frame.locator(".dr-cell")).toHaveCount(48);
    await expect(frame.locator(".dr-cell-name").first()).toBeVisible();
    await frame.getByRole("button", { name: "Dense", exact: true }).click();
    await expect(frame.locator(".dr-cell")).toHaveCount(geometry.count);
    console.log(`Dense viewport: ${geometry.count} cells, ${geometry.visible} fully visible on first screen, ${geometry.columns} columns.`);
  });

  test("previews precise pointer targets and exposes hoverable, dismissible, keyboard-accessible evidence", async ({ page }, testInfo) => {
    const frame = await openDense(page);
    await frame.locator(".dr-resource-panel").evaluate((element) => element.scrollIntoView({ block: "start" }));
    const tip = frame.locator("#resource-hover-preview");
    const total = await frame.locator(".dr-cell").count();
    for (const index of [0, 1, 15, Math.floor(total / 2), total - 1]) {
      await page.keyboard.press("Escape");
      const cell = frame.locator(".dr-cell").nth(index);
      await cell.hover();
      await expect(tip).toBeVisible();
      await expect(tip).toHaveAttribute("data-resource-id", (await cell.getAttribute("data-resource-id"))!);
      await expect(tip).toContainText("Operating state");
      await expect(tip).toContainText("Availability");
      await expect(tip).toContainText("Observation");
      expect(await tip.evaluate((element) => {
        const box = element.getBoundingClientRect();
        return box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight;
      })).toBe(true);
    }
    await tip.hover();
    await page.waitForTimeout(200);
    await expect(tip).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("dense-dashboard-hover.png") });
    await page.keyboard.press("Escape");
    await expect(tip).toBeHidden();
    await frame.locator(".dr-cell").first().focus();
    await expect(tip).toHaveAttribute("data-resource-id", "app-web-01");
    await expect(tip).toContainText("Running");
    await expect(tip).toContainText("Unavailable");
    await expect(tip).toContainText("11:58 KST");
    const columns = Number(await frame.locator("#resource-honeycomb").getAttribute("data-columns"));
    await page.keyboard.press("ArrowDown");
    await expect(frame.locator(".dr-cell").nth(columns)).toBeFocused();
    await expect(frame.locator(".dr-cell[tabindex='0']")).toHaveCount(1);
    await page.keyboard.press("End");
    await expect(frame.locator(".dr-cell").last()).toBeFocused();
    await frame.locator("body").evaluate(() => scrollTo(0, 0));
    await frame.locator(".dr-cell").first().focus();
    await page.keyboard.press("End");
    await expect(tip).toBeVisible();
    await expect(tip).toHaveAttribute("data-resource-id", (await frame.locator(".dr-cell").last().getAttribute("data-resource-id"))!);
    await frame.locator('[data-resource-lens="observation"]').click();
    await expect(tip).toBeHidden();
    await expect(frame.locator(".dr-cell[aria-describedby]")).toHaveCount(0);
  });

  test("pins details without moving the map or stealing focus and preserves the selected snapshot", async ({ page }, testInfo) => {
    const frame = await openDense(page);
    const cell = frame.locator(".dr-cell[data-resource-id='app-web-01']");
    await cell.scrollIntoViewIfNeeded();
    const scroll = await frame.locator("body").evaluate(() => scrollY);
    await cell.click();
    expect(await frame.locator("body").evaluate(() => scrollY)).toBe(scroll);
    await expect(cell).toBeFocused();
    await expect(cell).toHaveAttribute("aria-pressed", "true");
    await expect(frame.locator("#resource-inspector")).toBeVisible();
    await expect(frame.locator("#resource-selected-name")).toHaveText("web-checkout-01");
    await expect(frame.locator("#resource-selection-status")).toContainText("details pinned");
    await expect(frame.locator("#resource-hover-preview")).toBeHidden();
    await page.screenshot({ path: testInfo.outputPath("dense-dashboard-pinned.png") });
    await frame.locator("#resource-evidence > summary").click();
    const evidence = await frame.locator("#resource-selected-evidence").textContent();
    await frame.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(frame.locator("#resource-selection-paged")).toBeVisible();
    expect(await frame.locator("#resource-selected-evidence").textContent()).toBe(evidence);
    await frame.getByRole("button", { name: "Clear selection", exact: true }).click();
    await expect(frame.locator("#resource-inspector")).toBeHidden();
    await expect(frame.getByRole("heading", { name: "Check first", exact: true })).toBeVisible();
  });

  test("adapts dense geometry and keeps a nonmodal tap inspector on small screens", async ({ page }, testInfo) => {
    const frame = await openDense(page);
    await page.setViewportSize({ width: 993, height: 641 });
    await expect(frame.locator("#resource-honeycomb")).toHaveClass(/is-dense/);
    await frame.locator(".dr-resource-panel").evaluate((element) => element.scrollIntoView({ block: "start" }));
    const count = await frame.locator(".dr-cell").count();
    expect(count).toBeGreaterThanOrEqual(300);
    expect(count).toBeLessThanOrEqual(476);
    await frame.locator(".dr-cell").nth(count - 1).hover();
    expect(await frame.locator("#resource-hover-preview").evaluate((element) => {
      const box = element.getBoundingClientRect();
      return box.right <= innerWidth && box.bottom <= innerHeight;
    })).toBe(true);
    await page.keyboard.press("Escape");
    await page.screenshot({ path: testInfo.outputPath("dense-dashboard-993x641.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(frame.getByRole("button", { name: "Dense", exact: true })).toBeDisabled();
    await expect(frame.locator("#resource-honeycomb")).not.toHaveClass(/is-dense/);
    await expect(frame.locator(".dr-cell")).toHaveCount(48);
    const first = frame.locator(".dr-cell").first();
    await first.scrollIntoViewIfNeeded();
    const scroll = await frame.locator("body").evaluate(() => scrollY);
    await first.click();
    expect(await frame.locator("body").evaluate(() => scrollY)).toBe(scroll);
    await expect(frame.locator("#resource-inspector")).toHaveCSS("position", "fixed");
    await expect(frame.locator("[aria-modal='true']")).toHaveCount(0);
    await expect(frame.locator("#resource-hover-preview")).toBeHidden();
    await page.screenshot({ path: testInfo.outputPath("dense-dashboard-mobile-pin.png") });
    expect(await frame.locator("main").evaluate((element) => ({
      page: document.documentElement.scrollWidth <= innerWidth,
      main: element.scrollWidth <= element.clientWidth,
      touch: [...element.querySelectorAll(".dr-cell")].every((cell) => {
        const box = cell.getBoundingClientRect();
        return box.width >= 44 && box.height >= 44;
      }),
      inspector: document.getElementById("resource-inspector")!.scrollWidth <= document.getElementById("resource-inspector")!.clientWidth,
    }))).toEqual({ page: true, main: true, touch: true, inspector: true });
    await frame.getByRole("button", { name: "Clear selection", exact: true }).click();
    await expect(frame.locator("#resource-inspector")).toBeHidden();
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(frame.locator("#resource-honeycomb")).toHaveClass(/is-dense/);
    expect(await frame.locator(".dr-cell").count()).toBe(420);
  });

  test("uses large targets and tap selection on a wide touch device", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, hasTouch: true });
    const page = await context.newPage();
    try {
      const frame = await openDense(page, false);
      await expect(frame.getByRole("button", { name: "Dense", exact: true })).toBeDisabled();
      await expect(frame.locator(".dr-cell")).toHaveCount(48);
      await frame.locator(".dr-cell").first().tap();
      await expect(frame.locator("#resource-selected-name")).toHaveText("web-checkout-01");
      await expect(frame.locator("#resource-hover-preview")).toBeHidden();
    } finally {
      await context.close();
    }
  });
});
