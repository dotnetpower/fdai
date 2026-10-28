import { expect, test, type Page, type Route } from "@playwright/test";

function action(name: string, category: string, hilTiers: readonly string[], description: string) {
  return {
    name,
    operation: "apply",
    category,
    rollback_contract: "state_forward_only",
    irreversible: false,
    default_mode: "shadow",
    execution_path: "direct_api",
    env_scope: "any",
    hil_tiers: hilTiers,
    description,
  };
}

const PALETTE = [
  action("ops.tune-alert-evaluation", "ops", ["T0", "T1", "T2"], "Propose one approved alert evaluation change."),
  action("tool.request-release", "tool", ["T2"], "Open a deployment pull request for an environment."),
  action("remediate.right-size", "remediation", [], "Right-size an over-provisioned resource."),
  action("ops.publish-change-summary", "ops", [], "Post a change summary to the operator channel."),
];

function workflow(name: string, description: string, trigger: Record<string, string>, steps: Record<string, unknown>[]) {
  return {
    schema_version: "1.0.0",
    name,
    version: "1.0.0",
    description,
    trigger,
    default_mode: "shadow",
    promotion_gate: { min_shadow_days: 14, min_samples: 30, min_accuracy: 0.98, max_policy_escapes: 0 },
    steps,
    step_count: steps.length,
    yaml: `name: ${name}\n`,
  };
}

const CATALOG = [
  workflow("alert-evaluation-change", "Approve, then tune one alert evaluation plan.", {
    kind: "signal",
    signal_type: "alert_noise.evaluation.proposed",
  }, [
    { id: "approve_plan", kind: "approval", approval_role: "owner", timeout_seconds: 3600, quorum: 1 },
    { id: "tune_evaluation", kind: "action", action_type_ref: "ops.tune-alert-evaluation" },
  ]),
  workflow("alert-routing-change", "Approve, then update one alert route.", {
    kind: "signal",
    signal_type: "alert_noise.routing.proposed",
  }, [
    { id: "approve_plan", kind: "approval", approval_role: "owner", timeout_seconds: 3600, quorum: 1 },
    { id: "update_routing", kind: "action", action_type_ref: "ops.publish-change-summary" },
  ]),
  workflow("architecture-review", "Parallel domain reviews, then a design decision.", {
    kind: "signal",
    signal_type: "architecture.review.requested",
  }, [
    { id: "domain_reviews", kind: "parallel", branches: ["security", "reliability", "cost"] },
    { id: "design_decision", kind: "decision", outcomes: ["approved", "conditional", "rejected"] },
  ]),
  workflow("dr-failover-drill", "Rehearse a failover on a schedule.", {
    kind: "schedule",
    schedule: "0 3 * * 0",
  }, [
    { id: "right_size", kind: "action", action_type_ref: "remediate.right-size", on_failure: "summary" },
    { id: "summary", kind: "action", action_type_ref: "ops.publish-change-summary" },
  ]),
];

const RUNS = {
  source: "operator",
  synthetic: false,
  durable: true,
  principal_scoped: true,
  items: [
    {
      id: "process-1",
      workflow_ref: "alert-evaluation-change",
      workflow_version: "1.0.0",
      status: "waiting",
      current_step: "approve_plan",
      target_resource_id: "example-alert-rule",
      updated_at: "2026-09-30T08:00:00Z",
      has_view: false,
    },
    {
      id: "process-2",
      workflow_ref: "alert-evaluation-change",
      workflow_version: "1.0.0",
      status: "succeeded",
      current_step: "",
      target_resource_id: "example-alert-rule-2",
      updated_at: "2026-09-29T08:00:00Z",
      has_view: false,
    },
  ],
};

async function installFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    if (path === "/workflows/action-types") return json({ action_types: PALETTE, count: PALETTE.length });
    if (path === "/workflows/catalog") return json({ workflows: CATALOG, count: CATALOG.length });
    if (path === "/workflows/definitions") {
      return json({
        groups: { built_in: [], shared: [], mine: [] },
        bindings: [],
        counts: { built_in: 0, shared: 0, mine: 0 },
      });
    }
    if (path === "/views/process") {
      const ref = url.searchParams.get("workflow_ref");
      return json({ ...RUNS, items: RUNS.items.filter((item) => item.workflow_ref === ref) });
    }
    if (path === "/workflows/validate") {
      return json({ valid: true, issues: [], yaml_preview: "schema_version: 1.0.0\nname: draft\n" });
    }
    return json({}, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/workflows/**", handle);
  await page.route("**/python-tasks/**", handle);
  await page.route("**/views/**", handle);
}

async function expectNoHorizontalOverflow(page: Page, selectors: readonly string[]): Promise<void> {
  for (const selector of selectors) {
    const dimensions = await page.locator(selector).first().evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth, selector).toBeLessThanOrEqual(dimensions.clientWidth);
  }
}

function viewportFor(projectName: string): { width: number; height: number } {
  if (process.env["FDAI_WORKFLOW_VIEWPORT"] === "constrained") return { width: 993, height: 641 };
  return projectName === "mobile-chromium" ? { width: 390, height: 844 } : { width: 1440, height: 900 };
}

test("reviews published workflows with truthful facts, filters, paths, and run history", async ({
  page,
}, testInfo) => {
  await page.setViewportSize(viewportFor(testInfo.project.name));
  await installFixture(page);
  await page.goto("/workflow-builder?workflow=alert-evaluation-change");

  const summary = page.getByRole("region", { name: "Selected workflow summary" });
  await expect(summary).toContainText("Approval steps");
  await expect(summary).toContainText("1 HIL-gated ActionTypes");
  await expect(summary).toContainText("Reviewed");
  await expect(page.locator(".workflow-header-meta")).toContainText("Selected workflow");
  await expect(page.locator(".workflow-header-meta")).toContainText("alert-evaluation-change@1.0.0");

  const runs = page.getByRole("region", { name: "Run history" });
  await expect(runs.getByRole("link", { name: "example-alert-rule", exact: true })).toHaveAttribute(
    "href",
    "/processes/process-1",
  );
  await expect(runs).toContainText("waiting");

  await page.getByRole("combobox", { name: "Step kind" }).selectOption("parallel");
  await expect(page.getByRole("button", { name: /architecture-review/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /dr-failover-drill/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Clear filters" }).click();
  await page.getByRole("combobox", { name: "ActionType category" }).selectOption("remediation");
  await expect(page.getByRole("button", { name: /dr-failover-drill/ })).toBeVisible();
  await page.getByRole("button", { name: /dr-failover-drill/ }).click();

  const chain = page.getByRole("list", { name: "Workflow steps from trigger to terminal state" });
  await expect(chain).toContainText("Every Sunday at 03:00 (UTC)");
  await expect(chain).toContainText("On failure: summary");
  await page.getByRole("button", { name: "Clear filters" }).click();
  await page.getByRole("button", { name: /architecture-review/ }).click();
  await expect(chain).toContainText("Branches: security, reliability, cost (all must complete)");
  await expect(chain).toContainText("Outcomes: approved, conditional, rejected");
  await expect(chain).toContainText("Parallel");

  // A step selected in one workflow must not leak into another workflow that
  // reuses the same step id; the new selection matches its deep link.
  await page.goto("/workflow-builder?workflow=alert-evaluation-change&step=approve_plan");
  await page.getByRole("button", { name: /alert-routing-change/ }).click();
  await expect(page.locator(".workflow-canvas-node.is-selected")).toContainText("update_routing");

  await page.goto("/workflow-builder?workflow=dr-failover-drill&step=right_size");
  await expect(page.getByRole("link", { name: "View promotion status" })).toHaveAttribute(
    "href",
    "/promotion-gates?q=remediate.right-size",
  );
  await expectNoHorizontalOverflow(page, ["html", ".workflow-builder-route", ".workflow-catalog-workspace"]);
});

test("copies a workflow into a URL-backed draft and searches the ActionType palette", async ({
  page,
}, testInfo) => {
  await page.setViewportSize(viewportFor(testInfo.project.name));
  await installFixture(page);
  await page.goto("/workflow-builder?workflow=dr-failover-drill");
  await page.getByRole("button", { name: "Copy to new draft" }).click();

  await expect(page).toHaveURL(/mode=new/);
  await expect(page).not.toHaveURL(/from=/);
  await expect(page.locator(".wf-chat-thread")).toContainText("dr-failover-drill-copy");
  await expect(page.locator(".workflow-header-meta")).toHaveCount(0);
  const visualization = page.getByRole("list", { name: "Workflow visualization" });
  await expect(visualization.getByText("Action", { exact: true }).first()).toBeVisible();
  await expect(visualization).not.toContainText("workflow.stepKind");

  await page.getByRole("button", { name: "Start a new draft" }).click();
  const picker = page.getByRole("region", { name: "Choose an ActionType" });
  await expect(picker).toBeVisible();
  await picker.getByRole("searchbox", { name: "Search ActionTypes" }).fill("change summary");
  await expect(picker).toContainText("Showing 1 of 1");
  await picker.getByRole("button", { name: /Publish change summary/ }).click();
  await expect(page.locator(".wf-msg-op .wf-msg-plain").last()).toHaveText("Publish change summary");
  await expect(page.locator(".wf-chat-thread")).toContainText("When should it run?");
  await expect(picker).toHaveCount(0);

  await page.goBack();
  await expect(page).not.toHaveURL(/mode=new/);
  await expect(page.getByRole("region", { name: "Selected workflow summary" })).toBeVisible();
  await expectNoHorizontalOverflow(page, ["html", ".workflow-builder-route"]);
});

test("renders the designer in Korean and keeps the mobile header readable", async ({
  page,
}, testInfo) => {
  await page.setViewportSize(viewportFor(testInfo.project.name));
  await installFixture(page);
  await page.goto("/workflow-builder?locale=ko&mode=new");
  await expect(page.locator(".wf-chat-thread")).toContainText("함께 워크플로를 설계해 보겠습니다");
  await expect(page.getByRole("region", { name: "ActionType 선택" })).toBeVisible();
  const title = await page.locator(".page-header-title").boundingBox();
  const route = await page.locator(".workflow-builder-route").boundingBox();
  expect(title?.width ?? 0).toBeGreaterThan((route?.width ?? 0) * 0.6);
  await expectNoHorizontalOverflow(page, ["html", ".workflow-builder-route", ".wf-chat"]);
});

test("shows truthful workflow app lifecycle and filters runs by status", async ({ page }, testInfo) => {
  await page.setViewportSize(viewportFor(testInfo.project.name));
  await page.goto("/workflow-apps/sample-incident-review?data=sample");
  await expect(page.getByRole("link", { name: "Open workflow definition" })).toHaveAttribute(
    "href",
    "/workflow-builder?workflow=incident-review",
  );
  const filter = page.getByRole("group", { name: "Filter runs by status" });
  await filter.getByRole("button", { name: /failed/ }).click();
  const rows = page.locator(".workflow-app-runs tbody tr");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("evidence-gate");
  await expectNoHorizontalOverflow(page, ["html"]);
});
