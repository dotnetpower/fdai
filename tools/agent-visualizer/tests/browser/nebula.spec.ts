import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

test.use({ contextOptions: { reducedMotion: "reduce" }, trace: "off" });

test("nebula fills the space background outside the graph and preserves controls", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("#stage canvas")).toBeVisible();
  await expect(page.locator("#error")).toBeHidden();
  await page.locator("#reset").click();
  const stage = page.locator("#stage");
  await expect(page.locator(".city-label, #city-browser")).toHaveCount(0);
  expect(await stage.getAttribute("data-city-building-count")).toBeNull();
  const backdrop = page.locator("#app");
  const geometry = () => page.locator(".intro-panel, .activity-inspector, #stage, #controls-dock")
    .evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().toJSON()));
  const decoratedGeometry = await geometry();
  const background = await backdrop.evaluate((element) => getComputedStyle(element).backgroundImage);
  expect(background).not.toBe("none");
  await expect(stage).toHaveCSS("background-image", "none");
  const imageEvidence = await backdrop.evaluate(async (element) => {
    const style = getComputedStyle(element);
    const imageUrl = style.backgroundImage.match(/url\("([^"]+)"\)/)?.[1];
    if (!imageUrl) throw new Error("The shared nebula image is missing.");
    const image = new Image();
    image.src = imageUrl;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = 240;
    canvas.height = 160;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#070d13";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.globalAlpha = 1 - Number(style.getPropertyValue("--nebula-shade"));
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const luminance = (r: number, g: number, b: number) =>
      [r, g, b].map((value) => value / 255)
        .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
        .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index]!, 0);
    let brightest = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      brightest = Math.max(brightest, luminance(pixels[index]!, pixels[index + 1]!, pixels[index + 2]!));
    }
    return { imageUrl, contrast: (luminance(128, 150, 163) + 0.05) / (brightest + 0.05) };
  });
  const { contrast, imageUrl } = imageEvidence;
  expect(contrast).toBeGreaterThanOrEqual(4.5);
  const imageResponse = await page.request.get(imageUrl);
  expect(imageResponse.ok()).toBe(true);
  const source = await readFile(new URL("../../../../site/scripts/og-nebula-bg.png", import.meta.url));
  const digest = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
  expect(digest(await imageResponse.body())).toBe(digest(source));
  await testInfo.attach("backdrop-contrast", { body: `Faint text contrast against brightest sampled cloud: ${contrast.toFixed(2)}:1`, contentType: "text/plain" });
  await expect(backdrop).toHaveCSS("animation-name", "none");
  const beforeCount = await stage.getAttribute("data-function-count");
  await backdrop.evaluate((element) => { element.style.backgroundImage = "none"; });
  expect(await geometry()).toEqual(decoratedGeometry);
  const before = await page.locator(".topbar").screenshot();
  await backdrop.evaluate((element) => { element.style.removeProperty("background-image"); });
  expect((await page.locator(".topbar").screenshot()).equals(before)).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("nebula-desktop.png") });

  await page.locator('[data-agent="Huginn"]').focus();
  await expect(page.locator('[data-agent="Huginn"]')).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".agent-name")).toHaveText("Huginn");
  await page.locator("#stars").uncheck();
  await expect(stage).toHaveAttribute("data-stars-visible", "false");
  await expect(backdrop).toHaveCSS("background-image", background);
  expect(await stage.getAttribute("data-function-count")).toBe(beforeCount);
  await page.locator("#cinema").click();
  await expect(page.locator("#exit-cinema")).toBeFocused();
  await expect(page.locator(".cinema-watermark")).toContainText("SYNTHETIC DEMO");
  await expect(backdrop).toHaveCSS("background-image", background);
  await page.screenshot({ path: testInfo.outputPath("nebula-cinema.png") });
  await page.keyboard.press("Escape");
  await expect(page.locator("#cinema")).toBeFocused();
  const distance = Number(await stage.getAttribute("data-camera-distance"));
  await page.locator("#zoom-in").click();
  await expect.poll(async () => Number(await stage.getAttribute("data-camera-distance"))).toBeLessThan(distance);
  await page.emulateMedia({ forcedColors: "active" });
  await expect(backdrop).toHaveCSS("background-image", "none");
  expect(errors).toEqual([]);
});

test("nebula remains bounded on constrained and mobile screens", async ({ page }) => {
  await page.goto("/?lang=ko");
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    await expect(page.locator("#app")).not.toHaveCSS("background-image", "none");
    await expect(page.locator("#stage")).toHaveCSS("background-image", "none");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
});

test("translucent fields retain opaque text, focus and native options", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.locator("#loading")).toBeHidden();
  for (const selector of ["#scenario", "#function-query", "#speed"]) {
    await expect(page.locator(selector)).toHaveCSS("background-color", "rgba(12, 21, 29, 0.55)");
    await expect(page.locator(selector)).toHaveCSS("opacity", "1");
  }
  const scenario = page.locator("#scenario");
  await expect(scenario).toHaveCSS("color", "rgb(219, 232, 237)");
  await expect(scenario.locator("option").first()).toHaveCSS("background-color", "rgb(12, 21, 29)");
  await scenario.focus();
  await expect(scenario).toBeFocused();
  await expect(scenario).toHaveCSS("outline-width", "2px");
  await scenario.selectOption("recovery");
  await expect(page.locator("#duration")).toHaveText("00:56");
  const query = page.locator("#function-query");
  expect(await query.evaluate((element) => getComputedStyle(element, "::placeholder").color)).toBe("rgb(156, 174, 185)");
  await query.fill("not-a-real-function");
  await expect(page.locator("#function-list")).toHaveText("No matching source functions.");
  await expect(query).toBeFocused();
  await expect(query).toHaveCSS("outline-color", "rgb(132, 233, 223)");
  await query.fill("");
  await page.screenshot({ path: testInfo.outputPath("translucent-fields-desktop.png") });
  await page.locator("#controls-dock").hover();
  await page.locator("#speed").selectOption("2");
  await expect(page.locator("#speed")).toHaveValue("2");
  await page.locator("#language").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await expect(scenario).toHaveCSS("background-color", "rgba(12, 21, 29, 0.55)");
    await expect(query).toHaveCSS("background-color", "rgba(12, 21, 29, 0.55)");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
  await page.emulateMedia({ forcedColors: "active" });
  await expect(scenario).toHaveCSS("opacity", "1");
  await expect(query).toHaveCSS("opacity", "1");
  await expect(page.locator("#error")).toBeHidden();
});
