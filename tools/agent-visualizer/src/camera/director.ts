import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { AgentId, CameraMode } from "../model";
import type { sampleTour } from "./tour";

export const DEFAULT_ACTIVITY_CAMERA: CameraMode = "follow";

/** Slow camera choreography. Pointer input immediately yields control to the operator. */
export class CameraDirector {
  readonly controls: OrbitControls;
  mode: CameraMode = DEFAULT_ACTIVITY_CAMERA;
  focus: AgentId | null = null;
  focusPoint: THREE.Vector3 | null = null;
  private readonly desired = new THREE.Vector3();
  private readonly target = new THREE.Vector3();
  private previousMode: CameraMode = DEFAULT_ACTIVITY_CAMERA;
  private entryProgress = 1;
  private readonly entryPosition = new THREE.Vector3();
  private readonly entryTarget = new THREE.Vector3();

  constructor(
    private readonly camera: THREE.PerspectiveCamera,
    element: HTMLElement,
    private readonly anchors: ReadonlyMap<AgentId, THREE.Vector3>,
    onManual: () => void,
  ) {
    this.controls = new OrbitControls(camera, element);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.minDistance = 12;
    this.controls.maxDistance = 125;
    this.controls.maxPolarAngle = Math.PI * 0.88;
    this.controls.addEventListener("start", () => {
      this.mode = "manual";
      onManual();
    });
    camera.position.set(0, 6, 65);
  }

  update(time: number, delta: number, active: AgentId | null, reduced: boolean, tour: ReturnType<typeof sampleTour>) {
    if (this.mode === "tour" && !reduced) {
      if (this.previousMode !== "tour") {
        this.entryProgress = 0;
        this.entryPosition.copy(this.camera.position);
        this.entryTarget.copy(this.controls.target);
      }
      this.controls.enableDamping = false;
      this.controls.update();
      this.entryProgress = Math.min(1, this.entryProgress + Math.max(0, delta) / 1.2);
      const blend = THREE.MathUtils.smoothstep(this.entryProgress, 0, 1);
      this.desired.fromArray(tour.position);
      this.target.fromArray(tour.target);
      this.camera.position.copy(this.entryPosition).lerp(this.desired, blend);
      this.controls.target.copy(this.entryTarget).lerp(this.target, blend);
    } else if (this.mode !== "manual") {
      this.controls.enableDamping = true;
      const selected = this.focus ?? (this.mode === "follow" ? active : null);
      const anchor = this.focusPoint ?? (selected ? this.anchors.get(selected) : undefined);
      const phase = reduced ? 0 : time * 0.022;
      if (anchor) {
        this.target.copy(anchor).multiplyScalar(0.75);
        this.desired.copy(anchor).add(new THREE.Vector3(
          Math.sin(phase) * 9, 5, Math.max(30, 42 / this.camera.aspect),
        ));
      } else {
        this.target.set(0, 0, 0);
        const distance = Math.max(59, 58 / this.camera.aspect);
        this.desired.set(Math.sin(phase) * distance * 0.36, 6 + Math.sin(phase * 0.7) * 4, Math.cos(phase * 0.5) * 7 + distance);
      }
      const factor = reduced ? 1 : 1 - Math.exp(-Math.min(delta, 0.1) * 1.1);
      this.camera.position.lerp(this.desired, factor);
      this.controls.target.lerp(this.target, factor);
    }
    if (this.mode === "manual") this.controls.enableDamping = true;
    this.controls.update();
    this.previousMode = this.mode;
  }

  reset() {
    this.focus = null;
    this.focusPoint = null;
    this.mode = "orbit";
  }

  zoom(factor: number) {
    this.mode = "manual";
    const offset = this.camera.position.clone().sub(this.controls.target);
    offset.setLength(THREE.MathUtils.clamp(offset.length() * factor, 12, 125));
    this.camera.position.copy(this.controls.target).add(offset);
    this.controls.update();
  }
}
