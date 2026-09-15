import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";

const graph = {
  snapshot_at: "2026-08-22T00:00:00Z",
  freshness: "fresh",
  scope: null,
  depth: 4,
  included_link_types: ["contains", "attached_to", "depends_on", "peered_with"],
  truncated: false,
  active_view: "fdai-control-plane",
  views: [
    {
      id: "fdai-control-plane",
      label: "FDAI control plane",
      kind: "fdai",
      classification: "ownership_tag",
      description: "Example control plane",
      root_resource_id: "subscription",
    },
    {
      id: "example-service",
      label: "Example service",
      kind: "service",
      classification: "service_tag",
      description: "Example service scope",
      root_resource_id: "group",
    },
  ],
  resources: [
    { id: "subscription", type: "subscription", name: "Example subscription", status: "unknown" },
    { id: "group", type: "resource-group", name: "Example workload", status: "unknown", parent_id: "subscription" },
    { id: "vnet", type: "network.vnet", name: "Example network", status: "healthy", parent_id: "group" },
    { id: "ingress", type: "network.subnet", name: "Ingress subnet", status: "healthy", parent_id: "group" },
    { id: "workload", type: "network.subnet", name: "Workload subnet", status: "healthy", parent_id: "group" },
    { id: "private", type: "network.subnet", name: "Private endpoint subnet", status: "healthy", parent_id: "group" },
    { id: "peer-vnet", type: "network.vnet", name: "Shared services network", status: "healthy", parent_id: "group" },
    { id: "peer-subnet", type: "network.subnet", name: "Firewall subnet", status: "healthy", parent_id: "group" },
    { id: "gateway", type: "network.application-gateway", name: "Application Gateway", status: "healthy", parent_id: "group" },
    { id: "interface", type: "network.interface", name: "Workload interface", status: "healthy", parent_id: "group" },
    { id: "vm", type: "compute.vm", name: "Workload VM", status: "healthy", parent_id: "group" },
    { id: "endpoint", type: "network.private-endpoint", name: "Private Endpoint", status: "healthy", parent_id: "group" },
    { id: "firewall", type: "network.firewall", name: "Azure Firewall", status: "healthy", parent_id: "group" },
  ],
  links: [
    { source: "subscription", target: "group", type: "contains" },
    { source: "group", target: "vnet", type: "contains" },
    { source: "vnet", target: "ingress", type: "contains" },
    { source: "vnet", target: "workload", type: "contains" },
    { source: "vnet", target: "private", type: "contains" },
    { source: "group", target: "peer-vnet", type: "contains" },
    { source: "peer-vnet", target: "peer-subnet", type: "contains" },
    { source: "vnet", target: "peer-vnet", type: "peered_with", direction: "bidirectional" },
    { source: "gateway", target: "ingress", type: "attached_to" },
    { source: "gateway", target: "vm", type: "depends_on" },
    { source: "interface", target: "workload", type: "attached_to" },
    { source: "vm", target: "interface", type: "attached_to" },
    { source: "vm", target: "endpoint", type: "depends_on" },
    { source: "endpoint", target: "private", type: "attached_to" },
    { source: "firewall", target: "peer-subnet", type: "attached_to" },
    { source: "firewall", target: "vm", type: "depends_on" },
  ],
};

const impact = {
  schema_version: "1.0.0",
  ontology_release_digest: `sha256:${"a".repeat(64)}`,
  source_generation: "generation-1",
  source_cutoff: graph.snapshot_at,
  target: "vm",
  traversal_depth: 2,
  traversal_links: ["depends_on"],
  reached: [
    { resource_id: "vm", depth: 0, via_link_type: null },
    { resource_id: "endpoint", depth: 1, via_link_type: "depends_on" },
  ],
  edges: [{
    source: "vm",
    target: "endpoint",
    link_type: "depends_on",
    depth: 1,
    verification_status: "unverified",
  }],
  affected_count: 1,
  complete: true,
  truncated_at_depth: false,
  truncation_reasons: [],
  execution_authority: false,
  mutation_authority: false,
};

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installArchitectureFixture(
  page: Page,
  fixture: typeof graph & { readonly truncation_reasons?: readonly string[] } = graph,
  impactFixture: typeof impact | null = null,
): Promise<void> {
  const handleApi = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "inventory",
          source: "browser-test-fixture",
          routes: ["/inventory/graph"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: false,
          synthetic: true,
          reason: null,
          last_observed_at: fixture.snapshot_at,
        }],
      });
      return;
    }
    if (path === "/inventory/graph") {
      await json(route, {
        ...fixture,
        active_view: url.searchParams.get("scope") ?? fixture.active_view,
      });
      return;
    }
    if (path.startsWith("/simulate/blast-radius") && impactFixture) {
      await json(route, impactFixture);
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/system/data-sources", handleApi);
  await page.route("**/inventory/graph*", handleApi);
  await page.route("**/simulate/blast-radius*", handleApi);
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

async function settleArchitectureGraph(page: Page): Promise<void> {
  await page.locator(".architecture-topology-svg").evaluate(
    () => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }),
  );
}

async function selectResource(page: Page, name: string): Promise<void> {
  const resourceSearch = page.getByRole("combobox", { name: "Resource" });
  await resourceSearch.click();
  await resourceSearch.fill(name);
  await resourceSearch.press("ArrowDown");
  await resourceSearch.press("Enter");
}

type CaptureName =
  | "topology-overview"
  | "topology-selected"
  | "topology-constrained"
  | "topology-mobile"
  | "topology-minimum"
  | "topology-korean-adaptive"
  | "network-desktop"
  | "network-constrained"
  | "network-mobile"
  | "impact-desktop";

async function captureArchitectureViewport(
  page: Page,
  testInfo: TestInfo,
  name: CaptureName,
): Promise<void> {
  const screenshot = await page.screenshot({ fullPage: true });
  const metrics = await page.evaluate(() => {
    const bounds = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    };
    const html = document.documentElement;
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: { clientWidth: html.clientWidth, scrollWidth: html.scrollWidth },
      toolbar: bounds(".architecture-toolbar"),
      workbench: bounds(".architecture-workbench"),
      graph: bounds(".architecture-topology-scroll"),
      inspector: bounds(".architecture-inspector:not([hidden])"),
      resourceSearch: bounds(".architecture-toolbar .searchable-select-input"),
      graphTargets: [...document.querySelectorAll(".architecture-topology-tools button")].map(
        (element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        },
      ),
      modeTargets: [...document.querySelectorAll(".architecture-mode-control button")].map(
        (element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        },
      ),
      legacyCanvasCount: document.querySelectorAll(".architecture-map").length,
    };
  });
  const metricsJson = JSON.stringify(metrics, null, 2);
  await testInfo.attach(name, { body: screenshot, contentType: "image/png" });
  await testInfo.attach(`${name}-metrics`, {
    body: Buffer.from(metricsJson),
    contentType: "application/json",
  });
  const captureRoot = process.env.FDAI_NETWORK_VISUAL_CAPTURE_ROOT;
  if (!captureRoot) return;
  await mkdir(captureRoot, { recursive: true });
  await writeFile(`${captureRoot}/${name}.png`, screenshot);
  await writeFile(`${captureRoot}/${name}.json`, metricsJson);
}

test("shows the bounded topology overview and keeps selection in one workbench", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  await installArchitectureFixture(page);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/architecture");
  await expect(page.locator(".architecture-topology-svg")).toBeVisible();
  await settleArchitectureGraph(page);
  await expect(page.locator(".architecture-topology-region")).toHaveCount(1);
  await expect(page.locator(".architecture-topology-node")).toHaveCount(1);
  await expect(page.locator(".architecture-topology-node-type"))
    .toContainText("11 Resources - 0 external links");
  await expect(page.locator(".architecture-topology-unavailable")).toHaveCount(0);
  const overviewPositions = await page.locator(".architecture-topology-resource").evaluateAll(
    (resources) => resources.map((resource) =>
      resource.getAttribute("transform")
      ?? resource.querySelector("rect")?.getAttribute("x")
      ?? ""),
  );
  expect(new Set(overviewPositions).size).toBe(overviewPositions.length);
  await expect(page.locator(".architecture-map")).toHaveCount(0);
  await expect(page.locator(".architecture-coverage")).toContainText("13 returned - 2 shown");
  await expect(page.locator(".architecture-coverage")).not.toHaveAttribute("open");
  expect((await page.locator(".architecture-coverage").boundingBox())?.height)
    .toBeLessThanOrEqual(56);
  await expect(page.locator(".architecture-inspector")).toBeHidden();
  await expect(page.getByRole("button", { name: "Show Inspector" })).toBeVisible();
  const scope = page.getByRole("combobox", { name: "Scope" });
  await expect(scope).toHaveValue("fdai-control-plane");
  await scope.selectOption("example-service");
  await expect(page).toHaveURL(/view=example-service/);
  await expect(scope).toHaveValue("example-service");
  await scope.selectOption("fdai-control-plane");
  await expect(page).toHaveURL(/view=fdai-control-plane/);
  await page.getByRole("button", { name: "Enter full screen" }).click();
  await expect(page.locator(".architecture-topology-graph")).toHaveClass(/is-fullscreen/);
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect(page.locator(".architecture-topology-graph")).not.toHaveClass(/is-fullscreen/);
  await page.locator('.architecture-topology-node[data-resource-id="group"]').click();
  await expect(page).toHaveURL(/resource=group/);
  const resourceSearch = page.getByRole("combobox", { name: "Resource" });
  await resourceSearch.click();
  await resourceSearch.fill("Scope overview");
  await resourceSearch.press("ArrowDown");
  await resourceSearch.press("Enter");
  await expect(page).not.toHaveURL(/resource=/);
  const graphScroll = page.locator(".architecture-topology-scroll");
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await graphScroll.evaluate((element) => {
    element.scrollLeft = 0;
    element.scrollTop = 10;
  });
  const panStart = await graphScroll.evaluate((element) => ({
    left: element.scrollLeft,
    top: element.scrollTop,
  }));
  const graphBox = await graphScroll.boundingBox();
  await page.mouse.move((graphBox?.x ?? 0) + 110, (graphBox?.y ?? 0) + 120);
  await page.mouse.down();
  await page.mouse.move((graphBox?.x ?? 0) + 50, (graphBox?.y ?? 0) + 60, { steps: 5 });
  await page.mouse.up();
  const panEnd = await graphScroll.evaluate((element) => ({
    left: element.scrollLeft,
    top: element.scrollTop,
  }));
  expect(panEnd.top).toBeGreaterThan(panStart.top);
  await expect(page.getByRole("combobox", { name: "Resource" })).toHaveValue("Scope overview");
  await page.getByRole("button", { name: "Fit map" }).click();
  await assertNoHorizontalOverflow(page);
  await captureArchitectureViewport(page, testInfo, "topology-overview");

  const selectionStartedAt = Date.now();
  await selectResource(page, "Workload VM");
  await expect(page).toHaveURL(/resource=vm/);
  await expect(page.locator('.architecture-topology-node[data-resource-id="vm"]')).toHaveClass(/is-selected/);
  const selectionDurationMs = Date.now() - selectionStartedAt;
  expect(selectionDurationMs).toBeLessThan(1_000);
  const performanceEvidence = JSON.stringify({
    budget_ms: 1_000,
    observed_ms: selectionDurationMs,
    venue: "isolated-playwright",
  }, null, 2);
  await testInfo.attach("selection-feedback-budget", {
    body: Buffer.from(performanceEvidence),
    contentType: "application/json",
  });
  const captureRoot = process.env.FDAI_NETWORK_VISUAL_CAPTURE_ROOT;
  if (captureRoot) {
    await writeFile(`${captureRoot}/selection-feedback.json`, performanceEvidence);
  }
  await page.reload();
  await expect(page).toHaveURL(/resource=vm/);
  await expect(page.locator('.architecture-topology-node[data-resource-id="vm"]')).toHaveClass(/is-selected/);
  await expect(page.locator(".architecture-inspector")).toBeVisible();
  await expect(page.locator(".architecture-inspector")).toContainText("Workload VM");
  await page.getByRole("button", { name: "Links", exact: true }).click();
  await expect(page.locator(".architecture-relationships li")).toHaveCount(4);
  await page.locator(".architecture-inspector")
    .getByRole("button", { name: "Overview", exact: true }).click();
  await page.getByRole("button", { name: "Hide Inspector" }).click();
  await expect(page.locator(".architecture-workbench")).toHaveClass(/is-inspector-collapsed/);
  await page.getByRole("button", { name: "Show Inspector" }).click();
  await expect(page.locator(".architecture-inspector")).toBeVisible();

  const firstFocusable = page.locator('.architecture-topology-resource[tabindex="0"]');
  await firstFocusable.focus();
  const firstFocusedId = await firstFocusable.getAttribute("data-resource-id");
  await firstFocusable.press("ArrowRight");
  const nextFocusedId = await page.evaluate(
    () => document.activeElement?.getAttribute("data-resource-id"),
  );
  expect(nextFocusedId).not.toBe(firstFocusedId);
  for (const button of await page.locator(".architecture-topology-tools button").all()) {
    expect((await button.boundingBox())?.height).toBeGreaterThanOrEqual(34);
  }
  await assertNoHorizontalOverflow(page);
  await captureArchitectureViewport(page, testInfo, "topology-selected");

  await page.setViewportSize({ width: 993, height: 641 });
  await settleArchitectureGraph(page);
  await assertNoHorizontalOverflow(page);
  const constrainedGraph = await page.locator(".architecture-topology-scroll").boundingBox();
  const constrainedInspector = await page.locator(".architecture-inspector").boundingBox();
  expect(constrainedInspector?.y).toBeGreaterThanOrEqual(
    (constrainedGraph?.y ?? 0) + (constrainedGraph?.height ?? 0),
  );
  await captureArchitectureViewport(page, testInfo, "topology-constrained");

  await page.setViewportSize({ width: 390, height: 844 });
  await settleArchitectureGraph(page);
  await assertNoHorizontalOverflow(page);
  await expect(page.getByRole("combobox", { name: "Resource" })).toHaveCSS("height", "44px");
  for (const button of await page.locator(".architecture-topology-tools button").all()) {
    expect((await button.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  }
  await captureArchitectureViewport(page, testInfo, "topology-mobile");

  await page.setViewportSize({ width: 320, height: 844 });
  await settleArchitectureGraph(page);
  await assertNoHorizontalOverflow(page);
  await expect(page.locator(".page-header-domain")).toBeHidden();
  await captureArchitectureViewport(page, testInfo, "topology-minimum");
});

test("keeps observed Network paths and sanitized exports inside the Inspector", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  await installArchitectureFixture(page);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/architecture");
  await page.getByRole("button", { name: "Network", exact: true }).click();
  await expect(page).toHaveURL(/mode=network/);
  await page.reload();
  await expect(page).toHaveURL(/mode=network/);
  await expect(page.locator(".architecture-topology-graph.is-network")).toBeVisible();
  await expect(page.locator(".architecture-inspector")).toBeVisible();
  await expect(page.locator(".architecture-network-path-panel")).toBeVisible();
  await expect(page.locator(".architecture-topology-region")).toHaveCount(8);
  await expect(page.locator(".architecture-topology-node")).toHaveCount(4);
  await expect(page.locator(".architecture-topology-node-icon")).toHaveCount(4);
  await expect(page.locator(".architecture-topology-link-path")).toHaveCount(5);
  await expect(page.locator(".architecture-topology-endpoint")).toHaveCount(4);
  await expect(page.locator(".architecture-topology-link.is-peered_with")).toHaveCount(1);
  const networkNodePositions = await page.locator(".architecture-topology-node").evaluateAll(
    (nodes) => nodes.map((node) => node.getAttribute("transform")),
  );
  expect(new Set(networkNodePositions).size).toBe(networkNodePositions.length);
  const peeringPath = page.locator(".architecture-topology-link.is-peered_with .architecture-topology-link-path");
  expect((await peeringPath.getAttribute("d"))?.match(/\bL/g)).toHaveLength(1);
  const cardHitOwners = await page.locator(".architecture-topology-node").evaluateAll((nodes) =>
    nodes.map((node) => {
      const box = node.getBoundingClientRect();
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
      return {
        expected: node.getAttribute("data-resource-id"),
        actual: hit?.closest(".architecture-topology-node")?.getAttribute("data-resource-id") ?? null,
      };
    }));
  expect(cardHitOwners.every(({ actual, expected }) => actual === expected)).toBe(true);

  const pathPanel = page.locator(".architecture-network-path-panel");
  await pathPanel.getByRole("combobox").nth(0).selectOption("gateway");
  await pathPanel.getByRole("combobox").nth(1).selectOption("endpoint");
  await expect(page.locator(".architecture-network-path-result")).toContainText("Observed path");
  await expect(page.locator(".architecture-network-path-hops li")).toHaveCount(2);
  await expect(page.locator('.architecture-topology-node[data-resource-id="vm"]')).toBeVisible();
  await pathPanel.getByRole("checkbox", { name: "Gateways" }).uncheck();
  await expect(page.locator('.architecture-topology-node[data-resource-id="gateway"]')).toBeVisible();
  await expect(page.locator(".architecture-network-path-result")).toContainText("Observed path");
  await expect(page.locator(".architecture-topology-resource.is-muted")).not.toHaveCount(0);
  await assertNoHorizontalOverflow(page);
  await captureArchitectureViewport(page, testInfo, "network-desktop");

  const svgDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "SVG", exact: true }).click();
  const downloadedSvg = await svgDownload;
  expect(downloadedSvg.suggestedFilename()).toBe("observed-network-topology.svg");
  const svgPath = await downloadedSvg.path();
  expect(svgPath).not.toBeNull();
  const svgSource = await readFile(svgPath!, "utf8");
  expect(svgSource).toContain("data:image/svg+xml;base64,");
  expect(svgSource).toContain('data-edge-index="');
  expect(svgSource).toContain('data-relationship-type="peered_with"');
  expect(svgSource).toContain('marker-start="url(#network-arrow-start)"');
  expect(svgSource).toContain("<path");
  expect(svgSource).not.toContain("<line");
  const captureRoot = process.env.FDAI_NETWORK_VISUAL_CAPTURE_ROOT;
  if (captureRoot) await writeFile(`${captureRoot}/network-export.svg`, svgSource);

  const pngDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "PNG", exact: true }).click();
  const downloadedPng = await pngDownload;
  expect(downloadedPng.suggestedFilename()).toBe("observed-network-topology.png");
  const pngPath = await downloadedPng.path();
  expect(pngPath).not.toBeNull();
  expect((await stat(pngPath!)).size).toBeGreaterThan(10_000);
  if (captureRoot) await writeFile(`${captureRoot}/network-export.png`, await readFile(pngPath!));

  await page.setViewportSize({ width: 993, height: 641 });
  await settleArchitectureGraph(page);
  await assertNoHorizontalOverflow(page);
  await captureArchitectureViewport(page, testInfo, "network-constrained");

  await page.setViewportSize({ width: 390, height: 844 });
  await settleArchitectureGraph(page);
  await assertNoHorizontalOverflow(page);
  for (const target of await page.locator(".architecture-topology-node-target").all()) {
    const box = await target.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
  for (const button of await page.locator(".architecture-network-export button").all()) {
    const box = await button.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
  await captureArchitectureViewport(page, testInfo, "network-mobile");
});

test("keeps stale and partial inventory explicit in the workbench", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Evidence-state gate runs once.");
  await installArchitectureFixture(page, {
    ...graph,
    freshness: "stale",
    truncated: true,
    truncation_reasons: ["limit"],
    resources: graph.resources.map((resource) => {
      if (resource.id === "subscription") return { ...resource, w: 100, h: 24 };
      if (resource.id === "group") return { ...resource, w: 96, h: 20 };
      return resource;
    }),
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/architecture");
  await expect(page.locator(".architecture-toolbar-status")).toContainText("stale");
  await expect(page.locator(".architecture-coverage")).toContainText("Partial returned projection");
  await page.getByRole("button", { name: "Show Inspector" }).click();
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await expect(page.locator(".architecture-source-facts")).toContainText("Partial");
  await expect(page.locator(".architecture-source-warning")).toContainText(
    "Counts and relationships describe only the returned records.",
  );
  const graphScroll = page.locator(".architecture-topology-scroll");
  await settleArchitectureGraph(page);
  await graphScroll.evaluate((element) => {
    element.scrollLeft = 300;
    element.scrollTop = 120;
  });
  await page.getByRole("button", { name: "Fit map" }).click();
  await expect.poll(() => graphScroll.evaluate((element) => element.scrollLeft)).toBe(0);
  await graphScroll.evaluate((element) => {
    element.scrollLeft = 240;
    element.scrollTop = 100;
  });
  await page.getByRole("button", { name: "Fit map" }).click();
  await expect.poll(() => graphScroll.evaluate((element) => element.scrollLeft)).toBe(0);
});

test("preserves Korean and adaptive preferences on a narrow screen", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Adaptive presentation gate runs once.");
  await installArchitectureFixture(page);
  await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/architecture?locale=ko");
  await expect(page.getByRole("heading", { name: "아키텍처" })).toBeVisible();
  await expect(page.locator(".architecture-coverage")).toContainText("표현 범위");
  await page.getByRole("button", { name: "네트워크", exact: true }).click();
  expect(new URL(page.url()).searchParams.get("locale")).toBe("ko");
  await page.reload();
  await expect(page.getByRole("heading", { name: "아키텍처" })).toBeVisible();
  await page.addStyleTag({
    content: `
      html { font-size: 200% !important; }
      p { line-height: 1.5 !important; margin-block-end: 2em !important; }
      * { letter-spacing: .12em !important; word-spacing: .16em !important; }
    `,
  });
  await settleArchitectureGraph(page);
  await assertNoHorizontalOverflow(page);
  await expect(page.getByRole("combobox", { name: "리소스" })).toBeVisible();
  await expect(page.getByRole("button", { name: "전체 화면 시작" })).toBeVisible();
  await captureArchitectureViewport(page, testInfo, "topology-korean-adaptive");
});

test("renders Impact scope with the shared SVG instead of the retired Canvas", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Impact renderer gate runs once.");
  await installArchitectureFixture(page, graph, impact);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/blast-radius?target=vm&depth=2&links=depends_on&result=map");

  await expect(page.locator(".architecture-topology-graph.is-impact")).toBeVisible();
  await expect(page.locator(".architecture-map")).toHaveCount(0);
  await expect(page.locator('.architecture-topology-node[data-resource-id="vm"]'))
    .toHaveClass(/is-selected/);
  await expect(page.locator(".architecture-topology-resource.is-muted")).not.toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open full architecture" }))
    .toHaveAttribute("href", /resource=vm/);
  await assertNoHorizontalOverflow(page);
  await captureArchitectureViewport(page, testInfo, "impact-desktop");
});
