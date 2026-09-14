import { expect, test, type Page } from "@playwright/test";
import { fullMapFixture } from "../full-map-fixture";

// Chromium trace screencasting loses this WebGL context; keep DOM assertions and screenshots instead.
test.use({ trace: "off" });

async function distance(page: Page) {
  return Number(await page.locator("#stage").getAttribute("data-camera-distance"));
}

test("desktop controls: Activity starts and re-enters with Follow at 1x", async ({ page }) => {
  await page.route("**/__neural/ontology", (route) => route.fulfill({
    contentType: "application/json", body: JSON.stringify(fullMapFixture()),
  }));
  await page.goto("/");
  await expect(page.locator("#speed")).toHaveValue("1");
  await expect(page.locator('[data-camera="follow"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#stage")).toHaveAttribute("data-camera-mode", "follow");
  await page.locator('[data-view="ontology"]').click();
  await expect(page.locator("#stage")).toHaveAttribute("data-camera-mode", "orbit");
  await page.locator('[data-view="activity"]').click();
  await expect(page.locator("#stage")).toHaveAttribute("data-camera-mode", "follow");
  await expect(page.locator("#speed")).toHaveValue("1");
});

test("desktop controls: playback reveals on hover and keyboard focus, not retained mouse focus", async ({ page }) => {
  await page.goto("/");
  await page.mouse.move(20, 100);
  await expect(page.locator("#playback")).toHaveCSS("opacity", "0");
  await page.locator("#controls-dock").hover();
  await expect(page.locator("#playback")).toHaveCSS("opacity", "1");
  await page.locator("#play").click();
  await page.mouse.move(20, 100);
  await expect(page.locator("#playback")).toHaveCSS("opacity", "0");
  await page.locator("#playback").focus();
  await page.keyboard.press("Tab");
  await expect(page.locator("#play")).toBeFocused();
  await expect(page.locator("#playback")).toHaveCSS("opacity", "1");
  await page.locator("#cinema").focus();
  await expect(page.locator("#playback")).toHaveCSS("opacity", "0");
  await page.locator("#cinema").click();
  await page.locator("#playback").hover();
  await expect(page.locator("#playback")).toHaveCSS("opacity", "1");
  await page.locator("#exit-cinema").hover();
  await expect(page.locator("#playback")).toHaveCSS("opacity", "0");
});

test("desktop controls: Cinema border glows without animating text and respects motion preferences", async ({ page }, testInfo) => {
  await page.goto("/");
  const appearance = await page.locator("#cinema").evaluate((button) => ({
    animation: getComputedStyle(button, "::after").animationName,
    duration: getComputedStyle(button, "::after").animationDuration,
    shadow: getComputedStyle(button, "::after").boxShadow,
    textAnimation: getComputedStyle(button).animationName,
  }));
  expect(appearance.animation).toBe("cinema-border-glow");
  expect(appearance.duration).toBe("3.8s");
  expect(appearance.shadow).not.toBe("none");
  expect(appearance.textAnimation).toBe("none");
  const pulse = await page.locator("#cinema").evaluate((button) => {
    const [animation] = button.getAnimations({ subtree: true });
    if (!animation) return null;
    animation.pause();
    animation.currentTime = 0;
    const resting = getComputedStyle(button, "::after").boxShadow;
    animation.currentTime = 1900;
    const glowing = getComputedStyle(button, "::after").boxShadow;
    return { resting, glowing };
  });
  expect(pulse).not.toBeNull();
  expect(pulse!.glowing).not.toBe(pulse!.resting);
  await page.screenshot({ path: testInfo.outputPath("activity-controls.png") });
  await page.locator("#motion").check();
  expect(await page.locator("#cinema").evaluate((button) => getComputedStyle(button, "::after").animationName)).toBe("none");
  await page.locator("#motion").uncheck();
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await page.locator("#cinema").evaluate((button) => getComputedStyle(button, "::after").animationName)).toBe("none");
});

test("desktop wheel: labels zoom like the canvas, remain clickable, and do not trap sidebar scrolling", async ({ page }) => {
  await page.goto("/");
  await page.locator("#controls-dock").hover();
  await page.locator("#play").click();
  await page.locator('[data-camera="manual"]').click();
  const label = page.locator('.activity-labels [data-scene-label="Huginn"]');
  await label.hover();
  const before = await distance(page);
  await page.mouse.wheel(0, -250);
  await expect.poll(() => distance(page)).toBeLessThan(before * 0.95);
  const after = await distance(page);
  expect(after / before).toBeCloseTo(Math.pow(0.95, 2.5), 2);
  await page.locator("#stage canvas").hover({ position: { x: 60, y: 20 } });
  await page.mouse.wheel(0, 250);
  await expect.poll(() => distance(page)).toBeGreaterThan(after * 1.05);
  expect(await distance(page)).toBeCloseTo(before, 2);
  await page.locator('[data-camera="follow"]').click();
  await label.hover();
  await page.mouse.wheel(0, -100);
  await expect(page.locator("#stage")).toHaveAttribute("data-camera-mode", "manual");
  await page.locator("#zoom-in").click();
  await page.locator("#zoom-in").click();
  await page.locator('.function-node-label[aria-hidden="false"]:visible .function-annotation-name').first().hover();
  const functionDistance = await distance(page);
  await page.mouse.wheel(0, 100);
  await expect.poll(() => distance(page)).toBeGreaterThan(functionDistance * 1.02);
  await label.click();
  await expect(page.locator(".agent-name")).toHaveText("Huginn");
  await page.locator(".activity-inspector").evaluate((element) => { element.scrollTop = 0; });
  await page.locator(".activity-inspector .agent-name").hover();
  const fixed = await distance(page);
  await page.mouse.wheel(0, 450);
  await expect.poll(() => page.locator(".activity-inspector").evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  expect(await distance(page)).toBeCloseTo(fixed, 2);
});

test("desktop dock: rests lower and expands upward without moving camera controls or resizing the graph", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.mouse.move(20, 100);
  await expect(page.locator("#playback")).toHaveCSS("opacity", "0");
  const geometry = () => page.evaluate(() => Object.fromEntries(
    ["#controls-dock", ".view-toolbar", ".playback-reveal", "#playback", "#stage"].map((selector) => {
      const box = document.querySelector(selector)!.getBoundingClientRect();
      return [selector, { top: box.top, bottom: box.bottom, height: box.height }];
    }),
  ));
  await expect.poll(async () => (await geometry())[".playback-reveal"]!.height).toBeLessThan(1);
  const closed = await geometry();
  expect(closed[".view-toolbar"]!.bottom).toBeGreaterThan(850);
  expect(closed["#stage"]!.bottom).toBeGreaterThan(800);
  expect(closed[".view-toolbar"]!.top - closed["#stage"]!.bottom).toBeGreaterThan(7);
  await page.screenshot({ path: testInfo.outputPath("dock-collapsed.png") });
  await page.locator("#controls-dock").hover();
  await expect(page.locator("#playback")).toHaveCSS("opacity", "1");
  await expect.poll(async () => (await geometry())[".playback-reveal"]!.height).toBeGreaterThan(80);
  const open = await geometry();
  expect(open["#controls-dock"]!.top).toBeLessThan(closed["#controls-dock"]!.top - 70);
  expect(open["#controls-dock"]!.bottom).toBeCloseTo(closed["#controls-dock"]!.bottom, 0);
  expect(open[".view-toolbar"]!.top).toBeCloseTo(closed[".view-toolbar"]!.top, 0);
  expect(open["#stage"]!.height).toBeCloseTo(closed["#stage"]!.height, 0);
  expect(open["#playback"]!.bottom).toBeLessThan(open[".view-toolbar"]!.top);
  await page.screenshot({ path: testInfo.outputPath("dock-expanded.png") });
  await page.mouse.move(20, 100);
  await expect.poll(async () => (await geometry())[".playback-reveal"]!.height).toBeLessThan(1);
});

test("desktop wheel: ontology node overlays also pass wheel input to the camera", async ({ page }) => {
  await page.route("**/__neural/ontology", (route) => route.fulfill({
    contentType: "application/json", body: JSON.stringify(fullMapFixture()),
  }));
  await page.goto("/");
  await page.locator('[data-view="ontology"]').click();
  await expect(page.locator("#recorded-status")).toHaveText("Local database snapshot ready");
  await page.locator('[data-camera="manual"]').click();
  const label = page.locator('.recorded-labels [data-recorded-resource="catalog:ot:Resource"]');
  await label.hover();
  const before = await distance(page);
  await page.mouse.wheel(0, -200);
  await expect.poll(() => distance(page)).toBeLessThan(before * 0.95);
  await label.click();
  await expect(page.locator("#recorded-details .instance-name")).toHaveText("Resource");
});

test("touch controls: playback remains visible without hover", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  try {
    await page.goto("/");
    await page.locator("#playback").scrollIntoViewIfNeeded();
    await expect(page.locator("#playback")).toHaveCSS("opacity", "1");
    await page.locator("#play").tap();
    await expect(page.locator("#play")).toHaveAttribute("aria-label", "Play");
  } finally {
    await context.close();
  }
});
