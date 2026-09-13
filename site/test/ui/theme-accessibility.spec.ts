import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const routes = [
  "",
  "get-started/",
  "sre/",
  "architecture/",
  "diagram-gallery/",
  "reference/roadmap/",
  "reference/roadmap/interfaces/operator-console/",
];

for (const theme of ["light", "dark"] as const) {
  for (const locale of ["en", "ko"] as const) {
    test.describe(`${locale} ${theme}`, () => {
      test.beforeEach(async ({ context, page }) => {
        await page.emulateMedia({ colorScheme: theme });
        await context.addInitScript((value) => localStorage.setItem("starlight-theme", value), theme);
      });

      for (const route of routes) {
        test(`${route || "home"} has readable and accessible shared UI`, async ({ page }) => {
          const errors: string[] = [];
          page.on("pageerror", error => errors.push(error.message));
          const response = await page.goto(`${locale === "ko" ? "ko/" : ""}${route}`, { waitUntil: "networkidle" });
          expect(response?.status()).toBe(200);
          await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
          await expect(page.locator("html")).toHaveAttribute("lang", locale);
          await expect(page.locator("h1")).toHaveCount(1);
          const diagrams = page.locator("fdai-architecture-diagram");
          for (const diagram of await diagrams.all()) {
            await expect(diagram.locator(".stage > svg")).toHaveAttribute("role", "group");
          }
          const scan = await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
            .analyze();
          expect(scan.violations.map(({ id, nodes }) => ({ id, nodes: nodes.map(({ target, failureSummary }) => ({ target, failureSummary })) }))).toEqual([]);
          expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
          expect(errors).toEqual([]);
        });
      }
    });
  }
}
