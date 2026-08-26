import { describe, expect, it } from "vitest";
import {
  buildInstanceContainmentBoxes,
  flattenInstanceBoxes,
  INSTANCE_BOX_GAP,
  INSTANCE_BOX_HEADER,
  INSTANCE_BOX_PADDING,
  type InstanceBox,
} from "./ontology-instance-boxes";
import {
  INSTANCE_NODE_HEIGHT,
  INSTANCE_NODE_WIDTH,
} from "./ontology-instance-graph.model";
import type {
  OntologyInstanceExploration,
  OntologyInstanceLink,
  OntologyInstanceResource,
} from "./ontology-instances.model";

describe("buildInstanceContainmentBoxes", () => {
  it("reports nothing to nest when the root contains nothing", () => {
    expect(buildInstanceContainmentBoxes(exploration([resource("root")], []))).toBeNull();
    expect(buildInstanceContainmentBoxes(exploration(
      [resource("root"), resource("peer")],
      [link("root", "peer", "attached_to")],
    ))).toBeNull();
  });

  it("sizes an owner from what it contains rather than from itself", () => {
    const box = buildInstanceContainmentBoxes(exploration(
      [resource("root"), resource("a"), resource("b"), resource("c"), resource("d")],
      ["a", "b", "c", "d"].map((child) => link("root", child, "contains")),
    ))!;

    // Four children pack two by two, which is the point of nesting over an outline.
    expect(box.children).toHaveLength(4);
    expect(box.width).toBe(2 * INSTANCE_NODE_WIDTH + INSTANCE_BOX_GAP + INSTANCE_BOX_PADDING * 2);
    expect(box.height).toBe(
      INSTANCE_BOX_HEADER + 2 * INSTANCE_NODE_HEIGHT + INSTANCE_BOX_GAP + INSTANCE_BOX_PADDING,
    );
    expect(box.omittedChildren).toBe(0);
  });

  it("never lets a box overlap a sibling or leave its owner", () => {
    const children = Array.from({ length: 9 }, (_value, index) => resource(`child-${index}`));
    const grandchildren = Array.from({ length: 4 }, (_value, index) => resource(`grand-${index}`));
    const box = buildInstanceContainmentBoxes(exploration(
      [resource("root"), ...children, ...grandchildren],
      [
        ...children.map((child) => link("root", child.id, "contains")),
        ...grandchildren.map((grand) => link("child-0", grand.id, "contains")),
      ],
    ))!;

    assertContained(box);
    assertNoOverlap(box.children);
    box.children.forEach((child) => assertNoOverlap(child.children));
  });

  it("states how many children a bound left out", () => {
    const children = Array.from({ length: 20 }, (_value, index) => resource(`child-${index}`));
    const box = buildInstanceContainmentBoxes(
      exploration(
        [resource("root"), ...children],
        children.map((child) => link("root", child.id, "contains")),
      ),
      { maxChildren: 6 },
    )!;

    expect(box.children).toHaveLength(6);
    expect(box.omittedChildren).toBe(14);
  });

  it("keeps declared workloads ahead of derived ones when the bound cuts", () => {
    const pod = resource("pod-a", "kubernetes.pod");
    const replicaSet = resource("rs-a", "kubernetes.replica-set");
    const deployment = resource("deploy-a", "kubernetes.deployment");
    const service = resource("svc-a", "kubernetes.service");
    const box = buildInstanceContainmentBoxes(
      exploration(
        [resource("root"), pod, replicaSet, deployment, service],
        [pod, replicaSet, deployment, service].map((child) =>
          link("root", child.id, "contains")),
      ),
      { maxChildren: 2 },
    )!;

    expect(box.children.map((child) => child.resource.id)).toEqual(["deploy-a", "svc-a"]);
    expect(box.omittedChildren).toBe(2);
  });

  it("stops at the depth bound and survives a malformed containment cycle", () => {
    const deep = buildInstanceContainmentBoxes(
      exploration(
        [resource("root"), resource("a"), resource("b"), resource("c")],
        [
          link("root", "a", "contains"),
          link("a", "b", "contains"),
          link("b", "c", "contains"),
        ],
      ),
      { maxDepth: 2 },
    )!;
    expect(deep.children[0]!.children).toHaveLength(1);
    expect(deep.children[0]!.children[0]!.children).toHaveLength(0);

    const cyclic = buildInstanceContainmentBoxes(exploration(
      [resource("root"), resource("a")],
      [link("root", "a", "contains"), link("a", "root", "contains")],
    ))!;
    expect(flattenInstanceBoxes(cyclic).length).toBeGreaterThan(0);
  });

  it("resolves nested coordinates against the canvas origin", () => {
    const box = buildInstanceContainmentBoxes(exploration(
      [resource("root"), resource("a"), resource("b")],
      [link("root", "a", "contains"), link("a", "b", "contains")],
    ))!;
    const flat = flattenInstanceBoxes(box, 40, 24);
    const byId = new Map(flat.map((entry) => [entry.resource.id, entry]));

    expect(byId.get("root")).toMatchObject({ x: 40, y: 24 });
    expect(byId.get("a")).toMatchObject({
      x: 40 + INSTANCE_BOX_PADDING,
      y: 24 + INSTANCE_BOX_HEADER,
    });
    expect(byId.get("b")).toMatchObject({
      x: 40 + INSTANCE_BOX_PADDING * 2,
      y: 24 + INSTANCE_BOX_HEADER * 2,
    });
  });
});

function assertContained(box: InstanceBox): void {
  for (const child of box.children) {
    expect(child.x).toBeGreaterThanOrEqual(0);
    expect(child.y).toBeGreaterThanOrEqual(0);
    expect(INSTANCE_BOX_PADDING + child.x + child.width)
      .toBeLessThanOrEqual(box.width - INSTANCE_BOX_PADDING + 0.001);
    expect(INSTANCE_BOX_HEADER + child.y + child.height)
      .toBeLessThanOrEqual(box.height - INSTANCE_BOX_PADDING + 0.001);
    assertContained(child);
  }
}

function assertNoOverlap(boxes: readonly InstanceBox[]): void {
  for (let first = 0; first < boxes.length; first += 1) {
    for (let second = first + 1; second < boxes.length; second += 1) {
      const a = boxes[first]!;
      const b = boxes[second]!;
      const apart = a.x + a.width <= b.x || b.x + b.width <= a.x
        || a.y + a.height <= b.y || b.y + b.height <= a.y;
      expect(apart).toBe(true);
    }
  }
}

function exploration(
  resources: readonly OntologyInstanceResource[],
  links: readonly OntologyInstanceLink[],
): OntologyInstanceExploration {
  return {
    schema_version: "1.3.0",
    ontology_release_digest: `sha256:${"a".repeat(64)}`,
    source_generation: "generation-1",
    source_cutoff: "2026-08-22T08:00:00Z",
    root_id: "root",
    depth: 8,
    link_types: ["contains"],
    resources,
    links,
    timeline: { items: [], complete: true, truncation_reason: null },
    sources: [],
    relationship_drop_reasons: [],
    relationship_drop_classifications: [],
    complete: true,
    truncation_reasons: [],
    execution_authority: false,
    mutation_authority: false,
  };
}

function resource(id: string, resourceType = "compute.container-app"): OntologyInstanceResource {
  return {
    id,
    object_type: "Resource",
    resource_type: resourceType,
    name: id,
    location: null,
    resource_group: null,
    status: "Running",
    last_seen: null,
    selected: id === "root",
  };
}

function link(
  source: string,
  target: string,
  linkType: OntologyInstanceLink["link_type"],
): OntologyInstanceLink {
  return {
    source,
    target,
    link_type: linkType,
    evidence: {
      status: "available",
      evidence_kind: "configuration",
      verification_status: "configuration_observed",
      source: "azure-resource-graph",
      source_property_path: "properties.referenceId",
      mapping_id: `test.${linkType}`,
      evidence_method: "deterministic-cross-check",
      cutoff: "2026-08-22T08:00:00Z",
      freshness_ceiling_seconds: 21600,
      complete: true,
      reason: null,
    },
  };
}
