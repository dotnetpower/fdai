import * as THREE from "three";
import { placeLabels, type LabelCandidate } from "./label-layout";
import { approachLabelOpacity, functionLabelOpacity, LABEL_INTERACTION_OPACITY } from "./label-visibility";

interface LabelEntry {
  readonly id: string;
  readonly element: HTMLElement;
  readonly anchor: () => THREE.Vector3 | null;
  readonly leader: SVGLineElement;
  readonly compact: boolean;
  opacity: number;
  metrics: { text: string; width: number; height: number } | null;
}

/** Read-only label projection; moving labels never changes graph nodes, source edges, or focus. */
export class ScreenLabels {
  private readonly entries: LabelEntry[] = [];
  private readonly svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  private readonly projected = new THREE.Vector3();
  private size = "";

  constructor(layer: HTMLElement) {
    this.svg.classList.add("label-leaders");
    this.svg.setAttribute("aria-hidden", "true");
    layer.prepend(this.svg);
  }

  register(id: string, element: HTMLElement, anchor: () => THREE.Vector3 | null, compact = false) {
    const leader = document.createElementNS("http://www.w3.org/2000/svg", "line");
    this.svg.append(leader);
    element.dataset.sceneLabel = id;
    this.entries.push({ id, element, anchor, leader, compact, opacity: compact ? 0 : 1, metrics: null });
  }

  update(camera: THREE.PerspectiveCamera, width: number, height: number, priorities: ReadonlyMap<string, number>, delta: number, reduced: boolean) {
    const size = `${width}:${height}`;
    if (size !== this.size) {
      this.entries.forEach((entry) => { entry.metrics = null; });
      this.size = size;
      this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    }
    const candidates: LabelCandidate[] = [];
    const measuring = this.entries.filter((entry) => entry.metrics?.text !== (entry.element.textContent ?? ""));
    for (const entry of measuring) {
      entry.element.style.visibility = "hidden";
      entry.element.hidden = false;
    }
    for (const entry of measuring) {
      entry.metrics = { text: entry.element.textContent ?? "", width: entry.element.offsetWidth, height: entry.element.offsetHeight };
    }
    for (const entry of measuring) {
      entry.element.hidden = true;
      entry.element.style.visibility = "";
    }
    for (const entry of this.entries) {
      const anchor = entry.anchor();
      const focused = document.activeElement === entry.element;
      if (!anchor) continue;
      const distance = camera.position.distanceTo(anchor);
      const target = entry.compact && !focused ? functionLabelOpacity(distance, camera.zoom) : 1;
      entry.opacity = focused ? 1 : approachLabelOpacity(entry.opacity, target, delta, reduced);
      if (entry.opacity < 0.01) continue;
      this.projected.copy(anchor).project(camera);
      const x = (this.projected.x * 0.5 + 0.5) * width;
      const y = (-this.projected.y * 0.5 + 0.5) * height;
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      if (!focused && (this.projected.z > 1 || this.projected.z < -1 || x < 0 || x > width || y < 0 || y > height)) continue;
      candidates.push({
        id: entry.id, x: Math.max(4, Math.min(width - 4, x)), y: Math.max(4, Math.min(height - 4, y)),
        width: entry.metrics!.width, height: entry.metrics!.height,
        priority: focused ? 1000 : (priorities.get(entry.id) ?? (entry.compact ? -200 : 0)) - (entry.compact ? distance * 0.1 : 0),
        compact: entry.compact && !focused,
      });
    }
    const placements = new Map(placeLabels(candidates, width, height).map((placement) => [placement.id, placement]));
    for (const entry of this.entries) {
      const placement = placements.get(entry.id);
      entry.element.hidden = !placement;
      entry.leader.style.display = placement ? "" : "none";
      if (entry.compact) {
        entry.element.style.opacity = String(entry.opacity);
        entry.leader.style.opacity = String(entry.opacity * 0.5);
        const interactive = Boolean(placement) && entry.opacity >= LABEL_INTERACTION_OPACITY;
        entry.element.tabIndex = interactive ? 0 : -1;
        entry.element.style.pointerEvents = interactive ? "auto" : "none";
        entry.element.setAttribute("aria-hidden", String(!interactive));
      }
      if (!placement) continue;
      entry.element.style.transform = `translate(${placement.left}px, ${placement.top}px)`;
      const endX = Math.max(placement.left, Math.min(placement.left + placement.width, placement.x));
      const endY = Math.max(placement.top, Math.min(placement.top + placement.height, placement.y));
      entry.leader.setAttribute("x1", String(placement.x));
      entry.leader.setAttribute("y1", String(placement.y));
      entry.leader.setAttribute("x2", String(endX));
      entry.leader.setAttribute("y2", String(endY));
    }
  }
}
