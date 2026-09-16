import { expect, test, type TestInfo } from "@playwright/test";
import { installReportsFixture } from "./reports.fixture";
import { measureTextContrast } from "./reports-ui-measurements";

function reportsViewport(testInfo: TestInfo): {
  readonly label: string;
  readonly width: number;
  readonly height: number;
} {
  if (process.env["FDAI_REPORTS_VIEWPORT"] === "constrained") {
    return { label: "constrained", width: 993, height: 641 };
  }
  if (testInfo.project.name === "mobile-chromium") {
    return { label: "mobile", width: 390, height: 844 };
  }
  return { label: "desktop", width: 1440, height: 900 };
}

test("matches the report workbench hierarchy and renders source-backed widgets", async ({
  page,
}, testInfo) => {
  const viewport = reportsViewport(testInfo);
  await page.setViewportSize(viewport);
  const renders = await installReportsFixture(page);
  await page.goto(
    "/reports/weekly-operations?window=7d&scope=platform-production&locale=en",
  );

  await expect(page.locator(".reports-workspace")).toBeVisible();
  await expect(page.locator(".reports-boundary")).toContainText("Read-only report");
  await expect(page.locator(".reports-summary > div")).toHaveCount(4);
  await expect(page.locator(".reports-summary")).toContainText("2 / 3");
  await expect(page.getByRole("heading", { name: "Report templates" })).toBeVisible();
  await expect(page.locator(".reports-list a")).toHaveCount(3);
  await expect(page.locator(".reports-list a.active")).toContainText("Weekly Operations Review");
  await expect(page.locator(".reports-widget-grid > .kpi-card")).toHaveCount(3);
  await expect(page.getByText("73%", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Effect verification" })).toBeVisible();
  await expect(page.locator(".reports-provenance")).toContainText("Simulated evidence");
  await expect(page.locator(".reports-provenance")).toContainText("Partial evidence");
  await expect(page.locator(".reports-provenance")).toContainText("Mutation authority: none");
  expect(renders).toHaveLength(1);
  expect(renders[0]).toEqual({
    reportId: "weekly-operations",
    variables: { scope: "platform-production", window: "7d" },
  });

  for (const selector of ["html", ".reports-route", ".reports-toolbar", ".reports-workspace", ".reports-detail"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth, selector).toBeLessThanOrEqual(dimensions.clientWidth);
  }
  const catalogBox = await page.locator(".reports-catalog").boundingBox();
  const detailBox = await page.locator(".reports-detail").boundingBox();
  const pageTitleBox = await page.locator(".page-header-title").boundingBox();
  expect(catalogBox).not.toBeNull();
  expect(detailBox).not.toBeNull();
  expect(pageTitleBox).not.toBeNull();
  expect(pageTitleBox!.height).toBeLessThan(45);
  if (viewport.width >= 1100) {
    expect(detailBox!.x).toBeGreaterThan(catalogBox!.x);
    expect(catalogBox!.width).toBeGreaterThanOrEqual(220);
  } else {
    expect(detailBox!.y).toBeGreaterThan(catalogBox!.y);
  }
  await page.locator(".reports-route").evaluate((element) => {
    let ancestor = element.parentElement;
    while (ancestor) {
      ancestor.scrollTop = 0;
      ancestor.scrollLeft = 0;
      ancestor = ancestor.parentElement;
    }
    window.scrollTo(0, 0);
  });
  await page.screenshot({
    path: testInfo.outputPath(`reports-${viewport.label}.png`),
    fullPage: false,
  });
  if (viewport.label === "desktop") {
    for (const theme of ["light", "dark"]) {
      await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
      const contrast = await measureTextContrast(page, [
        ".reports-boundary p",
        ".reports-summary dt",
        ".reports-summary dd strong",
        ".reports-summary dd span",
        ".reports-list a.active > strong",
        ".reports-source-state.is-partial",
        ".reports-provenance",
      ]);
      expect(contrast.length).toBeGreaterThan(0);
      expect(
        contrast.every((measurement) => measurement.ratio >= 4.5),
        JSON.stringify(contrast),
      ).toBe(true);
      await testInfo.attach(`reports-contrast-${theme}.json`, {
        body: JSON.stringify(contrast),
        contentType: "application/json",
      });
    }
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  }
  const activeReport = page.locator(".reports-list a.active");
  await activeReport.focus();
  expect(await activeReport.evaluate((element) => getComputedStyle(element).outlineStyle))
    .not.toBe("none");
  const sourceDetails = page.locator(".reports-source-details");
  await sourceDetails.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(sourceDetails).toHaveAttribute("open", "");
  await expect(sourceDetails).toContainText("audit_log");
  if (viewport.label === "mobile") {
    const targets = await page.locator(
      ".reports-toolbar button, .reports-toolbar input, .reports-toolbar select, "
      + ".reports-variable-contract > summary, .reports-source-details > summary, "
      + ".reports-list a",
    ).evaluateAll((elements) => elements.map((element) => ({
      label: element.textContent?.trim() || element.getAttribute("name") || element.tagName,
      height: element.getBoundingClientRect().height,
    })));
    expect(
      targets.every((target) => target.height >= 44),
      JSON.stringify(targets),
    ).toBe(true);
  }
});

test("keeps a required-variable prompt distinct from rendered and empty data", async ({
  page,
}, testInfo) => {
  await page.setViewportSize(reportsViewport(testInfo));
  const renders = await installReportsFixture(page);
  await page.goto("/reports/incident-rca-dossier?locale=en");

  const renderButton = page.getByRole("button", { name: "Render report" });
  await expect(page.getByText(
    "Complete the required variables, then render the report.",
    { exact: true },
  )).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(renderButton).toBeDisabled();
  expect(renders).toHaveLength(0);

  const correlation = page.getByRole("textbox", { name: "correlation_id" });
  await correlation.fill("correlation-example");
  await expect(renderButton).toBeEnabled();
  await renderButton.click();
  await expect(page.getByRole("cell", { name: "Example incident" })).toBeVisible();
  await expect(page.locator(".reports-widget-grid > *")).toHaveCount(2);
  await expect(page.locator(".reports-provenance")).toContainText("Available");

  await correlation.fill("empty-evidence");
  await renderButton.click();
  await expect(page.getByText("No widgets were rendered.", { exact: true })).toBeVisible();
  await expect(page.locator(".reports-widget-grid > *")).toHaveCount(0);
  expect(renders.map((request) => request.variables["correlation_id"])).toEqual([
    "correlation-example",
    "empty-evidence",
  ]);
});

test("lets a variable-free report refresh without leaving the route", async ({
  page,
}, testInfo) => {
  await page.setViewportSize(reportsViewport(testInfo));
  const renders = await installReportsFixture(page);
  await page.goto("/reports/shadow-mode-daily?locale=en");

  const renderButton = page.getByRole("button", { name: "Render report" });
  await expect(page.getByText("34", { exact: true })).toBeVisible();
  await expect(renderButton).toBeEnabled();
  expect(renders).toHaveLength(1);
  await renderButton.click();
  await expect.poll(() => renders.length).toBe(2);
  await expect(page).toHaveURL(/\/reports\/shadow-mode-daily/);
});

test("keeps Korean labels and a long report identity within the content boundary", async ({
  page,
}, testInfo) => {
  const viewport = reportsViewport(testInfo);
  await page.setViewportSize(viewport);
  await installReportsFixture(page);
  const correlation = "correlation-example-with-a-long-opaque-identity-0123456789";
  await page.goto(
    `/reports/incident-rca-dossier?correlation_id=${correlation}&locale=ko`,
  );

  await expect(page.locator(".reports-boundary")).toContainText("읽기 전용 리포트");
  await expect(page.locator(".reports-summary")).toContainText("준비된 출처");
  await expect(page.getByRole("button", { name: "리포트 렌더링" })).toBeEnabled();
  await expect(page.locator(".reports-provenance")).toContainText("시뮬레이션 근거");
  await expect(page.getByRole("textbox", { name: "correlation_id" })).toHaveValue(correlation);
  for (const selector of ["html", ".reports-route", ".reports-toolbar", ".reports-workspace"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth, selector).toBeLessThanOrEqual(dimensions.clientWidth);
  }

  if (viewport.label === "mobile") {
    await page.setViewportSize({ width: 320, height: 844 });
    await page.addStyleTag({
      content: `
        .reports-route {
          --cs-type-page-title-size: 48px;
          --cs-type-page-subtitle-size: 26px;
          --cs-type-section-title-size: 36px;
          --cs-type-panel-title-size: 30px;
          --cs-type-body-size: 28px;
          --cs-type-compact-size: 26px;
          --cs-type-label-size: 24px;
          --cs-type-caption-size: 22px;
        }
      `,
    });
    for (const selector of ["html", ".reports-route", ".reports-toolbar", ".reports-workspace"]) {
      const dimensions = await page.locator(selector).evaluate((element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }));
      expect(dimensions.scrollWidth, `enlarged ${selector}`)
        .toBeLessThanOrEqual(dimensions.clientWidth);
    }
  }
});
