import { expect, test, type Page, type Route } from "@playwright/test";

const correlationId = "demo-correlation-001";
const actionIdentity = {
  action_id: "00000000-0000-0000-0000-000000000101",
  attempt: 1,
  execution_path: "direct_api",
} as const;
const trace = {
  correlation_id: correlationId,
  step_count: 6,
  steps: [
    {
      ...actionIdentity,
      seq: 1,
      recorded_at: "2026-09-14T02:00:01Z",
      stage: "plan",
      decision: null,
      reason: "proposal recorded",
      action_kind: "action.proposal.recorded",
      outcome: null,
      mode: "enforce",
      entry_hash: "hash-1",
    },
    {
      ...actionIdentity,
      seq: 2,
      recorded_at: "2026-09-14T02:00:02Z",
      stage: "risk-gate",
      decision: "hil",
      reason: "human approval required",
      action_kind: "risk_gate.unified",
      outcome: null,
      mode: "enforce",
      entry_hash: "hash-2",
    },
    {
      ...actionIdentity,
      seq: 3,
      recorded_at: "2026-09-14T02:00:03Z",
      stage: null,
      decision: null,
      reason: "approval recorded",
      action_kind: "hil.approved.execution_pending",
      outcome: "awaiting_effect_evidence",
      mode: "enforce",
      entry_hash: "hash-3",
    },
    {
      ...actionIdentity,
      seq: 4,
      recorded_at: "2026-09-14T02:00:04Z",
      stage: "execute",
      decision: "pending",
      reason: "independent effect evidence pending",
      action_kind: "executor.remote.awaiting_effect_evidence",
      outcome: "awaiting_effect_evidence",
      mode: "enforce",
      entry_hash: "hash-4",
    },
    {
      ...actionIdentity,
      seq: 5,
      recorded_at: "2026-09-14T02:00:05Z",
      stage: "verify",
      decision: "done",
      reason: "authoritative state matched",
      action_kind: "effect_observation.recorded",
      outcome: "observation_recorded",
      mode: "enforce",
      entry_hash: "hash-5",
    },
    {
      ...actionIdentity,
      seq: 6,
      recorded_at: "2026-09-14T02:00:06Z",
      stage: "audit",
      decision: "done",
      reason: "recovery receipt recorded",
      action_kind: "t2.proposer.route.rolled_back",
      outcome: "rollback_succeeded",
      mode: "enforce",
      entry_hash: "hash-6",
    },
  ],
  terminal_stage: "audit",
} as const;

async function installFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          surface: "read-data-sources",
          sources: [
            {
              key: "audit",
              source: "browser-test-fixture",
              routes: ["/audit"],
              availability: "available",
              configured: true,
              reachable: true,
              authoritative: true,
              durable: true,
              synthetic: true,
              reason: null,
            },
          ],
        }),
      });
      return;
    }
    if (path === `/audit/${correlationId}/trace`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(trace) });
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: `unmocked browser-test route: ${path}` }),
    });
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources", handle);
  await page.route("**/audit/**", handle);
}

async function assertLifecycle(
  page: Page,
  labels: readonly string[],
  screenshotPath: string,
): Promise<void> {
  const [heading, ...stageLabels] = labels;
  if (heading === undefined) throw new Error("lifecycle labels are required");
  await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  const lifecycleGroup = page.locator(".trace-action-lifecycle-group").first();
  await expect(lifecycleGroup).toContainText(actionIdentity.action_id);
  await expect(lifecycleGroup).toContainText(/Attempt 1|시도 1/);
  const lifecycle = page.locator(".trace-action-lifecycle");
  await expect(lifecycle.locator("li")).toHaveCount(6);
  for (const label of stageLabels) await expect(lifecycle).toContainText(label);
  await expect(lifecycle).toContainText("effect_observation.recorded");
  for (const selector of ["html", "main", ".trace-action-lifecycle"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(
      dimensions.scrollWidth,
      `${selector} overflowed: ${dimensions.scrollWidth} > ${dimensions.clientWidth}`,
    ).toBeLessThanOrEqual(dimensions.clientWidth);
  }
  await lifecycleGroup.screenshot({ path: screenshotPath });
}

test.describe.configure({ mode: "serial" });

test("shows the correlated action lifecycle at desktop width", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page);

  await page.goto(`/trace?correlation=${correlationId}`);

  await assertLifecycle(page, [
    "Action lifecycle evidence",
    "Proposal",
    "Decision",
    "Approval",
    "Dispatch",
    "Observation",
    "Recovery",
  ], testInfo.outputPath("trace-lifecycle-desktop.png"));
});

test("reflows the correlated action lifecycle at mobile width", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium");
  await page.setViewportSize({ width: 390, height: 844 });
  await installFixture(page);

  await page.goto(`/trace?correlation=${correlationId}&locale=ko`);

  await assertLifecycle(page, [
    "액션 수명 주기 근거",
    "제안",
    "판단",
    "승인",
    "전달",
    "관측",
    "복구",
  ], testInfo.outputPath("trace-lifecycle-mobile-ko.png"));
});
