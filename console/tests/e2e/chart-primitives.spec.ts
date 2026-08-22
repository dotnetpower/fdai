import { expect, test } from "@playwright/test";

test("keeps shared charts precise and accessible across supported viewports", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/tests/fixtures/chart-primitives.html");
    const fixture = page.locator("[data-chart-fixture-ready]");
    await expect(fixture).toBeVisible();

    const marks = fixture.locator(
      ".fd-chart-point, .fd-series-slice, .fd-bar-track, .fd-distribution-segment, " +
      ".fd-donut-visual, .fd-donut-legend button, .fd-spark-chart button, " +
      ".fd-progress-chart, .fd-progress-circle, .fd-tracker button, " +
      ".fd-scatter-chart button, .fd-heatmap button",
    );
    expect(await marks.count()).toBeGreaterThanOrEqual(100);
    await marks.first().focus();
    await expect(marks.first()).toBeFocused();
    await expect(page.getByRole("tooltip")).toContainText("Mon: 18");

    const linePanel = fixture.locator(".chart-fixture-panel").filter({ hasText: "Line chart" });
    const thursdaySlice = linePanel.locator(".fd-series-slice").nth(3);
    await thursdaySlice.hover();
    const groupedTooltip = page.getByRole("tooltip").filter({ hasText: "Thu" });
    await expect(groupedTooltip).toContainText("Observed31");
    await expect(groupedTooltip).toContainText("Baseline22");
    await expect(groupedTooltip).toContainText("Forecast25");
    await expect(groupedTooltip.locator(".fd-series-tooltip > span")).toHaveCount(3);
    await expect(thursdaySlice).toHaveCSS("cursor", "crosshair");

    const donutVisual = fixture.locator(".chart-fixture-panel").filter({ hasText: "Donut chart" }).locator(".fd-donut-visual");
    await donutVisual.hover();
    const donutTooltip = page.getByRole("tooltip").filter({ hasText: "Gate decision distribution" });
    await expect(donutTooltip).toContainText("Auto899");
    await expect(donutTooltip).toContainText("Deny37");

    const progressCircle = fixture.locator(".fd-progress-circle");
    await progressCircle.hover();
    await expect(page.getByRole("tooltip").filter({ hasText: "Evidence coverage: 84%" })).toBeVisible();

    const portfolioPanel = fixture.locator(".chart-fixture-panel").filter({ hasText: "Portfolio performance composition" });
    await expect(portfolioPanel.locator(".fd-metric-chart-head > strong")).toHaveText("$328,505.10");
    await expect(portfolioPanel.locator(".fd-series-y-axis span")).toHaveCount(3);
    await expect(portfolioPanel.locator(".fd-series-legend span")).toHaveCount(3);
    await portfolioPanel.locator(".fd-series-slice").nth(8).hover();
    const portfolioTooltip = page.getByRole("tooltip").filter({ hasText: "Sep 10" });
    await expect(portfolioTooltip).toContainText("ETF Shares Vital$7,649");
    await expect(portfolioTooltip).toContainText("Vitainvest Core$10,139.2");
    await expect(portfolioTooltip).toContainText("iShares Tech Growth$11,143.8");

    const interactiveKpiPanel = fixture.locator(".chart-fixture-panel").filter({ hasText: "Interactive KPI area composition" });
    await interactiveKpiPanel.locator(".fd-series-slice").nth(3).hover();
    await expect(interactiveKpiPanel.locator(".fd-metric-chart-head > strong")).toHaveText("31");
    await expect(interactiveKpiPanel.locator(".fd-metric-chart-head > small")).toHaveText("Thu");

    const geometry = await fixture.evaluate((element) => {
      const panels = Array.from(element.querySelectorAll<HTMLElement>(".chart-fixture-panel"));
      const point = element.querySelector<HTMLElement>(".fd-chart-point");
      return {
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        fixtureOverflow: element.scrollWidth - element.clientWidth,
        panelOverflow: Math.max(...panels.map((panel) => panel.scrollWidth - panel.clientWidth)),
        heatmapOverflow: element.querySelector<HTMLElement>(".fd-heatmap-wrap")!.scrollWidth -
          element.querySelector<HTMLElement>(".fd-heatmap-wrap")!.clientWidth,
        panelRows: new Set(panels.map((panel) => panel.offsetTop)).size,
        panelCount: panels.length,
        lineSlices: element.querySelectorAll(".chart-fixture-panel:nth-child(3) .fd-series-slice").length,
        lineLegendEntries: element.querySelectorAll(".chart-fixture-panel:nth-child(3) .fd-series-legend span").length,
        pointTransitionMs: Number.parseFloat(getComputedStyle(point!, "::after").transitionDuration) * 1_000,
      };
    });
    expect(geometry.documentOverflow).toBe(0);
    expect(geometry.fixtureOverflow).toBe(0);
    expect(geometry.panelOverflow).toBe(0);
    expect(geometry.heatmapOverflow).toBe(0);
    expect(geometry.panelCount).toBe(23);
    expect(geometry.lineSlices).toBe(7);
    expect(geometry.lineLegendEntries).toBe(3);
    expect(geometry.panelRows).toBe(viewport.width <= 760 ? 23 : 12);
    expect(geometry.pointTransitionMs).toBeLessThanOrEqual(1);

    await page.screenshot({
      path: testInfo.outputPath(`chart-primitives-${viewport.width}x${viewport.height}.png`),
      fullPage: true,
    });
  }
});
