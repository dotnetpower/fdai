import { expect, test, type Page, type Route } from "@playwright/test";

function inventory(count = 600) {
  return {
    snapshot_id: "example-snapshot-1", snapshot_at: "2026-09-05T03:00:00Z",
    source: "browser-test-fixture", observation_kind: "OBSERVED", freshness: "fresh",
    active_view: "example-workload", truncated: false, cursor: "revision-not-pagination",
    coverage_gaps: [], realtime: { pending_changes: 0 },
    resources: [
      { id: "sub-a", name: "Example subscription A", type: "subscription", status: "unknown" },
      { id: "sub-b", name: "Example subscription B", type: "subscription", status: "unknown" },
      { id: "group-a", name: "Application", type: "resource-group", status: "unknown", parent_id: "sub-a" },
      { id: "group-b", name: "Data", type: "resource-group", status: "unknown", parent_id: "sub-b" },
      ...Array.from({ length: count }, (_, index) => ({
        id: `resource-${index}`, name: `Example resource ${String(index).padStart(4, "0")}`,
        type: ["compute.vm", "postgresql", "network.vnet", "unmapped.example"][index % 4],
        status: ["running", "stopped", "Succeeded", "healthy", "deallocated", "starting"][index % 6],
        parent_id: index % 2 ? "group-b" : "group-a",
      })),
    ],
  };
}

function recordedPage(input: unknown, cursor: string | null = null) {
  const graph = input as ReturnType<typeof inventory>;
  const rawResources = graph.resources;
  const raw = Array.isArray(rawResources) ? rawResources.filter((resource) =>
    !["subscription", "resource-group", "authorization.role-assignment"].includes(resource.type ?? "")) : [];
  const offset = cursor ? Number(cursor.replace("fixture-", "")) : 0;
  const values = raw.slice(offset, offset + 500);
  const next = offset + values.length < raw.length ? `fixture-${offset + values.length}` : null;
  const fact = (value: string | null, source_path: string | null) => ({
    value, source_path, observed_at: value ? graph.snapshot_at : null,
    recorded_at: value ? graph.snapshot_at : null,
    freshness: value ? graph.freshness : "unknown", completeness: value ? 1 : null, conflicts: [],
    reason: value ? null : "state_not_recorded",
  });
  return {
    schema_version: "1.0.0", source_generation: graph.snapshot_id, source_cutoff: graph.snapshot_at,
    ontology_release_digest: `sha256:${"a".repeat(64)}`,
    resources: !Array.isArray(rawResources) ? null : values.map((row) => ({
      id: row.id, object_type: "Resource", resource_type: row.type, name: row.name, location: null,
      resource_group: "parent_id" in row && row.parent_id === "group-a" ? "Application" : "Data",
      subscription_id: "parent_id" in row && row.parent_id === "group-a" ? "sub-a" : "sub-b",
      status: row.status, last_seen: graph.snapshot_at, selected: false,
      states: {
        schema_version: "1.0.0",
        operational: fact(row.status && !["unknown", "Succeeded"].includes(row.status) ? row.status : null,
          row.status && !["unknown", "Succeeded"].includes(row.status) ? "properties.runningStatus" : null),
        provisioning: fact(row.status === "Succeeded" ? row.status : null, row.status === "Succeeded" ? "properties.provisioningState" : null),
        availability: fact(null, null),
      },
    })),
    total_count: raw.length, next_cursor: next, complete: next === null,
    execution_authority: false, mutation_authority: false,
  };
}

async function json(route: Route, payload: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
}

async function installApi(page: Page, graph: () => unknown = inventory) {
  const requests: string[] = [];
  const handle = async (route: Route) => {
    if (route.request().resourceType() === "document") { await route.continue(); return; }
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    requests.push(`${route.request().method()} ${path}`);
    if (path === "/system/data-sources") return json(route, {
      surface: "read-data-sources",
      sources: [{
        key: "inventory", source: "browser-test-fixture", routes: ["/ontology/instances/states"],
        availability: "available", configured: true, reachable: true,
        authoritative: true, durable: false, synthetic: true, reason: null, last_observed_at: "2026-09-05T03:00:00Z",
      }],
    });
    if (path === "/ontology/instances/states") return json(route, recordedPage(graph(), new URL(route.request().url()).searchParams.get("cursor")));
    if (path === "/kpi") return json(route, {
      event_count: 30, shadow_share: 1, enforce_share: 0, hil_pending: 0,
      by_action_kind: { evaluate: 30 }, by_outcome: { success: 30 }, by_tier: { T0: 30 },
      last_recorded_at: "2026-09-05T03:00:00Z",
    });
    return json(route, { detail: "Not configured in this browser test" }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources", handle);
  await page.route("**/ontology/instances/states*", handle);
  await page.route("**/kpi", handle);
  await page.route("**/kpi/**", handle);
  await page.route("**/cost-governance/**", handle);
  return requests;
}

async function openV2(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/dashboard-v2");
  await expect(page.locator(".dv2-summary")).toBeVisible();
}

test.describe("Native Dashboard v2", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop gate precedes constrained and touch scenarios.");
  });

  test("retains the original Dashboard and navigates to an independent resource route", async ({ page }, testInfo) => {
    await installApi(page);
    await openV2(page);
    await expect(page.locator(".page-header-title")).toContainText("Dashboard v2");
    await expect(page.locator(".dv2-summary strong")).toHaveText(["600", "500", "100", "100"]);
    await expect(page.locator(".dv2-scope")).toContainText("Active ontology Resource generation");
    await page.locator(".activity-bar").getByRole("button", { name: "Overview", exact: true }).hover();
    await expect(page.getByRole("tooltip")).toContainText("Overview");
    await page.keyboard.press("Escape");
    await expect(page.locator(".dv2-coverage")).toContainText("ontology-instances");
    expect(await page.locator(".dashboard-v2-map-cell").count()).toBeGreaterThan(200);
    expect(await page.locator(".dashboard-v2-map-cell").count()).toBeLessThanOrEqual(476);
    expect(await page.locator(".dashboard-v2-map").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("dashboard-v2-desktop.png") });
    await page.locator(".dv2-summary a").nth(1).click();
    await expect(page.locator(".dv2-meta")).toContainText("500 match filters");
    await expect(page.locator(".dv2-table-wrap")).toBeVisible();
    await page.getByRole("link", { name: "Original Dashboard", exact: true }).click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.locator(".overview-page")).toBeVisible();
    await expect(page.locator(".dashboard-v2-page")).toHaveCount(0);
    await page.goBack();
    await expect(page.locator(".dashboard-v2-page")).toBeVisible();
    await page.getByRole("button", { name: "Overview", exact: true }).last().click();
    await expect(page.locator(".navigation-explorer").getByRole("link", { name: "Dashboard v2", exact: true })).toBeVisible();
    await expect(page.locator(".navigation-explorer").getByRole("link", { name: "Dashboard", exact: true })).toBeVisible();
    await page.goto("/dashboard-v2?state=unknown");
    await expect(page.locator(".dv2-meta")).toContainText("100 match filters");
  });

  test("filters received records and preserves exact selection across lenses, pages and unknown availability", async ({ page }) => {
    const requests = await installApi(page);
    await openV2(page);
    const originalIds = await page.locator(".dashboard-v2-map-cell").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-resource-id")));
    const cell = page.locator(".dashboard-v2-map-cell").first();
    await cell.scrollIntoViewIfNeeded();
    const before = await page.locator("main").evaluate((element) => ({ main: element.scrollTop, page: scrollY }));
    await cell.click();
    await expect(cell).toBeFocused();
    await expect(page.locator(".dv2-inspector h3")).toHaveText("Example resource 0000");
    expect(await page.locator("main").evaluate((element) => ({ main: element.scrollTop, page: scrollY }))).toEqual(before);
    await page.locator(".dv2-inspector > details > summary").click();
    const evidence = await page.locator(".dv2-inspector pre").innerText();
    await page.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(page.locator(".dv2-inspector")).toContainText("outside the current filters");
    expect(await page.locator(".dv2-inspector pre").innerText()).toBe(evidence);
    await page.getByRole("button", { name: "Previous page", exact: true }).click();
    expect(await page.locator(".dashboard-v2-map-cell").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-resource-id")))).toEqual(originalIds);
    await page.getByRole("button", { name: "Availability", exact: true }).click();
    await expect(page.locator(".dv2-resource-panel")).toContainText("Only explicitly recorded availability");
    expect(await page.locator(".dashboard-v2-map-cell").evaluateAll((nodes) => nodes.every((node) => node.getAttribute("data-state") === "unknown"))).toBe(true);
    await page.getByRole("button", { name: "Clear selection", exact: true }).click();
    await page.getByRole("button", { name: "List", exact: true }).click();
    const picker = page.getByRole("combobox", { name: "Type", exact: true });
    await picker.fill("vm");
    await page.getByRole("option").filter({ hasText: "compute.vm" }).click();
    await expect(page.locator(".dv2-meta")).toContainText("150 match filters");
    await picker.fill("postgres");
    await page.locator(".page-header-title").click();
    await expect(picker).toHaveAttribute("aria-expanded", "false");
    await picker.focus();
    await expect(picker).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator(".dv2-meta")).toContainText("150 match filters");
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await page.getByRole("searchbox", { name: "Find resource" }).fill("Example resource 0599");
    await expect(page.locator(".dv2-table-wrap tbody tr")).toHaveCount(1);
    await page.locator(".dv2-table-wrap tbody button").click();
    await expect(page.locator(".dv2-inspector a")).toHaveAttribute("href", "/ontology?view=instances&instance=resource-599");
    expect(requests.filter((entry) => entry.includes("ontology/instances/states"))).toEqual(["GET /ontology/instances/states", "GET /ontology/instances/states"]);
    expect(requests.every((entry) => entry.startsWith("GET "))).toBe(true);
  });

  test("supports hover, keyboard navigation and zero-result type selection without new reads", async ({ page }, testInfo) => {
    await installApi(page);
    await openV2(page);
    const cell = page.locator(".dashboard-v2-map-cell").first();
    await cell.hover();
    const tip = page.getByRole("tooltip");
    await expect(tip).toContainText("Example resource 0000");
    await expect(tip).toContainText("Snapshot recorded at");
    await tip.hover();
    await page.waitForTimeout(100);
    await expect(tip).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("dashboard-v2-hover.png") });
    await page.keyboard.press("Escape");
    await expect(tip).toHaveCount(0);
    await cell.focus();
    await page.keyboard.press("End");
    await expect(page.locator(".dashboard-v2-map-cell").last()).toBeFocused();
    await expect(page.locator(".dashboard-v2-map-cell[tabindex='0']")).toHaveCount(1);
    await page.keyboard.press("Enter");
    await expect(page.locator(".dv2-inspector")).toBeVisible();
    await page.getByRole("button", { name: "Groups", exact: true }).click();
    await page.getByRole("button", { name: "Application / 300", exact: true }).click();
    await expect(page.locator(".dv2-meta")).toContainText("300 match filters");
    await page.getByRole("searchbox", { name: "Find resource" }).fill("does-not-exist");
    await expect(page.locator(".dv2-resource-panel")).toContainText("No matching resource records");
    await expect(page.locator(".dv2-inspector")).toBeVisible();
    await expect(page.locator(".dv2-inspector")).toContainText("outside the current filters");
  });

  test("retains stale recorded facts and rejects malformed query results", async ({ page }) => {
    let payload: unknown = { ...inventory(6), freshness: "stale", truncated: true, coverage_gaps: ["source_limit"] };
    await installApi(page, () => payload);
    await openV2(page);
    await expect(page.locator(".dv2-summary strong")).toHaveText(["6", "5", "1", "1"]);
    await page.locator(".dashboard-v2-map-cell").first().click();
    await expect(page.locator(".recorded-state-facts")).toContainText("Stale");
    payload = { ...inventory(6), resources: null };
    await page.getByRole("button", { name: "Refresh snapshot", exact: true }).click();
    await expect(page.locator(".state-error")).toBeVisible();
    await expect(page.locator(".dv2-summary")).toHaveCount(0);
    payload = inventory(0);
    await page.getByRole("button", { name: "Refresh snapshot", exact: true }).click();
    await expect(page.locator(".dv2-summary strong")).toHaveText(["0", "0", "0", "0"]);
    await expect(page.locator(".dv2-attention")).toContainText("not an all-clear");
  });

  test("shows an immediate skeleton and source-unavailable state rather than synthetic fallback", async ({ page }) => {
    await installApi(page);
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/ontology/instances/states*", async (route) => {
      await gate;
      await json(route, { detail: "projection unavailable" }, 503);
    });
    await page.goto("/dashboard-v2");
    await expect(page.locator(".dashboard-v2-page .loading-skeleton")).toBeVisible();
    await expect(page.locator(".dv2-summary")).toHaveCount(0);
    release!();
    await expect(page.getByText("The inventory projection is not available.", { exact: false })).toBeVisible();
    await expect(page.locator(".dashboard-v2-map-cell")).toHaveCount(0);
  });

  test("bounds a 10000-record projection and searches beyond the displayed page", async ({ page }) => {
    const payload = inventory(10000);
    const requests = await installApi(page, () => payload);
    await openV2(page);
    expect(await page.locator(".dashboard-v2-map-cell").count()).toBeLessThanOrEqual(476);
    await expect(page.locator(".dv2-summary strong").first()).toHaveText("10,000");
    await page.getByRole("searchbox", { name: "Find resource" }).fill("Example resource 9999");
    await expect(page.locator(".dashboard-v2-map-cell")).toHaveCount(1);
    await page.locator(".dashboard-v2-map-cell").click();
    await expect(page.locator(".dv2-inspector h3")).toHaveText("Example resource 9999");
    await page.getByRole("button", { name: "Refresh snapshot", exact: true }).click();
    await expect(page.locator(".dv2-summary")).toBeVisible();
    await expect(page.locator(".dv2-inspector")).toHaveCount(0);
    expect(requests.filter((entry) => entry === "GET /ontology/instances/states")).toHaveLength(40);
  });

  test("uses real producer provenance and excludes role assignments from counts and type suggestions", async ({ page }) => {
    const payload = inventory(6);
    await installApi(page, () => ({
      ...payload, observation_kind: "observed",
      resources: [...payload.resources, { id: "example-assignment", name: "Example assignment", type: "authorization.role-assignment", status: "unknown" }],
    }));
    await openV2(page);
    await expect(page.locator(".dv2-summary strong")).toHaveText(["6", "5", "1", "1"]);
    await expect(page.locator(".dv2-coverage")).toContainText("Authorization and scope-container records are excluded");
    const input = page.getByRole("combobox", { name: "Type", exact: true });
    await input.fill("role-assignment");
    await expect(page.locator(".searchable-select-empty")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.locator(".dashboard-v2-map-cell[data-resource-id='resource-0']").click();
    await expect(page.locator(".dv2-inspector")).toContainText("running");
    await page.locator(".dashboard-v2-map-cell[data-resource-id='resource-2']").click();
    await expect(page.locator(".dv2-inspector [data-state-axis='provisioning']")).toContainText("Succeeded");
    await page.getByRole("button", { name: "List", exact: true }).click();
    await expect(page.locator(".dv2-table-wrap tbody tr")).toHaveCount(6);
    await expect(page.locator(".dv2-table-wrap")).not.toContainText("role-assignment");
  });

  test("keeps native type suggestions dismissed after restored focus or cancelled IME input", async ({ page }) => {
    await installApi(page);
    await openV2(page);
    const input = page.getByRole("combobox", { name: "Type", exact: true });
    await input.fill("vm");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.locator(".dv2-meta")).toContainText("150 match filters");
    await input.fill("post");
    await input.dispatchEvent("compositionstart");
    await page.locator(".page-header-title").click();
    await input.dispatchEvent("compositionend");
    await input.evaluate((element) => element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertCompositionText" })));
    await input.focus();
    await expect(input).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("ArrowDown");
    await expect(input).toHaveAttribute("aria-expanded", "true");
    await input.dispatchEvent("compositionstart");
    await input.evaluate((element: HTMLInputElement) => { element.value = "postgres"; });
    await input.dispatchEvent("compositionend");
    await expect(page.getByRole("option").filter({ hasText: "postgresql" })).toHaveCount(1);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.locator(".dv2-meta")).toContainText("150 match filters");
  });

  test("does not apply a late inventory response after leaving and reopening the route", async ({ page }) => {
    await installApi(page);
    let release: (() => void) | undefined;
    let finish: (() => void) | undefined;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    const finished = new Promise<void>((resolve) => { finish = resolve; });
    let call = 0;
    await page.route("**/ontology/instances/states*", async (route) => {
      call += 1;
      if (call === 1) {
        await pending;
        await json(route, recordedPage(inventory(12)));
        finish!();
      } else await json(route, recordedPage({ ...inventory(6), snapshot_id: "example-snapshot-2" }));
    });
    await page.goto("/dashboard-v2");
    await expect(page.locator(".dashboard-v2-page .loading-skeleton")).toBeVisible();
    await page.getByRole("link", { name: "Original Dashboard", exact: true }).click();
    await expect(page.locator(".overview-page")).toBeVisible();
    await page.goBack();
    await expect(page.locator(".dv2-summary strong").first()).toHaveText("6");
    release!();
    await finished;
    await expect(page.locator(".dv2-summary strong").first()).toHaveText("6");
    await expect(page.locator(".dv2-coverage")).toContainText("example-snapshot-2");
  });

  test("supports constrained desktop, mobile taps, long names and Korean navigation", async ({ page, browser }, testInfo) => {
    await installApi(page);
    await openV2(page);
    await page.setViewportSize({ width: 993, height: 641 });
    await page.locator(".dv2-resource-panel").scrollIntoViewIfNeeded();
    expect(await page.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("dashboard-v2-constrained.png") });
    const touch = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
    const mobile = await touch.newPage();
    try {
      await installApi(mobile);
      await mobile.goto("/dashboard-v2?locale=ko");
      await expect(mobile.locator(".page-header-title")).toContainText("대시보드 v2");
      await expect(mobile.getByRole("button", { name: "조밀하게", exact: true })).toBeDisabled();
      await expect(mobile.locator(".dashboard-v2-map-cell")).toHaveCount(48);
      const input = mobile.getByRole("combobox", { name: "유형", exact: true });
      await input.tap();
      await input.fill("vm");
      await mobile.getByRole("option").filter({ hasText: "compute.vm" }).tap();
      await expect(input).toHaveAttribute("aria-expanded", "false");
      const first = mobile.locator(".dashboard-v2-map-cell").first();
      await first.scrollIntoViewIfNeeded();
      const before = await mobile.locator("main").evaluate((element) => element.scrollTop);
      await first.tap();
      expect(await mobile.locator("main").evaluate((element) => element.scrollTop)).toBe(before);
      await expect(mobile.locator(".dv2-inspector")).toBeVisible();
      await expect(mobile.getByRole("tooltip")).toHaveCount(0);
      await mobile.screenshot({ path: testInfo.outputPath("dashboard-v2-mobile.png") });
      await mobile.locator(".dv2-inspector h3").evaluate((element) => {
        element.textContent = "긴 리소스 이름 / " + "long-resource-name".repeat(10);
      });
      expect(await mobile.locator(".dv2-inspector").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      expect(await mobile.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      const box = await first.boundingBox();
      expect(box!.width).toBeGreaterThanOrEqual(44);
      expect(box!.height).toBeGreaterThanOrEqual(44);
      await mobile.screenshot({ path: testInfo.outputPath("dashboard-v2-mobile-long-name.png") });
      await mobile.getByRole("button", { name: "선택 해제", exact: true }).tap();
      await expect(mobile.locator(".dv2-inspector")).toHaveCount(0);
    } finally { await touch.close(); }
    await page.setViewportSize({ width: 1440, height: 900 });
    expect(await page.locator(".dashboard-v2-map").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.evaluate(() => localStorage.setItem("fdai:console:theme", "dark"));
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator(".dv2-summary")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("dashboard-v2-dark.png") });
  });
});
