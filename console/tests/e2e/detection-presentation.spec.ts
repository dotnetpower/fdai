import { expect, test, type Page } from "@playwright/test";

const views = ["coverage", "resources", "findings"] as const;
const visual = expect.configure({ soft: true, timeout: 250 });
const hashes = {
  coverage: "detection-coverage-summary",
  resources: "detection-resources",
  findings: "detection-findings",
};

async function openView(page: Page, locale: string, view: typeof views[number]) {
  await page.goto(`/detection-coverage?data=sample&locale=${locale}#${hashes[view]}`);
  const panel = page.locator(`#detection-readiness-panel-${view}`);
  await expect(panel).toBeVisible();
  await expect(page.locator(`#detection-readiness-tab-${view}`)).toHaveAttribute("aria-selected", "true");
  return panel;
}

async function expectBounds(page: Page) {
  for (const selector of ["html", "main", ".detection-readiness-route"]) {
    expect(await page.locator(selector).evaluate(e => e.scrollWidth <= e.clientWidth), selector).toBe(true);
  }
}

test.describe.configure({ mode: "serial" });

test("presents a quiet, consistent desktop workspace in English and Korean", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const locale of ["en", "ko"]) {
    for (const view of views) {
      const panel = await openView(page, locale, view);
      await page.locator("main").evaluate(e => { e.scrollTop = 0; });
      await page.screenshot({ path: testInfo.outputPath(`${locale}-${view}-1440.png`) });
      await expectBounds(page);
      const activeTab = page.locator(`#detection-readiness-tab-${view}`);
      await visual(activeTab).toHaveCSS("border-bottom-left-radius", "6px");
      await visual(page.locator(".governance-readonly-banner")).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
      if (view === "coverage") {
        await visual(panel.locator(".coverage-funnel")).toHaveCSS("padding-top", "0px");
        await visual(panel.locator(".detection-attempt-comparison")).toHaveCSS("border-left-width", "0px");
      } else {
        await visual(panel.locator(view === "resources" ? ".detection-resource-toolbar" : ".detection-finding-toolbar"))
          .toHaveCSS("border-left-width", "0px");
        await visual(panel.locator(".detection-record-workspace .status-pill").first())
          .toHaveCSS("text-transform", "none");
        const detail = panel.locator(".detection-record-detail");
        await visual(detail.locator(".details-list > div").first())
          .toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
      }
      if (view === "findings") {
        await visual(panel.locator(".kpi-card").first()).toHaveCSS("box-shadow", "none");
        await visual(panel.locator(".kpi-card-label").first()).toHaveCSS("text-transform", "none");
        await panel.locator(".kpi-card").first().focus();
        await page.keyboard.press("Enter");
        await expect(page).toHaveURL(/#detection-lifecycle-records$/);
        const history = panel.locator(".detection-lifecycle-history").first();
        await history.locator("summary").click();
        await expect(history).toHaveAttribute("open", "");
      }
    }
  }
});

for (const locale of ["en", "ko"]) {
  test(`keeps the refined workspace usable at constrained and mobile widths (${locale})`, async ({ page }, testInfo) => {
    for (const viewport of [
      { width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      for (const view of views) {
        const panel = await openView(page, locale, view);
        await expectBounds(page);
        const tab = page.locator(`#detection-readiness-tab-${view}`);
        await tab.focus();
        expect(await tab.evaluate(e => parseFloat(getComputedStyle(e).outlineWidth))).toBeGreaterThanOrEqual(2);
        if (viewport.width <= 640) expect((await tab.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        if (view === "findings") {
          const stats = panel.locator(".kpi-grid");
          expect(await stats.evaluate(e => e.scrollWidth <= e.clientWidth)).toBe(true);
          let previousBottom = 0;
          for (const card of await stats.locator("a").all()) {
            const box = (await card.boundingBox())!;
            expect(box.height).toBeGreaterThanOrEqual(44);
            if (viewport.width <= 640) {
              expect(box.y).toBeGreaterThanOrEqual(previousBottom);
              previousBottom = box.y + box.height;
            }
          }
          await page.locator("main").evaluate(e => { e.scrollTop = 0; });
          await page.screenshot({ path: testInfo.outputPath(`${locale}-findings-${viewport.width}.png`) });
        }
      }
    }
  });
}
