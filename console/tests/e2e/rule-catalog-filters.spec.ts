import { expect, test, type Page, type Route } from "@playwright/test";

const facets = {
  by_origin: { collected: 8487, active: 61 },
  by_category: {
    security: 6297,
    compliance: 2138,
    reliability: 57,
    config_drift: 44,
    cost: 12,
  },
  by_severity: { medium: 5277, low: 3194, high: 75, critical: 2 },
  by_source: {
    kube_bench: 4859,
    azure_policy: 3628,
    mcsb: 25,
    waf: 15,
    azure_advisor: 11,
    custom_long_source_name_that_must_not_overflow: 10,
  },
};

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installRuleCatalogFixture(page: Page): Promise<void> {
  const handleApi = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/rules/findings-summary") {
      await json(route, { evaluated: false, counts: {} });
      return;
    }
    if (path === "/rules") {
      const selectedSource = url.searchParams.get("source");
      await json(route, {
        total: 8548,
        filtered_total: selectedSource === "azure_policy" ? 3628 : 8548,
        offset: 0,
        limit: 100,
        resource_type_count: 372,
        facets,
        rules: [],
      });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/rules*", handleApi);
}

test("keeps the Source filter bounded as source options grow", async ({ page }) => {
  await installRuleCatalogFixture(page);
  await page.goto("/rules");

  const source = page.getByRole("combobox", { name: "Source" });
  await expect(source).toHaveValue("");
  await expect(source.locator("option")).toHaveText([
    "All (8548)",
    "kube_bench (4859)",
    "azure_policy (3628)",
    "mcsb (25)",
    "waf (15)",
    "azure_advisor (11)",
    "custom_long_source_name_that_must_not_overflow (10)",
  ]);

  for (const selector of ["html", ".rule-facet-toolbar", ".rule-facet-select"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }

  await source.selectOption("azure_policy");
  await expect(page).toHaveURL(/source=azure_policy/);
  await expect(source).toHaveValue("azure_policy");
});
