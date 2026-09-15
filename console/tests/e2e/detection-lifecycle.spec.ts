import { expect, test, type Page, type Route } from "@playwright/test";

const lifecycleAssessment = {
  idempotency_key: "analyzer:cluster/example/pod/orders:pod_replacement:1",
  resource_ref: "cluster/example/pod/orders-with-a-very-long-immutable-identity-segment",
  resource_kind: "kubernetes_pod",
  signal: "pod_replacement",
  occurred_at: "2026-08-31T06:59:50Z",
  recorded_at: "2026-08-31T07:00:00Z",
  current_state: "running",
  detection_latency_seconds: 10,
  evidence_complete: true,
  evidence_state: "complete",
  publication: {
    current: "duplicate_suppressed",
    attempts: ["published", "duplicate_suppressed"],
    duplicate_observed: true,
  },
  recovery_state: "verified",
  evidence_refs: [
    "kubernetes:pod/old/uid/very-long-retained-evidence-reference",
    "kubernetes:pod/new/uid/very-long-current-evidence-reference",
  ],
  cause_claim_supported: false,
  execution_authority: false,
} as const;

const noPublications = {
  published: 0,
  published_receipt_unrecorded: 0,
  duplicate_suppressed: 0,
  reconciled_duplicate: 0,
  publish_uncertain: 0,
  awaiting_reconciliation: 0,
  failed: 0,
} as const;

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "detection-readiness",
          source: "browser-test-fixture",
          routes: ["/detection-coverage", "/detection-readiness"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: true,
          synthetic: true,
          reason: null,
        }],
      });
      return;
    }
    if (path === "/detection-coverage" || path === "/detection-readiness") {
      await json(route, {
        source: "postgresql:state_kv:detection-readiness",
        observed_at: "2026-08-31T07:00:00Z",
        target_count: 0,
        counts: { ready: 0, partial: 0, blocked: 0, stale: 0, unauthorized: 0, unknown: 0 },
        targets: [],
        analyzer_coverage: {
          schema_version: "1.1.0",
          status: "available",
          unavailable_reason: null,
          source: "postgresql:state_kv:analyzer-tick-receipt",
          recorded_at: "2026-08-31T07:00:00Z",
          run_attempt_id: "browser-test-attempt",
          candidate_count: 3,
          selected_count: 3,
          evaluated_count: 2,
          held_count: 0,
          finding_count: 1,
          unsupported_count: 0,
          error_count: 1,
          unattributed_error_count: 0,
          unattributed_error_codes: [],
          publication_counts: {
            ...noPublications,
            duplicate_suppressed: 1,
          },
          resource_types: [
            {
              resource_type: "api-gateway",
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
            },
            {
              resource_type: "kubernetes-cluster",
              candidate_count: 1,
              selected_count: 1,
              evaluated_count: 1,
              held_count: 0,
              held_reason_counts: {},
              finding_count: 1,
              unsupported_count: 0,
              error_count: 0,
              error_codes: [],
              publication_counts: {
                ...noPublications,
                duplicate_suppressed: 1,
              },
            },
            {
              resource_type: "mysql-server",
              candidate_count: 1,
              selected_count: 1,
              evaluated_count: 0,
              held_count: 0,
              held_reason_counts: {},
              finding_count: 0,
              unsupported_count: 0,
              error_count: 1,
              error_codes: ["analyzer_timeout"],
              publication_counts: noPublications,
            },
          ],
          resources: [
            {
              resource_ref: "resource/api",
              resource_type: "api-gateway",
              resource_kind: "api_management",
              evaluation_state: "evaluated_no_finding",
              finding_count: 0,
              unsupported_count: 0,
              error_count: 0,
              error_codes: [],
              publication_counts: noPublications,
            },
            {
              resource_ref: lifecycleAssessment.resource_ref,
              resource_type: "kubernetes-cluster",
              resource_kind: "aks_cluster",
              evaluation_state: "finding",
              finding_count: 1,
              unsupported_count: 0,
              error_count: 0,
              error_codes: [],
              publication_counts: {
                ...noPublications,
                duplicate_suppressed: 1,
              },
            },
            {
              resource_ref: "resource/mysql",
              resource_type: "mysql-server",
              resource_kind: "mysql_flexible_server",
              evaluation_state: "evaluation_error",
              finding_count: 0,
              unsupported_count: 0,
              error_count: 1,
              error_codes: ["analyzer_timeout"],
              publication_counts: noPublications,
            },
          ],
          cause_claim_supported: false,
          execution_authority: false,
        },
        analyzer_run: {
          source: "postgresql:state_kv:analyzer-tick-receipt",
          recorded_at: "2026-08-31T06:55:00Z",
          targets: 22,
          findings: 0,
          published: 0,
          duplicates_suppressed: 0,
          uncertain: 0,
          configured_targets: 0,
          discovered_targets: 22,
          candidate_count: 35,
          inventory_consulted: true,
          source_complete: true,
          truncated: false,
          skipped_reasons: ["unverified_state_fact"],
          skipped_reason_counts: { unverified_state_fact: 13 },
          unsupported_target_count: 0,
          analyzer_error_count: 0,
          publish_error_count: 0,
          receipt_error_count: 0,
          scheduling: "local_loop",
          metric_access: "available",
          event_publication: "unverified",
          execution_authority: false,
        },
        lifecycle: {
          source: "postgresql:state_kv:analyzer-finding-receipt",
          observed_at: "2026-08-31T07:00:00Z",
          retained_from: "2026-08-31T06:45:05Z",
          receipt_count: 5,
          receipt_limit: 500,
          target_count: 3,
          assessment_count: 5,
          evidence_counts: { complete: 2, incomplete: 1, conflicting: 1, missed: 1 },
          targets: [
            {
              resource_ref: lifecycleAssessment.resource_ref,
              current: lifecycleAssessment,
              history: [
                {
                  ...lifecycleAssessment,
                  idempotency_key: "analyzer:orders:container_restart:0",
                  signal: "container_restart",
                  occurred_at: "2026-08-31T06:50:00Z",
                  recorded_at: "2026-08-31T06:50:07Z",
                  current_state: "failed",
                  publication: {
                    current: "published",
                    attempts: ["published"],
                    duplicate_observed: false,
                  },
                  recovery_state: "open",
                },
                {
                  ...lifecycleAssessment,
                  idempotency_key: "analyzer:orders:insufficient_evidence:0",
                  signal: "insufficient_evidence",
                  occurred_at: "2026-08-31T06:45:00Z",
                  recorded_at: "2026-08-31T06:45:05Z",
                  current_state: "unknown",
                  evidence_complete: false,
                  evidence_state: "missed",
                  publication: {
                    current: "published",
                    attempts: ["published"],
                    duplicate_observed: false,
                  },
                  recovery_state: "unknown",
                },
              ],
            },
            {
              resource_ref: "cluster/example/pod/conflicting",
              current: {
                ...lifecycleAssessment,
                idempotency_key: "analyzer:conflicting",
                resource_ref: "cluster/example/pod/conflicting",
                signal: "conflicting_evidence",
                evidence_complete: false,
                evidence_state: "conflicting",
                recovery_state: "unknown",
              },
              history: [],
            },
            {
              resource_ref: "resource/api/incomplete",
              current: {
                ...lifecycleAssessment,
                idempotency_key: "analyzer:incomplete",
                resource_ref: "resource/api/incomplete",
                resource_kind: "api_management",
                signal: "insufficient_evidence",
                current_state: "degraded",
                evidence_complete: false,
                evidence_state: "incomplete",
                recovery_state: "unknown",
              },
              history: [],
            },
          ],
        },
      });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${path}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources", handle);
  await page.route(
    (url) => ["/detection-coverage", "/detection-readiness"].includes(url.pathname),
    handle,
  );
}

async function expectNoHorizontalOverflow(page: Page, selectors: string[]): Promise<void> {
  for (const selector of selectors) {
    const dimensions = await page.locator(selector).first().evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(
      dimensions.scrollWidth,
      `${selector} overflowed: ${dimensions.scrollWidth} > ${dimensions.clientWidth}`,
    ).toBeLessThanOrEqual(dimensions.clientWidth);
  }
}

async function openFindings(page: Page): Promise<ReturnType<Page["getByRole"]>> {
  await page.getByRole("tab", { name: "Findings" }).click();
  await expect(page.locator("#detection-readiness-panel-coverage")).toHaveCSS("display", "none");
  const region = page.getByRole("region", { name: "Retained findings and delivery" });
  await expect(region).toBeVisible();
  return region;
}

test.describe.configure({ mode: "serial" });

test("renders the coverage funnel, comparison, and drill-down at desktop width", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page);
  await page.goto("/detection-coverage");

  await expect(page.getByRole("tab", { name: "Coverage" })).toHaveAttribute("aria-selected", "true");
  const coverage = page.getByRole("region", { name: "Coverage by resource type" });
  await expect(coverage).toContainText("API gateway");
  await expect(coverage).toContainText("Kubernetes cluster");
  await expect(coverage).toContainText("MySQL server");
  await expect(coverage.locator(".coverage-type-table tbody tr")).toHaveCount(3);
  await expect(page.getByRole("link", { name: /Candidate resources/ })).toContainText("3");
  await expect(page.getByRole("link", { name: /Evaluated resources/ })).toContainText("2");
  await expect(page.getByRole("link", { name: /Findings/ })).toContainText("1");
  await expect(page.getByRole("region", { name: "Attempt comparison" }))
    .toContainText("22");
  await expect(page.getByRole("region", { name: "Attempt comparison" }))
    .toContainText("5 minutes older");
  const provenance = page.locator(".detection-technical-details").first();
  await expect(provenance).not.toHaveAttribute("open", "");
  await provenance.locator("summary").click();
  await expect(provenance)
    .toContainText("postgresql:state_kv:analyzer-tick-receipt");
  await expect(page.locator(".details-list").first()).toHaveCSS("display", "flex");

  await page.evaluate(() => {
    (window as Window & { __coverageNavigationMarker?: string })
      .__coverageNavigationMarker = "preserved";
  });
  await page.getByRole("link", { name: /Selected resources/ }).click();
  await expect(page.getByRole("tab", { name: "Resources" }))
    .toHaveAttribute("aria-selected", "true");
  expect(await page.evaluate(() =>
    (window as Window & { __coverageNavigationMarker?: string })
      .__coverageNavigationMarker,
  )).toBe("preserved");
  await page.getByRole("tab", { name: "Coverage" }).click();

  await coverage.getByRole("button", {
    name: /Open filtered resources for MySQL server/,
  }).click();
  await expect(page.getByRole("tab", { name: "Resources" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/type=mysql-server/);
  await expect(page).toHaveURL(/resource=resource%2Fmysql/);
  const resourceDetail = page.locator("#detection-resource-detail");
  await expect(resourceDetail).toContainText("Analyzer timed out");
  await expect(resourceDetail).toContainText("resource/mysql");
  await expect(
    page.locator("#detection-readiness-panel-resources")
      .getByRole("status")
      .filter({ hasText: "Selected resource changed to resource/mysql." }),
  ).toHaveCount(1);
  const resourceSearch = page.getByLabel("Search resources", { exact: true });
  await resourceSearch.click();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(resourceSearch).toBeFocused();
  await expect(resourceSearch).toHaveCSS("outline-width", "2px");

  await expectNoHorizontalOverflow(page, [
    "html",
    "main",
    "#detection-readiness-panel-resources",
  ]);
});

test("restores resource URL state and updates search, filters, and sort", async ({ page }) => {
  await page.setViewportSize({ width: 993, height: 641 });
  await installFixture(page);
  await page.goto(
    "/detection-coverage?q=mysql&type=mysql-server&state=evaluation_error&sort=attention&resource=resource%2Fmysql#detection-resources",
  );

  const panel = page.locator("#detection-readiness-panel-resources");
  await expect(page.getByRole("tab", { name: "Resources" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByLabel("Search resources", { exact: true })).toHaveValue("mysql");
  await expect(panel.getByLabel("Resource type", { exact: true })).toHaveValue("mysql-server");
  await expect(panel.getByLabel("Evaluation state", { exact: true })).toHaveValue("evaluation_error");
  await expect(panel.getByLabel("Sort resources", { exact: true })).toHaveValue("attention");
  await expect(panel.locator(".detection-record-list button")).toHaveCount(1);
  await expect(panel.locator("#detection-resource-detail")).toContainText("resource/mysql");

  await page.getByRole("tab", { name: "Coverage" }).click();
  await page.getByRole("link", { name: /Selected resources/ }).click();
  await expect(page).toHaveURL(/q=mysql/);
  await expect(page).toHaveURL(/type=mysql-server/);
  await expect(page).toHaveURL(/state=evaluation_error/);
  await expect(page).toHaveURL(/resource=resource%2Fmysql/);

  await panel.getByLabel("Search resources", { exact: true }).fill("does-not-exist");
  await expect(panel.getByText("No matching resources")).toBeVisible();
  await expect(page).toHaveURL(/q=does-not-exist/);
  await panel.getByRole("button", { name: "Clear filters" }).click();
  await expect(panel.getByLabel("Search resources", { exact: true })).toHaveValue("");
  await expect(panel.locator(".detection-record-list button")).toHaveCount(3);
  await page.goBack();
  await expect(panel.getByLabel("Search resources", { exact: true }))
    .toHaveValue("does-not-exist");
  await page.goForward();
  await expect(panel.getByLabel("Search resources", { exact: true })).toHaveValue("");
  await page.reload();
  await expect(panel.locator("#detection-resource-detail")).toContainText("resource/mysql");
  await expectNoHorizontalOverflow(page, ["html", "main", ".detection-record-workspace"]);
});

test("filters retained findings and uses generic semantics for non-Pod resources", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page);
  await page.goto("/detection-coverage");

  const region = await openFindings(page);
  const targets = region.locator(".detection-record-list button");
  const detail = region.locator("#detection-lifecycle-detail");
  await expect(targets).toHaveCount(3);
  await expect(region).toContainText("5 retained receipts (limit 500)");
  await expect(region).toContainText("Oldest retained receipt");
  await expect(detail).toContainText("Latest recorded state");
  await expect(detail).toContainText("Duplicate suppressed");

  await targets.filter({ hasText: "cluster/example/pod/conflicting" }).click();
  await expect(detail).toContainText("Evidence conflicting");
  await targets.filter({ hasText: "resource/api/incomplete" }).click();
  await expect(detail).toContainText("Evidence incomplete");
  await expect(detail).not.toContainText("Recovery state");
  await targets.first().click();
  await expect(region).toContainText("no cause claim or execution authority");

  const history = region.getByText("Earlier retained assessments (2)");
  await history.click();
  await expect(detail).toContainText("container_restart");
  await expect(detail).toContainText("Evidence missed");
  await expect(detail).toContainText("Recovery not verified");

  await region.getByLabel("Search findings").fill("conflicting");
  await expect(targets).toHaveCount(1);
  await region.getByLabel("Evidence state").selectOption("incomplete");
  await expect(region.getByText("No matching retained findings")).toBeVisible();
  await region.getByRole("button", { name: "Clear filters" }).click();
  await region.getByLabel("From date").fill("2026-08-31");
  await region.getByLabel("To date").fill("2026-08-31");
  await expect(targets).toHaveCount(3);
  await region.getByLabel("From date").fill("2026-09-01");
  await expect(region.getByText("No matching retained findings")).toBeVisible();
  await expectNoHorizontalOverflow(page, ["html", "main", ".detection-lifecycle"]);
});

test("keeps core coverage visible, sticky, and card-based on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installFixture(page);
  await page.goto("/detection-coverage");

  const coverage = page.getByRole("region", { name: "Coverage by resource type" });
  const firstFunnelItem = page.getByRole("link", { name: /Candidate resources/ });
  const firstBox = await firstFunnelItem.boundingBox();
  expect(firstBox).not.toBeNull();
  expect(firstBox!.y).toBeLessThan(844);
  await expect(coverage.locator(".coverage-type-cards")).toBeVisible();
  await expect(coverage.locator(".coverage-type-table")).toBeHidden();
  const exact = coverage.locator(".coverage-exact-table");
  await expect(exact).toBeVisible();
  await expect(exact).not.toHaveAttribute("open", "");

  const main = page.locator("main");
  await main.evaluate((element) => { element.scrollTop = 520; });
  const [mainBox, tabBox] = await Promise.all([
    main.boundingBox(),
    page.locator(".detection-readiness-tabs").boundingBox(),
  ]);
  expect(mainBox).not.toBeNull();
  expect(tabBox).not.toBeNull();
  expect(Math.abs(tabBox!.y - mainBox!.y)).toBeLessThanOrEqual(25);
  await expect(page.getByRole("tab", { name: "Coverage" })).toHaveCSS("min-height", "44px");
  await expectNoHorizontalOverflow(page, [
    "html",
    "main",
    ".detection-readiness-route",
    ".detection-readiness-tabs",
    "#detection-readiness-panel-coverage",
    ".details-list",
  ]);
});

test("keeps collapsed scopes, restored selection, and zero overflow at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/detection-coverage?data=sample");

  const coverageTab = page.getByRole("tab", { name: "Coverage" });
  const resourcesTab = page.getByRole("tab", { name: "Resources" });
  await coverageTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(resourcesTab).toBeFocused();
  await expect(resourcesTab).toHaveAttribute("aria-selected", "true");
  const resources = page.locator("#detection-readiness-panel-resources");
  await expect(resources.locator(".detection-record-list button")).toHaveCount(5);
  await resources.locator(".detection-record-list button")
    .filter({ hasText: "example-kubernetes-cluster" }).click();
  await expect(resources.locator(".detection-resource-extension"))
    .not.toHaveAttribute("open", "");
  const podLifecycle = resources.getByRole("region", {
    name: "Show current-scope Kubernetes Pod evidence",
  });
  await expect(podLifecycle.locator("details")).not.toHaveAttribute("open", "");
  await page.reload();
  await expect(resources.locator("#detection-resource-detail"))
    .toContainText("example-kubernetes-cluster");
  await expectNoHorizontalOverflow(page, [
    "html",
    "main",
    ".detection-readiness-route",
    ".detection-record-workspace",
  ]);
});
