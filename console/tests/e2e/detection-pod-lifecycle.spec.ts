import { expect, test, type Page, type Route } from "@playwright/test";

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const lifecycle: unknown = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../src/routes/fixtures/detection-lifecycle-projection.json", import.meta.url)),
    "utf-8",
  ),
);

const noPublications = {
  published: 0,
  published_receipt_unrecorded: 0,
  duplicate_suppressed: 0,
  reconciled_duplicate: 0,
  publish_uncertain: 0,
  awaiting_reconciliation: 0,
  failed: 0,
};

const readiness = {
  source: "muninn-state-snapshot",
  observed_at: "2026-08-31T12:00:00Z",
  target_count: 0,
  counts: { ready: 0, partial: 0, blocked: 0, stale: 0, unauthorized: 0, unknown: 0 },
  targets: [],
  analyzer_coverage: {
    schema_version: "1.1.0",
    status: "available",
    unavailable_reason: null,
    source: "postgresql:state_kv:analyzer-tick-receipt",
    recorded_at: "2026-08-31T12:00:00Z",
    run_attempt_id: "pod-lifecycle-browser-test",
    candidate_count: 1,
    selected_count: 1,
    evaluated_count: 1,
    held_count: 0,
    finding_count: 0,
    unsupported_count: 0,
    error_count: 0,
    unattributed_error_count: 0,
    unattributed_error_codes: [],
    publication_counts: noPublications,
    resource_types: [{
      resource_type: "kubernetes-cluster",
      candidate_count: 1,
      selected_count: 1,
      evaluated_count: 1,
      held_count: 0,
      held_reason_counts: {},
      finding_count: 0,
      unsupported_count: 0,
      error_count: 0,
      error_codes: [],
      publication_counts: noPublications,
    }],
    resources: [{
      resource_ref: "cluster-a",
      resource_type: "kubernetes-cluster",
      resource_kind: "aks_cluster",
      evaluation_state: "evaluated_no_finding",
      finding_count: 0,
      unsupported_count: 0,
      error_count: 0,
      error_codes: [],
      publication_counts: noPublications,
    }],
    cause_claim_supported: false,
    execution_authority: false,
  },
  lifecycle: {
    source: "postgresql:state_kv:analyzer-finding-receipt",
    observed_at: "2026-08-31T12:00:00Z",
    retained_from: null,
    receipt_count: 0,
    receipt_limit: 500,
    target_count: 0,
    assessment_count: 0,
    evidence_counts: { complete: 0, incomplete: 0, conflicting: 0, missed: 0 },
    targets: [],
  },
  pod_lifecycle: lifecycle,
};

async function installFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path !== "/detection-coverage" && path !== "/detection-readiness") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(readiness),
    });
  };
  await page.route("**/api/**", handle);
  await page.route(
    (url) => ["/detection-coverage", "/detection-readiness"].includes(url.pathname),
    handle,
  );
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    return { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth };
  });
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
}

test.describe("Pod failure and recovery projection", () => {
  test("separates current state, history, recovery, and gaps", async ({ page }) => {
    await installFixture(page);
    await page.goto("/detection-coverage");

    await page.getByRole("tab", { name: "Resources" }).click();
    const section = page.getByRole("region", {
      name: "Show current-scope Kubernetes Pod evidence",
    });
    await expect(section).toBeVisible();
    await expect(section.locator("details")).not.toHaveAttribute("open", "");
    await section.getByText("Show current-scope Kubernetes Pod evidence").click();
    await expect(
      section.getByText(
        "not inferred as an exact association",
        { exact: false },
      ),
    ).toBeVisible();

    await expect(section.getByRole("link", { name: /Failing now/ })).toContainText("0");
    await expect(section.getByRole("link", { name: /Recovery verified/ })).toContainText("2");
    await expect(section.getByRole("link", { name: /Retained failures/ })).toContainText("3");
    await expect(section.getByRole("link", { name: /Targets with evidence gaps/ })).toContainText("1");

    const detail = section.locator("#pod-detection-lifecycle-detail");
    await expect(detail.getByText("Failure history")).toBeVisible();
    await expect(detail.getByRole("cell", { name: "container_restart" })).toBeVisible();
    await expect(detail.getByRole("cell", { name: "restart_observed_recovered" })).toBeVisible();
    await expect(detail.getByText("No evidence gap is recorded for this target.")).toBeVisible();

    await section.getByRole("button").filter({ hasText: "cluster-a/default/reports" }).click();
    await expect(detail.getByText("Incomplete evidence")).toBeVisible();
    await expect(detail.getByText("Not independently verified")).toBeVisible();
    await expect(detail.getByText("restart_history_restart_history_retention_gap")).toBeVisible();
  });

  test("stays within the viewport at desktop and laptop widths", async ({ page }) => {
    await installFixture(page);
    for (const size of [
      { width: 1440, height: 900 },
      { width: 993, height: 641 },
    ]) {
      await page.setViewportSize(size);
      await page.goto("/detection-coverage");
      await page.getByRole("tab", { name: "Resources" }).click();
      const section = page.getByRole("region", {
        name: "Show current-scope Kubernetes Pod evidence",
      });
      await expect(section).toBeVisible();
      await section.getByText("Show current-scope Kubernetes Pod evidence").click();
      await expectNoHorizontalOverflow(page);
    }
  });

  test("keeps target selection reachable and tappable on a phone", async ({ page }) => {
    await installFixture(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/detection-coverage");

    await page.getByRole("tab", { name: "Resources" }).click();
    const section = page.getByRole("region", {
      name: "Show current-scope Kubernetes Pod evidence",
    });
    await expect(section).toBeVisible();
    await section.getByText("Show current-scope Kubernetes Pod evidence").click();
    await expectNoHorizontalOverflow(page);
    const listWidth = await section.locator(".detection-record-list ul").evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(listWidth.scrollWidth).toBeLessThanOrEqual(listWidth.clientWidth);

    const target = section.getByRole("button").first();
    const box = await target.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(44);

    await target.focus();
    await page.keyboard.press("Enter");
    await expect(section.getByText("Failure history").first()).toBeVisible();
  });

  test("reflows without page or workspace overflow at 320px", async ({ page }) => {
    await installFixture(page);
    await page.setViewportSize({ width: 320, height: 844 });
    await page.goto("/detection-coverage#pod-detection-lifecycle");

    const section = page.getByRole("region", {
      name: "Show current-scope Kubernetes Pod evidence",
    });
    await expect(section).toBeVisible();
    await section.getByText("Show current-scope Kubernetes Pod evidence").click();
    await expectNoHorizontalOverflow(page);
    const workspace = await section.locator(".detection-record-workspace").evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(workspace.scrollWidth).toBeLessThanOrEqual(workspace.clientWidth);
  });
});
