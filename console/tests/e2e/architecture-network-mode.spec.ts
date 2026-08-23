import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";

const graph = {
  snapshot_at: "2026-08-22T00:00:00Z",
  freshness: "fresh",
  scope: null,
  depth: 4,
  included_link_types: ["contains", "attached_to", "depends_on", "peered_with"],
  truncated: false,
  resources: [
    { id: "subscription", type: "subscription", name: "Example subscription", status: "unknown", x: 0, y: 0, w: 18, h: 12 },
    { id: "group", type: "resource-group", name: "Example workload", status: "unknown", parent_id: "subscription", x: 1, y: 1, w: 16, h: 10 },
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

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installArchitectureFixture(page: Page): Promise<void> {
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
          last_observed_at: graph.snapshot_at,
        }],
      });
      return;
    }
    if (path === "/inventory/graph") {
      await json(route, graph);
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/system/data-sources", handleApi);
  await page.route("**/inventory/graph*", handleApi);
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

async function captureNetworkViewport(
  page: Page,
  testInfo: TestInfo,
  name: "network-desktop" | "network-constrained" | "network-mobile",
): Promise<void> {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(name, { body: screenshot, contentType: "image/png" });
  const captureRoot = process.env.FDAI_NETWORK_VISUAL_CAPTURE_ROOT;
  if (!captureRoot) return;
  await mkdir(captureRoot, { recursive: true });
  await writeFile(`${captureRoot}/${name}.png`, screenshot);
}

test("keeps observed Network mode readable and exportable across viewports", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  await installArchitectureFixture(page);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/architecture");
  await page.getByRole("button", { name: "Network", exact: true }).click();
  await expect(page.locator(".architecture-network-map-svg")).toBeVisible();
  await expect(page.locator(".architecture-network-region")).toHaveCount(8);
  await expect(page.locator(".architecture-network-node")).toHaveCount(5);
  await expect(page.locator(".architecture-network-node-icon")).toHaveCount(5);
  await expect(page.locator(".architecture-network-node-glyph")).toHaveCount(0);
  await expect(page.locator(".architecture-network-link-path")).toHaveCount(9);
  await expect(page.locator(".architecture-network-link-endpoint")).toHaveCount(5);
  await expect(page.locator('.architecture-network-link-path[marker-end="url(#architecture-network-arrow)"]')).toHaveCount(4);
  await expect(page.locator('.architecture-network-link-path[marker-start="url(#architecture-network-arrow)"]')).toHaveCount(1);
  await expect(page.locator(".architecture-network-link.is-peered_with")).toHaveCount(1);
  const peeringPath = page.locator(".architecture-network-link.is-peered_with .architecture-network-link-path");
  expect((await peeringPath.getAttribute("d"))?.match(/\bL/g)).toHaveLength(1);
  const peeringBox = await peeringPath.evaluate((element) => {
    const box = (element as SVGGraphicsElement).getBBox();
    return { width: box.width, height: box.height };
  });
  expect(peeringBox?.width).toBeGreaterThan(.5);
  expect(peeringBox?.height).toBeLessThanOrEqual(.01);
  const tools = page.locator(".architecture-network-tools");
  await expect(tools).toBeVisible();
  expect((await tools.boundingBox())?.y).toBeLessThan(700);
  expect(((await tools.boundingBox())?.y ?? 0) + ((await tools.boundingBox())?.height ?? 0)).toBeLessThanOrEqual(900);
  await assertNoHorizontalOverflow(page);

  await tools.getByRole("combobox").nth(0).selectOption("gateway");
  await tools.getByRole("combobox").nth(1).selectOption("endpoint");
  await expect(page.locator(".architecture-network-path-result")).toContainText("Observed path");
  await expect(page.locator(".architecture-network-path-hops li")).toHaveCount(2);
  await captureNetworkViewport(page, testInfo, "network-desktop");

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
  await expect(page.locator(".architecture-network-map-svg")).toBeVisible();
  await assertNoHorizontalOverflow(page);
  const constrainedTools = await tools.boundingBox();
  expect(constrainedTools?.width).toBeGreaterThan(500);
  await captureNetworkViewport(page, testInfo, "network-constrained");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".architecture-network-map-svg")).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await expect(page.locator(".architecture-overview-panel")).toHaveCount(0);
  for (const node of await page.locator(".architecture-network-node").all()) {
    const box = await node.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
  for (const button of await page.locator(".architecture-network-export button").all()) {
    const box = await button.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
  await captureNetworkViewport(page, testInfo, "network-mobile");
});
