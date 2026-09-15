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

function instanceDirectory() {
  return {
    schema_version: "1.0.0",
    ontology_release_digest: releaseDigest,
    source_generation: "example-generation",
    source_cutoff: "2026-09-14T00:00:00Z",
    search: null,
    resources: [],
    complete: true,
    truncation_reason: null,
    execution_authority: false,
    mutation_authority: false,
  };
}

function ontologyGraph() {
  return {
    schema_version: "2.0.0",
    _revision: releaseDigest,
    ontology_release_digest: releaseDigest,
    mutation_authority: false,
    complete: true,
    limitations: {
      source_coverage: [],
      query_truncation: [],
      access_redaction: [],
      presentation_omission: [],
    },
    mermaid: "classDiagram\nclass Resource",
    object_type_count: 1,
    link_type_count: 0,
    action_type_count: 0,
    interface_type_count: 0,
    function_type_count: 0,
    object_types: ["Resource"],
    link_types: [],
    action_types: [],
    interface_types: [],
    function_types: [],
    nodes: [{
      name: "Resource",
      key: "resource",
      property_count: 0,
      properties: [],
      description: "Observed resource.",
    }],
    edges: [],
    semantic_model: {
      schema_version: "1.0.0",
      bands: [
        { id: "operating_scope", label: "Scope", object_types: ["Resource"] },
        { id: "operating_intent", label: "Intent", object_types: [] },
        { id: "operating_reality", label: "Reality", object_types: [] },
        { id: "decision_and_learning", label: "Decision", object_types: [] },
      ],
      lenses: ["object", "relationship", "state", "context", "action"],
      mutation_authority: false,
    },
    catalog_topology: {
      schemaVersion: "2.0.0",
      generatedFrom: "browser test fixture",
      ontologyReleaseDigest: releaseDigest,
      mutationAuthority: false,
      nodes: [{
        id: "ot:Resource",
        label: "Resource",
        kind: "object_type",
        group: "ObjectTypes",
        detail: "Observed resource.",
        community: 1,
        degree: 0,
        x: 0,
        y: 0,
      }],
      edges: [],
    },
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
    if (path === "/ontology/graph") {
      await json(route, ontologyGraph());
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/ontology/instances*", handleApi);
  await page.route("**/ontology/graph*", handleApi);
  return requests;
}

async function expectNoDocumentOverflow(page: Page): Promise<void> {
  const dimensions = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

test.describe("Ontology instance-first navigation", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(
      testInfo.project.name !== "desktop-chromium",
      "Desktop, constrained, and mobile gates run sequentially in one scenario.",
    );
  });

  test("loads instances first and progressively discloses reference views", async ({
    page,
  }, testInfo) => {
    const requests = await installOntologyFixture(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/ontology");

    await expect(page.locator(".page-header-title")).toContainText("Ontology");
    await expect(page.getByText("Start with an observed Resource instance")).toBeVisible();
    await expect(page.getByRole("link", { name: "Ontology instances", exact: true }))
      .toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("combobox", { name: /Search active generation/ })).toBeVisible();
    await expect.poll(() => requests.filter((path) => path === "/ontology/instances").length)
      .toBe(1);
    expect(requests).not.toContain("/ontology/graph");
    const primaryColors = await page.locator(".ontology-view-primary").evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        background: style.backgroundColor,
        border: style.borderTopColor,
        pageBackground: getComputedStyle(document.body).backgroundColor,
        text: style.color,
      };
    });
    expect(contrastRatio(primaryColors.text, primaryColors.background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(primaryColors.border, primaryColors.pageBackground)).toBeGreaterThanOrEqual(3);
    await expectNoDocumentOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("ontology-instances-1440x900.png") });

    const referenceNav = page.locator(".ontology-reference-nav");
    const referenceSummary = page.locator(".ontology-reference-nav > summary");
    await expect(referenceSummary).toHaveText("Definitions and topology");
    await expect(referenceNav).not.toHaveAttribute("open", "");
    await referenceSummary.focus();
    await page.keyboard.press("Enter");
    await expect(referenceNav).toHaveAttribute("open", "");
    await expect(referenceNav.getByRole("link")).toHaveCount(5);
    await referenceNav.getByRole("link", { name: "Object types", exact: true }).click();

    await expect(page).toHaveURL(/\/ontology\?view=objects$/);
    await expect.poll(() => requests.filter((path) => path === "/ontology/graph").length).toBe(1);
    await expect(page.getByRole("heading", { name: "Neighborhood of Resource" })).toBeVisible();
    await expect(referenceNav).not.toHaveAttribute("open", "");
    await expect(page.locator(".ontology-reference-nav > summary")).toContainText("Object types");

    await page.getByRole("link", { name: "Ontology instances", exact: true }).click();
    await expect(page).toHaveURL(/\/ontology$/);
    await expect(page.getByRole("combobox", { name: /Search active generation/ })).toBeVisible();
    expect(requests.filter((path) => path === "/ontology/graph")).toHaveLength(1);

    await page.setViewportSize({ width: 993, height: 641 });
    await referenceSummary.focus();
    await page.keyboard.press("Enter");
    const constrainedBounds = await page.locator(".ontology-reference-links").boundingBox();
    if (constrainedBounds === null) throw new Error("reference links MUST have layout bounds");
    expect(constrainedBounds.x).toBeGreaterThanOrEqual(0);
    expect(constrainedBounds.x + constrainedBounds.width).toBeLessThanOrEqual(993);
    await expectNoDocumentOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("ontology-references-993x641.png") });
    await referenceNav.getByRole("link").first().focus();
    await page.keyboard.press("Escape");
    await expect(referenceNav).not.toHaveAttribute("open", "");
    await expect(referenceSummary).toBeFocused();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/ontology?locale=ko");
    const koreanReferenceSummary = page.locator(".ontology-reference-nav > summary");
    await expect(koreanReferenceSummary).toHaveText("정의 및 토폴로지");
    await expect(page.getByRole("link", { name: "온톨로지 인스턴스", exact: true }))
      .toHaveAttribute("aria-current", "page");
    await koreanReferenceSummary.click();
    await expect(page.locator(".ontology-reference-links")).toHaveCSS("position", "static");
    const targetHeights = await page.locator(".ontology-reference-links a").evaluateAll((links) =>
      links.map((link) => link.getBoundingClientRect().height));
    expect(targetHeights.every((height) => height >= 44)).toBe(true);
    expect(requests.filter((path) => path === "/ontology/graph")).toHaveLength(1);
    await expectNoDocumentOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("ontology-references-ko-390x844.png") });
  });
});
