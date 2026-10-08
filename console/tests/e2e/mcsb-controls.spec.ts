import { expect, test, type Page, type Route } from "@playwright/test";

const version = {
  benchmark_version: "v1",
  title: "Microsoft Cloud Security Benchmark v1",
  status: "stable",
  control_import_status: "complete",
  control_count: 86,
  coverage_counts: { partial: 16, manual: 9, unmapped: 61 },
  policy_profiles: [{ profile_id: "mcsb-v1", policy_ref_count: 222 }],
};
const preview = {
  benchmark_version: "v2-preview",
  title: "Microsoft Cloud Security Benchmark v2 preview",
  status: "preview",
  control_import_status: "complete",
  control_count: 1,
  coverage_counts: { unmapped: 1 },
  policy_profiles: [{ profile_id: "mcsb-v2", policy_ref_count: 410 }],
};
const controls = [
  {
    control_id: "DP-3",
    title: "Encrypt sensitive data in transit",
    domain: "DP",
    coverage: "partial",
    rule_count: 3,
    runtime_observation_count: 1,
    manual_evidence_count: 0,
  },
  {
    control_id: "IR-1",
    title: "Update incident response plan",
    domain: "IR",
    coverage: "manual",
    rule_count: 0,
    runtime_observation_count: 0,
    manual_evidence_count: 1,
  },
];
const previewControls = [
  {
    control_id: "AI-1",
    title: "Ensure use of approved models",
    domain: "AI",
    coverage: "unmapped",
    rule_count: 0,
    runtime_observation_count: 0,
    manual_evidence_count: 0,
  },
];

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

const ASSESSED_AT = "2026-10-08T12:00:00+00:00";
const assessmentSummary = {
  status: "evaluated",
  framework_id: "azure-mcsb",
  last_evaluated_at: ASSESSED_AT,
  satisfaction_counts: { failed: 1, unknown: 1 },
  execution_authority: false,
};
const controlAssessments: Readonly<Record<string, unknown>> = {
  "DP-3": {
    applicability: "applicable",
    evaluation_status: "evaluated",
    satisfaction: "failed",
    evaluated_at: ASSESSED_AT,
    evidence_complete: false,
    limitations: [],
  },
  "IR-1": {
    applicability: "applicable",
    evaluation_status: "not_evaluated",
    satisfaction: "unknown",
    evaluated_at: ASSESSED_AT,
    evidence_complete: false,
    limitations: ["decisive_evidence_unavailable"],
  },
};

async function installFixture(page: Page, { assessed = false } = {}): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (!path.startsWith("/mcsb-controls")) {
      await route.continue();
      return;
    }
    if (path.startsWith("/mcsb-controls/") && path !== "/mcsb-controls/") {
      await json(route, {
        ...controls[0],
        benchmark_version: "v1",
        rule_ids: ["object-storage.https-only.required"],
        runtime_observation_ids: ["mysql-tls"],
        manual_evidence_refs: [],
        source: { source_url: "https://learn.microsoft.com/" },
        evaluation_source: "catalog_crosswalk",
        ...(assessed
          ? {
              assessment: {
                ...(controlAssessments["DP-3"] as Record<string, unknown>),
                requirements: [
                  {
                    kind: "artifact",
                    ref: "mcsb-dp-3-control-evidence",
                    evidence_role: "decisive",
                    status: "unknown",
                    limitations: ["decisive_evidence_unavailable"],
                  },
                  {
                    kind: "rule",
                    ref: "object-storage.https-only.required",
                    evidence_role: "decisive",
                    status: "failed",
                    limitations: [],
                  },
                ],
              },
              assessment_summary: assessmentSummary,
            }
          : {}),
      });
      return;
    }
    if (path === "/mcsb-controls") {
      const selected = url.searchParams.get("version") === "v2-preview" ? preview : version;
      const items = selected === preview ? previewControls : controls;
      await json(route, {
        benchmark: selected,
        versions: [version, preview],
        total: items.length,
        filtered_total: items.length,
        offset: 0,
        limit: 100,
        facets: {
          by_domain: selected === preview ? { AI: 1 } : { DP: 1, IR: 1 },
          by_coverage: selected === preview ? { unmapped: 1 } : { partial: 1, manual: 1 },
        },
        controls:
          assessed && selected === version
            ? items.map((item) => ({ ...item, assessment: controlAssessments[item.control_id] ?? null }))
            : items,
        evaluation_source: "catalog_crosswalk",
        ...(assessed
          ? {
              assessment_summary:
                selected === version
                  ? assessmentSummary
                  : { status: "not_assessed", framework_id: "azure-mcsb", execution_authority: false },
            }
          : {}),
      });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/mcsb-controls*", handle);
  await page.route("**/mcsb-controls/**", handle);
}

test("shows versioned implementation coverage without compliance claims", async ({ page }) => {
  await installFixture(page);
  await page.goto("/rules?view=controls&framework=mcsb-v1");

  await expect(page.getByRole("link", { name: "MCSB v1" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("Implementation coverage, not compliance status.")).toBeVisible();
  await expect(page.getByText("DP-3", { exact: true })).toBeVisible();
  await expect(page.getByText("Partial", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Satisfied", { exact: true })).toHaveCount(0);

  await page.getByText("DP-3", { exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "MCSB control detail" });
  await expect(drawer.getByText("object-storage.https-only.required")).toBeVisible();
  await expect(drawer.getByText("mysql-tls")).toBeVisible();
  await drawer.getByRole("button", { name: "Close" }).click();

  await page.getByRole("link", { name: "MCSB v2 preview" }).click();
  await expect(page).toHaveURL(/framework=mcsb-v2-preview/);
  await expect(
    page.getByText("MCSB v2 preview definitions are imported; mappings are pending review."),
  ).toBeVisible();
  await expect(page.getByText("AI-1", { exact: true })).toBeVisible();

  for (const selector of ["html", ".control-framework-tabs", ".rule-facet-toolbar"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});

test("shows server-owned shadow assessment state for v1 controls", async ({ page }) => {
  await installFixture(page, { assessed: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/rules?view=controls&framework=mcsb-v1");

  await expect(page.getByRole("columnheader", { name: "Assessment" })).toBeVisible();
  await expect(page.getByText(`Shadow assessment from ${ASSESSED_AT}: 1 failed, 1 unknown, 0 satisfied.`, { exact: false })).toBeVisible();
  await expect(
    page.locator("td.mcsb-assessment-column").getByText("Failed", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Satisfied", { exact: true })).toHaveCount(0);

  await page.getByText("DP-3", { exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "MCSB control detail" });
  await expect(drawer.getByRole("heading", { name: "Shadow assessment" })).toBeVisible();
  const requirements = drawer.getByRole("list", { name: "Requirements" });
  await expect(requirements.getByText("mcsb-dp-3-control-evidence")).toBeVisible();
  await expect(requirements.getByText("Decisive", { exact: true })).toHaveCount(2);
  await expect(drawer.getByText("Decisive control evidence is required to satisfy this control.", { exact: false })).toBeVisible();
  await drawer.getByRole("button", { name: "Close" }).click();

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    for (const selector of ["html", ".rule-facet-toolbar", ".mcsb-coverage-banner"]) {
      const dimensions = await page.locator(selector).evaluate((element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }));
      expect(dimensions.scrollWidth, `${selector} at ${viewport.width}`).toBeLessThanOrEqual(
        dimensions.clientWidth,
      );
    }
  }

  await page.getByRole("link", { name: "MCSB v2 preview" }).click();
  await expect(page.getByRole("columnheader", { name: "Assessment" })).toHaveCount(0);
});
