import { expect, test } from "@playwright/test";
import { installHandoverUiFixture } from "./handover-ui-fixtures";

test("reporting-line edge confirmation stays review-only and responsive", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);

  await page.goto("/agent-oversight/reporting-lines");
  const workspace = page.locator(".report-lines-workspace");
  await expect(workspace.getByRole("heading", { name: "Import an organization chart" }))
    .toBeVisible();
  await expect(workspace.getByText("owner-1 reports to manager-1")).toBeVisible();
  const confirm = workspace.getByRole("button", { name: "Confirm relationship" });
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(workspace.getByText("Pending Owner review", { exact: true })).toBeVisible();
  expect(fixture.posts.at(-1)).toEqual({
    path: `/handover/reporting-line-cases/${fixture.reportingLine.operator_case_id}/confirm`,
    body: {
      expected_revision: 1,
      decision: "confirm",
      edge_digest: "7".repeat(64),
    },
  });
  const desktop = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(desktop.scroll).toBeLessThanOrEqual(desktop.client);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(workspace.getByRole("heading", { name: "Current reporting graph" })).toBeVisible();
  const geometry = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(geometry.scroll).toBeLessThanOrEqual(geometry.client);
});

test("requester contact consent sends no action approval", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);

  await page.goto("/approvals");
  const panel = page.getByRole("region", {
    name: "Approval requests waiting for your consent",
  });
  await expect(panel).toContainText("Sending the request does not approve the action.");
  await expect(panel).toContainText("manager-1");
  await expect(panel.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await panel.getByRole("button", { name: "Send approval request" }).click();
  await expect(page.locator(".state-success[role=status]"))
    .toContainText("Your choice was recorded");
  expect(fixture.posts.at(-1)).toEqual({
    path: "/hil/approval-1/report-line-contact",
    body: { consent: true, expected_revision: 0 },
  });
});
