import * as THREE from "three";
import type { RecordedAxis, RecordedGraph, RecordedResource } from "./contract";
import { layoutRelationships, relationshipSubset, type Position } from "./layout";
import { ScreenLabels } from "../scene/screen-labels";
import { mapCurve } from "./map-curves";
import { mapPointMaterial } from "./map-material";
import { recorded } from "./state";

const KIND_COLORS: Readonly<Record<string, string>> = {
  object_type: "#8cddd1", interface_type: "#c5b0e7", function_type: "#e2c995",
  resource_type: "#8faed3", rule: "#b9c990", action_type: "#e4b48e",
  workflow: "#aeb7df", agent: "#d0b9ea", signal_type: "#83bebb", property: "#a6c1c7",
  instance: "#789aab",
};

export function recordedStateColor(resource: RecordedResource, _axis: RecordedAxis): string {
  if (resource.nodeKind !== "instance") {
    if (resource.id === "catalog:agent:Loki") return "#ff747d";
    return KIND_COLORS[resource.nodeKind ?? ""] ?? "#9bb9d3";
  }
  const value = (resource.presentationState !== undefined ? resource.presentationState : resource.storedState?.value)?.toLowerCase().replace(/[^a-z]/g, "") ?? "";
  if (["failed", "unavailable", "notready", "unhealthy", "error"].includes(value)) return "#e89198";
  if (["stopped", "stopping", "deallocated", "disabled", "paused", "degraded", "provisioning", "updating", "pending"].includes(value)) return "#d8b985";
  if (["running", "ready", "available", "online", "succeeded", "active"].includes(value)) return "#92cbb8";
  return "#789aab";
}

/** Render every selected source node/link on the GPU; labels use a separate, disclosed detail budget. */
export class RecordedRelationScene {
  readonly group = new THREE.Group();
  readonly labelLayer = document.createElement("div");
  positions = new Map<string, Position>();
  private graph: RecordedGraph | null = null;
  private layout: ScreenLabels;
  private geometry = new THREE.BufferGeometry();
  private readonly nodes: THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>;
  private lines: THREE.LineSegments | null = null;
  private arrows: THREE.InstancedMesh | null = null;
  private labels = new Map<string, HTMLButtonElement>();
  private topologyKey = "";
  private labelKey = "";
  private visibleIds: string[] = [];
  private drawnLinks = 0;
  private byId = new Map<string, RecordedResource>();
  private palette = new Map<string, readonly [number, number, number]>();
  private hadPulse = false;
  private readonly selectedEdges = new THREE.LineSegments(new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({ color: "#d4e9c5", transparent: true, opacity: 0.8 }));
  private readonly highlight = new THREE.Mesh(new THREE.RingGeometry(1, 1.06, 48),
    new THREE.MeshBasicMaterial({ color: "#ddfff0", side: THREE.DoubleSide, transparent: true, opacity: 0.8 }));

  constructor(container: HTMLElement, private readonly onSelect: (id: string) => void, ratio: number) {
    this.labelLayer.className = "node-labels recorded-labels";
    container.append(this.labelLayer);
    this.layout = new ScreenLabels(this.labelLayer);
    this.nodes = new THREE.Points(this.geometry, mapPointMaterial(ratio));
    this.nodes.frustumCulled = false;
    this.group.add(this.nodes, this.highlight, this.selectedEdges);
  }

  pick(raycaster: THREE.Raycaster) {
    raycaster.params.Points.threshold = 0.25;
    const hit = raycaster.intersectObject(this.nodes)[0];
    if (hit?.index !== undefined) this.onSelect(this.visibleIds[hit.index]!);
  }

  private rebuild(graph: RecordedGraph, type: string) {
    if (this.graph?.generation !== graph.generation) this.positions = layoutRelationships(graph);
    const subset = relationshipSubset(graph, type, recorded.lens, recorded.objectType);
    this.visibleIds = subset.resources.map((node) => node.id);
    this.drawnLinks = subset.links.length;
    this.geometry.dispose();
    this.geometry = new THREE.BufferGeometry();
    this.geometry.setAttribute("position", new THREE.Float32BufferAttribute(subset.resources.flatMap((node) => [...this.positions.get(node.id)!]), 3));
    this.geometry.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(subset.resources.length * 3), 3));
    this.geometry.setAttribute("size", new THREE.Float32BufferAttribute(subset.resources.map((node) =>
      node.nodeKind === "object_type" ? 2 : node.nodeKind === "instance" ? 0.2 : 0.6), 1));
    this.geometry.setAttribute("alpha", new THREE.Float32BufferAttribute(subset.resources.map((node) =>
      node.nodeKind === "instance" ? 0.38 : 0.95), 1));
    this.nodes.geometry = this.geometry;
    if (this.lines) { this.group.remove(this.lines); this.lines.geometry.dispose(); (this.lines.material as THREE.Material).dispose(); }
    const positions: number[] = [];
    const colors: number[] = [];
    for (const link of subset.links) {
      const start = new THREE.Vector3(...this.positions.get(link.source)!);
      const end = new THREE.Vector3(...this.positions.get(link.target)!);
      const path = mapCurve(start, end, link.type).getPoints(link.origin === "catalog" ? 12 : 2);
      const strength = link.origin === "catalog" ? 0.16 : link.origin === "database" ? 0.035 : 0.012;
      for (let i = 1; i < path.length; i++) {
        positions.push(...path[i - 1]!.toArray(), ...path[i]!.toArray());
        colors.push(strength * 0.6, strength * 0.85, strength, strength * 0.6, strength * 0.85, strength);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    this.lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.8 }));
    this.group.add(this.lines);
    this.labelKey = "";
  }

  private rebuildLabels(graph: RecordedGraph, selected: string, type: string) {
    const active = document.activeElement instanceof HTMLElement && this.labelLayer.contains(document.activeElement)
      ? document.activeElement.dataset.recordedResource : null;
    this.labelLayer.replaceChildren();
    this.layout = new ScreenLabels(this.labelLayer);
    this.labels.clear();
    const visible = new Set(this.visibleIds);
    const neighbors = new Set(graph.links.filter((link) => (type === "all" || link.type === type)
      && (link.source === selected || link.target === selected)).flatMap((link) => [link.source, link.target]));
    const labelNodes = graph.resources.filter((node) => visible.has(node.id) && (
      node.nodeKind === "object_type" || node.id === selected || (neighbors.has(node.id) && node.nodeKind !== "instance")
    ));
    const nearbyInstances = graph.resources.filter((node) => visible.has(node.id) && node.nodeKind === "instance" && (node.id === selected || neighbors.has(node.id))).slice(0, 20);
    for (const node of [...new Map([...labelNodes, ...nearbyInstances].map((node) => [node.id, node])).values()]) {
      const label = document.createElement("button");
      label.type = "button";
      label.className = "node-label recorded-node-label";
      label.dataset.recordedResource = node.id;
      label.dataset.nodeKind = node.nodeKind;
      label.textContent = node.nodeKind === "object_type" ? `${node.name} (${node.instanceCount ?? 0})` : node.name;
      label.title = node.nodeKind === "instance" ? `${node.objectType} / ${node.id}` : node.detail ?? node.resourceType;
      label.onclick = () => this.onSelect(node.id);
      this.labelLayer.append(label);
      this.labels.set(node.id, label);
      const point = new THREE.Vector3(...this.positions.get(node.id)!);
      this.layout.register(node.id, label, () => point);
      if (active === node.id) label.dataset.restoreFocus = "true";
    }
    const positions: number[] = [];
    const selectedInstance = graph.resources.find((node) => node.id === selected)?.nodeKind === "instance";
    const related = graph.links.filter((link) => visible.has(link.source) && visible.has(link.target)
      && (link.origin !== "classification" || selectedInstance)
      && (type === "all" || link.type === type) && (link.source === selected || link.target === selected));
    if (this.arrows) {
      this.group.remove(this.arrows); this.arrows.geometry.dispose();
      (this.arrows.material as THREE.Material).dispose(); this.arrows.dispose();
    }
    this.arrows = new THREE.InstancedMesh(new THREE.ConeGeometry(0.13, 0.45, 5),
      new THREE.MeshBasicMaterial({ color: "#cee9ca", transparent: true, opacity: 0.8 }), related.length);
    this.arrows.frustumCulled = false;
    const arrow = new THREE.Object3D();
    let arrowIndex = 0;
    for (const link of related) {
      const curve = mapCurve(new THREE.Vector3(...this.positions.get(link.source)!), new THREE.Vector3(...this.positions.get(link.target)!), link.type);
      const path = curve.getPoints(12);
      for (let i = 1; i < path.length; i++) positions.push(...path[i - 1]!.toArray(), ...path[i]!.toArray());
      arrow.position.copy(curve.getPoint(0.65));
      arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), curve.getTangent(0.65).normalize());
      arrow.updateMatrix();
      this.arrows.setMatrixAt(arrowIndex++, arrow.matrix);
    }
    this.arrows.instanceMatrix.needsUpdate = true;
    this.group.add(this.arrows);
    this.selectedEdges.geometry.dispose();
    this.selectedEdges.geometry = new THREE.BufferGeometry();
    this.selectedEdges.geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    related.slice(0, 10).forEach((link, index) => {
      const middle = mapCurve(new THREE.Vector3(...this.positions.get(link.source)!), new THREE.Vector3(...this.positions.get(link.target)!), link.type).getPoint(0.5);
      const label = document.createElement("span");
      label.className = "recorded-edge-label";
      label.textContent = link.type;
      label.setAttribute("aria-hidden", "true");
      this.labelLayer.append(label);
      this.layout.register(`edge-label-${index}`, label, () => middle);
    });
  }

  render(graph: RecordedGraph | null, type: string, selected: string, axis: RecordedAxis, changes: readonly { resourceId: string; readAt: string }[], camera: THREE.PerspectiveCamera, width: number, height: number, delta: number, reduced: boolean) {
    if (!graph) { this.group.visible = false; this.labelLayer.hidden = true; return; }
    this.group.visible = true;
    this.labelLayer.hidden = false;
    const topologyKey = `${graph.generation}:${type}:${recorded.lens}:${recorded.objectType}`;
    const topologyChanged = topologyKey !== this.topologyKey;
    if (topologyChanged) { this.rebuild(graph, type); this.topologyKey = topologyKey; }
    const graphChanged = graph !== this.graph;
    if (graphChanged) {
      this.byId = new Map(graph.resources.map((node) => [node.id, node]));
      const color = new THREE.Color();
      this.palette = new Map(graph.resources.map((node) => {
        color.set(recordedStateColor(node, axis));
        return [node.id, [color.r, color.g, color.b] as const];
      }));
      this.graph = graph;
    }
    const labelKey = `${topologyKey}:${selected}`;
    if (labelKey !== this.labelKey) { this.rebuildLabels(graph, selected, type); this.labelKey = labelKey; }
    const colors = this.geometry.getAttribute("color");
    const priorities = new Map<string, number>();
    const changed = new Set(changes.filter((change) => Date.now() - Date.parse(change.readAt) < 3000).map((change) => change.resourceId));
    if (graphChanged || topologyChanged || changed.size || this.hadPulse) {
      this.visibleIds.forEach((id, index) => {
        const color = this.palette.get(id)!;
        const factor = changed.has(id) && !reduced ? 1.5 : 1;
        colors.setXYZ(index, color[0] * factor, color[1] * factor, color[2] * factor);
      });
      colors.needsUpdate = true;
    }
    this.hadPulse = changed.size > 0;
    for (const [id, label] of this.labels) {
      label.setAttribute("aria-pressed", String(id === selected));
      priorities.set(id, id === selected ? 300 : this.byId.get(id)?.nodeKind === "object_type" ? 100 : 0);
    }
    const point = this.positions.get(selected);
    this.highlight.visible = Boolean(point && this.visibleIds.includes(selected));
    if (point) { this.highlight.position.set(...point); this.highlight.quaternion.copy(camera.quaternion); }
    this.layout.update(camera, width, height, priorities, delta, reduced);
    const restore = this.labelLayer.querySelector<HTMLElement>("[data-restore-focus]");
    if (restore) { restore.focus({ preventScroll: true }); delete restore.dataset.restoreFocus; }
    this.labelLayer.dataset.drawnNodes = String(this.visibleIds.length);
    this.labelLayer.dataset.drawnLinks = String(this.drawnLinks);
  }

  dispose() { this.arrows?.dispose(); this.labelLayer.remove(); }
}
