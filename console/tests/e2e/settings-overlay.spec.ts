import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/api/**", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Optional test source unavailable." }),
    });
  });
});

test("Settings overlays and restores the current workspace without changing its URL", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/labs");
  await expect(page.getByRole("link", { name: /Logo lab/ })).toBeVisible();
  const originalUrl = page.url();

  await page.locator(".activity-bar").getByRole("button", { name: "Settings" }).click();

  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(originalUrl);
  await expect(page.locator(".labs-route")).toBeVisible();
  await expect(page.locator(".shell")).toHaveAttribute("inert", "");
  await expect(dialog.getByRole("link", { name: /General/ })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await dialog.getByRole("link", { name: /Models/ }).click();
  await expect(page).toHaveURL(originalUrl);
  await expect(dialog.getByRole("link", { name: /Models/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.locator(".labs-route")).toBeVisible();

  await dialog.getByRole("button", { name: "Close settings" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(originalUrl);
  await expect(page.getByRole("link", { name: /Logo lab/ })).toBeVisible();
});

test("Settings remains contained and closable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/labs");
  await page.locator(".activity-bar").getByRole("button", { name: "Settings" }).click();

  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  const geometry = await dialog.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    height: element.getBoundingClientRect().height,
  }));
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.height).toBe(844);

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/labs$/);
});

test("mobile Settings keeps every active destination visible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const routes = [
    "/settings/general",
    "/settings/models",
    "/settings/runtime-policies",
    "/settings/memory",
    "/settings/iam",
    "/settings/integrations",
    "/settings/diagnostics",
  ];
  for (const route of routes) {
    await page.goto(route);
    const dialog = page.getByRole("dialog", { name: "Settings" });
    const active = dialog.locator('.settings-overlay-navigation [aria-current="page"]');
    await expect(dialog).toBeVisible();
    await expect(active).toBeVisible();
    await expect.poll(() => active.evaluate((element) => {
      const item = element.getBoundingClientRect();
      const navigation = element.closest("nav")!.getBoundingClientRect();
      return item.left >= navigation.left && item.right <= navigation.right;
    })).toBe(true);
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
});

test("IAM tabs expose a visible keyboard focus indicator", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings/iam/users");
  const dialog = page.getByRole("dialog", { name: "Settings" });
  const usersTab = dialog.getByRole("tab", { name: "Users", exact: true });
  await expect(usersTab).toBeVisible();
  await dialog.getByRole("button", { name: "Close settings" }).focus();
  for (let index = 0; index < 8; index += 1) await page.keyboard.press("Tab");
  await expect(usersTab).toBeFocused();
  await expect(usersTab).toHaveCSS("outline-width", "2px");
});

test("a direct Settings URL closes to the default workspace", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/settings/iam");
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();

  await page.keyboard.press("Escape");

  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(0);
});
