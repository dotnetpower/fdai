import { expect, test } from "@playwright/test";
import { expectSettingsHierarchy } from "./settings-hierarchy";
import { openSurface, revealSettingsSection, routeMocks } from "./settings-mock-page";

const menus = [
  { file: "settings.html", detail: "#settings-context" },
  { file: "settings-models.html", detail: "#models-catalog" },
  { file: "settings-runtime.html", detail: "#runtime-override-editor" },
  { file: "settings-memory.html", detail: "#memory-entries" },
  { file: "settings-integrations.html", detail: "#integrations-diagnostics" },
  { file: "settings-diagnostics.html", detail: "#diagnostics-sources" },
];

test.describe("Settings workspace refinement", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await routeMocks(page);
  });

  for (const viewport of [
    { name: "desktop", width: 1070, height: 918, master: false },
    { name: "constrained", width: 993, height: 641, master: true },
    { name: "mobile", width: 390, height: 844, master: true },
  ]) {
    test(`${viewport.name} keeps six Settings menus readable in their actual shell`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      for (const menu of menus) {
        const frame = await openSurface(page, menu.file, viewport.master);
        const main = frame.locator("main");
        await expectSettingsHierarchy(main);
        await expect(frame.locator("html")).toHaveCSS("scrollbar-gutter", "stable");
        expect(await main.evaluate((element) =>
          element.scrollWidth <= element.clientWidth
          && document.documentElement.scrollWidth <= innerWidth,
        )).toBe(true);
        for (const facts of await frame.locator(".cs-settings-facts:visible").all()) {
          for (const row of await facts.locator(".cs-setting-row").all()) {
            expect(await row.evaluate((element) =>
              element.scrollWidth <= element.clientWidth,
            )).toBe(true);
            if (viewport.name === "desktop") {
              expect(await row.evaluate((element) => element.getBoundingClientRect().height)).toBeLessThanOrEqual(80);
            }
          }
        }
        if (menu.file === "settings-runtime.html" && viewport.name !== "mobile") {
          await expect(frame.locator(".cp-table")).toHaveCSS("display", "table");
          const tops = await frame.locator(".cp-kpi").evaluateAll((items) =>
            items.map((item) => item.getBoundingClientRect().top),
          );
          expect(new Set(tops).size).toBe(1);
          await expect(frame.getByRole("table", { name: "Runtime policy settings", exact: true })).toBeVisible();
          expect(await frame.locator(".cp-table caption").evaluate((element) =>
            element.getBoundingClientRect().height,
          )).toBe(1);
        }
        if (menu.file === "settings-memory.html") {
          await revealSettingsSection(frame, "#memory-filter");
          const filters = frame.getByRole("group", { name: "Memory scope filters" });
          await expect(filters).toHaveCSS("background-color", "rgb(245, 245, 245)");
          if (viewport.name === "desktop") {
            const bottoms = await filters.locator("input, select, button").evaluateAll((controls) =>
              controls.map((control) => control.getBoundingClientRect().bottom),
            );
            expect(Math.max(...bottoms) - Math.min(...bottoms)).toBeLessThanOrEqual(1);
          }
          await filters.getByRole("combobox", { name: "Scope kind" }).selectOption("resource-group");
          await filters.getByRole("textbox", { name: "Scope reference" }).fill("example-scope");
          await filters.getByRole("button", { name: "Apply filter" }).click();
          await expect(filters.getByRole("textbox")).toHaveValue("example-scope");
          if (viewport.name === "mobile") {
            const cell = frame.locator(".cs-table tbody td").first();
            expect(await cell.evaluate((element) =>
              Math.abs(element.querySelector("strong")!.getBoundingClientRect().left
                - element.querySelector(".cs-muted")!.getBoundingClientRect().left),
            )).toBeLessThanOrEqual(1);
          }
        }
        await frame.getByRole("tab").first().click();
        await frame.locator("body").evaluate(() => scrollTo(0, 0));
        await page.screenshot({ path: testInfo.outputPath(`${menu.file}-overview.png`) });
        const detail = await revealSettingsSection(frame, menu.detail);
        await detail.evaluate((element) => element.scrollIntoView({ block: "start" }));
        if (menu.file === "settings-models.html" && viewport.name === "desktop") {
          const buttons = await frame.locator(".cs-settings-option-card > button").evaluateAll((controls) =>
            controls.map((control) => control.getBoundingClientRect().bottom),
          );
          expect(Math.max(...buttons) - Math.min(...buttons)).toBeLessThanOrEqual(1);
        }
        await page.screenshot({ path: testInfo.outputPath(`${menu.file}-detail.png`) });
      }
    });
  }
});
