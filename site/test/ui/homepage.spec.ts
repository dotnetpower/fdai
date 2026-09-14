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
    await expect(page.locator(".hero .sl-link-button")).toHaveCount(3);
    await expect(page.locator(".hero .sl-link-button").nth(2)).toHaveAttribute(
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
      headings: [...document.querySelectorAll("main h2")].map(el => el.textContent),
    }));
    expect(geometry.overflow).toBeLessThanOrEqual(1);
    if (info.project.name === "desktop") {
      expect(geometry.height).toBeLessThan(5000);
      expect(geometry.primary).toBeLessThan(900);
    }
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
    await page.locator(".hero .sl-link-button").nth(2).click();
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
