import * as THREE from "three";
import { agents, agentColor } from "../agents";
import { callsFrom, functionById } from "../source-graph";
import type { AgentId, Scenario } from "../model";
import { ARG_VISUAL_HZ, BUS_FANOUT_DELAY, eventFlowAt } from "../playback/event-flow";
import { ARG_WORKFLOWS, independentWorkloads } from "../playback/workloads";
import { BUS_POSITION, connectionCurve, createPointMaterial } from "./geometry";
import { serviceMarker, servicePortPositions } from "./service-layout";

const CAPACITY = 4096;
export const AZURE_SERVICE_POSITION = servicePortPositions["resource-graph"]!;
export const ARG_ENTRY = ARG_WORKFLOWS[0].query;

/** Parallel synthetic work over source-backed functions and declared subscriptions; no network I/O. */
export class EventField {
  readonly group = new THREE.Group();
  private readonly geometry = new THREE.BufferGeometry();
  private readonly ring: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;
  private readonly dot = new THREE.Vector3();
  private readonly routes = new Map<string, THREE.Curve<THREE.Vector3>>();
  private readonly localRoutes = new Map<string, readonly THREE.Curve<THREE.Vector3>[]>();
  private readonly requests: THREE.Curve<THREE.Vector3>[] = [];
  private readonly responses: THREE.Curve<THREE.Vector3>[] = [];
  private readonly localColors = new Map(agents.map((agent) => [agent.id, new THREE.Color(agentColor(agent.id))]));

  constructor(
    anchors: ReadonlyMap<AgentId, THREE.Vector3>, functionPositions: ReadonlyMap<string, THREE.Vector3>, ratio: number,
  ) {
    this.geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(CAPACITY * 3), 3));
    this.geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(CAPACITY * 3), 3));
    this.geometry.setAttribute("size", new THREE.BufferAttribute(new Float32Array(CAPACITY), 1));
    this.geometry.setAttribute("energy", new THREE.BufferAttribute(new Float32Array(CAPACITY).fill(0.65), 1));
    const particles = new THREE.Points(this.geometry, createPointMaterial(ratio));
    particles.frustumCulled = false;
    this.group.add(particles);
    const bus = new THREE.Mesh(new THREE.OctahedronGeometry(0.75),
      new THREE.MeshBasicMaterial({ color: "#94c5c2", wireframe: true, transparent: true, opacity: 0.6 }));
    bus.position.copy(BUS_POSITION);
    const azure = serviceMarker(AZURE_SERVICE_POSITION);
    this.ring = new THREE.Mesh(new THREE.RingGeometry(1.2, 1.23, 64),
      new THREE.MeshBasicMaterial({ color: "#8abcd0", transparent: true, opacity: 0.25, side: THREE.DoubleSide, depthWrite: false }));
    this.ring.position.copy(BUS_POSITION);
    this.group.add(bus, azure, this.ring);
    for (const [id, position] of anchors) {
      this.routes.set(`${id}:publish`, connectionCurve(position, BUS_POSITION, 0.12));
      this.routes.set(`${id}:subscribe`, connectionCurve(BUS_POSITION, position, -0.12));
    }
    for (const work of independentWorkloads) {
      const position = functionPositions.get(work.functionId)!;
      const paths = [connectionCurve(anchors.get(work.agent)!, position, 0.1)];
      const callee = [...(callsFrom.get(work.functionId) ?? [])].find((id) => id !== work.functionId && functionById.get(id)?.owners.includes(work.agent));
      if (callee) paths.push(connectionCurve(position, functionPositions.get(callee)!, 0.08));
      this.localRoutes.set(work.agent, paths);
    }
    for (const workflow of ARG_WORKFLOWS) {
      const entry = functionPositions.get(workflow.entry)!;
      const query = functionPositions.get(workflow.query)!;
      this.requests.push(new THREE.CatmullRomCurve3([anchors.get(workflow.owner)!, entry, query, AZURE_SERVICE_POSITION]));
      this.responses.push(new THREE.CatmullRomCurve3([AZURE_SERVICE_POSITION, query, entry]));
      this.addWire(new THREE.CatmullRomCurve3([entry, query, AZURE_SERVICE_POSITION]), "#7295b0", 0.22);
      // This is an accountable collection lane, not a direct Python call or runtime ownership transfer.
      const responsibility = new THREE.Line(new THREE.BufferGeometry().setFromPoints(
        connectionCurve(anchors.get(workflow.owner)!, entry).getPoints(28),
      ), new THREE.LineDashedMaterial({ color: "#71899a", transparent: true, opacity: 0.4, dashSize: 0.4, gapSize: 0.3 }));
      responsibility.computeLineDistances();
      this.group.add(responsibility);
    }
  }

  private addWire(curve: THREE.Curve<THREE.Vector3>, color: string, opacity: number) {
    this.group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(48)),
      new THREE.LineBasicMaterial({ color, opacity, transparent: true })));
  }

  update(time: number, transportTime: number, scenario: Scenario, camera: THREE.Camera, reduced: boolean) {
    const flow = eventFlowAt(time, scenario);
    const position = this.geometry.getAttribute("position");
    const size = this.geometry.getAttribute("size");
    const color = this.geometry.getAttribute("color");
    let visible = 0;
    const trail = (curve: THREE.Curve<THREE.Vector3>, progress: number, tint: readonly number[], scale = 1, length = 18) => {
      if (reduced || progress < 0 || progress > 1.3) return;
      for (let j = 0; j < length; j++) {
        const at = progress - j * 0.012;
        if (at < 0 || at > 1) continue;
        if (visible >= CAPACITY) throw new Error("Visual event buffer capacity exceeded.");
        curve.getPoint(at, this.dot);
        const intensity = 1 - j / length;
        position.setXYZ(visible, this.dot.x, this.dot.y, this.dot.z);
        size.setX(visible, (j === 0 ? 1.05 : 0.55) * intensity * scale);
        color.setXYZ(visible, tint[0]! * intensity, tint[1]! * intensity, tint[2]! * intensity);
        visible++;
      }
    };
    for (const broadcast of flow.broadcasts) {
      trail(this.routes.get(`${broadcast.topic.publisher}:publish`)!, broadcast.age / 0.8, [0.6, 1.2, 1.1], 0.8);
      for (const id of broadcast.subscribers) {
        trail(this.routes.get(`${id}:subscribe`)!, (broadcast.age - BUS_FANOUT_DELAY) / 1.4, [0.4, 1.3, 0.9], 0.75);
      }
    }
    for (const work of flow.independent) {
      if (!work.active) continue;
      const tint = this.localColors.get(work.agent)!.toArray();
      this.localRoutes.get(work.agent)!.forEach((path, index) => {
        trail(path, ((work.phase / 1.7) - index * 0.35) % 1.3, tint, 0.6, 12);
      });
    }
    const argTick = Math.floor(transportTime * ARG_VISUAL_HZ);
    for (let slot = Math.max(0, argTick - 8); slot <= argTick; slot++) {
      const elapsed = transportTime - slot / ARG_VISUAL_HZ;
      const workflow = slot % ARG_WORKFLOWS.length;
      trail(this.requests[workflow]!, elapsed / 0.8, [0.3, 0.55, 0.8], 0.48, 9);
      trail(this.responses[workflow]!, (elapsed - 0.8) / 0.8, [0.4, 0.75, 0.7], 0.42, 9);
    }
    position.needsUpdate = color.needsUpdate = size.needsUpdate = true;
    this.geometry.setDrawRange(0, visible);
    this.ring.quaternion.copy(camera.quaternion);
    this.ring.material.opacity = reduced ? 0.22 : 0.2 + flow.broadcasts.length * 0.025;
  }
}
