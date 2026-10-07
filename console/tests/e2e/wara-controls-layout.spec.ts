import { expect, test, type Page, type Route } from "@playwright/test";

function recommendation(index: number): Record<string, unknown> {
  const id = `${index.toString(16).padStart(8, "0")}-aeab-46ef-80bd-9bd4479412ec`;
  return {
    id,
    title: index === 0
      ? "Enable Azure backup for FSLogix storage account file shares with a deliberately long advisory title"
      : `Configure user nodepool count ${index}`,
    recommendation_control: "HighAvailability",
    impact: index % 2 === 0 ? "High" : "Medium",
    resource_type: index === 0
      ? "Microsoft.NetApp/netAppAccounts/capacityPools/volumes"
      : "Microsoft.ContainerService/managedClusters",
    lifecycle: "active",
    product_group_verified: true,
    automation_available: index % 2 === 1,
    mapping_disposition: index % 2 === 0 ? "manual_evidence" : "ambiguous_or_blocked",
    mapping_state: "unmapped",
    applicability: "unknown",
    evaluation_status: "not_evaluated",
    satisfaction: "unknown",
    evaluation_scope: null,
    evaluated_at: null,
    evidence_complete: false,
    evidence_refs: [],
    evidence_digests: [],
    source_url: "https://example.test/aprl/recommendations.yaml",
    source_revision: "catalog-revision",
    source_version: "2026-08-24",
    retrieved_at: "2026-08-31T00:00:00Z",
    source_path: "azure-resources/example/recommendations.yaml",
    source_digest: `sha256:${"a".repeat(64)}`,
    source_license: "MIT",
    learn_more_name: null,
    learn_more_url: null,
    query_digest: null,
    evaluator_ref: null,
    manual_evidence: null,
    workload_tags: [],
    limitations: ["manual_evidence_required"],
    execution_authority: false,
  };
}

async function installWaraFixture(page: Page): Promise<void> {
  const controls = Array.from({ length: 6 }, (_, index) => recommendation(index));
  await page.route(/^https?:\/\/[^/]+(?:\/api)?\/(?:rules|wara-controls|incidents)(?:[/?]|$)/, async (route: Route) => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/wara-controls") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total: 456,
          filtered_total: controls.length,
          offset: 0,
          limit: 50,
          facets: {
            by_resource_type: { "Microsoft.ContainerService/managedClusters": 5 },
            by_satisfaction: { unknown: 456 },
          },
          controls,
          inventory: {
            active_recommendations: 393,
            disabled_recommendations: 63,
            resource_types: 80,
            automated_recommendations: 143,
            manual_recommendations: 250,
          },
          evaluation_source: "not_connected",
          source_revision: "catalog-revision",
          crosswalk_digest: `sha256:${"b".repeat(64)}`,
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{\"detail\":\"unmocked\"}" });
  });
}

async function expectBoundedWaraLayout(page: Page): Promise<void> {
  const table = page.locator(".wara-controls-view .data-table");
  await expect(table.getByRole("columnheader")).toHaveText([
    "Recommendation",
    "Advisory impact",
    "Mapping",
    "Evaluation",
    "Satisfaction",
  ]);
  const geometry = await page.locator(".wara-controls-view").evaluate((view) => {
    const headers = [...view.querySelectorAll(".data-table thead th")].map(
      (element) => element.getBoundingClientRect().width,
    );
    const firstRow = view.querySelector(".data-table tbody tr");
    const code = firstRow?.querySelector(".wara-recommendation-identity code")?.getBoundingClientRect();
    const title = firstRow?.querySelector(".wara-recommendation-title")?.getBoundingClientRect();
    const grid = view.querySelector(".kpi-grid")?.getBoundingClientRect();
    const cards = [...view.querySelectorAll(".kpi-grid .kpi-card")].map((element) => element.getBoundingClientRect());
    return {
      headers,
      identityStacked: code !== undefined && title !== undefined && code.top >= title.bottom - 1,
      cardsFillRow: grid !== undefined && cards.length === 4
        && Math.abs((cards[3]?.right ?? 0) - grid.right) <= 2,
    };
  });
  expect(Math.min(...geometry.headers)).toBeGreaterThanOrEqual(96);
  expect(geometry.identityStacked).toBe(true);
  expect(geometry.cardsFillRow).toBe(true);
  for (const selector of ["html", ".rules-route", ".wara-controls-view .data-table-wrap"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
}

test("keeps WARA recommendation columns readable on desktop and mobile", async ({ page }) => {
  await installWaraFixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/rules?view=controls&framework=azure-wara");
  await expect(page.getByText("Showing 1-6 of 6 filtered (456 total)")).toBeVisible();
  await expectBoundedWaraLayout(page);

  await page.setViewportSize({ width: 993, height: 641 });
  await expectBoundedWaraLayout(page);

  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = await page.locator(".wara-controls-view").evaluate((view) => {
    const wrap = view.querySelector(".data-table-wrap") as HTMLElement;
    const visible = [...view.querySelectorAll(".data-table thead th")]
      .map((element) => element.getBoundingClientRect().width)
      .filter((width) => width > 0);
    return { scrollWidth: wrap.scrollWidth, clientWidth: wrap.clientWidth, visible };
  });
  // Title and satisfaction stay readable without horizontal scrolling on a phone.
  expect(mobile.scrollWidth).toBeLessThanOrEqual(mobile.clientWidth);
  expect(mobile.visible).toHaveLength(2);
  expect(mobile.visible[0]).toBeGreaterThan(mobile.visible[1] ?? 0);
  expect(mobile.visible[1]).toBeGreaterThanOrEqual(90);
});
