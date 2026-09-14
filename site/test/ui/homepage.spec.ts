import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

for (const locale of ["en", "ko"] as const) {
  test(`${locale} editorial home presents a concise and complete reading journey`, async ({ page }, info) => {
    const prefix = locale === "ko" ? "ko/" : "";
    await page.goto(prefix, { waitUntil: "networkidle" });
    await expect(page.locator(".home-hero")).toBeVisible();
    await expect(page.locator("main h1")).toHaveCount(1);
    await expect(page.locator(".home-content > section")).toHaveCount(4);
    await expect(page.locator(".home-outcome")).toHaveCount(3);
    await expect(page.locator(".home-flow-list > li")).toHaveCount(4);
    await expect(page.locator(".home-flow-note")).toContainText(locale === "en" ? "not live activity" : "실시간 상태가 아닙니다");
    await expect(page.locator("main")).not.toContainText(/\d\s*%|Phase\s*\d|needs_review/);
    await expect(page.locator(".home-background-toggle")).toHaveAttribute("aria-label", locale === "en" ? "Home background" : "홈 배경");
    await expect(page.locator('.home-background-toggle button[data-home-background="video"]')).toHaveText(locale === "en" ? "Video" : "영상");
    await expect(page.locator('.home-background-toggle button[data-home-background="nebula"]')).toHaveText(locale === "en" ? "Nebula" : "성운");
    await expect(page.locator(".hero .sl-link-button")).toHaveCount(2);
    await expect(page.locator(".home-explore")).toHaveAttribute(
      "href",
      new RegExp(`/neural-view/${locale === "ko" ? "\\?lang=ko" : ""}$`),
    );
    await expect(page.locator(".home-safety-links a[href$='ontology-driven-automation/']")).toHaveAttribute("href", new RegExp(`/${prefix}concepts/ontology-driven-automation/`));
    const directory = path.resolve(import.meta.dirname, "../../../.fdai/homepage-premium");
    await mkdir(directory, { recursive: true });
    for (const theme of ["light", "dark"]) {
      await page.locator("header starlight-theme-select select").selectOption(theme);
      await page.evaluate(() => { window.scrollTo(0, 0); return document.fonts.ready; });
      await page.screenshot({ path: path.join(directory, `${info.project.name}-${locale}-${theme}.png`), fullPage: true });
    }
    const geometry = await page.evaluate(() => ({
      viewport: [innerWidth, innerHeight],
      height: document.documentElement.scrollHeight,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      primary: document.querySelector(".hero .primary")!.getBoundingClientRect().bottom,
      nextSectionTop: document.querySelector("#outcomes")!.getBoundingClientRect().top,
      headings: [...document.querySelectorAll("main h2")].map(el => el.textContent),
    }));
    expect(geometry.overflow).toBeLessThanOrEqual(1);
    if (info.project.name === "desktop") {
      expect(geometry.height).toBeLessThan(5000);
      expect(geometry.primary).toBeLessThan(900);
    }
    expect(geometry.nextSectionTop).toBeLessThan(geometry.viewport[1]);
    await writeFile(path.join(directory, `${info.project.name}-${locale}.json`), JSON.stringify(geometry, null, 2));
    await page.locator(".hero .secondary").press("Enter");
    await expect(page).toHaveURL(/#how-it-works$/);
    await expect(page.locator("#how-it-works")).toBeFocused();
    const outcome = page.locator(".home-outcome").first();
    await outcome.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/${prefix}capabilities/change-safety/?$`));
    await expect(page.locator("h1")).toBeVisible();
  });

  test(`${locale} Neural View entry opens the public static experience`, async ({ page }, testInfo) => {
    const prefix = locale === "ko" ? "ko/" : "";
    await page.goto(prefix, { waitUntil: "networkidle" });
    await page.locator(".home-explore").click();
    await expect(page).toHaveURL(new RegExp(`/neural-view/${locale === "ko" ? "\\?lang=ko" : ""}$`));
    await expect(page.locator("#stage canvas")).toBeVisible();
    await expect(page.locator(".provenance")).toContainText(locale === "ko" ? "합성 데모" : "SYNTHETIC DEMO");
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.locator(".view-switch")).toHaveCount(0);
    await expect(page.locator("#snapshot-reload")).toHaveCount(0);
    const canvas = page.locator("#stage canvas");
    const bounds = await canvas.boundingBox();
    expect(bounds).not.toBeNull();
    if (testInfo.project.name === "desktop") {
      const dragStart = { x: bounds!.x + Math.min(60, bounds!.width * 0.15), y: bounds!.y + Math.min(20, bounds!.height * 0.1) };
      await page.mouse.move(dragStart.x, dragStart.y);
      await page.mouse.down();
      await page.mouse.move(dragStart.x + Math.min(80, bounds!.width * 0.2), dragStart.y, { steps: 8 });
      await page.mouse.up();
      await expect(page.locator("#stage")).toHaveAttribute("data-camera-mode", "manual");
    }
    const pixels = await sharp(await canvas.screenshot()).stats();
    expect(pixels.channels.some(channel => channel.stdev > 2)).toBe(true);
  });
}

test("reduced motion defaults to nebula and persists an explicit background choice", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  await expect(page.locator("html")).toHaveAttribute("data-home-background", "nebula");
  await expect(page.locator('.home-background-toggle button[data-home-background="nebula"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".home-neural-video")).not.toHaveAttribute("src", /.+/u);
  await page.locator('.home-background-toggle button[data-home-background="video"]').click();
  await expect(page.locator("html")).toHaveAttribute("data-home-background", "video");
  await expect(page.locator("html")).toHaveAttribute("data-home-video-ready", "true");
  await expect(page.locator(".home-neural-video")).toHaveAttribute("src", /neural-view-hero\.mp4$/u);
  expect(await page.locator(".home-neural-video").evaluate(video => (video as HTMLVideoElement).paused)).toBe(true);
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.locator("html")).toHaveAttribute("data-home-background", "video");
});

test("desktop video background autoplays when motion and bandwidth are available", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("", { waitUntil: "networkidle" });
  await expect(page.locator("html")).toHaveAttribute("data-home-background", "video");
  await expect(page.locator("html")).toHaveAttribute("data-home-video-ready", "true");
  await expect.poll(() => page.locator(".home-neural-video").evaluate(video => (video as HTMLVideoElement).currentTime)).toBeGreaterThan(0);
  expect(await page.locator(".home-neural-video").evaluate(video => (video as HTMLVideoElement).muted && !(video as HTMLVideoElement).paused)).toBe(true);
});

test("data saver defaults to nebula without requesting the video", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.addInitScript(() => Object.defineProperty(navigator, "connection", {
    configurable: true,
    value: { saveData: true, effectiveType: "4g" },
  }));
  const videoRequests: string[] = [];
  page.on("request", request => { if (request.url().includes("neural-view-hero.mp4")) videoRequests.push(request.url()); });
  await page.goto("", { waitUntil: "networkidle" });
  await expect(page.locator("html")).toHaveAttribute("data-home-background", "nebula");
  await expect(page.locator(".home-neural-video")).not.toHaveAttribute("src", /.+/u);
  expect(videoRequests).toEqual([]);
});

test("video load failure falls back to the nebula", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/media/neural-view-hero.mp4", route => route.abort());
  await page.goto("", { waitUntil: "networkidle" });
  await expect(page.locator("html")).toHaveAttribute("data-home-background", "nebula");
  await expect(page.locator('.home-background-toggle button[data-home-background="nebula"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("[data-home-background-status]")).toContainText("could not play");
});
