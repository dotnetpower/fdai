import { expect, test } from "@playwright/test";
import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";

test.use({ trace: "off", screenshot: "off", video: "off" });

test("updates SSE activity throughput and explains the 60-second classification window", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await restoreBrowserEntraSessionStorage(page);
  await page.goto("/live?locale=en&data=sample");
  const rate = page.locator(".live-kpi-eps");
  await expect(rate).toContainText("Source reads");
  await expect(rate).toContainText("Unique SSE activity messages");
  const control = rate.locator(".live-spark-key").first().locator("b");
  const initial = Number(await control.innerText());
  await expect.poll(async () => Number(await control.innerText())).toBeGreaterThan(initial);
  const kpis = page.locator(".live-kpis");
  await expect(kpis).toContainText("observed decisions");
  await page.locator(".live-control-btn").click();
  const frozen = await kpis.innerText();
  await page.waitForTimeout(1_100);
  expect(await kpis.innerText()).toBe(frozen);
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    expect(await kpis.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
    expect(await page.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    )).toBe(true);
  }
});

test("keeps Sample cards chronological, readable, and in the right detail panel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await restoreBrowserEntraSessionStorage(page);
  await page.goto("/live?locale=en&data=sample");
  const cards = page.locator(".live-work-card");
  await expect(cards).toHaveCount(15);
  const initialIds = await cards.evaluateAll(nodes =>
    nodes.map(node => node.getAttribute("data-event-id")),
  );
  await expect.poll(async () => {
    const firstId = await cards.first().getAttribute("data-event-id");
    return firstId !== null && !initialIds.includes(firstId);
  }, { timeout: 10_000 }).toBe(true);
  await page.locator(".live-control-btn").click();
  const frozenIds = await cards.evaluateAll(nodes =>
    nodes.map(node => node.getAttribute("data-event-id")),
  );

  const terminal = page.locator('.live-tile[data-done="1"]').first();
  const style = await terminal.evaluate(node => {
    const css = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return {
      width: rect.width,
      height: rect.height,
      radius: css.borderRadius,
      opacity: css.opacity,
      animation: css.animationName,
    };
  });
  expect(style).toMatchObject({ width: 299, height: 164, radius: "9px", opacity: "1", animation: "none" });
  await expect(terminal.locator(".live-tile-bar")).toHaveCSS("height", "3px");
  await terminal.hover();
  await expect(terminal).toHaveCSS("border-color", "rgb(37, 99, 235)");
  await terminal.focus();
  await page.keyboard.press("Enter");
  const controlDrawer = page.locator("#live-detail-panel");
  await expect(controlDrawer).toBeVisible();
  await expect(terminal).toHaveAttribute("aria-expanded", "true");
  expect(new URL(page.url()).pathname).toBe("/live");
  const technical = controlDrawer.locator("summary").first();
  await technical.focus();
  await page.waitForTimeout(1_100);
  await expect(technical).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(controlDrawer).toBeHidden();
  await expect(terminal).toBeFocused();
  expect(await cards.evaluateAll(nodes =>
    nodes.map(node => node.getAttribute("data-event-id")),
  )).toEqual(frozenIds);

  await page.locator(".live-filter-chip").filter({ hasText: "Source reads" }).click();
  await expect(cards).toHaveCount(3);
  const degraded = page.locator('.live-observation-item[data-status="degraded"]');
  await expect(degraded).toContainText("3,205 evidence items");
  await expect(degraded).toContainText("Stale");
  await cards.first().click();
  const sourceDrawer = page.locator("#live-observation-detail-panel");
  await expect(sourceDrawer).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/live");
  await page.keyboard.press("Escape");
  await expect(sourceDrawer).toBeHidden();
  await page.locator(".live-filter-chip").first().click();
  await expect(cards).toHaveCount(15);
  await page.getByRole("button", { name: "List", exact: true }).click();
  await expect(page.locator(".live-activity-grid")).toHaveAttribute("data-view", "queue");
  await page.getByRole("button", { name: "Grid", exact: true }).click();
  await page.locator(".live-filter-chip").filter({ hasText: "Denied" }).click();
  await expect(cards.first()).toHaveClass(/live-tile-gate-deny/);
  await expect(cards.first().locator(".live-tile-stage")).toContainText("Denied");
  await page.locator(".live-filter-chip").filter({ hasText: "Failed" }).click();
  await expect(cards.first()).toHaveAttribute("data-failed", "1");
  await expect(cards.first().locator(".live-tile-stage")).toHaveText("Failed");
  await page.locator(".live-filter-chip").first().click();

  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const viewport of [
    { width: 993, height: 641 },
    { width: 390, height: 844 },
    { width: 320, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    )).toBe(true);
    const overflow = await cards.evaluateAll(nodes =>
      nodes.some(node => node.scrollWidth > node.clientWidth),
    );
    expect(overflow).toBe(false);
    await expect(cards.first()).toHaveCSS("animation-name", "none");
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/live?locale=ko&data=sample");
  await expect(cards).toHaveCount(15);
  await expect(page.locator(".live-workspace")).toContainText("실시간 활동");
  expect(await page.evaluate(() =>
    document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )).toBe(true);
});
