import { mkdir, writeFile } from "node:fs/promises";
import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";

const projection = {
  surface: "overview",
  complete: false,
  source_authority: "azure-consumption-usage-details",
  suppressed_count: 0,
  items: [
    ["Compute", "1600", 9],
    ["Databases", "980", 6],
    ["AI + Machine Learning", "720", 4],
    ["Storage", "440", 5],
    ["Networking", "260", 4],
    ["Management", "120", 3],
    ["Other", "80", 2],
  ].map(([group, amount, count]) => ({
    kind: "summary",
    group_id: group,
    currency: "USD",
    record_count: count,
    suppressed: false,
    amount_rounded: amount,
  })),
  analytics: {
    source_authority: "azure-cost-management-budget-advisor",
    observed_at: "2026-08-31T03:30:00Z",
    complete: true,
    trend: [520, 610, 570, 740, 680, 590, 490].map((amount, index) => ({
      observed_on: `2026-08-${String(25 + index).padStart(2, "0")}`,
      amount,
      currency: "USD",
      completeness: 1,
    })),
    budgets: [
      { budget_ref: "budget:0123456789abcdef", amount: 7500, current_spend: 4200, forecast_spend: 5100, currency: "USD", time_grain: "Monthly" },
      { budget_ref: "budget:fedcba9876543210", amount: 5000, current_spend: 3100, forecast_spend: null, currency: "USD", time_grain: "Monthly" },
    ],
    recommendations: [
      ["disk", "Unattached disk", "Review whether the disk is still required", "microsoft.compute/disks", 120, null],
      ["aks", "Enable Vertical Pod Autoscaler", "Enable recommendation mode", "microsoft.containerservice/managedclusters", 80, 34],
      ["plan", "Consider purchasing a savings plan", "Review commitment options", "microsoft.subscriptions/subscriptions", 65, null],
      ["insights", "Switch to Prometheus-based Container Insights", "Review monitoring configuration", "microsoft.containerservice/managedclusters", 45, 61],
    ].map(([id, problem, solution, resourceType, savings, utilization]) => ({
      recommendation_ref: `recommendation:${String(id).padEnd(16, "0")}`,
      resource_ref: `resource:${String(id).padEnd(16, "0")}`,
      resource_type: resourceType,
      problem,
      solution,
      impact: "Medium",
      monthly_savings: savings,
      currency: "USD",
      current_sku: null,
      target_sku: null,
      utilization_percent: utilization,
      utilization_metric: utilization === null ? null : "node_cpu_usage_percentage.hourly_average.p95",
      observed_at: "2026-08-31T03:30:00Z",
      source_authority: "azure-advisor",
    })),
    limitations: [],
  },
};

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
          key: "cost-governance",
          source: "browser-test-fixture",
          routes: ["/cost-governance"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: true,
          synthetic: true,
          reason: null,
          last_observed_at: "2026-08-31T03:30:00Z",
        }],
      });
      return;
    }
    if (path === "/cost-governance/availability") {
      await json(route, {
        available: true,
        enabled: true,
        access_allowed: true,
        availability_reasons: [],
        reason: null,
        activation_revision: 1,
        package_version: "0.1.1",
        image_digest: `sha256:${"a".repeat(64)}`,
        asset_manifest_digest: `sha256:${"b".repeat(64)}`,
        semantic_profile_digest: `sha256:${"c".repeat(64)}`,
        ontology_release_digest: `sha256:${"d".repeat(64)}`,
      });
      return;
    }
    if (path.startsWith("/cost-governance/")) {
      await json(route, {
        ...projection,
        surface: path.slice("/cost-governance/".length),
      });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${path}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources*", handle);
  await page.route("**/cost-governance/**", handle);
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(name, { body: screenshot, contentType: "image/png" });
  const root = process.env.FDAI_COST_GOVERNANCE_VISUAL_CAPTURE_ROOT;
  if (!root) return;
  await mkdir(root, { recursive: true });
  await writeFile(`${root}/${name}.png`, screenshot);
}

test("renders the mock-aligned Cost Governance overview", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Desktop presentation gate runs once.");
  await installFixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/cost-governance/overview");

  await expect(page.getByRole("heading", { name: "Actual cost, forecast, and budget" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "From subscription to resource detail" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cost change drivers" })).toBeVisible();
  await expect(page.getByText("$4,200").first()).toBeVisible();
  await expect(page.locator(".cost-flow li")).toHaveCount(6);
  await expect(page.locator(".cost-trend-chart circle")).toHaveCount(7);
  await expect(page.getByRole("combobox", { name: "Budget" })).toHaveCount(1);
  await expect(page.getByText("Incomplete", { exact: true }).first()).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-overview-desktop");

  await page.getByRole("link", { name: "Resource efficiency", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Savings opportunity and utilization" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Resource decisions" })).toBeVisible();
  await expect(page.locator(".cost-resource-table tbody tr")).toHaveCount(4);
  await expect(page.locator(".cost-inspector")).toBeVisible();
  await capture(page, testInfo, "cost-governance-resource-desktop");
  await page.getByRole("searchbox", { name: "Search resource or service" }).fill("disk");
  await expect(page.locator(".cost-resource-table tbody tr")).toHaveCount(1);
  await page.locator(".cost-resource-table tbody tr button").click();
  await expect(page.locator(".cost-inspector").getByText("Unattached disk")).toBeVisible();
  await assertNoHorizontalOverflow(page);

  await page.getByRole("link", { name: "Optimization cases", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Projected effects by type" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "From discovery to verification" })).toBeVisible();
  await expect(page.locator(".cost-decision-funnel li")).toHaveCount(5);
  await expect(page.locator(".cost-case-rows > div")).toHaveCount(4);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-cases-desktop");

  await page.getByRole("link", { name: "Outcomes", exact: true }).click();
  await expect(page.getByRole("heading", { name: "From projected to verified savings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cost per thousand requests" })).toBeVisible();
  await expect(page.locator(".cost-waterfall > div")).toHaveCount(6);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-outcomes-desktop");
});

test("keeps the Cost Governance workspace bounded at constrained widths", async ({ page }, testInfo) => {
  await installFixture(page);
  await page.setViewportSize({ width: 993, height: 641 });
  await page.goto("/cost-governance/resource-efficiency");

  await expect(page.getByRole("heading", { name: "Savings opportunity and utilization" })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-constrained");

  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-mobile");
});
