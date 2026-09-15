import { expect, test, type Page } from "@playwright/test";

test.use({ trace: "off", contextOptions: { reducedMotion: "no-preference" } });

async function pauseInOverview(page: Page) {
  await page.goto("/");
  await expect(page.locator("#loading")).toBeHidden();
  await expect(page.locator("#error")).toBeHidden();
  await page.locator("#controls-dock").hover();
  await page.locator("#play").click();
  await page.locator("#reset").click();
  await page.locator("#motion").check();
  await page.locator('[data-camera="manual"]').click();
  await page.locator("#motion").uncheck();
}

test("departure captions identify sources, fade with playback and never intercept node controls", async ({ page }, testInfo) => {
  await pauseInOverview(page);
  await page.locator("#timeline").fill("0.4");
  await page.mouse.move(24, 90);
  const publisher = page.locator('.event-launch-label[data-origin="Huginn"]');
  await expect(publisher).toBeVisible();
  await expect(publisher).toHaveText("object.event");
  await expect(publisher).toHaveCSS("opacity", "1");
  await expect(publisher).toHaveCSS("pointer-events", "none");
  await expect(publisher).toHaveAttribute("aria-hidden", "true");
  expect(await publisher.evaluate((element) => element.tabIndex)).toBe(-1);
  await expect(page.locator(".event-launch-label")).toHaveCount(6);
  const overlaps = await page.locator("[data-scene-label]:visible").evaluateAll((elements) => {
    const boxes = elements.map((element) => element.getBoundingClientRect());
    return boxes.some((a, index) => boxes.slice(index + 1).some((b) =>
      a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top));
  });
  expect(overlaps).toBe(false);
  const distances = await page.locator(".event-launch-label:visible").evaluateAll((elements) => {
    const stage = document.querySelector("#stage")!.getBoundingClientRect();
    return elements.map((element) => {
      const source = document.querySelector(`line[data-launch-origin="${element.getAttribute("data-origin")}"]`)!;
      const x = stage.left + Number(source.getAttribute("x1"));
      const y = stage.top + Number(source.getAttribute("y1"));
      const box = element.getBoundingClientRect();
      return Math.hypot(Math.max(box.left - x, 0, x - box.right), Math.max(box.top - y, 0, y - box.bottom));
    });
  });
  expect(distances.every((distance) => distance <= 21)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("departure-captions.png") });
  await page.locator("#controls-dock").hover();
  await page.locator("#timeline").fill("0.9");
  await expect(page.locator('.event-launch-label[data-origin="EVENT BUS"]')).toContainText("object.event");
  await page.locator("#timeline").fill("1.4");
  await expect.poll(async () => Number(await publisher.evaluate((element) => getComputedStyle(element).opacity))).toBeLessThan(1);
  expect(Number(await publisher.evaluate((element) => getComputedStyle(element).opacity))).toBeGreaterThan(0);
  await page.locator("#timeline").fill("2.6");
  await expect(page.locator(".event-launch-label:visible")).toHaveCount(0);
  await page.locator("#timeline").fill("0.4");
  await expect(publisher).toHaveCSS("opacity", "1");
  await page.locator('[data-agent="Huginn"]').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".agent-name")).toHaveText("Huginn");
  await expect(page.locator('[data-agent="Huginn"]')).toBeFocused();
  await page.locator("#labels").uncheck();
  await expect(publisher).toBeHidden();
  await page.locator("#labels").check();
  await expect(publisher).toBeVisible();
  await page.locator("#cinema").click();
  await expect(publisher).toBeVisible();
  await expect(page.locator('.event-launch-label[data-origin="EVENT BUS"]')).toBeVisible();
  await expect(page.locator(".cinema-watermark")).toContainText("SYNTHETIC DEMO");
  await page.screenshot({ path: testInfo.outputPath("departure-captions-cinema.png") });
  await page.keyboard.press("Escape");
  await page.locator("#motion").check();
  await expect(page.locator(".event-launch-label:visible")).toHaveCount(0);
  await expect(page.locator("#error")).toBeHidden();
});

test("departure captions remain within constrained and mobile scene bounds", async ({ page }) => {
  await pauseInOverview(page);
  await page.locator("#language").click();
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.locator("#timeline").fill("0.4");
    const outside = await page.locator(".event-launch-label:visible").evaluateAll((elements) => {
      const stage = document.querySelector("#stage")!.getBoundingClientRect();
      return elements.some((element) => {
        const box = element.getBoundingClientRect();
        return box.left < stage.left || box.right > stage.right || box.top < stage.top || box.bottom > stage.bottom;
      });
    });
    expect(outside).toBe(false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
});
