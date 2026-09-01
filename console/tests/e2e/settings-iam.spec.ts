import { expect, test, type Page, type Route } from "@playwright/test";

const overview = {
  principal: {
    oid: "owner-1",
    roles: ["Owner"],
    capabilities: ["view-console", "manage-group-membership"],
  },
  roles: [
    { value: "Reader", capabilities: ["view-console"], routine_assignment: true },
    {
      value: "Owner",
      capabilities: ["view-console", "manage-group-membership"],
      routine_assignment: true,
    },
  ],
  assignment_boundary: "identity-provider-group",
  access_authority: {
    source: "server-verified",
    is_owner: true,
    can_manage_group_membership: true,
  },
  directory: {
    source: "microsoft-graph",
    availability: "available",
    observed_at: "2026-09-01T05:00:00Z",
    detail: null,
  },
  workflow: {
    access_request_authority: "proposal_only",
    assignment_authority: "observation_only",
    provider_mutation: "promotion_required",
  },
};

async function installFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    const payload = path === "/iam"
      ? overview
      : path === "/iam/access-requests"
      ? { items: [], total: 0, next_cursor: null }
      : path === "/iam/directory/roster"
      ? {
          items: [
            {
              provider: "entra",
              subject_id: "user-1",
              display_name: "Example Operator",
              principal_type: "person",
              roles: ["Reader"],
              username: "operator@example.com",
              active: true,
            },
          ],
        }
      : null;
    if (payload !== null) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
      return;
    }
    await route.continue();
  };
  await page.route("**/api/**", handle);
  await page.route("**/iam**", handle);
}

test("explains Owner authority and preserves IAM data on narrow screens", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page);
  await page.goto("/settings/iam");

  await expect(page.getByText("FDAI Owner access is verified")).toBeVisible();
  await expect(page.getByText("Azure subscription, Entra tenant")).toBeVisible();
  await expect(page.getByText("Separate protected workflow")).toBeVisible();
  await page.getByRole("tab", { name: "Users" }).click();
  await expect(page).toHaveURL(/\/settings\/iam\/users$/);
  await expect(page.getByText("Find a user for a role request")).toBeVisible();
  await expect(page.getByText("Example Operator")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open assignment reviews" })).toBeVisible();

  const desktop = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(desktop.scrollWidth).toBeLessThanOrEqual(desktop.clientWidth);

  await page.setViewportSize({ width: 993, height: 641 });
  await expect(page.getByText("Example Operator")).toBeVisible();
  const constrained = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(constrained.scrollWidth).toBeLessThanOrEqual(constrained.clientWidth);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText("Example Operator")).toBeVisible();
  await expect(page.getByText("Current roles")).toBeVisible();
  const mobile = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(mobile.scrollWidth).toBeLessThanOrEqual(mobile.clientWidth);
});
