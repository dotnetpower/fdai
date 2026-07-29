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

async function installFixture(page: Page): Promise<void> {
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
        controls: items,
        evaluation_source: "catalog_crosswalk",
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
