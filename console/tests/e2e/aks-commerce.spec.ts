import { expect, test, type Page } from "@playwright/test";

async function geometry(page: Page) {
  return page.evaluate(() => {
    const route = document.querySelector(".aks-commerce-route")!;
    return {
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      },
      route: {
        clientWidth: route.clientWidth,
        scrollWidth: route.scrollWidth,
      },
    };
  });
}

async function expectNoOverflow(page: Page): Promise<void> {
  const measured = await geometry(page);
  expect(measured.document.scrollWidth).toBeLessThanOrEqual(measured.document.clientWidth + 1);
  expect(measured.route.scrollWidth).toBeLessThanOrEqual(measured.route.clientWidth + 1);
}

test("presents the synthetic order-impact path without action authority", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/aks-commerce?data=sample&locale=ko");

  await expect(page.getByRole("heading", { name: "주문 적체" })).toBeVisible();
  await expect(page.locator(".aks-commerce-path li")).toHaveCount(5);
  await expect(page.locator(".aks-commerce-slo-grid article")).toHaveCount(1);
  await expect(page.locator(".aks-commerce-hero-state")).toContainText("합성 여정");
  await expect(page.locator(".aks-commerce-split")).toContainText("ops.scale-out");
  await expectNoOverflow(page);

  await page.setViewportSize({ width: 993, height: 641 });
  await expectNoOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".aks-commerce-service-picker button")).toHaveCount(2);
  await expectNoOverflow(page);
});

test("switches to catalog impact without retaining an order action", async ({ page }) => {
  await page.goto("/aks-commerce?data=sample");

  await page.getByRole("button", { name: "Catalog browse" }).click();

  await expect(page.getByRole("heading", { name: "Healthy" })).toBeVisible();
  await expect(page.locator(".aks-commerce-path li")).toHaveCount(2);
  await expect(page.locator(".aks-commerce-split")).toContainText(
    "No recovery action is proposed",
  );
});
