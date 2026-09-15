import { expect, test } from "@playwright/test";
import { installHandoverUiFixture, SCOPED_CASE, scopedCaseFixture } from "./handover-ui-fixtures";

test("scoped keyboard decisions recover to manual refresh without treating acceptance as completion", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  const panel = page.locator(".scoped-duty-workspace");
  for (const [state, decision, button] of [
    ["draft", null, "Submit for current-source review"],
    ["pending_review", "approve", "Approve ownership plan"],
    ["pending_review", "reject", "Reject ownership plan"],
  ] as const) {
    fixture.scopedCase = { ...scopedCaseFixture(), state, requester_ref: state === "draft" ? "owner-1" : "requester-1" };
    await page.goto(`/agent-oversight/mapping-reviews?scoped_case=${SCOPED_CASE}`);
    const action = panel.getByRole("button", { name: button, exact: true });
    await expect(action).toBeEnabled();
    await action.focus();
    await page.keyboard.press("Enter");
    await expect(panel.getByRole("status").filter({ hasText: "Request accepted, awaiting Core" })).toBeVisible();
    await expect(action).toBeDisabled();
    await expect(panel.getByRole("button", { name: "Refresh case", exact: true })).toBeFocused();
    expect(fixture.posts.at(-1)?.body).toEqual(decision === null ? { expected_revision: 2 }
      : { expected_revision: 2, decision, plan_digest: "d".repeat(64) });
  }
  expect(fixture.posts).toHaveLength(3);
});

test("scoped materialized case states preserve exact review and merge evidence", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  const panel = page.locator(".scoped-duty-workspace");
  for (const [state, label] of [["approved", "Two reviews recorded"], ["ownership_pr_open", "Ownership review PR open"],
    ["ownership_merged", "Ownership merge recorded"], ["rejected", "Rejected"]]) {
    fixture.scopedCase = { ...scopedCaseFixture(), state, revision: 4,
      reviews: (state === "rejected" ? ["owner-2"] : ["owner-2", "owner-3"]).map((reviewer_ref) => ({ reviewer_ref,
        decision: state === "rejected" ? "reject" : "approve", plan_digest: "d".repeat(64), reviewed_at: "2026-09-15T12:00:00Z" })),
      ...(state?.startsWith("ownership_") ? { pr_ref: "https://example.com/review/1", candidate_digest: "e".repeat(64) } : {}),
      merge_commit_sha: state === "ownership_merged" ? "f".repeat(40) : null };
    await page.goto(`/agent-oversight/mapping-reviews?scoped_case=${SCOPED_CASE}`);
    await expect(panel.getByText(label!, { exact: true })).toBeVisible();
    await expect(panel.getByRole("button", { name: "Approve ownership plan", exact: true })).toHaveCount(0);
    await expect(panel.locator(".scoped-duty-reviews li")).toHaveCount(state === "rejected" ? 1 : 2);
  }
  fixture.catalogStatus = 503;
  fixture.caseStatus = 404;
  await page.goto(`/agent-oversight/mapping-reviews?scoped_case=${SCOPED_CASE}`);
  await expect(panel.locator(".state-unavailable")).toHaveCount(2);
  await expect(panel.getByRole("button", { name: "Approve ownership plan", exact: true })).toHaveCount(0);
  await panel.locator("#scoped-justification").fill("Synthetic source outage correction.");
  const catalogCorrection = panel.locator('.scoped-duty-validation a[href="#scoped-catalog-title"]');
  await catalogCorrection.focus();
  await page.keyboard.press("Enter");
  await expect(panel.locator("#scoped-catalog-title")).toBeFocused();
  fixture.catalogStatus = 200;
  fixture.caseStatus = 403;
  await panel.locator("#scoped-catalog").click();
  await expect(panel.locator(".state-unavailable")).toHaveCount(1);
  await panel.getByRole("button", { name: "Refresh case", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("server denied access");
  await expect(panel.getByRole("button", { name: "Approve ownership plan", exact: true })).toHaveCount(0);
  await panel.getByRole("button", { name: "Remove declaration 1", exact: true }).click();
  await expect(panel.locator(".scoped-duty-binding")).toHaveCount(0);
  await expect(panel.locator(".scoped-duty-validation")).toContainText("between 1 and 30");
  await expect(panel.getByRole("button", { name: "Request draft", exact: true })).toBeDisabled();
  await panel.locator("#scoped-add-binding").click();
  await expect(panel.locator("#scoped-binding-0-agent_name")).toBeFocused();
  expect(fixture.posts).toEqual([]);
});
