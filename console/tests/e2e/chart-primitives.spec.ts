import { expect, test } from "@playwright/test";
import { TREMOR_CHART_CATALOG } from "../../src/components/chart-colors";

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

    const donutPanel = fixture.locator(".chart-fixture-panel").filter({ has: page.getByRole("heading", { name: "Donut chart", exact: true }) });
    const donutVisual = donutPanel.locator(".fd-donut-visual");
    await donutVisual.hover();
    const donutTooltip = page.getByRole("tooltip").filter({ hasText: "Gate decision distribution" });
    await expect(donutTooltip).toContainText("Auto899");
    await expect(donutPanel.locator(".fd-donut-legend button").last()).toContainText("Deny37");
    await expect(donutPanel.getByRole("listitem")).toHaveCount(4);
    await expect(donutPanel.getByRole("button", { name: /Deny: 37/ })).toBeVisible();

    const progressCircle = fixture.locator(".chart-fixture-panel").filter({ has: page.getByRole("heading", { name: "Progress circle", exact: true }) }).locator(".fd-progress-circle");
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

    const catalogExamples = fixture.locator("[data-tremor-catalog-example]");
    await expect(catalogExamples).toHaveCount(TREMOR_CHART_CATALOG.length);
    expect(await catalogExamples.evaluateAll((elements) => elements.map((element) => element.getAttribute("data-tremor-catalog-example")))).toEqual([...TREMOR_CHART_CATALOG]);
    const catalogFocusability = await catalogExamples.evaluateAll((elements) => elements.map((element) => {
      const targets = Array.from(element.querySelectorAll<HTMLElement>('button, [tabindex="0"]'));
      return {
        name: element.getAttribute("data-tremor-catalog-example"),
        count: targets.length,
        named: targets.every((target) => Boolean(target.getAttribute("aria-label"))),
      };
    }));
    expect(catalogFocusability.filter((entry) => entry.count === 0 || !entry.named)).toEqual([]);
    await expect(catalogExamples.filter({ hasText: "Area Chart with percentages" }).locator(".fd-series-chart")).toHaveAttribute("data-type", "percent");
    await expect(catalogExamples.filter({ hasText: "Bar Chart with stacked categories" }).locator(".fd-series-chart")).toHaveAttribute("data-type", "stacked");
    await expect(catalogExamples.filter({ hasText: "Vertical Bar Chart" }).locator(".fd-series-chart")).toHaveAttribute("data-layout", "vertical");
    await expect(catalogExamples.filter({ hasText: "Bar Chart with gradient bars" }).locator("linearGradient")).toHaveCount(1);
    await expect(catalogExamples.filter({ hasText: "Category Bar with marker" }).locator(".fd-category-marker")).toBeVisible();
    await expect(catalogExamples.filter({ hasText: "Progress Circle with its default variants" }).locator(".fd-progress-circle")).toHaveCount(4);
    const catalog = (name: string) => fixture.locator(`[data-tremor-catalog-example="${name}"]`);
    await expect(catalog("Area Chart with percentages").locator(".fd-series-y-axis span").first()).toHaveText("100%");
    await expect(catalog("Area Chart with axis titles").locator(".fd-series-x-title")).toHaveText("Month");
    await expect(catalog("Area Chart with axis titles").locator(".fd-series-y-title")).toHaveText("Spend Category");
    const stackedBars = catalog("Bar Chart with stacked categories").locator(".fd-series-bar");
    expect(await stackedBars.nth(0).getAttribute("x")).toBe(await stackedBars.nth(6).getAttribute("x"));
    const verticalBarBox = await catalog("Vertical Bar Chart").locator(".fd-series-bar").first().boundingBox();
    expect(verticalBarBox!.width).toBeGreaterThan(verticalBarBox!.height);
    const conditionalBars = catalog("Bar Chart with conditional formatting").locator(".fd-series-bar");
    await expect(conditionalBars.nth(0)).toHaveCSS("color", "rgb(16, 185, 129)");
    await expect(conditionalBars.nth(1)).toHaveCSS("color", "rgb(236, 72, 153)");
    await expect(catalog("Bar Chart with rounded-sm top corner bars").locator(".fd-series-bar").first()).toHaveAttribute("rx", "5");
    const customLine = catalog("Line Chart with custom tooltip");
    await customLine.locator(".fd-series-slice").first().hover();
    await expect(page.getByRole("tooltip").filter({ hasText: "Jan custom" })).toBeVisible();
    const callbackDonut = catalog("Donut Chart with tooltip callback");
    await callbackDonut.locator(".fd-donut-visual").hover({ position: { x: 68, y: 2 } });
    await expect(callbackDonut.locator("[data-donut-callback]")).toHaveText("Auto: 899");
    await callbackDonut.locator(".fd-donut-visual").hover({ position: { x: 68, y: 68 } });
    await expect(callbackDonut.locator("[data-donut-callback]")).toHaveText("No active segment");
    await callbackDonut.locator(".fd-donut-visual").focus();
    await callbackDonut.locator(".fd-donut-visual").press("End");
    await expect(callbackDonut.locator("[data-donut-callback]")).toHaveText("Deny: 37");
    await callbackDonut.locator(".fd-donut-visual").hover({ position: { x: 68, y: 68 } });
    await expect(callbackDonut.locator("[data-donut-callback]")).toHaveText("No active segment");
    expect(await catalog("Progress Circle with its default variants").locator(".fd-progress-circle").evaluateAll((elements) => elements.map((element) => element.getAttribute("data-variant")))).toEqual(["default", "warning", "success", "error"]);
    expect(await catalog("Progress Circle with its default variants").locator(".fd-progress-circle").evaluateAll((elements) => elements.map((element) => getComputedStyle(element).getPropertyValue("--series-color").trim()))).toEqual(["#3b82f6", "#f59e0b", "#10b981", "#ec4899"]);
    await expect(catalog("Progress Circle complemented by a metric").locator(".fd-progress-circle strong")).toHaveText("75%");
    const categoryMarker = catalog("Category Bar with marker").locator(".fd-category-marker");
    await categoryMarker.focus();
    await expect(page.getByRole("tooltip").filter({ hasText: "68" })).toBeVisible();
    expect(await categoryMarker.evaluate((element) => getComputedStyle(element, "::before").animationName)).toBe("none");
    await catalog("Vertical Bar Chart").locator(".fd-series-row").first().focus();
    await expect(page.getByRole("tooltip").filter({ hasText: "Jan" })).toContainText("Solar panels$2,890");
    expect(await catalog("Area Chart").locator(".fd-series-area").first().evaluate((element) => getComputedStyle(element).fill)).toContain("url(");
    const selectableArea = catalog("Area Chart");
    const selectedSlice = selectableArea.locator(".fd-series-slice").nth(2);
    await selectedSlice.focus();
    await selectedSlice.press("Enter");
    await expect(selectedSlice).toHaveAttribute("aria-pressed", "true");
    await expect(selectableArea.locator("[data-series-selection]")).toHaveText("Selected: Mar");
    await selectableArea.locator(".fd-series-slice").nth(3).focus();
    await expect(selectedSlice).toHaveAttribute("data-selected", "true");
    await selectedSlice.press("Enter");
    await expect(selectedSlice).toHaveAttribute("aria-pressed", "false");
    await expect(selectableArea.locator("[data-series-selection]")).toHaveText("No selection");
    await expect(catalog("Area Chart with axis titles").locator(".fd-series-area").first()).toHaveCSS("opacity", "0.28");
    const heatmapCells = fixture.locator(".fd-heatmap button");
    expect(await heatmapCells.first().evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(await heatmapCells.nth(15).evaluate((element) => getComputedStyle(element).backgroundColor));

    const gapPanel = fixture.locator(".chart-fixture-panel").filter({ has: page.getByRole("heading", { name: "Gap-preserving area edge", exact: true }) });
    await expect(gapPanel.locator(".fd-series-area")).toHaveCount(2);
    await expect(gapPanel.locator(".fd-series-isolated")).toHaveCount(1);
    await expect(gapPanel.locator(".fd-series-line")).toHaveCount(1);
    await expect(fixture.locator(".chart-fixture-panel").filter({ has: page.getByRole("heading", { name: "Invalid percent edge", exact: true }) }).locator(".fd-series-chart")).toHaveCount(0);
    const categoryColors = await fixture.locator(".chart-fixture-panel").filter({ has: page.getByRole("heading", { name: "Nine-color category edge", exact: true }) }).locator(".fd-distribution-segment").evaluateAll((elements) => elements.map((element) => getComputedStyle(element).backgroundColor));
    expect(new Set(categoryColors).size).toBe(9);
    await expect(fixture.locator(".chart-fixture-panel").filter({ has: page.getByRole("heading", { name: "Zero-total marker edge", exact: true }) }).locator(".fd-category-marker")).toHaveCount(0);
    const singleSpark = fixture.locator(".chart-fixture-panel").filter({ has: page.getByRole("heading", { name: "Single-point spark edge", exact: true }) });
    const singleBarBox = await singleSpark.locator(".fd-spark-bar").boundingBox();
    expect(singleBarBox!.width).toBeLessThanOrEqual(120);
    expect(await singleSpark.evaluate((element) => element.scrollWidth - element.clientWidth)).toBe(0);
    const invalidBarList = fixture.locator(".chart-fixture-panel").filter({ has: page.getByRole("heading", { name: "Invalid BarList edge", exact: true }) });
    await expect(invalidBarList.locator(".fd-bar-row")).toHaveCount(2);
    await expect(invalidBarList).not.toContainText("Negative current");
    await expect(invalidBarList.locator(".fd-bar-baseline")).toHaveCount(1);

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
    expect(geometry.panelCount).toBe(62);
    expect(geometry.lineSlices).toBe(7);
    expect(geometry.lineLegendEntries).toBe(3);
    expect(geometry.panelRows).toBe(viewport.width <= 760 ? 62 : 31);
    expect(geometry.pointTransitionMs).toBeLessThanOrEqual(1);

    await page.screenshot({
      path: testInfo.outputPath(`chart-primitives-${viewport.width}x${viewport.height}.png`),
      fullPage: true,
    });
  }
});

test("animates a CategoryBar marker unless reduced motion is requested", async ({ page }) => {
  await page.goto("/tests/fixtures/chart-primitives.html");
  const marker = page.locator('[data-tremor-catalog-example="Category Bar with marker"] .fd-category-marker');
  await expect(marker).toBeVisible();
  expect(await marker.evaluate((element) => getComputedStyle(element, "::before").animationName)).toBe("fd-category-marker-in");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  expect(await marker.evaluate((element) => getComputedStyle(element, "::before").animationName)).toBe("none");
});
