import { expect, test } from "@playwright/test";
import { openSurface, routeMocks } from "./settings-mock-page";
import { exerciseGovernance, expectGovernance, governanceRoutes } from "./governance-mock-checks";

test.describe("Current Governance UI contract", () => {
  test.describe.configure({ mode: "default" });
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "This scope validates desktop before explicit responsive states.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await routeMocks(page);
  });

  for (const route of governanceRoutes) {
    test(`desktop ${route}: current theme, complete authored interactions and readable evidence`, async ({ page }, testInfo) => {
      if (route === "ontology") test.slow();
      const errors: string[] = [];
      const writes: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("requestfailed", (request) => {
        const path = new URL(request.url()).pathname;
        const failure = request.failure()?.errorText;
        const expectedIframeCancellation =
          route === "ontology" &&
          path === "/mocks/ui/ontology-instances-2d.html" &&
          failure === "net::ERR_ABORTED";
        if (!expectedIframeCancellation) errors.push(`${path}: ${failure}`);
      });
      page.on("request", (request) => { if (request.method() !== "GET") writes.push(request.url()); });
      const frame = await openSurface(page, `${route}.html`, true);
      await expect(frame.locator("main")).toHaveAttribute("data-governance-ready", "true");
      await expect(frame.locator(".gw-preview-note, .oa-preview")).toContainText("No live reads or changes");
      const baseline = await expectGovernance(frame);
      await page.screenshot({ path: testInfo.outputPath(`${route}-desktop.png`), animations: "disabled" });
      await exerciseGovernance(frame);
      await testInfo.attach("desktop-geometry-and-colors", { body: JSON.stringify(baseline), contentType: "application/json" });
      expect(errors).toEqual([]);
      expect(writes).toEqual([]);
    });
  }

  for (const route of governanceRoutes) {
    test(`responsive ${route}: real iframe, narrow controls and expanded states`, async ({ page }, testInfo) => {
      const frame = await openSurface(page, `${route}.html`, true);
      const measurements = [];
      for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
        await page.setViewportSize(viewport);
        measurements.push(await expectGovernance(frame));
        await exerciseGovernance(frame);
        await frame.locator("h1").scrollIntoViewIfNeeded();
        await page.screenshot({ path: testInfo.outputPath(`${route}-${viewport.width}.png`), animations: "disabled" });
      }
      await testInfo.attach("responsive-geometry-and-colors", { body: JSON.stringify(measurements), contentType: "application/json" });
    });
  }
});
