import { expect, test } from "@playwright/test";
import { openSurface, routeMocks } from "./settings-mock-page";
import { expectGovernance, governanceRoutes, inspectGovernance } from "./governance-mock-checks";

test.describe("Governance accessibility and preference contracts", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Explicit constrained viewport follows completed desktop acceptance.");
    await page.setViewportSize({ width: 993, height: 641 });
    await routeMocks(page);
  });
  for (const route of governanceRoutes) {
    test(`${route}: enlarged text, spacing, forced colors and visible keyboard focus`, async ({ page }, testInfo) => {
      const frame = await openSurface(page, `${route}.html`, true);
      await expect(frame.locator("main")).toHaveAttribute("data-governance-ready", "true");
      await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
      const controls = frame.locator("main button:visible, main a:visible, main input:visible, main select:visible, main summary:visible");
      const first = controls.first();
      if (await controls.count()) {
        await first.focus();
        await first.press("Tab");
        const focused = frame.locator(":focus");
        await expect(focused).toHaveCSS("outline-width", /[2-9]px/);
        const focusStyle = await focused.evaluate((element) => {
          const style = getComputedStyle(element);
          return { tag: element.tagName, className: element.className, focusVisible: element.matches(":focus-visible"), outline: style.outline, width: Number.parseFloat(style.outlineWidth), style: style.outlineStyle };
        });
        expect(focusStyle.style !== "none" && focusStyle.width >= 2, JSON.stringify(focusStyle)).toBe(true);
      }
      const forced = await inspectGovernance(frame);
      expect(forced.documentFits).toBe(true);
      expect(forced.mainFits).toBe(true);
      expect(forced.clippedControls).toEqual([]);
      await page.emulateMedia({ forcedColors: "none" });
      await frame.locator("main").evaluate(() => {
        const style = document.createElement("style");
        style.textContent = `.cs-governance-neutral {
          --cs-type-page-title-size:48px; --cs-type-section-title-size:40px;
          --cs-type-panel-title-size:30px; --cs-type-body-size:28px;
          --cs-type-compact-size:26px; --cs-type-label-size:24px; --cs-type-caption-size:22px;
        }
        .cs-governance-neutral * { line-height:1.5!important; letter-spacing:.12em!important; word-spacing:.16em!important; }
        .cs-governance-neutral p { margin-bottom:2em!important; }`;
        document.head.append(style);
      });
      await expect(frame.locator("main h1")).toHaveCSS("font-size", "48px");
      const enlarged = await expectGovernance(frame, "48px");
      for (const details of await frame.locator("details").all()) {
        if (!(await details.isVisible())) continue;
        if (await details.getAttribute("open") === null) await details.locator(":scope > summary").click();
        await expectGovernance(frame, "48px");
      }
      await testInfo.attach("accessible-layout", { body: JSON.stringify({ forced, enlarged }), contentType: "application/json" });
      await page.screenshot({ path: testInfo.outputPath(`${route}-enlarged.png`) });
    });
  }
});
