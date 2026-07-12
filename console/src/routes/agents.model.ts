/**
 * Now > Agents route state model (Track B, Phase 2).
 *
 * Folds the three agent-activity SSE message kinds into a view state:
 *
 * - `agents` - the 15 pantheon agents keyed by name, each carrying its
 *   current status ring + the incident it is engaged on.
 * - `incidents` - open/collaborating/resolved incident tickets keyed by
 *   `correlation_id`, each accumulating its agent-to-agent conversation
 *   turns.
 *
 * Pure reducer: no I/O, deterministic, so it is trivially testable.
 */

import type {
  AgentActivityMessage,
  AgentStatus,
  ConversationTurnMessage,
  TicketStatus,
} from "../hooks/use-agent-stream";

/** Cognitive layer of each agent (drives the node colour). */
export type AgentLayer =
  | "sensing"
  | "judge"
  | "executor"
  | "approver"
  | "conversational"
  | "auditor"
  | "governance"
  | "domain";

/** The 15 pantheon agents in a stable display order, with their layer. */
export const PANTHEON: readonly { readonly name: string; readonly layer: AgentLayer }[] = [
  { name: "Odin", layer: "judge" },
  { name: "Heimdall", layer: "sensing" },
  { name: "Huginn", layer: "sensing" },
  { name: "Forseti", layer: "judge" },
  { name: "Var", layer: "approver" },
  { name: "Thor", layer: "executor" },
  { name: "Vidar", layer: "executor" },
  { name: "Saga", layer: "auditor" },
  { name: "Bragi", layer: "conversational" },
  { name: "Njord", layer: "domain" },
  { name: "Freyr", layer: "domain" },
  { name: "Loki", layer: "domain" },
  { name: "Mimir", layer: "governance" },
  { name: "Norns", layer: "governance" },
  { name: "Muninn", layer: "governance" },
];

const _LAYER_OF: Record<string, AgentLayer> = Object.fromEntries(
  PANTHEON.map((a) => [a.name, a.layer]),
);

export interface AgentNode {
  readonly name: string;
  readonly layer: AgentLayer;
  readonly state: AgentStatus;
  readonly correlationId: string | null;
  readonly since: string;
}

export interface Incident {
  readonly correlationId: string;
  readonly ticketId: string;
  readonly title: string;
  readonly severity: string;
  readonly status: TicketStatus;
  readonly involved: readonly string[];
  readonly rca: string | null;
  readonly turns: readonly ConversationTurnMessage[];
  readonly updatedAt: string;
}

export interface AgentsState {
  readonly agents: Record<string, AgentNode>;
  readonly incidents: Record<string, Incident>;
  /** Incident correlation ids, newest first. */
  readonly incidentOrder: readonly string[];
}

/** Cap retained incidents so a long-lived tab cannot grow without bound. */
const MAX_INCIDENTS = 30;

export function makeInitialState(): AgentsState {
  const agents: Record<string, AgentNode> = {};
  for (const { name, layer } of PANTHEON) {
    agents[name] = { name, layer, state: "idle", correlationId: null, since: "" };
  }
  return { agents, incidents: {}, incidentOrder: [] };
}

function applyAgentState(
  state: AgentsState,
  msg: Extract<AgentActivityMessage, { type: "agent.state" }>,
): AgentsState {
  const prev = state.agents[msg.agent];
  const layer = prev?.layer ?? _LAYER_OF[msg.agent] ?? "governance";
  const node: AgentNode = {
    name: msg.agent,
    layer,
    state: msg.state,
    correlationId: msg.correlation_id,
    since: msg.ts,
  };
  return { ...state, agents: { ...state.agents, [msg.agent]: node } };
}

function applyTicket(
  state: AgentsState,
  msg: Extract<AgentActivityMessage, { type: "incident.ticket" }>,
): AgentsState {
  const existing = state.incidents[msg.correlation_id];
  const incident: Incident = {
    correlationId: msg.correlation_id,
    ticketId: msg.ticket_id,
    title: msg.title,
    severity: msg.severity,
    status: msg.status,
    involved: msg.involved_agents,
    rca: msg.rca ?? existing?.rca ?? null,
    turns: existing?.turns ?? [],
    updatedAt: msg.ts,
  };
  const isNew = existing === undefined;
  const incidentOrder = isNew
    ? [msg.correlation_id, ...state.incidentOrder].slice(0, MAX_INCIDENTS)
    : state.incidentOrder;
  const incidents = { ...state.incidents, [msg.correlation_id]: incident };
  // Drop incidents that fell off the order cap.
  if (isNew) {
    for (const id of Object.keys(incidents)) {
      if (!incidentOrder.includes(id)) delete incidents[id];
    }
  }
  return { ...state, incidents, incidentOrder };
}

function applyTurn(
  state: AgentsState,
  msg: Extract<AgentActivityMessage, { type: "conversation.turn" }>,
): AgentsState {
  const existing = state.incidents[msg.correlation_id];
  if (existing === undefined) {
    // A turn can arrive before its ticket in a lossy stream; seed a stub.
    const stub: Incident = {
      correlationId: msg.correlation_id,
      ticketId: "",
      title: "(incident forming)",
      severity: "unknown",
      status: "open",
      involved: [],
      rca: null,
      turns: [msg],
      updatedAt: msg.ts,
    };
    return {
      ...state,
      incidents: { ...state.incidents, [msg.correlation_id]: stub },
      incidentOrder: [msg.correlation_id, ...state.incidentOrder].slice(0, MAX_INCIDENTS),
    };
  }
  const incident: Incident = {
    ...existing,
    turns: [...existing.turns, msg],
    updatedAt: msg.ts,
  };
  return { ...state, incidents: { ...state.incidents, [msg.correlation_id]: incident } };
}

export type AgentsAction =
  | { readonly kind: "message"; readonly msg: AgentActivityMessage }
  | { readonly kind: "reset" };

export function reducer(state: AgentsState, action: AgentsAction): AgentsState {
  if (action.kind === "reset") return makeInitialState();
  const { msg } = action;
  switch (msg.type) {
    case "agent.state":
      return applyAgentState(state, msg);
    case "incident.ticket":
      return applyTicket(state, msg);
    case "conversation.turn":
      return applyTurn(state, msg);
    default:
      return state;
  }
}

/** Count of agents currently engaged (not idle/watching). */
export function activeAgentCount(state: AgentsState): number {
  return Object.values(state.agents).filter(
    (a) => a.state !== "idle" && a.state !== "watching",
  ).length;
}
