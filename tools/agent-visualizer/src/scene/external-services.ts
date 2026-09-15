import * as THREE from "three";
import { functionById, serviceFor, sourceServices } from "../source-graph";
import { servicePacketsAt, type TransportKind } from "../playback/service-traffic";
import { connectionCurve, createPointMaterial } from "./geometry";
import { serviceLayouts, serviceMarker, servicePortPositions } from "./service-layout";

interface ServicePort {
  readonly id: string;
  readonly label: string;
  readonly functionId: string;
  readonly position: THREE.Vector3;
  readonly route: THREE.QuadraticBezierCurve3;
  readonly kind: TransportKind;
  readonly color: THREE.Color;
}

/** Static API adapter lanes. Only Console/model chunks stream; webhook channels send discrete messages. */
export class ExternalServices {
  readonly group = new THREE.Group();
  readonly ports: readonly ServicePort[];
  private readonly geometry = new THREE.BufferGeometry();
  private readonly point = new THREE.Vector3();
  private readonly capacity = 512;

  constructor(functionPositions: ReadonlyMap<string, THREE.Vector3>, pixelRatio: number) {
    this.group.name = "source-adapter-services";
    this.ports = sourceServices.filter((service) => service.id !== "azure-resource-graph")
      .flatMap((service) => service.ports.map((port): ServicePort => {
        const definition = functionById.get(port.function_id);
        const start = functionPositions.get(port.function_id);
        const position = servicePortPositions[port.id];
        const group = definition ? serviceFor(definition) : null;
        if (!start || !position || !group || group !== service.id) {
          throw new Error(`Service port is not grounded in its source group: ${port.id}`);
        }
        if (port.mode !== "stream" && port.mode !== "message") throw new Error(`Unsupported transport mode: ${port.mode}`);
        const color = new THREE.Color(serviceLayouts[group].color);
        this.group.add(serviceMarker(position, serviceLayouts[group].color));
        const route = connectionCurve(start, position, 0.14);
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(route.getPoints(32)),
          new THREE.LineDashedMaterial({ color, transparent: true, opacity: 0.28, dashSize: 0.3, gapSize: 0.18 }));
        line.computeLineDistances();
        this.group.add(line);
        return { id: port.id, label: port.label, functionId: port.function_id, position, route,
          kind: port.id === "openai" ? "model" : port.mode, color };
      }));
    this.geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(this.capacity * 3), 3));
    this.geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(this.capacity * 3), 3));
    this.geometry.setAttribute("size", new THREE.BufferAttribute(new Float32Array(this.capacity), 1));
    this.geometry.setAttribute("energy", new THREE.BufferAttribute(new Float32Array(this.capacity).fill(0.45), 1));
    this.geometry.setDrawRange(0, 0);
    const packets = new THREE.Points(this.geometry, createPointMaterial(pixelRatio));
    packets.frustumCulled = false;
    packets.name = "simulated-service-packets";
    this.group.add(packets);
  }

  update(time: number, reduced: boolean) {
    const positions = this.geometry.getAttribute("position");
    const colors = this.geometry.getAttribute("color");
    const sizes = this.geometry.getAttribute("size");
    let count = 0;
    let channelStreamCount = 0;
    if (!reduced) this.ports.forEach((port, index) => {
      const packets = servicePacketsAt(time, port.kind, port.kind === "message" ? index * 1.3 : 0);
      for (const packet of packets) {
        for (let tail = 0; tail < 4; tail++) {
          const progress = packet.progress - tail * 0.025;
          if (progress < 0 || progress > 1) continue;
          if (count >= this.capacity) throw new Error("Service illustration particle budget exceeded.");
          port.route.getPoint(packet.direction === "inbound" ? 1 - progress : progress, this.point);
          const strength = 1 - tail / 4;
          positions.setXYZ(count, this.point.x, this.point.y, this.point.z);
          colors.setXYZ(count, (port.color.r + 0.3) * strength, (port.color.g + 0.3) * strength, (port.color.b + 0.3) * strength);
          sizes.setX(count, (tail === 0 ? 0.52 : 0.28) * strength);
          if (port.id === "console") channelStreamCount++;
          count++;
        }
      }
    });
    positions.needsUpdate = colors.needsUpdate = sizes.needsUpdate = true;
    this.geometry.setDrawRange(0, count);
    return { count, channelStreamCount };
  }
}
