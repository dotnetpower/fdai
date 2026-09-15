import * as THREE from "three";
import { callsFrom, callsTo, functionById } from "../source-graph";
import { connectionCurve } from "./geometry";

/** Selection highlights source references, not a measured invocation. */
export class FunctionSelection {
  readonly object: THREE.LineSegments;
  readonly label = document.createElement("div");
  private readonly geometry = new THREE.BufferGeometry();
  private readonly material = new THREE.LineBasicMaterial({ color: "#c1ffee", transparent: true, opacity: 0.9 });
  private current: string | null = null;

  constructor(private readonly positions: ReadonlyMap<string, THREE.Vector3>, layer: HTMLElement) {
    this.object = new THREE.LineSegments(this.geometry, this.material);
    this.object.visible = false;
    this.label.className = "function-scene-label";
    this.label.hidden = true;
    this.label.setAttribute("aria-hidden", "true");
    layer.append(this.label);
  }

  get anchor(): THREE.Vector3 | null {
    return this.current ? this.positions.get(this.current) ?? null : null;
  }

  update(id: string | null) {
    if (id !== this.current) {
      this.current = id;
      const origin = id ? this.positions.get(id) : null;
      const values: number[] = [];
      if (id && origin) {
        for (const target of new Set([...(callsFrom.get(id) ?? []), ...(callsTo.get(id) ?? [])])) {
          const destination = this.positions.get(target)!;
          const path = connectionCurve(origin, destination, 0.08).getPoints(12);
          for (let i = 1; i < path.length; i++) values.push(...path[i - 1]!.toArray(), ...path[i]!.toArray());
        }
      }
      // Release the old attribute's GPU buffer before replacing its identity.
      this.geometry.dispose();
      this.geometry.setAttribute("position", new THREE.Float32BufferAttribute(values, 3));
      this.geometry.computeBoundingSphere();
      this.object.visible = values.length > 0;
      this.label.hidden = !origin;
      if (origin && id) {
        const fn = functionById.get(id)!;
        this.label.textContent = `${fn.id.split(".").slice(-2).join(".")}() :${fn.line}`;
      }
    }

  }

  dispose() {
    this.object.removeFromParent();
    this.geometry.dispose();
    this.material.dispose();
    this.label.remove();
    this.current = null;
  }
}
