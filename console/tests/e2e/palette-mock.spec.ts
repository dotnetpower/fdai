import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const origin = "http://127.0.0.1:5373";
const tokenSource = readFileSync(path.join(root, "ui/calm-slate-tokens.css"), "utf8");

async function openColors(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route(`${origin}/**`, async (route) => {
    const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
    const file = path.resolve(root, "." + (pathname === "/" ? "/index.html" : pathname));
    if (!file.startsWith(root) || !/\.(html|css|js|json|svg|png)$/.test(file)) {
      await route.fulfill({ status: 404, body: "Not a UI fixture." });
      return;
    }
    await route.fulfill({ path: file });
  });
  await page.goto(`${origin}/#mocks/ui/components.html::colors`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("body")).toHaveClass(/is-gallery-ready/);
  await expect(frame.locator("#colors")).toHaveAttribute("data-gallery-status", "Documented");
  return frame;
}

test.describe("Colors foundation specimen", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop acceptance precedes responsive checks.");
  });

  test("compares identical samples, copies HEX, and reports actual contrast without changing shared tokens", async ({ page, context }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const frame = await openColors(page);
    const study = frame.locator("#colors");
    const current = study.locator('[data-palette="current"]');
    const fresh = study.locator('[data-palette="fresh"]');
    await expect(frame.getByRole("navigation", { name: "Component subviews" }).getByRole("link", { name: "Colors", exact: true })).toHaveAttribute("aria-current", "page");
    await expect(study.locator("#cp-token-rows tr")).toHaveCount(15);
    expect(await current.locator(".cp-chat").innerText()).toBe(await fresh.locator(".cp-chat").innerText());
    await expect(current.locator(".cp-primary")).toHaveCSS("background-color", "rgb(68, 104, 142)");
    await expect(fresh.locator(".cp-primary")).toHaveCSS("background-color", "rgb(37, 99, 235)");
    await expect(fresh).toHaveCSS("background-color", "rgb(248, 248, 248)");
    await expect(fresh.locator(".cp-question")).toHaveCSS("background-color", "rgb(242, 242, 242)");
    await expect(fresh.locator(".cp-observation")).toHaveCSS("background-color", "rgb(245, 245, 245)");
    await expect(fresh.locator(".cp-chat-body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
    const neutralChannels = await fresh.evaluate((element) => {
      const samples = [element, ...element.querySelectorAll(".cp-question, .cp-observation, .cp-chat-body")];
      return samples.map((sample) => getComputedStyle(sample).backgroundColor.match(/\d+/g)!.slice(0, 3));
    });
    expect(neutralChannels.every((channels) => new Set(channels).size === 1)).toBe(true);
    await expect(current.locator(".cp-question")).toHaveCSS("font-size", "13px");
    await expect(fresh.locator(".cp-question")).toHaveCSS("font-size", "13px");
    const layout = await study.locator(".cp-comparison").evaluate((element) => {
      const samples = [...element.children].map((child) => child.getBoundingClientRect());
      return { equalTop: samples[0]!.top === samples[1]!.top, sameWidth: samples[0]!.width === samples[1]!.width, overflow: element.scrollWidth > element.clientWidth };
    });
    expect(layout).toEqual({ equalTop: true, sameWidth: true, overflow: false });
    await page.screenshot({ path: testInfo.outputPath("colors-1440x900.png") });

    await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
    const copyBlue = study.getByRole("button", { name: "Copy fresh Action / selected #2563EB", exact: true });
    await copyBlue.click();
    await expect(study.getByRole("status")).toHaveText("Copied fresh Action / selected: #2563EB");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("#2563EB");
    await frame.locator("body").evaluate(() => {
      Object.defineProperty(navigator.clipboard, "writeText", {
        configurable: true,
        value: () => Promise.reject(new DOMException("Denied", "NotAllowedError")),
      });
    });
    await copyBlue.click();
    await expect(study.getByRole("status")).toContainText("Clipboard unavailable");
    await expect(study.getByRole("status")).toContainText("#2563EB");

    await study.locator(".cp-details").nth(1).locator("summary").click();
    const ratios = await study.locator('[data-palette-pair="fresh"]').evaluateAll((cells) =>
      cells.map((cell) => Number(cell.getAttribute("data-ratio"))),
    );
    expect(ratios).toHaveLength(7);
    expect(ratios.every((ratio) => ratio >= 4.5)).toBe(true);
    await expect(study.locator('[data-palette-pair="current"][data-result="below"]')).toHaveCount(3);
    const primaryRow = study.locator("#cp-contrast-rows tr").filter({ hasText: "Primary button" });
    expect(Number(await primaryRow.locator('[data-palette-pair="fresh"]').getAttribute("data-ratio"))).toBeCloseTo(5.17, 2);

    await fresh.getByRole("button", { name: "Review evidence", exact: true }).click();
    await expect(fresh.locator(".cp-evidence")).toHaveAttribute("open", "");
    await expect(fresh.locator(".cp-evidence summary")).toBeFocused();
    await expect(current.locator(".cp-evidence")).not.toHaveAttribute("open", "");
    await study.getByRole("button", { name: "Clear neutral", exact: true }).click();
    await expect(current).toBeHidden();
    await expect(fresh).toBeVisible();
    await study.getByRole("button", { name: "Current", exact: true }).click();
    await expect(fresh).toBeHidden();
    await expect(current).toBeVisible();
    await study.getByRole("button", { name: "Compare", exact: true }).click();

    await frame.getByRole("button", { name: "Dark preview", exact: true }).click();
    await expect(frame.locator("body")).toHaveAttribute("data-theme", "dark");
    await expect(current).toHaveCSS("background-color", "rgb(251, 250, 249)");
    await expect(fresh).toHaveCSS("background-color", "rgb(248, 248, 248)");
    await expect(frame.locator(".cs-gallery-error")).toBeHidden();
    const rootAccent = await frame.locator("html").evaluate((element) => getComputedStyle(element).getPropertyValue("--cs-steel").trim());
    expect(rootAccent.toLowerCase()).toBe("#44688e");
    expect(readFileSync(path.join(root, "ui/calm-slate-tokens.css"), "utf8")).toBe(tokenSource);
    await frame.getByRole("button", { name: "Light preview", exact: true }).click();
    expect(errors).toEqual([]);
  });

  test("keeps gallery routing, stacked palettes and color values usable in narrow frames", async ({ page }, testInfo) => {
    const frame = await openColors(page);
    const study = frame.locator("#colors");
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await expect.poll(() => frame.locator("html").evaluate((element) => element.clientWidth <= 745)).toBe(true);
      await study.locator(".cp-toolbar").scrollIntoViewIfNeeded();
      const geometry = await study.evaluate((element) => ({
        document: document.documentElement.scrollWidth <= innerWidth,
        study: element.scrollWidth <= element.clientWidth,
        samples: [...element.querySelectorAll(".cp-scheme")].every((scheme) => scheme.scrollWidth <= scheme.clientWidth),
        table: element.querySelector(".cp-token-table")!.scrollWidth <= element.querySelector(".cp-token-table")!.clientWidth,
        columns: getComputedStyle(element.querySelector(".cp-comparison")!).gridTemplateColumns,
      }));
      expect(geometry.document).toBe(true);
      expect(geometry.study).toBe(true);
      expect(geometry.samples).toBe(true);
      expect(geometry.table).toBe(true);
      expect(geometry.columns.trim().split(/\s+/)).toHaveLength(1);
      await study.getByRole("button", { name: "Clear neutral", exact: true }).click();
      await expect(study.locator('[data-palette="fresh"]')).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath(`colors-${viewport.width}x${viewport.height}.png`) });
      if (viewport.width === 390) {
        const heights = await study.locator("button").evaluateAll((buttons) => buttons
          .filter((button) => button.getBoundingClientRect().height > 0)
          .map((button) => button.getBoundingClientRect().height));
        expect(heights.every((height) => height >= 44)).toBe(true);
        await study.locator('[data-palette="fresh"] .cp-answer').evaluate((element) => {
          element.textContent = "현재 근거의 범위와 확인되지 않은 상태 / " + "long-unbroken-identifier".repeat(6);
        });
        expect(await study.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      }
      await study.getByRole("button", { name: "Compare", exact: true }).click();
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await frame.getByRole("navigation", { name: "Component subviews" }).getByRole("link", { name: "Metrics", exact: true }).click();
    await expect(study).toBeHidden();
    await expect(page).toHaveURL(/::display$/);
    await frame.getByRole("navigation", { name: "Component subviews" }).getByRole("link", { name: "Colors", exact: true }).click();
    await expect(study).toBeVisible();
    await expect(page).toHaveURL(/::colors$/);
    await page.reload();
    await expect(study).toHaveAttribute("data-gallery-status", "Documented");
    await expect(study.getByRole("button", { name: "Compare", exact: true })).toHaveAttribute("aria-pressed", "true");
    await frame.getByRole("searchbox", { name: "Find a component" }).fill("Colors");
    await expect(study).toBeVisible();
    await expect(frame.locator("main > .cs-section:visible")).toHaveCount(1);
  });
});
