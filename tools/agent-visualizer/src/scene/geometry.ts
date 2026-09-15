import * as THREE from "three";
import { agents, agentColor } from "../agents";
import type { AgentId } from "../model";
import { callsFrom, callsTo, codeGraph, functionById, homeAgent, pythonFunctions, serviceFor } from "../source-graph";
import { serviceLayouts } from "./service-layout";

export interface NeuralPoint {
  position: THREE.Vector3;
  owner: AgentId | null;
  functionId: string | null;
  size: number;
  color: THREE.Color;
}

export const AZURE_POSITION = serviceLayouts["azure-resource-graph"].center;
export const BUS_POSITION = new THREE.Vector3(0, 0, -2);

/** Stable presentation layout; no random firing, fabricated functions, or guessed call edges. */
export function seededRandom(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

export function connectionCurve(start: THREE.Vector3, end: THREE.Vector3, bend = 0.15) {
  const middle = start.clone().lerp(end, 0.5);
  const direction = end.clone().sub(start);
  middle.add(new THREE.Vector3(-direction.y, direction.x, direction.z * 0.25).multiplyScalar(bend));
  return new THREE.QuadraticBezierCurve3(start, middle, end);
}

/** Every subordinate point is one real Python definition. Edges are AST references or membership. */
export function makeNeuralGeometry() {
  const random = seededRandom(1517);
  const points: NeuralPoint[] = [];
  const linePositions: number[] = [];
  const lineColors: number[] = [];
  const anchors = new Map<AgentId, THREE.Vector3>();
  const functionPositions = new Map<string, THREE.Vector3>();
  const colorById = new Map<string, THREE.Color>();
  const counts = new Map<string, number>();
  for (const fn of pythonFunctions) {
    const group = serviceFor(fn) ?? homeAgent(fn) ?? "shared";
    counts.set(group, (counts.get(group) ?? 0) + 1);
  }
  function connect(a: THREE.Vector3, b: THREE.Vector3, color: THREE.Color, strength: number) {
    const path = connectionCurve(a, b, 0.08).getPoints(5);
    for (let i = 1; i < path.length; i++) {
      linePositions.push(...path[i - 1]!.toArray(), ...path[i]!.toArray());
      const faded = color.clone().multiplyScalar(strength);
      lineColors.push(...faded.toArray(), ...faded.toArray());
    }
  }
  for (const agent of agents) {
    const center = new THREE.Vector3(...agent.position);
    const color = new THREE.Color(agentColor(agent.id));
    anchors.set(agent.id, center);
    colorById.set(agent.id, color);
    points.push({ position: center, owner: agent.id, functionId: null, size: 1.7, color });
  }
  const placed = new Map<string, number>();
  for (const fn of pythonFunctions) {
    const owner = homeAgent(fn);
    const service = serviceFor(fn);
    const group = service ?? owner ?? "shared";
    const index = placed.get(group) ?? 0;
    placed.set(group, index + 1);
    const count = counts.get(group)!;
    const fraction = (index + 0.5) / count;
    const angle = index * 2.399963;
    const radius = 2.2 + Math.sqrt(fraction) * (3.2 + Math.min(3, Math.sqrt(count) * 0.17));
    const latitude = (random() - 0.5) * 1.6;
    const center = service ? serviceLayouts[service].center : owner ? anchors.get(owner)! : AZURE_POSITION;
    const position = center.clone().add(new THREE.Vector3(
      Math.cos(angle) * radius, Math.sin(angle) * radius * 0.85, latitude * radius,
    ));
    const color = service ? new THREE.Color(serviceLayouts[service].color)
      : owner ? colorById.get(owner)! : new THREE.Color("#70b9ff");
    const degree = (callsFrom.get(fn.id)?.size ?? 0) + (callsTo.get(fn.id)?.size ?? 0);
    functionPositions.set(fn.id, position);
    points.push({ position, owner, functionId: fn.id, size: 0.28 + Math.min(0.65, Math.log1p(degree) * 0.16), color });
    if (fn.direct_owners.includes(owner ?? "")) connect(center, position, color, 0.07);
  }
  for (const edge of codeGraph.calls) {
    const start = functionPositions.get(edge.source);
    const end = functionPositions.get(edge.target);
    if (!start || !end) throw new Error("Generated call edge refers to a missing Python function.");
    const shared = homeAgent(functionById.get(edge.source)!) !== homeAgent(functionById.get(edge.target)!);
    connect(start, end, new THREE.Color("#639baf"), shared ? 0.045 : edge.resolution === "declared-receiver" ? 0.06 : 0.13);
  }
  const lines = new THREE.BufferGeometry();
  lines.setAttribute("position", new THREE.Float32BufferAttribute(linePositions, 3));
  lines.setAttribute("color", new THREE.Float32BufferAttribute(lineColors, 3));
  return { points, lines, anchors, functionPositions };
}

export function createPointMaterial(pixelRatio: number) {
  return new THREE.ShaderMaterial({
    uniforms: { pixelRatio: { value: pixelRatio } },
    vertexShader: `
      attribute float size;
      attribute float energy;
      attribute vec3 color;
      varying vec3 vColor;
      varying float vEnergy;
      uniform float pixelRatio;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vColor = color;
        vEnergy = energy;
        gl_PointSize = clamp(size * (1.0 + energy * 0.85) * pixelRatio * 240.0 / -mv.z, 1.0, 96.0);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: `
      varying vec3 vColor;
      varying float vEnergy;
      void main() {
        float d = length(gl_PointCoord - vec2(0.5)) * 2.0;
        if (d > 1.0) discard;
        float halo = exp(-d * d * 5.0);
        float core = exp(-d * d * 48.0);
        vec3 color = vColor * (0.5 + vEnergy * 1.9);
        color += vec3(core * (0.5 + vEnergy));
        gl_FragColor = vec4(color, halo * 0.8 + core * 0.2);
      }
    `,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
}

/** Write node silhouettes after additive graph rendering so backdrop stars remain behind them. */
export function createPointOcclusionMaterial(pixelRatio: number) {
  return new THREE.ShaderMaterial({
    uniforms: { pixelRatio: { value: pixelRatio } },
    vertexShader: `
      attribute float size;
      attribute float energy;
      uniform float pixelRatio;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = clamp(size * (1.0 + energy * 0.85) * pixelRatio * 240.0 / -mv.z, 1.0, 96.0);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: `
      void main() {
        if (length(gl_PointCoord - vec2(0.5)) * 2.0 > 1.0) discard;
        gl_FragColor = vec4(0.0);
      }
    `,
    colorWrite: false,
    depthTest: true,
    depthWrite: true,
    transparent: true,
    toneMapped: false,
  });
}
