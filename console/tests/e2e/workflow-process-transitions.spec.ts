import { expect, test, type Page, type Route } from "@playwright/test";

const processRecord = {
  id: "process-1",
  workflow_ref: "review-workflow",
  workflow_version: "1.0.0",
  status: "waiting",
  current_step: "wait_for_evidence",
  target_resource_id: "resource-1",
  started_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:01:00Z",
  correlation_id: "correlation-1",
  revision: 3,
  has_view: false,
};

function control(available: boolean) {
  if (!available) {
    return {
      schema_version: "1.0.0",
      authoritative: true,
      principal_scoped: true,
      available: false,
      process_revision: 3,
      reason: "Authoritative Workflow catalog projection is unavailable",
      step: null,
      permitted_transitions: [],
      acceptance_is_success: false,
    };
  }
  return {
    schema_version: "1.0.0",
    authoritative: true,
    principal_scoped: true,
    available: true,
    process_revision: 3,
    catalog_revision: "catalog-7",
    mode: "shadow",
    step: {
      id: "wait_for_evidence",
      kind: "wait",
      state: "waiting",
      attempt: 1,
      reason: "waiting_for:evidence.updated",
      requirements: {
        wait_for: "evidence.updated",
        timeout_seconds: 300,
        deadline_at: "2026-08-31T00:05:00Z",
      },
    },
    permitted_transitions: [
      {
        id: "resume",
        method: "POST",
        path: "/workflows/process-1/resume",
        expected_revision: 3,
        requires_confirmation: false,
        runtime_recheck: true,
      },
      {
        id: "cancel",
        method: "POST",
        path: "/workflows/process-1/cancel",
        expected_revision: 3,
        requires_confirmation: true,
        runtime_recheck: true,
      },
    ],
    acceptance_is_success: false,
  };
}

async function installFixture(page: Page, available = true): Promise<{
  denyNext: () => void;
  requestHeaders: () => Record<string, string> | null;
}> {
  let deny = false;
  let headers: Record<string, string> | null = null;
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/views/process") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          source: "postgresql:process_runtime",
          synthetic: false,
          durable: true,
          principal_scoped: true,
          items: [processRecord],
        }),
      });
      return;
    }
    if (path === "/views/process/process-1/events") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          process: processRecord,
          events: [{
            event_id: "event-1",
            kind: "step.waiting",
            recorded_at: "2026-08-31T00:01:00Z",
            correlation_id: "correlation-1",
            causation_id: null,
            step_id: "wait_for_evidence",
            attempt: 1,
            payload: {
              step_kind: "wait",
              reason: "waiting_for:evidence.updated",
            },
          }],
          count: 1,
          planning: null,
          investigation: null,
          control: control(available),
        }),
      });
      return;
    }
    if (path === "/workflows/process-1/resume") {
      headers = route.request().headers();
      await route.fulfill({
        status: deny ? 409 : 202,
        contentType: "application/json",
        body: JSON.stringify(deny
          ? { detail: "Process revision is stale; refresh before retrying" }
          : {
              accepted: true,
              proposal_id: "proposal-1",
              operation: "workflow.resume-request",
              duplicate: false,
            }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  };
  await page.route("**/api/**", handle);
  await page.route("**/views/process**", handle);
  await page.route("**/workflows/**", handle);
  return {
    denyNext: () => { deny = true; },
    requestHeaders: () => headers,
  };
}

test("renders authoritative Process state and never reports acceptance as success", async ({
  page,
}, testInfo) => {
  const viewport = process.env["FDAI_PROCESS_VIEWPORT"] === "constrained"
    ? { width: 993, height: 641 }
    : testInfo.project.name === "mobile-chromium"
      ? { width: 390, height: 844 }
      : { width: 1440, height: 900 };
  await page.setViewportSize(viewport);
  const fixture = await installFixture(page);
  await page.goto("/processes/process-1");

  await expect(page.getByRole("heading", { name: "Permitted next transitions" })).toBeVisible();
  await expect(page.getByText("evidence.updated", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Request resume" }).click();
  await expect(page.getByRole("status")).toContainText("Acceptance is not operational success");
  expect(fixture.requestHeaders()?.["if-match"]).toBe("3");
  expect(fixture.requestHeaders()?.["idempotency-key"]).toBe(
    "process:process-1:resume:revision:3",
  );

  fixture.denyNext();
  await page.getByRole("button", { name: "Request resume" }).click();
  await expect(page.getByRole("alert")).toContainText("Process revision is stale");

  for (const selector of ["html", ".process-route", ".process-control-panel"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});

test("denies every transition when authoritative control evidence is unavailable", async ({
  page,
}) => {
  await installFixture(page, false);
  await page.goto("/processes/process-1");

  await expect(page.getByText(
    "Authoritative Workflow catalog projection is unavailable",
  )).toBeVisible();
  await expect(page.getByRole("button", { name: /Request (resume|cancellation|retry)/ })).toHaveCount(0);
});
