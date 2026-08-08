import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { layoutIntegrityErrors } from "../src/layout/integrity.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const networkFlowUrl = new URL(
  "../../../docs/diagrams/fdai-azure-resource-network-flow.diagram.yaml",
  import.meta.url,
);

test("Azure resource network flow routes every compound edge", async () => {
  const source = await readFile(networkFlowUrl, "utf8");
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");

  assert.equal(spec.kind, "deployment");
  assert.equal(layout.edges.length, spec.edges.length);
  assert.ok(layout.edges.every((edge) => (edge.sections?.length ?? 0) > 0));
  assert.deepEqual(layoutIntegrityErrors(spec, layout), []);
  const explicitRoutes = new Set(
    spec.edges
      .filter(
        (edge) =>
          edge.route === "orthogonal" ||
          edge.route === "orthogonal-horizontal",
      )
      .map((edge) => edge.id),
  );
  for (const edge of layout.edges.filter((candidate) => explicitRoutes.has(candidate.id))) {
    const bends = (edge.sections ?? []).reduce(
      (total, section) => total + (section.bendPoints?.length ?? 0),
      0,
    );
    assert.ok(bends <= 2, `${edge.id} has ${bends} bends`);
  }
  assert.equal([...svg.matchAll(/data-edge-id=/g)].length, spec.edges.length);
  assert.match(svg, /data-group-id="fdai-vnet"/);
  assert.match(svg, /data-group-id="container-apps-subnet"/);
  assert.match(svg, /data-group-id="private-endpoint-subnet"/);
  assert.match(svg, /data-group-id="gateway-subnet"/);
  assert.doesNotMatch(svg, /data-group-id="postgres-subnet"/);
  assert.match(svg, /data-node-id="postgres-pe"/);
  assert.match(svg, /data-node-id="ingestion-gateway"/);
  assert.match(svg, /data-node-id="document-blob-pe"/);
  assert.match(svg, /data-node-id="document-dfs-pe"/);
  assert.match(svg, /data-node-id="document-storage"/);
  for (const [nodeId, icon] of [
    ["operator", "users"],
    ["entra-id", "entra-id"],
    ["application-gateway", "application-gateway"],
    ["waf-policy", "waf-policy"],
    ["microsoft-foundry", "ai-foundry"],
    ["managed-grafana", "managed-grafana"],
    ["email-approval", "communication-services"],
    ["teams-approval", "teams"],
    ["slack-approval", "slack"],
    ["github-delivery", "github"],
    ["gitlab-delivery", "gitlab"],
    ["azure-devops-delivery", "azure-devops"],
  ] as const) {
    assert.equal(spec.nodes.find((node) => node.id === nodeId)?.icon, icon);
    assert.match(svg, new RegExp(`data-node-id="${nodeId}"`));
  }
  assert.doesNotMatch(source, /\bTBD\b/);
  assert.equal(
    spec.nodes.find((node) => node.id === "document-storage")!.label.en,
    "ADLS Gen2 (optional)",
  );
  assert.equal(
    spec.nodes.find((node) => node.id === "document-storage")!.icon,
    "storage-account",
  );
  assert.match(svg, /data-node-id="operator-console"/);
  assert.doesNotMatch(svg, /data-node-id="operator-cli"/);
  for (const groupId of [
    "container-apps-subnet",
    "private-endpoint-subnet",
    "private-service-backends",
  ]) {
    const children = spec.nodes
      .filter((node) => node.parent === groupId)
      .map((node) => layout.nodes.get(node.id)!);
    const centers = children.map((node) => node.y + node.height / 2);
    assert.ok(
      Math.max(...centers) - Math.min(...centers) <= 28,
      `${groupId} children must share one horizontal row`,
    );
    const group = layout.groups.get(groupId)!;
    assert.ok(group.width > group.height, `${groupId} must be wider than tall`);
  }
  const gridGroups = [
    layout.groups.get("container-apps-subnet")!,
    layout.groups.get("private-endpoint-subnet")!,
    layout.groups.get("private-service-backends")!,
  ];
  assert.ok(Math.max(...gridGroups.map((group) => group.x)) - Math.min(...gridGroups.map((group) => group.x)) <= 1);
  assert.ok(Math.max(...gridGroups.map((group) => group.width)) - Math.min(...gridGroups.map((group) => group.width)) <= 1);
  const containerApps = layout.groups.get("container-apps-subnet")!;
  const gatewaySubnet = layout.groups.get("gateway-subnet")!;
  const privateEndpoints = layout.groups.get("private-endpoint-subnet")!;
  const privateServices = layout.groups.get("private-service-backends")!;
  assert.equal(gatewaySubnet.width, 320);
  assert.ok(gatewaySubnet.width > gatewaySubnet.height);
  assert.ok(
    Math.abs(
      gatewaySubnet.x + gatewaySubnet.width / 2 -
      privateEndpoints.x - privateEndpoints.width / 2,
    ) <= 1,
  );
  const gatewayChildren = ["application-gateway", "waf-policy"].map(
    (id) => layout.nodes.get(id)!,
  );
  assert.equal(
    gatewayChildren[1]!.x -
      gatewayChildren[0]!.x -
      gatewayChildren[0]!.width,
    48,
  );
  assert.equal(
    gatewayChildren[0]!.y + gatewayChildren[0]!.height / 2,
    gatewayChildren[1]!.y + gatewayChildren[1]!.height / 2,
  );
  const wafEdge = layout.edges.find(
    (candidate) => candidate.id === "waf-to-gateway",
  )!;
  assert.equal(wafEdge.sections?.[0]?.bendPoints?.length ?? 0, 0);
  assert.ok(gatewaySubnet.y + gatewaySubnet.height < containerApps.y);
  assert.ok(containerApps.y + containerApps.height < privateEndpoints.y);
  assert.equal(containerApps.y - gatewaySubnet.y - gatewaySubnet.height, 132);
  assert.equal(privateEndpoints.y - containerApps.y - containerApps.height, 132);
  assert.ok(privateEndpoints.y + privateEndpoints.height < privateServices.y);
  assert.ok(privateServices.y - privateEndpoints.y - privateEndpoints.height >= 64);
  const operatorAccess = layout.groups.get("operator-access")!;
  const azureRegion = layout.groups.get("azure-region")!;
  const governedDelivery = layout.groups.get("governed-delivery")!;
  assert.ok(operatorAccess.x + operatorAccess.width < azureRegion.x);
  assert.ok(azureRegion.x + azureRegion.width < governedDelivery.x);
  assert.equal(operatorAccess.width, 184);
  assert.ok(operatorAccess.height > operatorAccess.width);
  assert.ok(governedDelivery.width <= 460);
  assert.ok(layout.width < 2050);
  const gitProviders = layout.groups.get("git-providers")!;
  const approvalChannels = layout.groups.get("approval-channels")!;
  assert.ok(gitProviders.y + gitProviders.height < approvalChannels.y);
  assert.ok(Math.max(
    operatorAccess.y,
    azureRegion.y,
    governedDelivery.y,
  ) - Math.min(
    operatorAccess.y,
    azureRegion.y,
    governedDelivery.y,
  ) <= 1);
  const contentBottom = Math.max(
    operatorAccess.y + operatorAccess.height,
    azureRegion.y + azureRegion.height,
    governedDelivery.y + governedDelivery.height,
  );
  assert.ok(layout.height - contentBottom <= 72);
  const vnet = layout.groups.get("fdai-vnet")!;
  const platformServices = layout.groups.get("platform-services")!;
  assert.ok(vnet.x + vnet.width < platformServices.x);
  assert.ok(vnet.y - azureRegion.y >= 49);
  assert.ok(vnet.y - azureRegion.y <= 50);
  assert.equal(privateServices.y - (vnet.y + vnet.height), 48);
  const operatorNodes = spec.nodes
    .filter((node) => node.parent === "operator-access")
    .map((node) => layout.nodes.get(node.id)!);
  const operatorCenters = operatorNodes.map((node) => node.x + node.width / 2);
  assert.ok(Math.max(...operatorCenters) - Math.min(...operatorCenters) <= 1);
  const orderedOperatorNodes = ["operator", "entra-id", "operator-console"].map(
    (id) => layout.nodes.get(id)!,
  );
  for (let index = 1; index < orderedOperatorNodes.length; index += 1) {
    const gap =
      orderedOperatorNodes[index]!.y -
      (orderedOperatorNodes[index - 1]!.y + orderedOperatorNodes[index - 1]!.height);
    assert.equal(gap, 48, `operator access gap ${index} is ${gap}`);
  }
  assert.equal(spec.nodes.find((node) => node.id === "entra-id")!.label.en, "Microsoft Entra ID");
  assert.equal(
    spec.nodes.find((node) => node.id === "monitor")!.label.en,
    "App Insights + Logs",
  );
  for (const endpoint of spec.nodes.filter(
    (node) => node.parent === "private-endpoint-subnet",
  )) {
    assert.doesNotMatch(endpoint.label.en, /private endpoint/iu);
  }
  const orderedContainerApps = [
    "operator-api",
    "scheduled-jobs",
    "core-runtime",
    "ingestion-gateway",
  ].map((id) => layout.nodes.get(id)!);
  for (let index = 1; index < orderedContainerApps.length; index += 1) {
    assert.ok(orderedContainerApps[index - 1]!.x < orderedContainerApps[index]!.x);
    const gap = orderedContainerApps[index]!.x -
      orderedContainerApps[index - 1]!.x -
      orderedContainerApps[index - 1]!.width;
    assert.equal(gap, 48);
  }
  const platformNodes = spec.nodes
    .filter((node) => node.parent === "platform-services")
    .map((node) => layout.nodes.get(node.id)!);
  const platformCenters = platformNodes.map((node) => node.x + node.width / 2);
  assert.ok(Math.max(...platformCenters) - Math.min(...platformCenters) <= 1);
  for (let index = 1; index < platformNodes.length; index += 1) {
    assert.ok(platformNodes[index - 1]!.y < platformNodes[index]!.y);
  }
  for (const [endpointId, serviceId] of [
    ["registry-pe", "container-registry"],
    ["event-hubs-pe", "event-hubs"],
    ["key-vault-pe", "key-vault"],
    ["openai-pe", "azure-openai"],
    ["foundry-pe", "microsoft-foundry"],
    ["postgres-pe", "postgres"],
  ] as const) {
    const endpoint = layout.nodes.get(endpointId)!;
    const service = layout.nodes.get(serviceId)!;
    const endpointCenter = endpoint.x + endpoint.width / 2;
    const serviceCenter = service.x + service.width / 2;
    assert.ok(
      Math.abs(endpointCenter - serviceCenter) <= 1,
      `${endpointId} must align with ${serviceId}`,
    );
  }
  const storageCenter = layout.nodes.get("document-storage")!.x +
    layout.nodes.get("document-storage")!.width / 2;
  const blobCenter = layout.nodes.get("document-blob-pe")!.x +
    layout.nodes.get("document-blob-pe")!.width / 2;
  const dfsCenter = layout.nodes.get("document-dfs-pe")!.x +
    layout.nodes.get("document-dfs-pe")!.width / 2;
  assert.ok(Math.abs(storageCenter - (blobCenter + dfsCenter) / 2) <= 1);
  const resourceGraphEdge = layout.edges.find(
    (candidate) => candidate.id === "core-to-resource-graph",
  );
  const resourceGraphBends = resourceGraphEdge?.sections?.[0]?.bendPoints ?? [];
  assert.equal(resourceGraphBends.length, 3);
  assert.equal(
    resourceGraphBends.at(-1)!.x,
    resourceGraphEdge!.sections![0]!.endPoint.x,
  );
  assert.equal(
    resourceGraphEdge!.sections![0]!.endPoint.y,
    layout.nodes.get("resource-graph")!.y,
  );
  for (const edgeId of [
    "event-pe-to-core",
    "api-to-event-pe",
    "registry-pe-to-core",
    "core-to-key-vault-pe",
    "core-to-openai-pe",
    "core-to-foundry-pe",
    "core-to-postgres-pe",
    "api-to-postgres-pe",
  ]) {
    const edge = layout.edges.find((candidate) => candidate.id === edgeId)!;
    const bends = edge.sections?.[0]?.bendPoints ?? [];
    assert.ok(bends.length <= 2, `${edgeId} has ${bends.length} bends`);
  }
  const coreTrunkAnchors = spec.edges
    .filter(
      (edge) =>
        edge.route === "orthogonal-trunk" &&
        (edge.from === "core-runtime" || edge.to === "core-runtime"),
    )
    .map((edge) => {
      const section = layout.edges.find((candidate) => candidate.id === edge.id)!
        .sections![0]!;
      return edge.from === "core-runtime"
        ? section.startPoint.x
        : section.endPoint.x;
    });
  assert.equal(new Set(coreTrunkAnchors).size, coreTrunkAnchors.length);
  const eventHubsEdge = spec.edges.find((edge) => edge.id === "event-hubs-to-pe")!;
  assert.equal(eventHubsEdge.from, "event-hubs");
  assert.equal(eventHubsEdge.to, "event-hubs-pe");
  const registryEdge = spec.edges.find((edge) => edge.id === "registry-to-pe")!;
  assert.equal(registryEdge.from, "container-registry");
  assert.equal(registryEdge.to, "registry-pe");
  const gatewayToIngestion = layout.edges.find(
    (candidate) => candidate.id === "gateway-to-ingestion",
  )!.sections![0]!;
  assert.equal(
    spec.edges.find((edge) => edge.id === "gateway-to-ingestion")!.route,
    "orthogonal-shortest",
  );
  assert.equal(gatewayToIngestion.bendPoints?.length, 2);
  assert.equal(
    gatewayToIngestion.startPoint.y,
    layout.nodes.get("application-gateway")!.y +
      layout.nodes.get("application-gateway")!.height,
  );
  assert.equal(
    gatewayToIngestion.startPoint.x,
    gatewayToIngestion.bendPoints![0]!.x,
  );
  assert.equal(
    gatewayToIngestion.bendPoints![0]!.y,
    gatewayToIngestion.bendPoints![1]!.y,
  );
  assert.equal(
    gatewayToIngestion.bendPoints![1]!.x,
    gatewayToIngestion.endPoint.x,
  );
  assert.equal(
    gatewayToIngestion.endPoint.y,
    layout.nodes.get("ingestion-gateway")!.y,
  );
  const gitSection = layout.edges.find(
    (candidate) => candidate.id === "core-to-git-providers",
  )?.sections?.[0];
  const approvalSection = layout.edges.find(
    (candidate) => candidate.id === "core-to-approval-channels",
  )?.sections?.[0];
  assert.ok(gitSection?.bendPoints?.length === 3);
  assert.ok(approvalSection?.bendPoints?.length === 4);
  assert.ok(gitSection.bendPoints[1]!.y < gitSection.startPoint.y);
  for (const edge of layout.edges) {
    for (const section of edge.sections ?? []) {
      const previous = section.bendPoints?.at(-1) ?? section.startPoint;
      assert.ok(
        Math.hypot(
          section.endPoint.x - previous.x,
          section.endPoint.y - previous.y,
        ) >= 16,
        `${edge.id} has a short terminal shaft`,
      );
    }
  }
  const approvalEdge = spec.edges.find(
    (edge) => edge.id === "core-to-approval-channels",
  )!;
  const gitEdge = spec.edges.find(
    (edge) => edge.id === "core-to-git-providers",
  )!;
  assert.equal(approvalEdge.to, "approval-channels");
  assert.equal(gitEdge.to, "git-providers");
  assert.equal(approvalEdge.step, 6);
  assert.equal(gitEdge.step, 7);
  assert.equal(gitSection.endPoint.x, gitProviders.x + gitProviders.width / 2);
  assert.equal(gitSection.endPoint.y, gitProviders.y);
  assert.equal(approvalSection.endPoint.x, approvalChannels.x);
  assert.equal(
    approvalSection.endPoint.y,
    approvalChannels.y + approvalChannels.height / 2,
  );
  assert.match(
    svg,
    /data-edge-id="core-to-approval-channels"[^>]*data-edge-route="orthogonal-above"[^>]*data-edge-step="6"/,
  );
  assert.match(
    svg,
    /data-edge-route="orthogonal-above"\]\[data-edge-step\] > \.edge-path/,
  );
  assert.match(svg, /markerUnits="userSpaceOnUse" markerWidth="7" markerHeight="7"/);
  assert.match(
    svg,
    /data-group-id="azure-region"\] > \.group-surface \{ fill: #f8fbfe;/,
  );
  assert.match(
    svg,
    /data-group-id="platform-services"\] > \.group-header \{ fill: #e7f0f7;/,
  );
  assert.equal(
    spec.nodes.find((node) => node.id === "postgres")!.parent,
    "private-service-backends",
  );
  const postgresWrite = spec.edges.find(
    (edge) => edge.id === "postgres-pe-to-service",
  )!;
  assert.equal(postgresWrite.from, "postgres-pe");
  assert.equal(postgresWrite.to, "postgres");
  const blobWrite = spec.edges.find((edge) => edge.id === "blob-pe-to-storage")!;
  const dfsWrite = spec.edges.find((edge) => edge.id === "dfs-pe-to-storage")!;
  assert.equal(blobWrite.from, "document-blob-pe");
  assert.equal(blobWrite.to, "document-storage");
  assert.equal(dfsWrite.from, "document-dfs-pe");
  assert.equal(dfsWrite.to, "document-storage");
});
