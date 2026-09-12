import { expect, test } from "@playwright/test";
import { DASHBOARD_SAMPLE_DATA } from "../../src/routes/dashboard.sample";

test("admitted comparison stays separate, expires and reflows", async ({ page }) => {
  const contexts: Array<{ records?: Record<string, unknown> }> = [];
  await page.clock.install({ time: new Date("2026-09-01T00:00:00Z") });
  await page.setViewportSize({ width: 1440, height: 900 });
  const arm = (name: string, value: number) => ({
    arm: name, sample_count: 30,
    window_start: "2026-08-01T00:00:00Z", window_end: "2026-08-30T00:00:00Z",
    metrics: [{
      metric_id: "auto_resolution_rate", absolute_value: value, sample_size: 30,
      lower_bound: 0.1, upper_bound: 0.9, confidence_level_basis_points: 9500,
    }],
    guards: [{
      guard_id: "policy_violation_escape_rate", sample_size: 30,
      observed_basis_points: 0, maximum_basis_points: 0, breached: false,
    }],
  });
  await page.route("**/*", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/chat/health")) return route.fulfill({
      json: { available: true, mode: "test", model: "test" },
    });
    if (path.endsWith("/chat/stream")) {
      contexts.push(route.request().postDataJSON().view_context);
      return route.fulfill({
        contentType: "text/event-stream",
        body: `event: done\ndata: ${JSON.stringify({
          seq: 1, revision: 1, answer: "Fixture response.",
          source: "semantic:direct-response", model: "test",
        })}\n\n`,
      });
    }
    if (path === "/kpi") return route.fulfill({ json: {
      ...DASHBOARD_SAMPLE_DATA.kpi, event_count: 280, by_tier: {}, by_outcome: {},
    } });
    if (path === "/kpi/autonomy") return route.fulfill({ json: {
      ...DASHBOARD_SAMPLE_DATA.autonomy,
      synthetic: false, sample_size: 0, verticals: [],
      success: Object.fromEntries(Object.entries(DASHBOARD_SAMPLE_DATA.autonomy!.success)
        .map(([key, value]) => [key, { ...value, value: null, baseline: null }])),
      attribution: { attributed_events: 0, unattributed_events: 0, coverage: null },
      finalization: { finalized_events: 0, pending_events: 0, adverse_events: 0 },
      comparison: {
        schema_version: "1.0.0", publication_id: `sha256:${"a".repeat(64)}`,
        cohort_id: "example-cohort", fdai_revision: "a".repeat(40),
        measurement_protocol_version: "1.0.0", artifact_origin: "governed_external",
        synthetic: false, execution_authority: false, promotion_authority: false,
        published_at: "2026-09-01T00:00:00Z", valid_until: "2026-09-01T00:01:00Z",
        baseline: arm("baseline", 0.4), treatment: arm("treatment", 0.8),
      },
    } });
    if (/^\/(api\/|kpi\/|system\/data-sources|cost-governance\/)/.test(path)) {
      return route.fulfill({ status: 404, json: { detail: "Unavailable in comparison fixture" } });
    }
    return route.continue();
  });
  await page.goto("/overview?locale=en");
  await expect(page.locator(".overview-details > summary")).toBeVisible();
  await page.locator(".overview-details > summary").click();
  const comparison = page.locator(".dashboard-cohort-comparison");
  await expect(comparison).toContainText("Admitted cohort comparison");
  await expect(comparison).toContainText("not a comparison with the rolling Live values");
  await expect(comparison.locator(".comparison-estimate strong")).toHaveText(["40%", "80%"]);
  await expect(comparison.getByRole("link", { name: "View publication evidence" }))
    .toHaveAttribute("href", "/audit?action=measurement.dashboard_comparison.v1");
  await page.clock.runFor(600);
  await page.locator(".deck-invoke").click();
  await page.locator(".deck-input").fill("Describe the comparison.");
  await page.locator(".deck-input").press("Enter");
  await expect.poll(() => contexts.length).toBe(1);
  expect(contexts[0]?.records?.cohort_comparison_metrics).toHaveLength(1);
  await page.locator(".deck-close").click();
  for (const width of [993, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.locator("main").evaluate((element) =>
      element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  }
  await page.clock.fastForward(60_001);
  await expect(page.locator(".dashboard-cohort-comparison")).toHaveCount(0);
  await expect(page.locator(".overview-details")).toContainText("This comparison has expired");
  await page.clock.fastForward(501);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator(".deck-invoke").click();
  await page.locator(".deck-input").fill("Describe the current comparison.");
  await page.locator(".deck-input").press("Enter");
  await expect.poll(() => contexts.length).toBe(2);
  expect(contexts[1]?.records?.cohort_comparison_metrics).toEqual([]);
  expect(contexts[1]?.records?.cohort_comparison_context).toEqual([]);
});
