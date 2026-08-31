import { expect, test, type Page, type Route } from "@playwright/test";

const actionType = {
  name: "ops.restart-service",
  operation: "apply",
  category: "ops",
  rollback_contract: "scripted",
  irreversible: false,
  default_mode: "shadow",
  execution_path: "direct_api",
  env_scope: "any",
  hil_tiers: ["T0"],
  description: "Restart a service.",
};

const form = {
  name: "governed-review",
  version: "1.0.0",
  description: "Wait for evidence, then require independent approval.",
  triggerKind: "signal",
  signalType: "review.requested",
  schedule: "",
  minShadowDays: "14",
  minSamples: "100",
  minAccuracy: "0.95",
  maxPolicyEscapes: "0",
  antiScope: "Does not execute a managed-resource action.",
  steps: [
    {
      key: 0,
      id: "wait_for_evidence",
      kind: "wait",
      action_type_ref: "",
      guard_rule_ref: "",
      compensated_by: "",
      on_failure: "",
      params: {},
      wait_for: "evidence.updated",
      timeout_seconds: "3600",
      approval_role: "",
      quorum: "1",
      no_self_approval: true,
    },
    {
      key: 1,
      id: "human_approval",
      kind: "approval",
      action_type_ref: "",
      guard_rule_ref: "",
      compensated_by: "",
      on_failure: "",
      params: {},
      wait_for: "",
      timeout_seconds: "1800",
      approval_role: "approver",
      quorum: "2",
      no_self_approval: true,
    },
  ],
};

async function installFixture(page: Page): Promise<() => readonly Record<string, unknown>[]> {
  const validations: Record<string, unknown>[] = [];
  await page.addInitScript((savedForm) => {
    window.sessionStorage.setItem("fdai.workflow-builder.chat.v1", JSON.stringify({
      slots: {
        stage: "ready",
        form: savedForm,
        triggerConfirmed: true,
        actionsConfirmed: true,
        extraOffered: true,
        nameConfirmed: true,
        planConfirmed: true,
        safetyConfirmed: true,
        resourceHint: "",
        goalText: "Wait for evidence, then require independent approval.",
        warnings: [],
      },
      messages: [{
        id: 1,
        role: "bot",
        text: "The private draft is ready for structural validation.",
        preview: savedForm,
      }],
    }));
  }, form);
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/workflows/action-types") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ action_types: [actionType], count: 1 }),
      });
      return;
    }
    if (path === "/workflows/catalog") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ workflows: [], count: 0 }),
      });
      return;
    }
    if (path === "/workflows/definitions") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          groups: { built_in: [], shared: [], mine: [] },
          bindings: [],
          counts: { built_in: 0, shared: 0, mine: 0 },
        }),
      });
      return;
    }
    if (path === "/python-tasks/capabilities") {
      await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
      return;
    }
    if (path === "/workflows/validate") {
      validations.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          valid: true,
          issues: [],
          yaml_preview: "schema_version: 1.0.0\nname: governed-review\n",
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  };
  await page.route("**/api/**", handle);
  await page.route("**/workflows/**", handle);
  await page.route("**/python-tasks/**", handle);
  return () => validations;
}

test("authors and restores governed WAIT and APPROVAL steps accessibly", async ({
  page,
}, testInfo) => {
  const viewport = process.env["FDAI_WORKFLOW_VIEWPORT"] === "constrained"
    ? { width: 993, height: 641 }
    : testInfo.project.name === "mobile-chromium"
      ? { width: 390, height: 844 }
      : { width: 1440, height: 900 };
  await page.setViewportSize(viewport);
  const validations = await installFixture(page);

  await page.goto("/workflow-builder");
  await page.getByRole("button", { name: "Design a new workflow" }).click();

  await expect(page.getByText("Recovered this tab's workflow draft.")).toBeVisible();
  await expect(page.getByText("evidence.updated", { exact: true })).toBeVisible();
  await expect(page.getByText("approver", { exact: true })).toBeVisible();
  const visualization = page.getByRole("list", { name: "Workflow visualization" });
  await expect(visualization.getByText("Wait", { exact: true })).toBeVisible();
  await expect(visualization.getByText("Human approval", { exact: true })).toBeVisible();

  await page.getByText("Edit validated draft", { exact: true }).click();
  await page.getByLabel("Wait for event or evidence").fill("review.evidence.ready");
  await page.getByLabel("Minimum approval role").selectOption("owner");
  await page.getByLabel("Approval quorum").fill("3");
  await expect(page.getByText(
    "Disabling this draft field does not bypass runtime anti-self-approval.",
  )).toBeVisible();

  await expect.poll(() => validations().length).toBeGreaterThan(1);
  const latest = validations().at(-1);
  expect(latest?.["default_mode"]).toBe("shadow");
  expect(latest?.["steps"]).toEqual([
    {
      id: "wait_for_evidence",
      kind: "wait",
      wait_for: "review.evidence.ready",
      timeout_seconds: 3600,
    },
    {
      id: "human_approval",
      kind: "approval",
      approval_role: "owner",
      timeout_seconds: 1800,
      quorum: 3,
      no_self_approval: true,
    },
  ]);

  for (const selector of ["html", ".workflow-builder-route", ".wf-preview"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});
