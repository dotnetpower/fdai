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

async function installRuleCatalogFixture(
  page: Page,
  options: {
    readonly ruleStatus?: number;
    readonly waitForRules?: Promise<void>;
  } = {},
): Promise<void> {
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
      await options.waitForRules;
      if (options.ruleStatus !== undefined) {
        await json(route, { detail: "rule catalog unavailable" }, options.ruleStatus);
        return;
      }
      const selectedSource = url.searchParams.get("source");
      await json(route, {
        total: 8548,
        filtered_total: selectedSource === "azure_policy" ? 3628 : 8548,
        offset: 0,
        limit: 100,
        resource_type_count: 372,
        facets,
        rules: [{
          id: "managed-identity.role-assignment.no-privileged-subscription-scope",
          origin: "active",
          version: "1.0.0",
          source: "mcsb",
          severity: "critical",
          category: "security",
          resource_type: "managed-identity",
          check_logic: { kind: "rego", reference: "policies/example.rego" },
          remediation: { template_ref: "remediation/example.tftpl", cost_impact_monthly_usd: 0 },
          remediates: "remediate.right-size-role",
          provenance: {
            source_url: "https://learn.microsoft.com/azure/role-based-access-control/best-practices",
            license: "LicenseRef-reference-only",
            redistribution: "reference-only",
          },
        }],
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

  for (const locator of [page.locator("html"), page.locator(".rule-facet-toolbar"), source.locator("..")]) {
    const dimensions = await locator.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }

  await source.selectOption("azure_policy");
  await expect(page).toHaveURL(/source=azure_policy/);
  await expect(source).toHaveValue("azure_policy");
});

test("keeps the desktop Rules workspace compact and horizontally bounded", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installRuleCatalogFixture(page);
  await page.goto("/rules");

  await expect(page.getByRole("columnheader", { name: "Rule" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Resource" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Category" })).toBeHidden();
  await expect(page.getByRole("heading", { name: "Catalog views" })).toBeVisible();
  const catalogRail = page.locator(".rules-catalog-rail");
  await expect(catalogRail.getByRole("link", { name: /Total rules/ })).toHaveAttribute("aria-current", "page");

  const workbenchColumns = await page.locator(".rules-catalog-workbench").evaluate((element) => {
    const rail = element.querySelector(".rules-catalog-rail")?.getBoundingClientRect();
    const detail = element.querySelector(".rules-catalog-detail")?.getBoundingClientRect();
    return { railWidth: rail?.width, aligned: rail?.top === detail?.top };
  });
  expect(workbenchColumns).toEqual({ railWidth: 220, aligned: true });

  const tableTop = await page.locator("#rule-catalog-table .data-table").evaluate(
    (element) => element.getBoundingClientRect().top,
  );
  expect(tableTop).toBeLessThan(650);

  for (const selector of ["html", ".rules-route", ".rule-facet-toolbar", ".data-table-wrap"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }

  const ruleAction = page.getByRole("button", {
    name: "Rule detail: managed-identity.role-assignment.no-privileged-subscription-scope",
  });
  await ruleAction.press("Enter");
  const drawer = page.getByRole("dialog", { name: "Rule detail" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toBeFocused();
  await drawer.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(ruleAction).toBeFocused();

  await ruleAction.press("Enter");
  await expect(drawer).toBeVisible();
  await page.evaluate(() => history.back());
  await expect(drawer).toBeHidden();
  await expect(ruleAction).toBeFocused();

  await catalogRail.getByRole("link", { name: /Controls/ }).click();
  await expect(page).toHaveURL(/view=controls/);
  await expect(page.locator(".rules-catalog-rail").getByRole("link", { name: /Controls/ })).toHaveAttribute("aria-current", "page");
});

test("reflows Rules controls and honors mobile preference gates", async ({ page }) => {
  await page.setViewportSize({ width: 993, height: 641 });
  await installRuleCatalogFixture(page);
  await page.goto("/rules");
  await expect(page.getByRole("columnheader", { name: "Rule" })).toBeVisible();
  const constrainedRail = await page.locator(".rules-catalog-rail nav a").evaluateAll(
    (elements) => elements.map((element) => element.getBoundingClientRect()),
  );
  expect(new Set(constrainedRail.map((rect) => rect.top)).size).toBe(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });

  const targets = page.locator(
    ".rules-view-tabs a, .rule-facet-toolbar input, .rule-facet-toolbar select, .pager button",
  );
  for (let index = 0; index < await targets.count(); index += 1) {
    const height = await targets.nth(index).evaluate((element) => element.getBoundingClientRect().height);
    expect(height).toBeGreaterThanOrEqual(44);
  }

  await page.addStyleTag({
    content: ".rules-route * { line-height:1.5!important; letter-spacing:.12em!important; word-spacing:.16em!important } .rules-route p { margin-bottom:2em!important }",
  });
  const documentWidth = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(documentWidth.scrollWidth).toBeLessThanOrEqual(documentWidth.clientWidth);

  await page.setViewportSize({ width: 320, height: 844 });
  const kpiLeftEdges = await page.locator(".rules-route .kpi-card").evaluateAll(
    (elements) => elements.map((element) => element.getBoundingClientRect().left),
  );
  expect(new Set(kpiLeftEdges).size).toBe(1);
  const minimumWidth = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(minimumWidth.scrollWidth).toBeLessThanOrEqual(minimumWidth.clientWidth);
});

test("shows a skeleton before data and keeps API failure explicit", async ({ page }) => {
  let releaseRules: (() => void) | undefined;
  const waitForRules = new Promise<void>((resolve) => {
    releaseRules = resolve;
  });
  await installRuleCatalogFixture(page, { waitForRules });
  await page.goto("/rules");

  await expect(page.getByText("Loading rule catalog...", { exact: true })).toBeVisible();
  releaseRules?.();
  await expect(page.getByRole("columnheader", { name: "Rule" })).toBeVisible();

  await page.unroute("**/api/**");
  await page.unroute("**/rules*");
  await installRuleCatalogFixture(page, { ruleStatus: 500 });
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Failed to load rule catalog");
});
