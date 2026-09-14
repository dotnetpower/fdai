import { expect, test, type Page, type Route } from "@playwright/test";

const releaseDigest = `sha256:${"a".repeat(64)}`;

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
      resource("root", "Example application", "compute.container-app", false),
      resource(
        "environment",
        "Example environment",
        "compute.container-app-environment",
        false,
      ),
    ],
    complete: true,
    truncation_reason: null,
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
      resource("root", "Example application", "compute.container-app", true),
      resource(
        "environment",
        "Example environment",
        "compute.container-app-environment",
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
    const canvas = scroll.querySelector<SVGElement>(".ontology-instance-graph-canvas");
    if (direction === null || canvas === null) {
      throw new Error("direction background and graph canvas MUST render");
    }
    const selectedDirection = direction.querySelector<HTMLElement>(".is-selected");
    if (selectedDirection === null) {
      throw new Error("selected direction background MUST render");
    }
    const scrollRect = scroll.getBoundingClientRect();
    const directionRect = direction.getBoundingClientRect();
    const canvasRect = canvas.getBoundingClientRect();
    return {
      canvasHeight: canvasRect.height,
      canvasLeft: canvasRect.left,
      canvasWidth: canvasRect.width,
      directionBottom: directionRect.bottom,
      directionHeight: directionRect.height,
      directionLeft: directionRect.left,
      directionWidth: directionRect.width,
      scrollBottom: scrollRect.bottom,
      scrollHeight: scroll.clientHeight,
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
  expect(requests).not.toContain("/ontology/graph");

  await page.getByRole("button", { name: "Full screen", exact: true }).click();
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
  expectDirectionSurfaceCoverage(await graphSurfaceGeometry(page));
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: testInfo.outputPath("ontology-direction-surface-ko-390x844.png"),
  });
});
