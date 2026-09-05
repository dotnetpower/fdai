import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test } from "@playwright/test";

const shell = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;

test("keeps Dashboard evidence and chart values intact in the neutral presentation", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "One scenario checks desktop before constrained and mobile.");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${shell}#mocks/ui/dashboard.html`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("body")).toHaveAttribute("data-chat-theme", "clear-neutral");
  await expect(frame.locator(".cs-readonly-banner")).toContainText("make no operational claim");
  await expect(frame.locator("#historical-performance")).not.toHaveAttribute("open", "");
  await expect(frame.locator("#resource-count")).toHaveText("24 shown / 24 match scope / 24 in snapshot");
  await expect(frame.locator(".dr-summary dd")).toHaveText(["24", "14", "3", "7"]);
  await page.screenshot({ path: testInfo.outputPath("dashboard-resource-desktop.png") });
  await frame.locator("#historical-performance > summary").click();
  await expect(frame.locator(".db-metric-value")).toHaveText([
    "73%", "6.7", "Insufficient evidence", "Unavailable", "Unavailable",
  ]);
  await expect(frame.locator(".db-evidence-strip")).toContainText("2026-07-22T15:18Z");
  await expect(frame.locator(".db-unobserved").first()).toContainText("does not establish an all-clear state");
  await expect(frame.locator("body")).toHaveCSS("background-color", "rgb(248, 248, 248)");
  await expect(frame.locator(".db-posture")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(frame.locator(".db-posture")).toHaveCSS("box-shadow", "none");
  await expect(frame.locator(".db-count")).toHaveCSS("background-color", "rgb(255, 247, 237)");
  await expect(frame.locator(".db-count")).toHaveCSS("color", "rgb(180, 83, 9)");
  await expect(frame.locator(".db-metric.is-unavailable").first()).toHaveCSS("background-color", "rgb(245, 245, 245)");
  await expect(frame.locator(".db-metric.is-unavailable .db-metric-value").first()).toHaveCSS("color", "rgb(64, 64, 64)");
  await expect(frame.locator(".db-metric-grid")).toHaveCSS("gap", "12px");
  const chartData = await frame.locator(".js-chartable").evaluateAll((elements) =>
    elements.map((element) => JSON.parse(element.getAttribute("data-chart-rows")!)),
  );
  expect(chartData).toEqual([
    [["T0 deterministic", "73%", "22"], ["T1 lightweight", "20%", "6"], ["T2 reasoning", "7%", "2"]],
    [["auto", "73%", "22"], ["approval", "7%", "2"], ["held for review", "17%", "5"], ["deny", "3%", "1"]],
  ]);
  const segmentShares = await frame.locator(".cs-stackbar").evaluateAll((bars) => bars.map((bar) =>
    [...bar.children].map((segment) => (segment as HTMLElement).style.width),
  ));
  expect(segmentShares).toEqual([["73%", "20%", "7%"], ["73%", "7%", "17%", "3%"], ["80%", "20%"]]);
  await expect(frame.locator(".db-detail")).not.toHaveAttribute("open", "");
  await page.screenshot({ path: testInfo.outputPath("dashboard-neutral-desktop.png") });
  await frame.locator(".db-detail > summary").focus();
  await page.keyboard.press("Enter");
  await expect(frame.locator(".db-detail")).toHaveAttribute("open", "");
  await expect(frame.getByRole("link", { name: "Open audit", exact: false })).toHaveAttribute("href", "audit.html");
  await expect(frame.getByRole("link", { name: "Browse rules", exact: false })).toHaveAttribute("href", "rules.html");
  await expect(frame.getByRole("link", { name: "Open approvals", exact: false })).toHaveAttribute("href", "hil.html");
  await frame.getByRole("link", { name: "Open approvals", exact: false }).focus();
  await expect(frame.getByRole("link", { name: "Open approvals", exact: false })).toHaveCSS("outline-width", "2px");

  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await frame.locator("body").evaluate(() => scrollTo(0, 0));
    const geometry = await frame.locator("main").evaluate((element) => ({
      document: document.documentElement.scrollWidth <= innerWidth,
      main: element.scrollWidth <= element.clientWidth,
      cards: [...element.querySelectorAll(".db-metric,.db-panel,.db-attention-card,.db-vertical")]
        .every((card) => card.scrollWidth <= card.clientWidth),
    }));
    expect(geometry).toEqual({ document: true, main: true, cards: true });
    await page.screenshot({ path: testInfo.outputPath(`dashboard-neutral-${viewport.width}x${viewport.height}.png`) });
    if (viewport.width === 390) {
      const heights = await frame.locator(".db-detail-links a").evaluateAll((links) =>
        links.map((link) => link.getBoundingClientRect().height),
      );
      expect(heights.every((height) => height >= 44)).toBe(true);
      await frame.locator(".db-fact-list strong").first().evaluate((element) => {
        element.textContent = "긴 운영 대상 식별자 / " + "long-identifier".repeat(10);
      });
      expect(await frame.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(frame.locator(".db-metric-value")).toHaveText([
    "73%", "6.7", "Insufficient evidence", "Unavailable", "Unavailable",
  ]);
  expect(errors).toEqual([]);
});
