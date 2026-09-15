import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

const runtimeSettings = {
  revision: 2,
  can_manage: true,
  updated_at: "2026-09-01T05:00:00Z",
  updated_by: "owner-1",
  integrations: [],
  runtime: {
    environment: "dev",
    state_store_durable: true,
    autonomy_default: "shadow",
    pantheon_enabled: true,
    workflow_observation_enabled: true,
    primary_transport_configured: true,
    auxiliary_transport_configured: false,
    case_history_configured: false,
  },
  settings: [
    {
      key: "analyzer.budget_seconds",
      group: "analysis",
      value_type: "number",
      environment_value: 60,
      override_value: null,
      effective_value: 60,
      minimum: 1,
      maximum: 3600,
      options: [],
      restart_required: false,
      available: true,
      unavailable_reason: null,
    },
  ],
};

const operatorMemory = {
  items: [
    {
      id: "memory-1",
      scope_kind: "resource-group",
      scope_ref: "resource-group:example",
      category: "preference",
      body: "Use the approved maintenance window.",
      source_event: "hil.reject",
      source_ref: "hil.reject:1",
      author: "operator-a",
      approved_by: "operator-b",
      approval_state: "approved",
      created_at: "2026-09-01T05:00:00Z",
      expires_at: null,
      expired: false,
      superseded_by: null,
      active: true,
    },
  ],
  compactions: [
    {
      candidate_id: "memory-compaction:1",
      scope_kind: "resource-group",
      scope_ref: "resource-group:example",
      category: "preference",
      body: "Compacted approved guidance.",
      source_refs: ["hil.reject:1", "hil.reject:2"],
      proposed_by_agent: "Norns",
      state: "approved",
      reviewed_by: "owner-a",
      review_reason: "Grounded.",
    },
  ],
};

const fixtures: Readonly<Record<string, unknown>> = {
  "/runtime/settings": runtimeSettings,
  "/operator-memory": operatorMemory,
  "/healthz": { status: "ok" },
};

async function installFixtures(page: Page): Promise<void> {
  await page.route("**/*", async (route: Route) => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path in fixtures) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(fixtures[path]),
      });
      return;
    }
    if (new URL(route.request().url()).pathname.startsWith("/api/")) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Optional test source unavailable." }),
      });
      return;
    }
    await route.continue();
  });
}

async function expectControlPresentation(
  root: Locator,
  minimumHeight: number,
): Promise<void> {
  const failures = await root
    .locator("button, input:not([type='checkbox']):not([type='radio']), select, textarea")
    .evaluateAll((elements, minimum) => {
      const pageFont = getComputedStyle(document.body).fontFamily;
      return elements.flatMap((element) => {
        if (element.getClientRects().length === 0) return [];
        const style = getComputedStyle(element);
        const height = element.getBoundingClientRect().height;
        const clipped = element.scrollHeight > element.clientHeight + 1;
        if (
          height >= minimum
          && !clipped
          && (style.fontFamily === pageFont || style.fontFamily.includes("monospace"))
        ) return [];
        return [{
          name: element.getAttribute("aria-label") ?? element.textContent?.trim() ?? element.tagName,
          height,
          clipped,
          font: style.fontFamily,
          pageFont,
        }];
      });
    }, minimumHeight);
  expect(failures).toEqual([]);
  expect(await root.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installFixtures(page);
});

test("production Settings controls share desktop typography and sizing", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto("/settings/memory");
  const memory = page.locator(".settings-overlay .operator-memory-route");
  await expect(memory.locator(".data-table").first()).toBeVisible();
  await expectControlPresentation(memory.locator(".settings-filter-bar"), 34);

  await page.goto("/settings/runtime-policies");
  const runtime = page.locator(".settings-overlay .settings-runtime-route");
  const runtimeControl = runtime.locator('.settings-runtime-control:has(input[type="number"])');
  await expect(runtimeControl).toBeVisible();
  await expectControlPresentation(runtimeControl, 34);

  await page.goto("/settings/diagnostics");
  const diagnostics = page.locator(".settings-overlay .settings-route");
  const retry = diagnostics.locator(".settings-diagnostic-action");
  await expect(retry.getByRole("button")).toBeVisible();
  await expectControlPresentation(retry, 34);
});

for (const locale of ["en", "ko"] as const) {
  test(`production Settings controls reflow on mobile in ${locale}`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });

    await page.goto(`/settings/memory?locale=${locale}`);
    const memory = page.locator(".settings-overlay .operator-memory-route");
    await expect(memory.locator(".data-table").first()).toBeVisible();
    await expectControlPresentation(memory.locator(".settings-filter-bar"), 44);

    await page.goto(`/settings/runtime-policies?locale=${locale}`);
    const runtime = page.locator(".settings-overlay .settings-runtime-route");
    const runtimeControl = runtime.locator('.settings-runtime-control:has(input[type="number"])');
    await expect(runtimeControl).toBeVisible();
    await expectControlPresentation(runtimeControl, 44);

    await page.goto(`/settings/diagnostics?locale=${locale}`);
    const diagnostics = page.locator(".settings-overlay .settings-route");
    const retry = diagnostics.locator(".settings-diagnostic-action");
    await expect(retry.getByRole("button")).toBeVisible();
    await expectControlPresentation(retry, 44);

    const documentSize = await page.locator("html").evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(documentSize.scrollWidth).toBeLessThanOrEqual(documentSize.clientWidth);
  });
}
