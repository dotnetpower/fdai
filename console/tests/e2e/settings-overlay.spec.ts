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
    "/settings/environment-and-deployment",
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

test("Environment and deployment combines readiness and deployment evidence", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/settings/environment-and-deployment");

  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("link", { name: /Environment and deployment/ }))
    .toHaveAttribute("aria-current", "page");
  await expect(dialog.getByRole("tab", { name: "Readiness" }))
    .toHaveAttribute("aria-selected", "true");
  await expect(dialog.getByRole("heading", { name: "Onboarding readiness" })).toBeVisible();

  await dialog.getByRole("tab", { name: "Deployment run" }).click();

  await expect(page).toHaveURL(/\/settings\/environment-and-deployment\/deployment$/);
  await expect(dialog.getByRole("tab", { name: "Deployment run" }))
    .toHaveAttribute("aria-selected", "true");
  await expect(dialog.getByRole("heading", { name: "Provisioning" })).toBeVisible();
});

test("IAM tabs expose a visible keyboard focus indicator", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings/iam/users");
  const dialog = page.getByRole("dialog", { name: "Settings" });
  const usersTab = dialog.getByRole("tab", { name: "Users", exact: true });
  await expect(usersTab).toBeVisible();
  await dialog.getByRole("button", { name: "Close settings" }).focus();
  for (let index = 0; index < 9; index += 1) await page.keyboard.press("Tab");
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

test("a direct Settings URL does not load the hidden Dashboard", async ({ page }) => {
  const dashboardRequests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path === "/api/kpi" || path === "/api/kpi/promotion-gates") {
      dashboardRequests.push(path);
    }
  });

  await page.goto("/settings/iam");
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
  expect(dashboardRequests).toEqual([]);
});

test("a failed Settings shell chunk renders a recoverable error", async ({ page }) => {
  await page.route("**/src/components/settings-overlay.tsx*", (route) => route.abort());

  await page.goto("/settings/iam");

  await expect(page.getByText("Panel failed to load.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Reload console" })).toBeVisible();
});

test("a failed Settings projection can recover without a full page reload", async ({ page }) => {
  let attempts = 0;
  await page.route("**/runtime/settings", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "temporary runtime settings failure" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        revision: 1,
        can_manage: false,
        updated_at: null,
        updated_by: null,
        integrations: [],
        runtime: {
          environment: "dev",
          state_store_durable: true,
          autonomy_default: "shadow",
          pantheon_enabled: true,
          workflow_observation_enabled: true,
          primary_transport_configured: true,
          auxiliary_transport_configured: false,
          case_history_configured: false,
        },
        settings: [],
      }),
    });
  });

  await page.goto("/settings/runtime-policies");
  await expect(page.getByText("HTTP 503", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click();

  await expect(page.getByText(
    "Owner role is required to change runtime policies. Current and effective values remain visible.",
  )).toBeVisible();
  expect(attempts).toBe(2);
});
