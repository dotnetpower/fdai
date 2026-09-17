import { mkdir, writeFile } from "node:fs/promises";
import {
  expect,
  test,
  type Locator,
  type Page,
  type Route,
  type TestInfo,
} from "@playwright/test";

const OBSERVED_AT = "2026-08-31T03:30:00Z";
const WINDOW_START = "2026-08-01T00:00:00Z";
const DIGEST = `sha256:${"a".repeat(64)}`;

const SUMMARY_ITEMS = [
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
}));

const RESOURCE_CANDIDATES = [
  ["1111111111111111", "microsoft.compute/disks", "premium-ssd", "standard-ssd", 18, 120],
  ["2222222222222222", "microsoft.containerservice/managedclusters", "node-pool-8", "node-pool-4", 34, 80],
  ["3333333333333333", "microsoft.web/serverfarms", "premium-v3", "standard-v3", 47, 65],
  ["4444444444444444", "microsoft.insights/components", "workspace", "basic", 61, 45],
].map(([id, resourceType, current, proposed, utilization, savings]) => ({
  kind: "resource_candidate",
  recommendation_ref: `recommendation:${String(id).padEnd(16, "0")}`,
  resource: `resource:${String(id).padEnd(24, "0")}`,
  resource_type: resourceType,
  current_configuration: current,
  proposed_configuration: proposed,
  utilization_metric: "cpu.hourly_average.p95",
  utilization_percent: utilization,
  projected_monthly_savings: savings,
  currency: "USD",
  observed_at: OBSERVED_AT,
  source_authority: "azure-advisor",
}));

const CASE_ITEMS = ["a", "b"].map((id, index) => ({
  kind: "decision_case",
  case_ref: `case:${id.repeat(24)}`,
  revision: 1,
  target_refs: [`resource:${id.repeat(24)}`],
  evidence_cutoff: OBSERVED_AT,
  decision_frame_digest: DIGEST,
  option_ids: ["option.no-action", `option.review-${index + 1}`],
  selected_option_id: "option.no-action",
  verdict: "hold",
  reason: "observation_mode",
  evidence_refs: ["observation:cost", "observation:capacity"],
  evidence_sources: ["forseti-observation-mode"],
  recovery_steps: [],
  recorded_at: OBSERVED_AT,
  source_authority: "forseti-observation-mode",
}));

const OUTCOME_ITEMS = [
  {
    kind: "settlement_outcome",
    case_ref: `case:${"a".repeat(24)}`,
    revision: 2,
    action_ref: `action:${"a".repeat(24)}`,
    action_revision: 1,
    decision_frame_digest: DIGEST,
    terminal: true,
    verified_savings: 120,
    currency: "USD",
    rollback_requested: false,
    recovery_observed: false,
    effects: [
      ["cost", "cost", "verified", "expected_effect_observed", true],
      ["service", "service", "verified", "expected_effect_observed", true],
    ].map(([id, kind, status, reason, terminal]) => ({
      effect_id: id,
      kind,
      status,
      reason,
      terminal,
      observation_digest: DIGEST,
      completeness_digest: DIGEST,
    })),
    settled_at: OBSERVED_AT,
  },
  {
    kind: "settlement_outcome",
    case_ref: `case:${"b".repeat(24)}`,
    revision: 2,
    action_ref: `action:${"b".repeat(24)}`,
    action_revision: 1,
    decision_frame_digest: DIGEST,
    terminal: true,
    verified_savings: null,
    currency: null,
    rollback_requested: false,
    recovery_observed: false,
    effects: [{
      effect_id: "service",
      kind: "service",
      status: "failed",
      reason: "slo_regression_observed",
      terminal: true,
      observation_digest: DIGEST,
      completeness_digest: DIGEST,
    }],
    settled_at: OBSERVED_AT,
  },
];

const ANALYTICS = {
  source_authority: "azure-cost-management-budget-advisor",
  observed_at: OBSERVED_AT,
  complete: true,
  window_start_at: WINDOW_START,
  window_end_at: OBSERVED_AT,
  sources: [],
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
  recommendations: [],
  limitations: [],
};

type FixtureMode =
  | "candidate"
  | "service-summary"
  | "below-rounding"
  | "stale-service"
  | "projection-error"
  | "missing-action-lineage";

function disclosure(mode: FixtureMode) {
  const detailed = mode === "candidate" || mode === "missing-action-lineage";
  return {
    granularity: detailed ? "resource" : "group",
    identity_visibility: detailed ? "pseudonymous" : "none",
    amount_precision: detailed ? "exact" : "rounded",
    small_cell_minimum: 3,
    rounding_increment: 100,
  };
}

function projectionEvidence(mode: FixtureMode) {
  const candidateReady = mode === "candidate" || mode === "missing-action-lineage";
  const stale = mode === "stale-service";
  return {
    window_start_at: WINDOW_START,
    window_end_at: OBSERVED_AT,
    latest_source_at: OBSERVED_AT,
    freshness: stale ? "stale" : "fresh",
    freshness_threshold_seconds: 172800,
    complete_count: 32,
    partial_count: 1,
    sources: [{
      source_authority: "azure-consumption-usage-details",
      state: "partial",
      window_start_at: WINDOW_START,
      window_end_at: OBSERVED_AT,
      latest_source_at: OBSERVED_AT,
      complete_count: 32,
      partial_count: 1,
      reason: "pagination_incomplete",
    }],
    disclosure: disclosure(mode),
    readiness: [
      { surface: "observations", state: stale ? "unavailable" : "partial", reason: stale ? "observations_stale" : "observations_partial", record_count: 33, latest_evidence_at: OBSERVED_AT },
      { surface: "analytics", state: "complete", reason: null, record_count: 1, latest_evidence_at: OBSERVED_AT },
      { surface: "resource-candidates", state: candidateReady ? "complete" : "unavailable", reason: candidateReady ? null : "disclosure_insufficient", record_count: candidateReady ? 4 : 0, latest_evidence_at: candidateReady ? OBSERVED_AT : null },
      { surface: "decision-cases", state: candidateReady ? "complete" : "unavailable", reason: candidateReady ? null : "decision_cases_missing", record_count: candidateReady ? 2 : 0, latest_evidence_at: candidateReady ? OBSERVED_AT : null },
      { surface: "settlements", state: candidateReady ? "partial" : "unavailable", reason: candidateReady ? "settlement_incomplete" : "settlements_missing", record_count: candidateReady ? 2 : 0, latest_evidence_at: candidateReady ? OBSERVED_AT : null },
    ],
    latest_analytics_run: {
      run_id: `costrun:${"f".repeat(64)}`,
      scope_digest: DIGEST,
      venue: "local",
      window_start_at: WINDOW_START,
      window_end_at: OBSERVED_AT,
      started_at: "2026-08-31T03:28:00Z",
      finished_at: OBSERVED_AT,
      status: "complete",
      sources: [],
      observation_count: 33,
      trend_point_count: 7,
      budget_count: 2,
      recommendation_count: candidateReady ? 4 : 0,
      utilization_count: candidateReady ? 4 : 0,
      limitations: [],
      failure_reason: null,
      snapshot_id: `analytics:${"e".repeat(64)}`,
    },
  };
}

function projectionFor(surface: string, mode: FixtureMode) {
  const serviceItems = mode === "below-rounding"
    ? [{
      kind: "summary",
      group_id: "Low-volume service",
      currency: "USD",
      record_count: 3,
      suppressed: false,
      amount_rounded: "100",
      positive_below_rounding_increment: true,
    }]
    : SUMMARY_ITEMS;
  const outcomes = mode === "missing-action-lineage"
    ? OUTCOME_ITEMS.map(({ action_ref: _actionRef, action_revision: _actionRevision, ...item }) =>
      item
    )
    : OUTCOME_ITEMS;
  const items = surface === "resource-efficiency"
    ? mode === "candidate" ? RESOURCE_CANDIDATES : serviceItems
    : surface === "optimization-cases"
    ? mode === "candidate" ? CASE_ITEMS : []
    : surface === "outcomes"
    ? mode === "candidate" || mode === "missing-action-lineage" ? outcomes : []
    : serviceItems;
  return {
    surface,
    complete: false,
    generated_at: "2026-08-31T03:35:00Z",
    source_authority: "azure-consumption-usage-details",
    suppressed_count: 0,
    disclosure: disclosure(mode),
    resource_efficiency_mode: surface === "resource-efficiency"
      ? mode === "candidate" ? "resource_candidate" : "service_summary"
      : null,
    items,
    analytics: ANALYTICS,
    evidence: projectionEvidence(mode),
  };
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installFixture(
  page: Page,
  mode: FixtureMode = "candidate",
): Promise<(nextMode: FixtureMode) => void> {
  let activeMode = mode;
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
          last_observed_at: OBSERVED_AT,
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
      if (activeMode === "projection-error") {
        await json(route, {
          error: {
            status: 500,
            code: "cost_projection_failed",
            message: "Cost projection failed",
          },
        }, 500);
        return;
      }
      await json(route, projectionFor(path.slice("/cost-governance/".length), activeMode));
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${path}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources*", handle);
  await page.route("**/cost-governance/**", handle);
  return (nextMode) => {
    activeMode = nextMode;
  };
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.locator("html, body, main, .cost-governance-route")
    .evaluateAll((elements) => elements.map((element) => ({
      name: element.tagName.toLowerCase(),
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    })));
  for (const dimension of dimensions) {
    expect(
      dimension.scrollWidth,
      `${dimension.name} has horizontal overflow`,
    ).toBeLessThanOrEqual(dimension.clientWidth);
  }
}

async function contrastRatio(
  locator: Locator,
  foregroundProperty: "color" | "outlineColor",
  backgroundSelector: string,
): Promise<number> {
  return locator.evaluate((element, options) => {
    const channels = (value: string): number[] => (
      value.match(/[\d.]+/g)?.slice(0, 3).map(Number) ?? []
    );
    const luminance = (value: string): number => {
      const [red = 0, green = 0, blue = 0] = channels(value).map((item) => item / 255)
        .map((item) => item <= .04045 ? item / 12.92 : ((item + .055) / 1.055) ** 2.4);
      return .2126 * red + .7152 * green + .0722 * blue;
    };
    const foreground = getComputedStyle(element)[options.foregroundProperty];
    const background = getComputedStyle(element.closest(options.backgroundSelector)!).backgroundColor;
    const light = Math.max(luminance(foreground), luminance(background));
    const dark = Math.min(luminance(foreground), luminance(background));
    return (light + .05) / (dark + .05);
  }, { foregroundProperty, backgroundSelector });
}

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(name, { body: screenshot, contentType: "image/png" });
  const root = process.env.FDAI_COST_GOVERNANCE_VISUAL_CAPTURE_ROOT;
  if (!root) return;
  await mkdir(root, { recursive: true });
  await writeFile(`${root}/${name}.png`, screenshot);
}

test("renders authoritative candidate, case, and outcome modes", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Desktop presentation gate runs once.");
  await installFixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/cost-governance/overview");

  await expect(page.getByRole("heading", { name: "Actual cost, forecast, and budget" })).toBeVisible();
  await expect(page.getByText("$4,200").first()).toBeVisible();
  await expect(page.locator(".cost-trend-chart circle")).toHaveCount(7);
  const evidenceToggle = page.locator(".cost-evidence-toggle");
  await expect(evidenceToggle).toHaveAccessibleName("Show evidence details");
  await evidenceToggle.focus();
  await expect(evidenceToggle).toBeFocused();
  const focusStyle = await evidenceToggle.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: Number.parseFloat(style.outlineWidth) };
  });
  expect(focusStyle.outlineStyle).not.toBe("none");
  expect(focusStyle.outlineWidth).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter");
  await expect(evidenceToggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("heading", { name: "Disclosure policy" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Surface readiness" })).toBeVisible();
  await expect(page.getByText("32 complete, 1 partial").first()).toBeVisible();
  await expect(page.getByText("Pseudonymous", { exact: true })).toBeVisible();
  await expect(page.getByText(/Latest analytics run: Complete/)).toBeVisible();
  const runReceipt = page.locator(".cost-analytics-run");
  await runReceipt.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(runReceipt).toContainText("Execution venue");
  await expect(runReceipt.getByText("Local", { exact: true })).toBeVisible();
  await expect(runReceipt).toContainText("33 observations");
  expect(await contrastRatio(
    page.locator(".cost-evidence-value.is-fresh"),
    "color",
    ".cost-evidence-toolbar",
  )).toBeGreaterThanOrEqual(4.5);
  expect(await contrastRatio(
    evidenceToggle,
    "outlineColor",
    ".cost-evidence-toolbar",
  )).toBeGreaterThanOrEqual(3);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-overview-desktop");

  await page.getByRole("link", { name: "Resource efficiency", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Resource candidates", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Savings opportunity and utilization" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Resource candidates", exact: true }).last()).toBeVisible();
  await expect(page.locator(".cost-resource-table tbody tr")).toHaveCount(4);
  await expect(page.locator(".cost-inspector")).toBeVisible();
  await page.getByRole("searchbox", { name: "Search resource or service" }).fill("disk");
  await expect(page.locator(".cost-resource-table tbody tr")).toHaveCount(1);
  await page.locator(".cost-resource-table tbody tr button").press("Enter");
  await expect(page.locator(".cost-inspector")).toContainText("premium-ssd");
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-resource-candidates-desktop");
  await page.setViewportSize({ width: 993, height: 641 });
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-resource-candidates-constrained");
  await page.setViewportSize({ width: 390, height: 844 });
  const candidateTarget = await page.locator(".cost-resource-table tbody tr button").boundingBox();
  expect(candidateTarget?.height).toBeGreaterThanOrEqual(44);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-resource-candidates-mobile");
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.getByRole("link", { name: "Optimization cases", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Decision-case source" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "From discovery to verification" })).toBeVisible();
  await expect(page.locator(".cost-case-rows > div")).toHaveCount(2);
  await expect(page.locator(".cost-case-rows")).not.toContainText("Azure Advisor");
  const caseLineage = page.locator(".cost-record-lineage").first();
  await caseLineage.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(caseLineage).toContainText(`resource:${"a".repeat(24)}`);
  await expect(caseLineage).toContainText(DIGEST);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-cases-desktop");

  await page.getByRole("link", { name: "Outcomes", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Independent outcome status" })).toBeVisible();
  await expect(page.locator(".cost-settlement-grid > article")).toHaveCount(2);
  await expect(page.locator(".cost-kpi-grid > div").first()).toContainText("$120");
  await expect(page.locator(".cost-settlement-grid")).toContainText("Failed");
  await expect(page.locator(".cost-settlement-grid")).toContainText(
    `action:${"a".repeat(24)}, revision 1`,
  );
  await expect(page.locator(".cost-settlement-grid")).toContainText(
    `Observation ${DIGEST}`,
  );
  await assertNoHorizontalOverflow(page);
  await page.locator("#cost-effect-list").scrollIntoViewIfNeeded();
  await capture(page, testInfo, "cost-governance-outcomes-desktop");
});

test("uses service-summary mode without resource-only fields or scatter", async ({ page }, testInfo) => {
  await installFixture(page, "service-summary");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/cost-governance/resource-efficiency?locale=en");

  await expect(page.getByRole("heading", { name: "Service-cost summary", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Service-cost summary", exact: true }).last()).toBeVisible();
  await expect(page.locator(".cost-service-summary-table tbody tr")).toHaveCount(7);
  await expect(page.locator(".cost-scatter")).toHaveCount(0);
  await expect(page.getByRole("columnheader", { name: "Current SKU" })).toHaveCount(0);
  await expect(page.getByRole("columnheader", { name: "30-day utilization" })).toHaveCount(0);
  await expect(page.getByRole("columnheader", { name: "Decision" })).toHaveCount(0);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-service-summary-desktop");

  await page.setViewportSize({ width: 993, height: 641 });
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-service-summary-constrained");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".cost-evidence-toggle").click();
  await expect(page.locator(".cost-evidence-details")).toBeVisible();
  const runDisclosureTarget = await page.locator(".cost-analytics-run > summary").boundingBox();
  expect(runDisclosureTarget?.height).toBeGreaterThanOrEqual(44);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-service-summary-mobile");
  await page.setViewportSize({ width: 320, height: 800 });
  await assertNoHorizontalOverflow(page);

  await page.getByRole("link", { name: "Optimization cases", exact: true }).click();
  await expect(page.getByText("No agent-owned decision cases are projected.", { exact: true }).first()).toBeVisible();
  await page.getByRole("link", { name: "Outcomes", exact: true }).click();
  await expect(page.getByText("No independently owned settlements are projected.", { exact: true }).first()).toBeVisible();
});

test("renders positive rounded cost below the disclosure increment without measured zero", async ({ page }) => {
  await installFixture(page, "below-rounding");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/cost-governance/resource-efficiency?locale=en");

  await expect(page.getByText("Less than $100", { exact: true })).toBeVisible();
  await expect(page.getByText("$0", { exact: true })).toHaveCount(0);
  await assertNoHorizontalOverflow(page);

  await page.goto("/cost-governance/resource-efficiency?locale=ko");
  await expect(page.getByRole("heading", { name: "서비스 비용 요약", exact: true }).first()).toBeVisible();
  await expect(page.getByText("US$100 미만", { exact: true })).toBeVisible();
  await expect(page.getByText("$0", { exact: true })).toHaveCount(0);
  await assertNoHorizontalOverflow(page);
});

test("keeps stale evidence and operational errors distinct", async ({ page }) => {
  const setMode = await installFixture(page, "stale-service");
  await page.goto("/cost-governance/resource-efficiency?locale=en");
  await expect(page.getByText("Stale", { exact: true }).first()).toBeVisible();
  await page.locator(".cost-evidence-toggle").click();
  await expect(page.locator(".cost-readiness-list")).toContainText(
    "The latest observations are stale.",
  );

  setMode("projection-error");
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Cost Governance");
  await expect(page.locator(".cost-resource-mode")).toHaveCount(0);

  setMode("missing-action-lineage");
  await page.goto("/cost-governance/outcomes?locale=en");
  await expect(page.getByText(
    "2 settlement records are unavailable because exact action identity and revision were not reported.",
    { exact: true },
  ).first()).toBeVisible();
  await expect(page.locator(".cost-settlement-grid")).toHaveCount(0);
});

test("preserves bounded Sample candidates, cases, and outcomes", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Desktop presentation gate runs once.");
  await installFixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/cost-governance/resource-efficiency?data=sample&locale=en");

  await expect(page.getByText("synthetic-preview", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Resource candidates", exact: true }).first()).toBeVisible();
  await expect(page.locator(".cost-resource-table tbody tr")).toHaveCount(2);

  await page.getByRole("link", { name: "Optimization cases", exact: true }).click();
  await expect(page.locator(".cost-case-rows > div")).toHaveCount(2);
  await page.getByRole("link", { name: "Outcomes", exact: true }).click();
  await expect(page.locator(".cost-settlement-grid > article")).toHaveCount(2);
  await expect(page.locator(".cost-kpi-grid > div").first()).toContainText("$41,400");
  await expect(page.locator(".cost-settlement-grid")).toContainText("$12,800");
  await expect(page.locator(".cost-settlement-grid")).toContainText("$28,600");
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "cost-governance-sample-outcomes-desktop");
});
