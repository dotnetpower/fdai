import {
  AGENT_RUNTIME_BINDING,
  STATE_TASK,
  type AgentNode,
} from "./agents.model";

export const STATE_LABEL: Readonly<Record<string, string>> = {
  idle: "idle",
  watching: "watching",
  collecting: "collecting",
  analyzing: "analyzing",
  deciding: "deciding",
  executing: "executing",
  approving: "approving",
  auditing: "auditing",
};

export interface Point {
  readonly x: number;
  readonly y: number;
}

export interface Geometry {
  readonly centers: Record<string, Point>;
  readonly w: number;
  readonly h: number;
}

export const EMPTY_GEOMETRY: Geometry = { centers: {}, w: 0, h: 0 };

export type AgentLayout = "roster" | "constellation" | "org";
export type RosterLayer = "all" | "governance" | "pipeline" | "domain";
export type RosterState = "all" | "engaged" | "watching" | "idle" | "unobserved";

const GOVERNANCE_AGENTS = new Set(["Odin", "Mimir", "Muninn", "Saga", "Norns"]);
const DOMAIN_AGENTS = new Set(["Njord", "Freyr", "Loki"]);

export function rosterLayerOf(name: string): Exclude<RosterLayer, "all"> {
  if (GOVERNANCE_AGENTS.has(name)) return "governance";
  if (DOMAIN_AGENTS.has(name)) return "domain";
  return "pipeline";
}

export function stateTime(iso: string): string {
  if (!iso) return "No signal yet";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return iso;
  return value.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function currentTask(node: AgentNode): string {
  if (!node.observed) return "No runtime signal observed";
  const binding = AGENT_RUNTIME_BINDING[node.name];
  if (
    node.state === "idle" &&
    (binding === "event-bus subscriber" || binding === "raw ingress subscriber")
  ) {
    return "Subscribed and waiting for events";
  }
  return node.detail ?? STATE_TASK[node.state];
}

export function agentStateLabel(node: AgentNode): string {
  return node.observed ? (STATE_LABEL[node.state] ?? node.state) : "unobserved";
}

export function agentStateClass(node: AgentNode): string {
  return node.observed ? node.state : "unobserved";
}

export function agentIconUrl(name: string): string {
  return `url("${import.meta.env.BASE_URL}agent-icons/${name.toLowerCase()}.svg")`;
}

export function hueForIncident(correlationId: string): number {
  let hue = 0;
  for (let index = 0; index < correlationId.length; index += 1) {
    hue = (hue * 31 + correlationId.charCodeAt(index)) % 360;
  }
  return hue;
}

export function pairsOf(names: readonly string[]): [string, string][] {
  const pairs: [string, string][] = [];
  for (let first = 0; first < names.length; first += 1) {
    for (let second = first + 1; second < names.length; second += 1) {
      pairs.push([names[first]!, names[second]!]);
    }
  }
  return pairs;
}

export function centroid(points: readonly Point[]): Point | null {
  if (points.length === 0) return null;
  const sum = points.reduce(
    (total, point) => ({ x: total.x + point.x, y: total.y + point.y }),
    { x: 0, y: 0 },
  );
  return { x: sum.x / points.length, y: sum.y / points.length };
}
