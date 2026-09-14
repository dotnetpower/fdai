import {
  AGENT_CONTRACT,
  AGENT_ROLE,
  AGENT_RUNTIME_BINDING,
  STATE_TASK,
  type AgentNode,
} from "./agents.model";
import { getLocale, t } from "../i18n";

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

export type AgentLayout = "roster" | "org";
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
  if (!iso) return t("agents.common.noSignalYet");
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return iso;
  return value.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function currentTask(node: AgentNode): string {
  if (!node.observed) return t("agents.task.unobserved");
  if (node.detail === "awaiting human approval") return t("agents.task.awaitingApproval");
  const binding = AGENT_RUNTIME_BINDING[node.name];
  if (
    node.state === "idle" &&
    (binding === "event-bus subscriber" || binding === "raw ingress subscriber")
  ) {
    return t("agents.task.subscribed");
  }
  return node.detail ?? stateTaskLabel(node.state);
}

export function agentStateLabel(node: AgentNode): string {
  return node.observed ? t(`agents.state.${node.state}`) : t("agents.state.unobserved");
}

export function stateTaskLabel(state: AgentNode["state"]): string {
  return t(`agents.task.${state}`);
}

export function agentRoleTitle(name: string): string | undefined {
  return AGENT_ROLE[name] ? t(`agents.role.${name.toLowerCase()}.title`) : undefined;
}

export function agentRoleSummary(name: string): string | undefined {
  return AGENT_ROLE[name] ? t(`agents.role.${name.toLowerCase()}.summary`) : undefined;
}

export function agentRuntimeBindingLabel(name: string): string {
  const binding = AGENT_RUNTIME_BINDING[name];
  if (binding === "raw ingress subscriber") return t("agents.binding.rawIngressSubscriber");
  if (binding === "external adapter") return t("agents.binding.externalAdapter");
  if (binding === "scheduled trigger") return t("agents.binding.scheduledTrigger");
  if (binding === "event-bus subscriber") return t("agents.binding.eventBusSubscriber");
  return t("agents.common.notConfigured");
}

export function agentViewContextRecord(
  node: AgentNode,
  layout: AgentLayout,
): Readonly<Record<string, unknown>> {
  if (layout === "org") {
    const role = AGENT_ROLE[node.name];
    return {
      agent: node.name,
      role: agentRoleTitle(node.name) ?? node.name,
      reports_to: role?.reportsTo ?? t("pantheon.root"),
      staff: role?.staff ?? false,
      layer: rosterLayerOf(node.name),
      runtime_binding: agentRuntimeBindingLabel(node.name),
      owns: AGENT_CONTRACT[node.name]?.owns ?? [],
      state: agentStateLabel(node),
    };
  }
  return {
    agent: node.name,
    state: agentStateLabel(node),
    task: currentTask(node),
    correlation_id: node.correlationId,
  };
}

export function agentStateClass(node: AgentNode): string {
  return node.observed ? node.state : "unobserved";
}

export function agentIconUrl(name: string): string {
  return `url("${import.meta.env.BASE_URL}agent-icons/${name.toLowerCase()}.svg")`;
}
