import { expect, test } from "@playwright/test";

import {
  ALL_CONSOLE_ROUTES,
  measureRouteRubric,
  SAMPLE_ENABLED_ROUTES,
  type RouteRubricMeasurement,
} from "./shared-ui-rubric-probe";

test.beforeEach(async ({ page }) => {
  const unavailableHandler = async (route: import("@playwright/test").Route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Optional test source unavailable." }),
    });
  };
  await page.route("**/api/**", unavailableHandler);
  await page.route("http://127.0.0.1:8011/**", unavailableHandler);
  await page.route("http://localhost:8011/**", unavailableHandler);
});

test("all 63 registered Console routes satisfy desktop (1440x900) UI/UX rubric invariants in EN and KO", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1440, height: 900 });

  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const violations: { route: string; locale: string; mode: string; issues: Record<string, unknown> }[] = [];

  for (const locale of ["en", "ko"] as const) {
    for (const routePath of ALL_CONSOLE_ROUTES) {
      await page.goto(`${routePath}?locale=${locale}`, { waitUntil: "domcontentloaded" });
      const m = await measureRouteRubric(page, routePath, locale, "live");
      recordIfViolated(m, violations);
    }
    for (const routePath of SAMPLE_ENABLED_ROUTES) {
      await page.goto(`${routePath}?data=sample&locale=${locale}`, {
        waitUntil: "domcontentloaded",
      });
      const m = await measureRouteRubric(page, routePath, locale, "sample");
      recordIfViolated(m, violations);
    }
  }

  expect(pageErrors).toEqual([]);
  expect(violations).toEqual([]);
});

test("sample-enabled and representative Console routes satisfy constrained desktop (993x641) and mobile (390x844) geometry invariants", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const violations: { route: string; viewport: string; mode: string; issues: Record<string, unknown> }[] = [];

  for (const vp of [
    { width: 993, height: 641, label: "993x641" },
    { width: 390, height: 844, label: "390x844" },
  ] as const) {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    for (const routePath of ALL_CONSOLE_ROUTES) {
      const useSample = (SAMPLE_ENABLED_ROUTES as readonly string[]).includes(routePath);
      const url = useSample
        ? `${routePath}?data=sample&locale=ko`
        : `${routePath}?locale=ko`;
      await page.goto(url, { waitUntil: "domcontentloaded" });
      const m = await measureRouteRubric(
        page,
        routePath,
        "ko",
        useSample ? "sample" : "live",
      );
      const issues = extractIssues(m);
      if (Object.keys(issues).length > 0) {
        violations.push({
          route: routePath,
          viewport: vp.label,
          mode: useSample ? "sample" : "live",
          issues,
        });
      }
    }
  }

  expect(pageErrors).toEqual([]);
  expect(violations).toEqual([]);
});

test("FJ-1 through FJ-8 interactive functional journeys preserve state, accessibility, and geometry", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1440, height: 900 });

  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  // FJ-1: Global Shell, Navigation Explorer, and EN <-> KO Locale Switching
  await page.goto("/overview?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  const mOverviewEn = await measureRouteRubric(page, "/overview", "en", "sample");
  expect(extractIssues(mOverviewEn)).toEqual({});

  await page.getByRole("button", { name: "Operations" }).click();
  const explorer = page.locator("#navigation-explorer");
  await expect(explorer).toHaveAttribute("aria-hidden", "false");

  await page.goto("/overview?data=sample&locale=ko", { waitUntil: "domcontentloaded" });
  const mOverviewKo = await measureRouteRubric(page, "/overview", "ko", "sample");
  expect(extractIssues(mOverviewKo)).toEqual({});

  // FJ-2: Situation Room & Live Observation
  await page.goto("/live?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  const mLive = await measureRouteRubric(page, "/live", "en", "sample");
  expect(extractIssues(mLive)).toEqual({});

  // FJ-3: Incidents Selection & Audit Filter Submission
  await page.goto("/incidents?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  await measureRouteRubric(page, "/incidents", "en", "sample");
  const incidentButtons = page.locator(".incident-roster-item");
  if ((await incidentButtons.count()) > 1) {
    await incidentButtons.nth(1).click();
    await expect(incidentButtons.nth(1)).toHaveClass(/is-selected/);
  }
  expect(extractIssues(await measureRouteRubric(page, "/incidents", "en", "sample"))).toEqual({});

  await page.goto("/audit?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  await measureRouteRubric(page, "/audit", "en", "sample");
  const auditSearch = page.locator("form.audit-query input[type='search']").first();
  if (await auditSearch.isVisible()) {
    await auditSearch.fill("sample-action-1");
    await page.locator("form.audit-query button[type='submit']").first().click();
    await expect(page).toHaveURL(/q=sample-action-1/);
  }
  expect(extractIssues(await measureRouteRubric(page, "/audit", "en", "sample"))).toEqual({});

  // FJ-4: Approvals Safeguards, Scheduler Runs Row Inspector, and Background Tasks
  await page.goto("/approvals?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  expect(extractIssues(await measureRouteRubric(page, "/approvals", "en", "sample"))).toEqual({});
  await expect(page.getByText("sample-checkout-standby-vm-01").first()).toBeVisible();

  await page.goto("/scheduler-runs?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  await measureRouteRubric(page, "/scheduler-runs", "en", "sample");
  const firstRunAction = page.locator(".data-table-row-action").first();
  await firstRunAction.click();
  await expect(firstRunAction).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#scheduler-run-detail")).toBeVisible();
  expect(extractIssues(await measureRouteRubric(page, "/scheduler-runs", "en", "sample"))).toEqual({});

  await page.goto("/background-tasks?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  expect(extractIssues(await measureRouteRubric(page, "/background-tasks", "en", "sample"))).toEqual({});

  // FJ-5: Ontology, Pantheon, and Rule Catalog Keyboard Focus
  await page.goto("/rules?locale=en", { waitUntil: "domcontentloaded" });
  await measureRouteRubric(page, "/rules", "en", "live");
  const rulesTab = page.locator(".rules-view-tabs a").first();
  if (await rulesTab.isVisible()) {
    await rulesTab.focus();
    await expect(rulesTab).toBeFocused();
  }
  expect(extractIssues(await measureRouteRubric(page, "/rules", "en", "live"))).toEqual({});

  await page.goto("/pantheon?locale=en", { waitUntil: "domcontentloaded" });
  expect(extractIssues(await measureRouteRubric(page, "/pantheon", "en", "live"))).toEqual({});

  // FJ-6: Command Deck Open & Input Interaction
  await page.goto("/overview?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  await measureRouteRubric(page, "/overview", "en", "sample");
  const deck = page
    .getByRole("complementary", { name: "Command deck" })
    .or(page.getByRole("dialog", { name: "Command deck" }));
  if (!(await deck.isVisible())) {
    await page.locator(".deck-invoke").click();
  }
  await expect(deck).toBeVisible();
  const deckInput = deck.getByPlaceholder(/Ask anything/i);
  if (await deckInput.isVisible()) {
    await deckInput.fill("Show current checkout resilience posture");
    await expect(deckInput).toHaveValue("Show current checkout resilience posture");
  }

  // FJ-7: Knowledge, Document Library Collections, and Cost Governance Canonicalization
  await page.goto("/documents?locale=en", { waitUntil: "domcontentloaded" });
  await measureRouteRubric(page, "/documents", "en", "live");
  const folderButtons = page.locator(".document-library-folders button");
  if ((await folderButtons.count()) > 1) {
    await folderButtons.nth(1).click();
    await expect(folderButtons.nth(1)).toHaveAttribute("aria-current", "page");
  }
  expect(extractIssues(await measureRouteRubric(page, "/documents", "en", "live"))).toEqual({});

  await page.goto("/cost-governance/unknown-segment?data=sample&locale=en", {
    waitUntil: "domcontentloaded",
  });
  await expect(page).toHaveURL(/\/cost-governance\/overview/);
  expect(extractIssues(await measureRouteRubric(page, "/cost-governance", "en", "sample"))).toEqual({});

  // FJ-8: Settings Overlay Tabs & Onboarding/Provisioning Sample Flows
  for (const settingsRoute of [
    "/settings/general",
    "/settings/iam",
    "/settings/diagnostics",
  ] as const) {
    await page.goto(`${settingsRoute}?locale=en`, { waitUntil: "domcontentloaded" });
    expect(extractIssues(await measureRouteRubric(page, settingsRoute, "en", "live"))).toEqual({});
  }
  await page.goto("/onboarding?data=sample&locale=en", { waitUntil: "domcontentloaded" });
  expect(extractIssues(await measureRouteRubric(page, "/onboarding", "en", "sample"))).toEqual({});

  expect(pageErrors).toEqual([]);
});

function extractIssues(m: RouteRubricMeasurement): Record<string, unknown> {
  const issues: Record<string, unknown> = {};
  if (!m.headingText) issues.missingHeading = true;
  if (m.documentOverflowPx > 1) issues.documentOverflowPx = m.documentOverflowPx;
  if (m.mainOverflowPx > 1) issues.mainOverflowPx = m.mainOverflowPx;
  if (m.unlabeledControls.length > 0) issues.unlabeledControls = m.unlabeledControls;
  if (m.nestedInteractiveControls.length > 0) {
    issues.nestedInteractiveControls = m.nestedInteractiveControls;
  }
  if (m.coloredEdgeContainers.length > 0) {
    issues.coloredEdgeContainers = m.coloredEdgeContainers;
  }
  if (m.clippedControls.length > 0) issues.clippedControls = m.clippedControls;
  if (m.lowContrastElements.length > 0) {
    issues.lowContrastElements = m.lowContrastElements;
  }
  if (m.dataMode === "sample" && m.unexpectedErrorBlocks > 0) {
    issues.unexpectedErrorBlocks = m.unexpectedErrorBlocks;
  }
  return issues;
}

function recordIfViolated(
  m: RouteRubricMeasurement,
  out: { route: string; locale: string; mode: string; issues: Record<string, unknown> }[],
): void {
  const issues = extractIssues(m);
  if (Object.keys(issues).length > 0) {
    out.push({ route: m.route, locale: m.locale, mode: m.dataMode, issues });
  }
}
