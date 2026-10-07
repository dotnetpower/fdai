import { expect, test, type Page, type Route } from "@playwright/test";

const RULE_ID = "cache.zone-redundant";
const CONTROL_ID = "azure-waf.reliability.re-05";

const CONTROL = {
  id: CONTROL_ID,
  version: "1.0.0",
  framework: "azure-waf",
  control_id: "RE:05",
  title: "Add redundancy for critical flows",
  rationale: "Current evidence is required to assess add redundancy for critical flows.",
  severity: "high",
  category: "reliability",
  pillar: "reliability",
  requirement_mode: "all",
  requirement_count: 3,
  owner: "reliability-owner",
  cadence_days: 1,
  catalog_status: "present",
  mapping_status: "mapped",
  evaluation_status: "not_evaluated",
  applicability: "unknown",
  satisfaction: "unknown",
  evaluation_scope: null,
  evaluated_at: null,
  status: "unknown",
  satisfied_requirement_count: 0,
  evaluation_source: "not_connected",
  profile_id: null,
  profile_digest: null,
  approved_exception: null,
  evidence_refs: [],
  evidence_digests: [],
  limitations: ["not_evaluated"],
  tradeoffs: [],
  execution_authority: false,
} as const;

const REQUIREMENTS = [
  { kind: "rule", ref: RULE_ID, freshness_days: null, status: "unknown", evidence_refs: [] },
  { kind: "artifact", ref: "critical-flow-redundancy-review", freshness_days: 180, status: "unknown", evidence_refs: [] },
  { kind: "approval", ref: "reliability-owner", freshness_days: null, status: "unknown", evidence_refs: [] },
];

const RULE = {
  id: RULE_ID,
  origin: "active",
  version: "1.0.0",
  source: "waf",
  severity: "high",
  category: "reliability",
  resource_type: "cache",
  check_logic: { kind: "rego", reference: "policies/cache/zone_redundant.rego" },
  remediation: { template_ref: "remediation/cache/zone_redundant.tftpl", cost_impact_monthly_usd: 0 },
  remediates: "remediate.enable-zone-redundancy",
  provenance: {
    source_url: "https://learn.microsoft.com/azure/well-architected/reliability/redundancy",
    source_version: null,
    resolved_ref: "catalog-revision",
    content_hash: "sha256:catalog",
    license: "LicenseRef-reference-only",
    redistribution: "reference-only",
    retrieved_at: "2026-07-06T00:00:00Z",
    mapped_by: null,
  },
};

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function controlList(controls: readonly unknown[], extra: Record<string, unknown> = {}): unknown {
  return {
    total: 1,
    filtered_total: controls.length,
    offset: 0,
    limit: 200,
    facets: {
      by_pillar: { reliability: 1 },
      by_status: { unknown: 1 },
      by_severity: { high: 1 },
    },
    controls,
    evaluation_source: "not_connected",
    ...extra,
  };
}

async function installCrossLinkFixture(
  page: Page,
  options: { readonly confirmRuleFilter?: boolean } = {},
): Promise<string[]> {
  const requests: string[] = [];
  const handleApi = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    if (route.request().method() !== "GET") {
      await json(route, { detail: "browser fixture is read-only" }, 405);
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    requests.push(`${path}${url.search}`);
    if (path === "/rules/findings-summary") {
      await json(route, { evaluated: false, counts: {} });
      return;
    }
    if (path === "/rules") {
      await json(route, {
        total: 2,
        filtered_total: 2,
        offset: 0,
        limit: 100,
        resource_type_count: 1,
        facets: {
          by_origin: { active: 1, collected: 1 },
          by_category: { reliability: 2 },
          by_severity: { high: 2 },
          by_source: { waf: 2 },
        },
        rules: [RULE],
      });
      return;
    }
    if (path === `/rules/${RULE_ID}`) {
      await json(route, {
        ...RULE,
        schema_version: "2.0.0",
        alternatives: [],
        parameters: {},
        applies_to: {},
        check_logic_body: "package fdai.cache.zone_redundant",
        remediation_body: null,
        explanation: { title: "Require zone-redundant cache", description: null, source: null, details: {} },
      });
      return;
    }
    if (path === `/rules/${RULE_ID}/findings`) {
      await json(route, { rule_id: RULE_ID, origin: "active", evaluated: false, findings: [] });
      return;
    }
    if (path === "/best-practices") {
      const ruleFilter = url.searchParams.get("rule");
      if (ruleFilter === null) {
        await json(route, controlList([CONTROL]));
      } else if (options.confirmRuleFilter === false) {
        await json(route, controlList([CONTROL]));
      } else {
        await json(route, controlList(ruleFilter === RULE_ID ? [CONTROL] : [], { rule_filter: ruleFilter }));
      }
      return;
    }
    if (path === `/best-practices/${CONTROL_ID}`) {
      await json(route, { ...CONTROL, requirements: REQUIREMENTS, provenance: {} });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route(/^https?:\/\/[^/]+(?:\/api)?\/(?:rules|best-practices|incidents)(?:[/?]|$)/, handleApi);
  return requests;
}

test("separates detection rules from framework assessments in both catalog views", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installCrossLinkFixture(page);
  await page.goto("/rules");

  const rail = page.locator(".rules-catalog-rail");
  await expect(rail.getByRole("heading", { name: "Detection rules" })).toBeVisible();
  await expect(rail.getByRole("heading", { name: "Framework assessments" })).toBeVisible();
  await expect(rail.getByRole("link", { name: /Total rules/ })).toContainText("2 - Curated and collected definitions");

  await rail.getByRole("link", { name: /Controls/ }).click();
  await expect(page).toHaveURL(/view=controls/);
  await expect(page.getByText(/Assessments run in shadow mode and never start remediation/)).toBeVisible();
  await expect(rail.getByRole("link")).toHaveText([
    /Total rules/,
    /Curated catalog/,
    /Collected corpus/,
    /Controls/,
  ]);
  await expect(rail.getByRole("link", { name: /Controls/ })).toHaveAttribute("aria-current", "page");
  await expect(rail.getByRole("link", { name: /Total rules/ })).toContainText("Curated and collected definitions");

  const railWidth = await rail.evaluate((element) => element.getBoundingClientRect().width);
  expect(railWidth).toBe(220);
  for (const selector of ["html", ".rules-route"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});

test("navigates from a control requirement to its rule and back to citing controls", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const requests = await installCrossLinkFixture(page);
  await page.goto(`/rules?view=controls&control=${CONTROL_ID}`);

  const controlDrawer = page.getByRole("dialog", { name: "Control detail" });
  await expect(controlDrawer).toBeVisible();
  await expect(controlDrawer.getByText("Every 1 day(s)")).toBeVisible();
  await expect(controlDrawer.getByText("Detection rule", { exact: true })).toBeVisible();
  await expect(controlDrawer.getByText("Document", { exact: true })).toBeVisible();
  await expect(controlDrawer.getByText("A rule result is one input.", { exact: false })).toBeVisible();
  await expect(controlDrawer.getByRole("link", { name: "Open rule critical-flow-redundancy-review" })).toHaveCount(0);

  await controlDrawer.getByRole("link", { name: `Open rule ${RULE_ID}` }).click();
  await expect(page).toHaveURL(new RegExp(`rule=${RULE_ID.replace(/\./g, "\\.")}`));
  await expect(page).toHaveURL(/rule_origin=active/);

  const ruleDrawer = page.getByRole("dialog", { name: "Rule detail" });
  await expect(ruleDrawer).toBeVisible();
  await expect(ruleDrawer.getByRole("heading", { name: "Used in framework assessments (1)" })).toBeVisible();
  expect(requests).toContain(`/best-practices?rule=${RULE_ID}&limit=200`);

  const citation = ruleDrawer.getByRole("link", { name: /RE:05/ });
  await expect(citation).toContainText("Add redundancy for critical flows");
  await citation.click();
  await expect(page).toHaveURL(new RegExp(`control=${CONTROL_ID}`));
  await expect(page.getByRole("dialog", { name: "Control detail" })).toBeVisible();

  const dimensions = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
});

test("never presents an unfiltered control list as rule citations", async ({ page }) => {
  await installCrossLinkFixture(page, { confirmRuleFilter: false });
  await page.goto(`/rules?rule=${RULE_ID}&rule_origin=active`);

  const ruleDrawer = page.getByRole("dialog", { name: "Rule detail" });
  await expect(ruleDrawer.getByText("This Operator API does not provide control citations.")).toBeVisible();
  await expect(ruleDrawer.getByRole("link", { name: /RE:05/ })).toHaveCount(0);
});

test("keeps the grouped rail aligned in constrained desktop and mobile", async ({ page }) => {
  await page.setViewportSize({ width: 993, height: 641 });
  await installCrossLinkFixture(page);
  await page.goto("/rules?view=controls");

  const rail = page.locator(".rules-catalog-rail");
  await expect(rail.getByRole("heading", { name: "Framework assessments" })).toBeVisible();
  const linkTops = await rail.locator("nav a").evaluateAll(
    (elements) => elements.map((element) => Math.round(element.getBoundingClientRect().top)),
  );
  expect(linkTops).toHaveLength(4);
  expect(new Set(linkTops).size).toBe(1);
  const dimensions = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileLinks = await rail.locator("nav a").evaluateAll(
    (elements) => elements.map((element) => {
      const rect = element.getBoundingClientRect();
      return { left: Math.round(rect.left), height: rect.height };
    }),
  );
  expect(new Set(mobileLinks.map((link) => link.left)).size).toBe(1);
  for (const link of mobileLinks) expect(link.height).toBeGreaterThanOrEqual(44);
  const mobileWidth = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(mobileWidth.scrollWidth).toBeLessThanOrEqual(mobileWidth.clientWidth);
});
