import { expect, test, type Page, type Route } from "@playwright/test";

const releaseDigest = `sha256:${"a".repeat(64)}`;
type Rgb = readonly [number, number, number];

function cssRgb(value: string): Rgb {
  const channels = value.match(/[\d.]+/g)?.slice(0, 3).map(Number);
  if (channels?.length !== 3) throw new Error(`unsupported CSS color: ${value}`);
  if (value.startsWith("color(srgb")) {
    return [channels[0]!, channels[1]!, channels[2]!];
  }
  return [channels[0]! / 255, channels[1]! / 255, channels[2]! / 255];
}

function contrastRatio(first: string, second: string): number {
  const luminance = (color: string): number => {
    const linear = cssRgb(color).map((channel) =>
      channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
    return 0.2126 * linear[0]! + 0.7152 * linear[1]! + 0.0722 * linear[2]!;
  };
  const bright = Math.max(luminance(first), luminance(second));
  const dark = Math.min(luminance(first), luminance(second));
  return (bright + 0.05) / (dark + 0.05);
}

function resource(
  id: string,
  name: string,
  resourceType: string,
  selected: boolean,
) {
  return {
    id,
    object_type: "Resource",
    resource_type: resourceType,
    name,
    location: "example-region",
    resource_group: "example-group",
    status: selected ? "Running" : null,
    last_seen: "2026-09-14T00:00:00Z",
    selected,
  };
}

function instanceDirectory() {
  return {
    schema_version: "1.0.0",
    ontology_release_digest: releaseDigest,
    source_generation: "example-generation",
    source_cutoff: "2026-09-14T00:00:00Z",
    search: null,
    resources: [
      resource("root", "Example AKS cluster", "kubernetes-cluster", false),
      resource(
        "environment",
        "Example node pool",
        "kubernetes-node-pool",
        false,
      ),
    ],
    complete: false,
    truncation_reason: "resource_limit",
    execution_authority: false,
    mutation_authority: false,
  };
}

function instanceExploration() {
  return {
    schema_version: "1.3.0",
    ontology_release_digest: releaseDigest,
    source_generation: "example-generation",
    source_cutoff: "2026-09-14T00:00:00Z",
    root_id: "root",
    depth: 8,
    link_types: ["depends_on"],
    resources: [
      resource("root", "Example AKS cluster", "kubernetes-cluster", true),
      resource(
        "environment",
        "Example node pool",
        "kubernetes-node-pool",
        false,
      ),
    ],
    links: [{
      source: "root",
      target: "environment",
      link_type: "depends_on",
      evidence: {
        status: "available",
        evidence_kind: "configuration",
        verification_status: "configuration_observed",
        source: "browser-test-fixture",
        source_property_path: "properties.managedEnvironmentId",
        mapping_id: "example-container-app-dependency",
        evidence_method: "deterministic-cross-check",
        cutoff: "2026-09-14T00:00:00Z",
        freshness_ceiling_seconds: 21600,
        complete: true,
        reason: null,
      },
    }],
    timeline: { items: [], complete: true, truncation_reason: null },
    sources: [
      {
        source: "inventory_snapshot",
        status: "available",
        observed_at: "2026-09-14T00:00:00Z",
        reason: null,
      },
      {
        source: "inventory_relationships",
        status: "available",
        observed_at: "2026-09-14T00:00:00Z",
        reason: null,
      },
      {
        source: "fdai_audit",
        status: "available",
        observed_at: "2026-09-14T00:00:00Z",
        reason: null,
      },
      {
        source: "runtime_call_graph",
        status: "unavailable",
        observed_at: null,
        reason: "endpoint_identity_projection_unavailable",
      },
      {
        source: "kubernetes_runtime_inventory",
        status: "unavailable",
        observed_at: null,
        reason: "kubernetes_source_unconfigured",
      },
      {
        source: "postgres_role_evidence",
        status: "unavailable",
        observed_at: null,
        reason: "projection_not_bound",
      },
      {
        source: "azure_resource_health",
        status: "unavailable",
        observed_at: null,
        reason: "projection_not_bound",
      },
    ],
    complete: true,
    relationship_drop_reasons: [],
    relationship_drop_classifications: [],
    truncation_reasons: [],
    execution_authority: false,
    mutation_authority: false,
  };
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installOntologyFixture(page: Page): Promise<string[]> {
  const requests: string[] = [];
  const handleApi = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    requests.push(path);
    if (path === "/ontology/instances") {
      await json(route, instanceDirectory());
      return;
    }
    if (path === "/ontology/instances/explore") {
      await json(route, instanceExploration());
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/ontology/instances*", handleApi);
  await page.route("**/ontology/instances/**", handleApi);
  return requests;
}

async function graphSurfaceGeometry(page: Page) {
  return page.locator(".ontology-instance-graph-scroll").evaluate((scroll) => {
    const direction = scroll.querySelector<HTMLElement>(".ontology-instance-direction-surface");
    const stage = scroll.querySelector<HTMLElement>(".ontology-instance-graph-stage");
    const canvas = scroll.querySelector<SVGElement>(".ontology-instance-graph-canvas");
    if (direction === null || stage === null || canvas === null) {
      throw new Error("direction background, graph stage, and graph canvas MUST render");
    }
    const selectedDirection = direction.querySelector<HTMLElement>(".is-selected");
    if (selectedDirection === null) {
      throw new Error("selected direction background MUST render");
    }
    const scrollRect = scroll.getBoundingClientRect();
    const directionRect = direction.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const canvasRect = canvas.getBoundingClientRect();
    return {
      canvasHeight: canvasRect.height,
      canvasLeft: canvasRect.left,
      canvasOffsetTop: canvasRect.top - stageRect.top,
      canvasWidth: canvasRect.width,
      directionBottom: directionRect.bottom,
      directionHeight: directionRect.height,
      directionLeft: directionRect.left,
      directionWidth: directionRect.width,
      scrollBottom: scrollRect.bottom,
      scrollHeight: scroll.clientHeight,
      stageHeight: stageRect.height,
      selectedBackground: getComputedStyle(selectedDirection).backgroundColor,
    };
  });
}

function expectDirectionSurfaceCoverage(
  geometry: Awaited<ReturnType<typeof graphSurfaceGeometry>>,
): void {
  expect(geometry.directionHeight).toBeGreaterThanOrEqual(geometry.scrollHeight);
  expect(geometry.directionBottom).toBeGreaterThanOrEqual(geometry.scrollBottom - 1);
  expect(geometry.directionHeight).toBeGreaterThanOrEqual(geometry.canvasHeight);
  expect(geometry.stageHeight).toBeGreaterThanOrEqual(geometry.scrollHeight);
  if (geometry.canvasHeight < geometry.scrollHeight) {
    expect(geometry.canvasOffsetTop).toBeCloseTo(
      (geometry.scrollHeight - geometry.canvasHeight) / 2,
      0,
    );
  }
  expect(geometry.directionLeft).toBeCloseTo(geometry.canvasLeft, 0);
  expect(geometry.directionWidth).toBeCloseTo(geometry.canvasWidth, 0);
  expect(geometry.selectedBackground).not.toBe("rgba(0, 0, 0, 0)");
}

async function expectNoDocumentOverflow(page: Page): Promise<void> {
  const dimensions = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

test("fills the selected graph viewport with continuous direction regions", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "Desktop, constrained, and mobile gates run sequentially in one scenario.",
  );
  const requests = await installOntologyFixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/ontology?view=instances&instance=root");

  await expect.poll(() =>
    requests.filter((path) => path === "/ontology/instances/explore").length).toBe(1);
  await expect(page.locator(".ontology-instance-graph-scroll")).toBeVisible();
  const iconHrefs = await page.locator(".ontology-instance-node image").evaluateAll((images) =>
    images.map((image) => image.getAttribute("href")).filter((href): href is string => href !== null));
  for (const href of new Set(iconHrefs)) {
    const response = await page.request.get(new URL(href, page.url()).href);
    expect(response.status(), `icon request failed: ${href}`).toBe(200);
  }
  expect(requests).not.toContain("/ontology/graph");
  const toolbar = page.locator(".ontology-instance-toolbar");
  await expect(toolbar).toContainText(
    "First 2 Resources shown - search reaches the full generation",
  );
  const toolbarStatusColors = await toolbar.evaluate((element) => {
    const boundStatus = element.querySelector(".ontology-instance-toolbar-scope > span");
    if (boundStatus === null) throw new Error("compact bound status MUST render");
    return {
      background: getComputedStyle(element).backgroundColor,
      text: getComputedStyle(boundStatus).color,
    };
  });
  expect(contrastRatio(toolbarStatusColors.text, toolbarStatusColors.background))
    .toBeGreaterThanOrEqual(4.5);
  await expect(page.locator(".ontology-instance-bound-notice")).toHaveCount(0);
  const aksEvidence = page.locator(".ontology-instance-aks-lanes");
  await expect(aksEvidence).not.toHaveAttribute("open", "");
  await expect(aksEvidence.locator(":scope > div")).not.toBeVisible();
  await aksEvidence.locator("summary").click();
  await expect(aksEvidence).toHaveAttribute("open", "");
  await expect(aksEvidence.locator(":scope > div")).toBeVisible();
  await expectNoDocumentOverflow(page);
  await aksEvidence.locator("summary").click();
  const refreshStatus = toolbar.locator(".ontology-instance-refresh-status");
  await expect(refreshStatus).toBeVisible();
  await refreshStatus.focus();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await page.keyboard.press("Escape");

  const coverage = page.locator(".ontology-instance-presentation-coverage");
  await expect(coverage).not.toHaveAttribute("open", "");
  expect(await coverage.locator("summary").evaluate((element) =>
    element.getBoundingClientRect().height))
    .toBeLessThanOrEqual(44);
  await coverage.locator("summary").click();
  await expect(coverage).toHaveAttribute("open", "");
  await expect(coverage.locator(".ontology-instance-presentation-coverage-details")).toBeVisible();
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: testInfo.outputPath("ontology-coverage-expanded-1440x900.png"),
  });
  await coverage.locator("summary").click();

  const legend = page.locator(".ontology-instance-legend-dock");
  await expect(legend).not.toHaveAttribute("open", "");
  expect(await legend.evaluate((element) => element.getBoundingClientRect().width))
    .toBeLessThan(420);
  await legend.locator("summary").click();
  await expect(legend).toHaveAttribute("open", "");
  await expect(legend.locator(".ontology-instance-legend-body")).toBeVisible();
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: testInfo.outputPath("ontology-legend-expanded-1440x900.png"),
  });
  await legend.locator("summary").click();

  const graphToolGeometry = await page.locator(".ontology-instance-graph-tools").evaluate(
    (element) => {
      const style = getComputedStyle(element);
      const button = element.querySelector("button");
      if (button === null) throw new Error("graph tool button MUST render");
      const buttonRect = button.getBoundingClientRect();
      return {
        border: style.borderTopWidth,
        buttonHeight: buttonRect.height,
        buttonWidth: buttonRect.width,
      };
    },
  );
  expect(graphToolGeometry).toEqual({
    border: "0px",
    buttonHeight: 36,
    buttonWidth: 36,
  });

  const fullscreenButton = page.getByRole("button", { name: "Full screen", exact: true });
  await fullscreenButton.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(fullscreenButton).toBeFocused();
  expect(await fullscreenButton.evaluate((element) => element.matches(":focus-visible"))).toBe(true);
  const fullscreenFocusColors = await fullscreenButton.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      background: style.backgroundColor,
      border: style.borderTopColor,
    };
  });
  expect(contrastRatio(fullscreenFocusColors.border, fullscreenFocusColors.background))
    .toBeGreaterThanOrEqual(3);
  await fullscreenButton.click();
  await expect.poll(() => page.evaluate(() =>
    document.fullscreenElement?.classList.contains("ontology-instance-graph"))).toBe(true);
  expectDirectionSurfaceCoverage(await graphSurfaceGeometry(page));
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: testInfo.outputPath("ontology-direction-surface-fullscreen-1440x900.png"),
  });
  await page.getByRole("button", { name: "Exit full screen", exact: true }).click();

  await page.setViewportSize({ width: 993, height: 641 });
  expectDirectionSurfaceCoverage(await graphSurfaceGeometry(page));
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: testInfo.outputPath("ontology-direction-surface-993x641.png"),
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/ontology?locale=ko&view=instances&instance=root");
  await expect(page.locator(".ontology-instance-graph-scroll")).toBeVisible();
  await expect(page.locator(".ontology-instance-toolbar")).toContainText(
    "첫 Resource 2개 표시 - 검색으로 전체 세대 탐색",
  );
  await expect(page.locator(".ontology-instance-bound-notice")).toHaveCount(0);
  const mobileCoverageTarget = await page
    .locator(".ontology-instance-presentation-coverage > summary")
    .evaluate((element) => element.getBoundingClientRect().height);
  const mobileLegendTarget = await page
    .locator(".ontology-instance-legend-dock > summary")
    .evaluate((element) => element.getBoundingClientRect().height);
  const mobileAksEvidenceTarget = await page
    .locator(".ontology-instance-aks-lanes > summary")
    .evaluate((element) => element.getBoundingClientRect().height);
  expect(mobileCoverageTarget).toBeGreaterThanOrEqual(44);
  expect(mobileLegendTarget).toBeGreaterThanOrEqual(44);
  expect(mobileAksEvidenceTarget).toBeGreaterThanOrEqual(44);
  expectDirectionSurfaceCoverage(await graphSurfaceGeometry(page));
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: testInfo.outputPath("ontology-direction-surface-ko-390x844.png"),
  });

  await page.setViewportSize({ width: 320, height: 844 });
  expectDirectionSurfaceCoverage(await graphSurfaceGeometry(page));
  await expect(page.locator(".ontology-instance-toolbar-status")).toBeVisible();
  await expectNoDocumentOverflow(page);
});
