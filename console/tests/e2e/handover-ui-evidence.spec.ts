import { expect, test } from "@playwright/test";
import { goalFixture, HANDOVER_GOAL, installHandoverUiFixture } from "./handover-ui-fixtures";
import { assertHandoverGeometry, assertTabOrder, enlargeHandoverText, recordUiEvidence } from "./handover-ui-measurements";

test("checklist desktop exposes only individually advertised operations", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  fixture.goal = goalFixture("in_progress", ["evidence"]);
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}`);
  const panel = page.locator(".handover-checklist");
  await expect(panel.getByRole("combobox", { name: "Evidence area", exact: true })).toBeVisible();
  await expect.soft(panel.getByRole("button", { name: "Record not applicable", exact: true })).toHaveCount(0);
  await expect.soft(panel.getByRole("button", { name: "Reuse reviewed evidence", exact: true })).toHaveCount(0);
  fixture.goal = goalFixture("in_progress", ["reuse"]);
  await panel.getByRole("button", { name: "Refresh evidence" }).click();
  await expect(panel.getByRole("combobox")).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "Reuse reviewed evidence", exact: true })).toBeVisible();
  expect(fixture.posts).toEqual([]);
});

test("checklist desktop pending feedback and refreshed conflict recovery are explicit", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  let release!: () => void;
  fixture.writeGate = new Promise<void>((resolve) => { release = resolve; });
  fixture.writeStatus = 409;
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}`);
  const panel = page.locator(".handover-checklist");
  await panel.getByRole("combobox", { name: "Evidence area", exact: true }).selectOption("scope_exclusions");
  const reason = panel.getByRole("textbox", { name: "Reason reference", exact: true });
  await reason.fill("reason:synthetic-reviewed-exclusion");
  const submit = panel.getByRole("button", { name: "Record not applicable", exact: true });
  await submit.focus();
  await page.keyboard.press("Enter");
  await expect(reason).toBeDisabled();
  await expect.soft(panel.locator('.loading-skeleton[role="status"][aria-busy="true"]')).toBeVisible();
  release();
  await expect(panel.getByRole("alert")).toContainText("409");
  expect(fixture.posts.map((item) => item.body)).toEqual([
    { expected_revision: 9, slot: "scope_exclusions", reason_ref: "reason:synthetic-reviewed-exclusion" },
  ]);
  fixture.goal = goalFixture("in_progress");
  fixture.goal.revision = 10;
  await panel.getByRole("button", { name: "Refresh evidence" }).click();
  await expect(panel.getByRole("status").filter({ hasText: "Evidence checklist incomplete" })).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
});

test("checklist desktop completed review returns focus when its action disappears", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  fixture.goal = goalFixture("ready_for_review", ["accept"]);
  fixture.nextGoal = goalFixture("accepted", []);
  fixture.nextGoal.revision = 10;
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}`);
  const panel = page.locator(".handover-checklist");
  await panel.getByRole("button", { name: "Record Owner review", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByRole("status").filter({ hasText: "Evidence accepted" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Refresh evidence", exact: true })).toBeFocused();
  expect(fixture.posts.map((item) => item.body)).toEqual([{ expected_revision: 9 }]);
});

test("scoped desktop validation links have field-bound error descriptions", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installHandoverUiFixture(page);
  await page.goto("/agent-oversight/mapping-reviews");
  const panel = page.locator(".scoped-duty-workspace");
  await panel.locator("#scoped-justification").fill("short");
  const summary = panel.locator(".scoped-duty-validation");
  await expect(summary).toBeVisible();
  const issues = await summary.locator("a").evaluateAll((links) => links.map((link) => {
    const target = document.getElementById((link as HTMLAnchorElement).hash.slice(1));
    return { label: link.textContent, target: target?.id, invalid: target?.getAttribute("aria-invalid"),
      described: target?.getAttribute("aria-describedby")?.split(/\s+/).some((id) => document.getElementById(id)?.textContent === link.textContent) ?? false };
  }));
  expect(issues.length).toBeGreaterThan(3);
  expect.soft(issues.filter((item) => !item.target)).toEqual([]);
  expect.soft(issues.filter((item) => item.invalid !== "true")).toEqual([]);
  expect(issues.filter((item) => !item.described)).toEqual([]);
});

for (const locale of ["en", "ko"] as const) {
test(`checklist ${locale} default form geometry, themes and keyboard have measurable boundaries`, async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installHandoverUiFixture(page);
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}&locale=${locale}`);
  const panel = page.locator(".handover-checklist");
  const refresh = panel.getByRole("button", { name: locale === "en" ? "Refresh evidence" : "근거 새로 고침", exact: true });
  await expect(panel.getByRole("combobox")).toBeVisible();
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await assertHandoverGeometry(panel, info, `checklist-desktop-${theme}`);
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  await assertTabOrder(page, [refresh, panel.locator("summary").first(), panel.getByRole("combobox"),
    panel.getByRole("textbox", { name: locale === "en" ? "Reason reference" : "사유 참조", exact: true }),
    panel.getByRole("textbox", { name: locale === "en" ? "Accepted source goal ID" : "수락된 원본 목표 ID", exact: true })]);
  expect(info.errors).toEqual([]);
  await page.screenshot({ path: info.outputPath("checklist-desktop.png") });
  await panel.getByRole("combobox").scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("checklist-desktop-form.png") });
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    await assertHandoverGeometry(panel, info, `checklist-form-${viewport.width}`);
  }
  await enlargeHandoverText(panel);
  await assertHandoverGeometry(panel, info, "checklist-form-320-200-percent");
});
}

test("checklist desktop late response cannot restore another goal's input or authority", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}`);
  const panel = page.locator(".handover-checklist");
  await panel.getByRole("combobox").selectOption("scope_exclusions");
  await panel.getByRole("textbox", { name: "Reason reference", exact: true }).fill("reason:old-synthetic-goal");
  await panel.getByRole("textbox", { name: "Accepted source goal ID", exact: true }).fill("c".repeat(64));
  let release!: () => void;
  fixture.writeGate = new Promise<void>((resolve) => { release = resolve; });
  fixture.nextGoal = goalFixture("accepted", []);
  await panel.getByRole("button", { name: "Record not applicable", exact: true }).click();
  await expect.poll(() => fixture.posts.length).toBe(1);
  const nextId = "b".repeat(64);
  fixture.goal = { ...goalFixture(), goal_id: nextId, agent_name: "Huginn" };
  await page.evaluate((id) => {
    history.pushState({}, "", `/documents?handover_goal=${id}`);
    window.dispatchEvent(new Event("fdai:route-changed"));
  }, nextId);
  await expect(panel.getByRole("status").filter({ hasText: "Huginn" })).toBeVisible();
  await expect(panel.getByRole("textbox", { name: "Reason reference", exact: true })).toHaveValue("");
  await expect(panel.getByRole("textbox", { name: "Accepted source goal ID", exact: true })).toHaveValue("");
  await expect(panel.getByRole("combobox")).toHaveValue("");
  const oldResponse = page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes(HANDOVER_GOAL));
  release();
  await (await oldResponse).finished();
  await expect(panel.getByRole("status").filter({ hasText: "Huginn" })).toBeVisible();
  await expect(panel.getByRole("status").filter({ hasText: "Evidence accepted" })).toHaveCount(0);
  expect(fixture.posts).toHaveLength(1);
});

test("checklist desktop reuse is keyboard-operable with exact field guidance", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  fixture.goal = goalFixture("in_progress", ["reuse"]);
  fixture.nextGoal = goalFixture("ready_for_review", []);
  fixture.nextGoal.revision = 10;
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}`);
  const panel = page.locator(".handover-checklist");
  const input = panel.getByRole("textbox", { name: "Accepted source goal ID", exact: true });
  await input.fill("bad-synthetic-id");
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(input).toHaveAccessibleDescription(/64 lowercase hexadecimal/);
  await expect(panel.getByRole("button", { name: "Reuse reviewed evidence", exact: true })).toBeDisabled();
  await input.fill("b".repeat(64));
  await page.keyboard.press("Tab");
  await expect(panel.getByRole("button", { name: "Reuse reviewed evidence", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(panel.getByRole("status").filter({ hasText: "Independent review pending" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Refresh evidence", exact: true })).toBeFocused();
  expect(fixture.posts.map((item) => item.body)).toEqual([{ expected_revision: 9, source_goal_id: "b".repeat(64) }]);
});

test("checklist desktop request timing and deliberate focus movement remain bounded", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  fixture.goal = goalFixture("ready_for_review", ["accept"]);
  fixture.nextGoal = goalFixture("accepted", []);
  fixture.nextGoal.revision = 10;
  let release!: () => void;
  fixture.writeGate = new Promise<void>((resolve) => { release = resolve; });
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}`);
  const panel = page.locator(".handover-checklist");
  const action = panel.getByRole("button", { name: "Record Owner review", exact: true });
  await action.focus();
  const started = performance.now();
  await page.keyboard.press("Enter");
  await expect(panel.locator('.loading-skeleton[role="status"][aria-busy="true"]')).toBeVisible();
  const pendingMs = performance.now() - started;
  expect(pendingMs).toBeLessThan(250);
  const summary = panel.locator("summary").first();
  await summary.focus();
  await page.keyboard.press("Enter");
  const released = performance.now();
  release();
  await expect(panel.getByRole("status").filter({ hasText: "Evidence accepted" })).toBeVisible();
  const responseMs = performance.now() - released;
  expect(responseMs).toBeLessThan(1000);
  await expect(summary).toBeFocused();
  await recordUiEvidence(info, "request-budget", { pendingMs, pendingBudgetMs: 250, responseMs, responseBudgetMs: 1000,
    singleSyntheticSample: true, noFocusSteal: true, posts: fixture.posts.length });
  expect(fixture.posts).toHaveLength(1);
});

test("handover desktop hover and invalid field states preserve contrast in both themes", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}`);
  const checklist = page.locator(".handover-checklist");
  await checklist.getByRole("textbox", { name: "Accepted source goal ID", exact: true }).fill("invalid-synthetic-source");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await checklist.getByRole("button", { name: "Refresh evidence", exact: true }).hover();
    await assertHandoverGeometry(checklist, info, `checklist-${theme}-hover-invalid`);
  }
  await page.goto("/agent-oversight/mapping-reviews");
  const scoped = page.locator(".scoped-duty-workspace");
  await scoped.locator("#scoped-binding-0-scope_ref").selectOption("scope:example");
  await scoped.locator("#scoped-binding-0-subject_ref").fill("person:synthetic-primary");
  await scoped.locator("#scoped-binding-0-effective_from").fill("2026-09-15T11:00:00Z");
  await scoped.locator("#scoped-binding-0-effective_until").fill("2026-09-16T12:00:00Z");
  await scoped.locator("#scoped-justification").fill("Synthetic contrast review of the unchanged proposal-only operation.");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await scoped.getByRole("button", { name: "Request draft", exact: true }).hover();
    await assertHandoverGeometry(scoped, info, `scoped-${theme}-primary-hover`);
  }
  expect(fixture.posts).toEqual([]);
});
