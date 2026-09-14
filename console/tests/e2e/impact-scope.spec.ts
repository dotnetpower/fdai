import { expect, test, type Page, type Route } from "@playwright/test";

const primaryResourceId = [
  "/subscriptions/example-subscription",
  "resourceGroups/example-runtime",
  "providers/Microsoft.DBforPostgreSQL/flexibleServers/database-primary",
].join("/");
const duplicateResourceId = [
  "/subscriptions/example-subscription",
  "resourceGroups/example-recovery",
  "providers/Microsoft.DBforPostgreSQL/flexibleServers/database-primary",
].join("/");

function relationshipEvidence(
  kind: "configuration" | "observation",
): Record<string, unknown> {
  return {
    status: "available",
    evidence_kind: kind,
    verification_status: kind === "configuration"
      ? "configuration_observed"
      : "independently_verified",
    source: kind === "configuration" ? "azure-resource-graph" : "runtime-telemetry",
    source_property_path: "properties.parent",
    mapping_id: "test.relationship",
    evidence_method: "deterministic-cross-check",
    cutoff: "2026-09-14T07:00:00Z",
    freshness_ceiling_seconds: 3_600,
    complete: true,
    reason: null,
  };
}

const unavailableRelationshipEvidence = {
  status: "unavailable",
  evidence_kind: null,
  verification_status: "unavailable",
  source: null,
  source_property_path: null,
  mapping_id: null,
  evidence_method: null,
  cutoff: null,
  freshness_ceiling_seconds: null,
  complete: false,
  reason: "provider_relationship_evidence_unavailable",
};

const impactFixture = {
  schema_version: "1.1.0",
  ontology_release_digest: `sha256:${"a".repeat(64)}`,
  source_generation: "impact-preview-generation",
  source_cutoff: "2026-09-14T07:00:00Z",
  target: primaryResourceId,
  traversal_depth: 2,
  traversal_links: ["contains", "depends_on", "runtime_calls"],
  reached: [
    { resource_id: primaryResourceId, depth: 0, via_link_type: null },
    { resource_id: "billing-api", depth: 1, via_link_type: "depends_on" },
    { resource_id: "invoice-worker", depth: 1, via_link_type: "runtime_calls" },
    { resource_id: "read-replica", depth: 1, via_link_type: "contains" },
    { resource_id: "backup-storage", depth: 2, via_link_type: "depends_on" },
    { resource_id: "traffic-source", depth: 2, via_link_type: "depends_on" },
  ],
  edges: [
    {
      source: primaryResourceId,
      target: "billing-api",
      link_type: "depends_on",
      depth: 1,
      verification_status: "verified",
      evidence: relationshipEvidence("configuration"),
    },
    {
      source: primaryResourceId,
      target: "invoice-worker",
      link_type: "runtime_calls",
      depth: 1,
      verification_status: "verified",
      evidence: relationshipEvidence("observation"),
    },
    {
      source: primaryResourceId,
      target: "read-replica",
      link_type: "contains",
      depth: 1,
      verification_status: "verified",
      evidence: relationshipEvidence("configuration"),
    },
    {
      source: "billing-api",
      target: "backup-storage",
      link_type: "depends_on",
      depth: 2,
      verification_status: "verified",
      evidence: relationshipEvidence("configuration"),
    },
    {
      source: "invoice-worker",
      target: "traffic-source",
      link_type: "depends_on",
      depth: 2,
      verification_status: "unverified",
      evidence: unavailableRelationshipEvidence,
    },
  ],
  affected_count: 5,
  complete: true,
  relationship_evidence_complete: false,
  relationship_source_coverage: {
    materialized: 5,
    reviewed_unavailable: 1,
    unclassified: 0,
    total_candidates: 6,
    complete: true,
  },
  truncated_at_depth: false,
  truncation_reasons: [],
  execution_authority: false,
  mutation_authority: false,
};

const graphFixture = {
  snapshot_id: "impact-preview-generation",
  observation_kind: "observed",
  snapshot_at: "2026-09-14T07:00:00Z",
  freshness: "fresh",
  source: "impact-e2e-inventory",
  scope: null,
  root: null,
  depth: 4,
  limit: 100,
  included_link_types: ["contains", "attached_to", "depends_on", "runtime_calls"],
  resources: impactFixture.reached.map((resource) => ({
    id: resource.resource_id,
    type: "application.container-app",
    name: resource.resource_id.split("/").at(-1),
    status: "Ready",
  })),
  links: impactFixture.edges.map((edge) => ({
    source: edge.source,
    target: edge.target,
    type: edge.link_type,
  })),
  truncated: false,
  truncation_reasons: [],
  coverage_gaps: [],
  cursor: "impact-preview-generation",
  cache: {
    status: "fresh",
    age_seconds: 0,
    persistent: true,
  },
  realtime: {
    pending_changes: 0,
    latest_at: null,
  },
  views: [],
};

const directoryResources = [
  {
    id: primaryResourceId,
    object_type: "Resource",
    resource_type: "database.postgresql-flexible-server",
    name: "database-primary",
    location: "koreacentral",
    resource_group: "example-runtime",
    status: "Ready",
    last_seen: "2026-09-14T06:58:00Z",
    selected: false,
  },
  {
    id: duplicateResourceId,
    object_type: "Resource",
    resource_type: "database.postgresql-flexible-server",
    name: "database-primary",
    location: "koreacentral",
    resource_group: "example-recovery",
    status: "Ready",
    last_seen: "2026-09-14T06:58:00Z",
    selected: false,
  },
  {
    id: "mock:resource:billing-api",
    object_type: "Resource",
    resource_type: "application.container-app",
    name: "billing-api",
    location: "koreacentral",
    resource_group: "example-apps",
    status: "Ready",
    last_seen: "2026-09-14T06:58:00Z",
    selected: false,
  },
];

async function respond(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installFixtures(
  page: Page,
  options: {
    readonly directoryStatus?: number;
    readonly invalidGraph?: boolean;
  } = {},
): Promise<{
  readonly graphInclude: () => string | null;
  readonly graphScope: () => string | null;
}> {
  let graphInclude: string | null = null;
  let graphScope: string | null = null;
  const handleDirectory = async (route: Route): Promise<void> => {
    if (options.directoryStatus !== undefined) {
      await respond(route, { detail: "Resource directory unavailable" }, options.directoryStatus);
      return;
    }
    const url = new URL(route.request().url());
    const search = url.searchParams.get("search")?.toLowerCase() ?? "";
    const resources = directoryResources.filter((resource) => [
      resource.name,
      resource.resource_type,
      resource.resource_group,
      resource.location,
      resource.id,
    ].some((value) => value.toLowerCase().includes(search)));
    await respond(route, {
      schema_version: "1.0.0",
      ontology_release_digest: `sha256:${"b".repeat(64)}`,
      source_generation: "resource-directory-generation",
      source_cutoff: "2026-09-14T06:58:00Z",
      search: search || null,
      resources,
      complete: true,
      truncation_reason: null,
      execution_authority: false,
      mutation_authority: false,
    });
  };
  await page.route("**/simulate/blast-radius?*", async (route) => {
    await respond(route, impactFixture);
  });
  const handleGraph = async (route: Route): Promise<void> => {
    const params = new URL(route.request().url()).searchParams;
    graphInclude = params.get("include");
    graphScope = params.get("scope");
    await respond(route, options.invalidGraph ? { snapshot_at: "invalid" } : graphFixture);
  };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/ontology/instances") {
      await handleDirectory(route);
      return;
    }
    if (path === "/inventory/graph") {
      await handleGraph(route);
      return;
    }
    await respond(route, { detail: `unmocked impact-scope route: ${path}` }, 404);
  });
  await page.route("**/ontology/instances?*", handleDirectory);
  await page.route("**/inventory/graph?*", handleGraph);
  return {
    graphInclude: () => graphInclude,
    graphScope: () => graphScope,
  };
}

async function overflowState(page: Page): Promise<{
  readonly documentFits: boolean;
  readonly contentFits: boolean;
}> {
  return page.evaluate(() => {
    const content = document.querySelector<HTMLElement>(".shell-body > main");
    return {
      documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      contentFits: content !== null && content.scrollWidth <= content.clientWidth,
    };
  });
}

test("Impact scope matches the approved workbench across supported widths", async ({
  page,
}, testInfo) => {
  const fixtures = await installFixtures(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/blast-radius?locale=en&view=stale-scope");

  await expect(page.getByRole("heading", { name: "Governance Impact scope" })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Read-only what-if");
  const simulate = page.getByRole("button", { name: "Simulate impact" });
  await expect(simulate).toBeDisabled();
  const picker = page.getByRole("combobox", { name: "Target Resource" });
  await picker.click();
  await picker.fill("database");
  const resourceOptions = page.locator(".searchable-select-popup").getByRole("option");
  await expect(resourceOptions).toHaveCount(2);
  await expect(resourceOptions.first()).toContainText("example-runtime");
  await expect(resourceOptions.last()).toContainText("example-recovery");
  await expect(simulate).toBeDisabled();
  await page.screenshot({
    path: testInfo.outputPath("impact-resource-search-1440.png"),
    animations: "disabled",
  });
  await picker.fill("example-runtime");
  await expect(resourceOptions).toHaveCount(1);
  await picker.press("ArrowDown");
  await picker.press("Enter");
  await expect(page.getByLabel("Selected target Resource")).toContainText("database-primary");
  await expect(page.getByLabel("Selected target Resource")).toContainText("example-runtime");
  await expect(page.getByLabel("Selected target Resource")).toContainText(primaryResourceId);
  await expect(page).not.toHaveURL(/view=stale-scope/);
  const runtimeCalls = page.getByRole("checkbox", { name: "runtime_calls" });
  await page.locator(".impact-query-check").filter({ hasText: "runtime_calls" }).click();
  await expect(runtimeCalls).toBeChecked();
  await expect(simulate).toBeEnabled();
  await simulate.click();
  await expect(page).toHaveURL(/target=%2Fsubscriptions%2Fexample-subscription/);
  await expect(page).toHaveURL(/runtime_calls/);
  await expect(page.locator(".blast-summary-metric")).toHaveCount(4);
  await expect(page.locator(".blast-summary-metric").last()).toContainText("Partial");
  await expect(page.locator(".blast-traversal-contract")).toContainText(
    "1 known unavailable",
  );
  await expect(page.locator(".blast-impact-node")).toHaveCount(6);
  await expect(page.locator(".blast-impact-node[aria-pressed=true]")).toContainText(
    "database-primary",
  );
  await expect(page.locator(".blast-impact-inspector")).toContainText(
    "Configuration observed",
  );
  await expect(page.locator(".blast-impact-inspector")).toContainText(
    "Independently verified",
  );

  const desktop = await page.evaluate(() => {
    const graph = document.querySelector<HTMLElement>(".blast-impact-graph");
    const inspector = document.querySelector<HTMLElement>(".blast-impact-inspector");
    const nodes = [...document.querySelectorAll<HTMLElement>(".blast-impact-node")]
      .map((node) => {
        const bounds = node.getBoundingClientRect();
        return {
          name: node.textContent?.trim() ?? "",
          x: bounds.x,
          y: bounds.y,
          width: bounds.width,
          height: bounds.height,
        };
      });
    const overlaps: string[][] = [];
    for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
        const left = nodes[leftIndex];
        const right = nodes[rightIndex];
        if (left === undefined || right === undefined) continue;
        if (
          left.x < right.x + right.width
          && left.x + left.width > right.x
          && left.y < right.y + right.height
          && left.y + left.height > right.y
        ) {
          overlaps.push([left.name, right.name]);
        }
      }
    }
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d", { willReadFrequently: true })!;
    const rgba = (value: string): number[] => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data];
    };
    const luminance = (color: number[]): number => color.slice(0, 3)
      .map((value) => {
        const channel = value / 255;
        return channel <= 0.04045
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4;
      })
      .reduce(
        (sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index]!,
        0,
      );
    const background = (element: Element): number[] => {
      let current: Element | null = element;
      while (current !== null) {
        const color = rgba(getComputedStyle(current).backgroundColor);
        if (color[3] === 255) return color;
        current = current.parentElement;
      }
      return [255, 255, 255, 255];
    };
    const contrastFailures = [...document.querySelectorAll<HTMLElement>(
      ".blast-readonly-banner, .blast-summary-metric > span, "
      + ".blast-summary-metric > small, .blast-impact-legend, "
      + ".blast-impact-node, .blast-impact-node small, "
      + ".blast-impact-inspector-head p, .blast-impact-facts dt",
    )].flatMap((element) => {
      const foreground = luminance(rgba(getComputedStyle(element).color));
      const backdrop = luminance(background(element));
      const ratio = (Math.max(foreground, backdrop) + 0.05)
        / (Math.min(foreground, backdrop) + 0.05);
      return ratio + 0.01 < 4.5
        ? [{ text: element.textContent?.trim().slice(0, 60), ratio }]
        : [];
    });
    return {
      graph: graph?.getBoundingClientRect().toJSON(),
      inspector: inspector?.getBoundingClientRect().toJSON(),
      nodeTargets: nodes.map(({ width, height }) => ({ width, height })),
      overlaps,
      contrastFailures,
    };
  });
  expect(desktop.graph?.width).toBeGreaterThan(desktop.inspector?.width ?? Number.MAX_VALUE);
  expect(desktop.nodeTargets.every(({ width, height }) => width >= 44 && height >= 44)).toBe(
    true,
  );
  expect(desktop.overlaps).toEqual([]);
  expect(desktop.contrastFailures).toEqual([]);
  expect(await overflowState(page)).toEqual({ documentFits: true, contentFits: true });

  await page.getByRole("button", { name: /billing-api/ }).click();
  await expect(page.locator(".blast-impact-inspector h4")).toContainText("billing-api");
  await expect(page.locator(".blast-impact-inspector")).toContainText(
    "A current reviewed provider configuration and deterministic cross-check confirm this edge",
  );
  await expect(page.locator(".blast-impact-inspector")).toContainText(
    "azure-resource-graph",
  );
  await expect(page.locator(".blast-impact-inspector")).toContainText(
    "test.relationship",
  );
  const coverageGap = page.getByRole("button", { name: /traffic-source/ });
  await coverageGap.focus();
  await expect(coverageGap).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".blast-impact-inspector")).toContainText("Coverage gap");
  await expect(page.locator(".blast-impact-inspector")).toContainText("Evidence unavailable");
  await expect(page.locator(".blast-impact-inspector")).toContainText(
    "Collect and promote relationship evidence",
  );
  expect(
    Number.parseFloat(await coverageGap.evaluate((element) => getComputedStyle(element).outlineWidth)),
  ).toBeGreaterThanOrEqual(2);

  await page.getByRole("button", { name: "Table", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Reached resources (6)" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Edges traversed (5)" })).toBeVisible();
  await expect(page.locator(".blast-table-view")).toContainText("Configuration observed");
  await expect(page.locator(".blast-table-view")).toContainText("Independently verified");
  await expect(page.locator(".blast-table-view")).toContainText("Evidence unavailable");
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await expect(page.locator(".blast-map-wrap")).toBeVisible();
  expect(fixtures.graphInclude()).toContain("runtime_calls");
  expect(fixtures.graphScope()).toBeNull();
  await page.getByRole("button", { name: "Impact", exact: true }).click();

  await page.locator(".shell-body > main").evaluate((element) =>
    element.scrollTo({ top: 0, left: 0, behavior: "auto" }));
  await page.screenshot({
    path: testInfo.outputPath("impact-scope-final-1440.png"),
    animations: "disabled",
  });
  await page.locator(".blast-impact-layout").screenshot({
    path: testInfo.outputPath("impact-scope-workbench-1440.png"),
    animations: "disabled",
  });

  await page.setViewportSize({ width: 993, height: 641 });
  const constrained = await page.evaluate(() => {
    const graph = document.querySelector<HTMLElement>(".blast-impact-graph")
      ?.getBoundingClientRect();
    const inspector = document.querySelector<HTMLElement>(".blast-impact-inspector")
      ?.getBoundingClientRect();
    return {
      graph: graph?.toJSON(),
      inspector: inspector?.toJSON(),
    };
  });
  expect(Math.abs((constrained.graph?.x ?? 0) - (constrained.inspector?.x ?? 1))).toBeLessThan(
    1,
  );
  expect(constrained.inspector?.y ?? 0).toBeGreaterThanOrEqual(
    (constrained.graph?.bottom ?? Number.MAX_VALUE) - 1,
  );
  expect(await overflowState(page)).toEqual({ documentFits: true, contentFits: true });

  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = await page.evaluate(() => {
    const fields = [...document.querySelectorAll<HTMLElement>(
      ".impact-query-input, .impact-query-check, .impact-query-submit, "
      + ".blast-impact-node, .blast-radius-route .segmented-control button",
    )];
    const header = document.querySelector<HTMLElement>(".blast-radius-route > .page-header")!;
    const headerText = header.querySelector<HTMLElement>(".page-header-text")!;
    const headerActions = header.querySelector<HTMLElement>(".page-header-actions")!;
    const columns = getComputedStyle(
      document.querySelector<HTMLElement>(".impact-query-grid")!,
    ).gridTemplateColumns;
    return {
      columns,
      targets: fields.map((field) => field.getBoundingClientRect().height),
      header: {
        bounds: header.getBoundingClientRect().toJSON(),
        textBounds: headerText.getBoundingClientRect().toJSON(),
        actionsBounds: headerActions.getBoundingClientRect().toJSON(),
      },
    };
  });
  expect(mobile.columns.split(" ")).toHaveLength(1);
  expect(mobile.targets.every((height) => height >= 44)).toBe(true);
  expect(mobile.header.bounds.height).toBeLessThan(220);
  expect(mobile.header.actionsBounds.y).toBeLessThan(240);
  expect(await overflowState(page)).toEqual({ documentFits: true, contentFits: true });
  await page.locator(".shell-body > main").evaluate((element) =>
    element.scrollTo({ top: 0, left: 0, behavior: "auto" }));
  await page.screenshot({
    path: testInfo.outputPath("impact-scope-final-390.png"),
    animations: "disabled",
  });
  await page.locator(".blast-impact-layout").screenshot({
    path: testInfo.outputPath("impact-scope-workbench-390.png"),
    animations: "disabled",
  });
  await page.locator(".blast-impact-graph").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("impact-scope-workbench-viewport-390.png"),
    animations: "disabled",
  });
  const spacingStyle = await page.addStyleTag({
    content: `
      .blast-radius-route * {
        line-height: 1.5 !important;
        letter-spacing: .12em !important;
        word-spacing: .16em !important;
      }
      .blast-radius-route p { margin-bottom: 2em !important; }
    `,
  });
  expect(await overflowState(page)).toEqual({ documentFits: true, contentFits: true });
  await spacingStyle.evaluate((element) => element.parentNode?.removeChild(element));
  await page.getByRole("button", { name: "Change" }).click();
  const mobilePicker = page.getByRole("combobox", { name: "Target Resource" });
  await mobilePicker.fill("database");
  await expect(page.locator(".searchable-select-popup").getByRole("option")).toHaveCount(2);
  const mobilePopup = await page.locator(".searchable-select-popup").boundingBox();
  expect(mobilePopup?.x ?? -1).toBeGreaterThanOrEqual(8);
  expect(mobilePopup?.width ?? Number.MAX_VALUE).toBeLessThanOrEqual(374);
  expect((mobilePopup?.x ?? 0) + (mobilePopup?.width ?? Number.MAX_VALUE)).toBeLessThanOrEqual(
    382,
  );
  await page.screenshot({
    path: testInfo.outputPath("impact-resource-search-390.png"),
    animations: "disabled",
  });

  await page.goto(
    `/blast-radius?locale=ko&target=${encodeURIComponent(primaryResourceId)}&depth=2&links=contains,depends_on,runtime_calls`,
  );
  await expect(page.getByRole("heading", { name: /영향 범위/ })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("읽기 전용 가상 분석");
  await expect(page.locator(".blast-impact-node")).toHaveCount(6);
  expect(await overflowState(page)).toEqual({ documentFits: true, contentFits: true });
  await page.screenshot({
    path: testInfo.outputPath("impact-scope-final-ko-390.png"),
    animations: "disabled",
  });
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  const targetNode = page.getByRole("button", { name: /database-primary/ });
  await targetNode.focus();
  await expect(targetNode).toBeFocused();
  expect(await targetNode.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe(
    "none",
  );

  await testInfo.attach("impact-scope-geometry", {
    body: JSON.stringify({ desktop, constrained, mobile }),
    contentType: "application/json",
  });
});

test("Impact scope retains exact-id entry when Resource search is unavailable", async ({
  page,
}) => {
  await installFixtures(page, { directoryStatus: 503 });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/blast-radius?locale=en");

  const picker = page.getByRole("combobox", { name: "Target Resource" });
  await picker.click();
  await expect(page.getByText(
    "Resource search unavailable: HTTP 503",
    { exact: true },
  )).toBeVisible();

  await page.locator(".searchable-select-empty-action").getByRole("button").click();
  await page.getByLabel("Exact Resource id").fill(primaryResourceId);
  await page.getByRole("button", { name: "Use this id" }).click();

  await expect(page.getByLabel("Selected target Resource")).toContainText(primaryResourceId);
  await expect(page.getByLabel("Selected target Resource")).toContainText(
    "Resource details are unavailable",
  );
  await expect(page.getByRole("button", { name: "Simulate impact" })).toBeEnabled();
});

test("Impact scope Map fails closed on a malformed graph response", async ({ page }) => {
  await installFixtures(page, { invalidGraph: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(
    `/blast-radius?locale=en&target=${encodeURIComponent(primaryResourceId)}`
    + "&depth=2&links=contains,depends_on,runtime_calls",
  );
  await expect(page.locator(".blast-impact-layout")).toBeVisible();

  await page.getByRole("button", { name: "Map", exact: true }).click();

  await expect(page.getByText(
    "Map unavailable: the architecture map response is malformed",
    { exact: true },
  )).toBeVisible();
  await expect(page.locator(".blast-map-wrap")).toHaveCount(0);
});
