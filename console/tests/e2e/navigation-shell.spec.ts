import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Optional test source unavailable." }),
    });
  });
});

test("hides Architecture from Governance navigation while preserving its route", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const locale of ["en", "ko"]) {
    await page.goto(`/labs?locale=${locale}`);
    await page
      .getByRole("button", { name: locale === "ko" ? "거버넌스" : "Governance" })
      .click();

    const explorer = page.locator("#navigation-explorer");
    await expect(explorer).toHaveAttribute("aria-hidden", "false");
    await expect(explorer.locator('a[href="/architecture"]')).toHaveCount(0);
    await expect(explorer.locator("a").first()).toHaveAttribute("href", "/ontology");
    expect(await page.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth
    )).toBe(true);
  }

  await page.goto("/architecture?locale=en");
  await expect(page.getByRole("heading", { name: /Architecture$/ })).toBeVisible();
  await expect(page).toHaveURL(/\/architecture\?locale=en$/);
});
