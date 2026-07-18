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
import type { IncidentSummary } from "../types";

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

export type AgentRuntimeBinding =
  | "event-bus subscriber"
  | "raw ingress subscriber"
  | "external adapter"
  | "scheduled trigger";

export const AGENT_RUNTIME_BINDING: Readonly<Record<string, AgentRuntimeBinding>> = {
  Odin: "event-bus subscriber",
  Thor: "event-bus subscriber",
  Forseti: "event-bus subscriber",
  Huginn: "raw ingress subscriber",
  Heimdall: "event-bus subscriber",
  Vidar: "event-bus subscriber",
  Var: "event-bus subscriber",
  Bragi: "event-bus subscriber",
  Saga: "event-bus subscriber",
  Mimir: "event-bus subscriber",
  Muninn: "event-bus subscriber",
  Norns: "event-bus subscriber",
  Njord: "external adapter",
  Freyr: "external adapter",
  Loki: "scheduled trigger",
};

export function runtimeConsumerCount(): number {
  return Object.values(AGENT_RUNTIME_BINDING).filter(
    (binding) => binding === "event-bus subscriber" || binding === "raw ingress subscriber",
  ).length;
}

const _LAYER_OF: Record<string, AgentLayer> = Object.fromEntries(
  PANTHEON.map((a) => [a.name, a.layer]),
);

export interface AgentNode {
  readonly name: string;
  readonly layer: AgentLayer;
  readonly state: AgentStatus;
  readonly observed: boolean;
  readonly correlationId: string | null;
  readonly since: string;
  /** Free-text task description streamed with the state (may be null). */
  readonly detail: string | null;
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
    agents[name] = {
      name,
      layer,
      state: "idle",
      observed: false,
      correlationId: null,
      since: "",
      detail: null,
    };
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
    observed: true,
    correlationId: msg.correlation_id,
    since: msg.ts,
    detail: msg.detail,
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
  | { readonly kind: "hydrate"; readonly incidents: readonly IncidentSummary[] }
  | { readonly kind: "reset" };

function hydrateIncidents(
  state: AgentsState,
  summaries: readonly IncidentSummary[],
): AgentsState {
  const incidents = { ...state.incidents };
  for (const summary of summaries) {
    const existing = incidents[summary.correlation_id];
    if (
      existing &&
      new Date(existing.updatedAt).getTime() > new Date(summary.last_updated_at).getTime()
    ) continue;
    incidents[summary.correlation_id] = {
      correlationId: summary.correlation_id,
      ticketId: summary.ticket_id ?? summary.incident_id ?? `INC-${summary.correlation_id}`,
      title: summary.title,
      severity: summary.severity,
      status: summary.status === "in_progress" ? "investigating" : summary.status,
      involved: summary.involved_agents,
      rca: existing?.rca ?? null,
      turns: existing?.turns ?? [],
      updatedAt: summary.last_updated_at,
    };
  }
  const agents = { ...state.agents };
  const awaitingApproval = summaries.find(
    (summary) =>
      summary.disposition === "awaiting_hil" &&
      summary.status !== "resolved" &&
      summary.involved_agents.includes("Var"),
  );
  const currentVar = agents.Var;
  if (
    awaitingApproval &&
    currentVar &&
    new Date(currentVar.since || 0).getTime() <=
      new Date(awaitingApproval.last_updated_at).getTime()
  ) {
    agents.Var = {
      ...currentVar,
      state: "approving",
      observed: true,
      correlationId: awaitingApproval.correlation_id,
      since: awaitingApproval.last_updated_at,
      detail: "awaiting human approval",
    };
  }
  const incidentOrder = [
    ...summaries.map((summary) => summary.correlation_id),
    ...state.incidentOrder,
  ].filter((id, index, all) => all.indexOf(id) === index).slice(0, MAX_INCIDENTS);
  return {
    ...state,
    agents,
    incidents: Object.fromEntries(
      Object.entries(incidents).filter(([id]) => incidentOrder.includes(id)),
    ),
    incidentOrder,
  };
}

export function reducer(state: AgentsState, action: AgentsAction): AgentsState {
  if (action.kind === "reset") return makeInitialState();
  if (action.kind === "hydrate") return hydrateIncidents(state, action.incidents);
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

export function currentRuntimeCount(streamOpen: boolean, count: number): number | null {
  return streamOpen ? count : null;
}

/** True when an agent is actively working (not resting or merely watching). */
export function isEngaged(node: AgentNode): boolean {
  return node.state !== "idle" && node.state !== "watching";
}

/**
 * A one-line, human-readable description of what an agent doing `state`
 * is working on. Used by the constellation hover card so an operator can
 * tell collecting from analyzing from executing at a glance.
 */
export const STATE_TASK: Readonly<Record<AgentStatus, string>> = {
  idle: "Resting - no active work",
  watching: "On standby watch, sensing signals",
  collecting: "Ingesting and correlating signals for an event",
  analyzing: "Root-cause reasoning on the incident",
  deciding: "Issuing a verdict at the risk gate",
  executing: "Applying an approved remediation",
  approving: "Reviewing a human-in-the-loop approval",
  auditing: "Writing the append-only audit record",
};

/** One cluster of agents currently co-engaged on the same incident. */
export interface EngagedGroup {
  readonly correlationId: string;
  /** Engaged agent names, sorted for a stable render order. */
  readonly agents: readonly string[];
  /** The incident they collaborate on, when its ticket has arrived. */
  readonly incident: Incident | null;
}

/**
 * Group every currently-engaged agent by the incident (`correlationId`)
 * it is working on. This is the source of truth for the constellation's
 * connection lines: each returned group becomes one set of links tying
 * the collaborating agents to a single ticket, so an operator can see
 * *who is working on which ticket with whom* at a glance.
 *
 * Agents that are idle, merely watching, or not attached to any
 * correlation id are excluded. Groups are returned newest-incident-first
 * (by incident order) with unknown incidents last, so colours stay stable.
 */
export function engagedGroups(state: AgentsState): EngagedGroup[] {
  const byCorr = new Map<string, string[]>();
  for (const node of Object.values(state.agents)) {
    if (!isEngaged(node) || node.correlationId === null) continue;
    const arr = byCorr.get(node.correlationId) ?? [];
    arr.push(node.name);
    byCorr.set(node.correlationId, arr);
  }
  const order = (id: string): number => {
    const idx = state.incidentOrder.indexOf(id);
    return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
  };
  return [...byCorr.entries()]
    .map(([correlationId, agents]) => ({
      correlationId,
      agents: [...agents].sort(),
      incident: state.incidents[correlationId] ?? null,
    }))
    .sort((a, b) => order(a.correlationId) - order(b.correlationId));
}

/** Role card for one agent: its title, one-line duty, and reporting line. */
export interface AgentRole {
  readonly title: string;
  readonly summary: string;
  /** Manager in the org chart, or null for the top (Odin). */
  readonly reportsTo: string | null;
  /** True for a staff agent (dotted line to Odin, off the operations line). */
  readonly staff: boolean;
}

/**
 * The fixed pantheon org chart (see docs/roadmap/agents/agent-pantheon.md
 * § 2). Two lines report to Odin - Thor (operations) and Forseti
 * (judgment); four governance staff report as staff (dotted) to Odin;
 * recovery/approval/narration sit under Thor and sensing/domain sit under
 * Forseti. Fork-locked upstream, so a static map is safe.
 */
export const AGENT_ROLE: Readonly<Record<string, AgentRole>> = {
  Odin: {
    title: "Master Planner",
    summary: "Cross-vertical arbitration; final tie-breaker before a verdict is finalized.",
    reportsTo: null,
    staff: false,
  },
  Thor: {
    title: "Responder",
    summary: "Dispatches verdicts and is the sole privileged executor; never judges.",
    reportsTo: "Odin",
    staff: false,
  },
  Forseti: {
    title: "Judge",
    summary: "Issues the verdict (auto / hil / deny) after cross-check, verifier, grounding.",
    reportsTo: "Odin",
    staff: false,
  },
  Vidar: {
    title: "Recovery",
    summary: "Rollback and disaster-recovery failover principal.",
    reportsTo: "Thor",
    staff: false,
  },
  Bragi: {
    title: "Narrator",
    summary: "Conversational-port translator only; never calls an executor directly.",
    reportsTo: "Thor",
    staff: false,
  },
  Var: {
    title: "Approver",
    summary: "Human-in-the-loop approval principal; stays distinct from Thor.",
    reportsTo: "Thor",
    staff: false,
  },
  Huginn: {
    title: "Event Collector",
    summary: "Owns real-time resource discovery ingress and normalizes events; cloud I/O stays in adapters.",
    reportsTo: "Forseti",
    staff: false,
  },
  Heimdall: {
    title: "Observer",
    summary: "Monitors discovery freshness and coverage, then correlates signals into findings.",
    reportsTo: "Forseti",
    staff: false,
  },
  Njord: {
    title: "Cost",
    summary: "Cost / FinOps domain specialist; advises Forseti, does not execute.",
    reportsTo: "Forseti",
    staff: false,
  },
  Freyr: {
    title: "Capacity",
    summary: "Capacity / forecast domain specialist; advises Forseti, does not execute.",
    reportsTo: "Forseti",
    staff: false,
  },
  Loki: {
    title: "Chaos",
    summary: "Chaos / resilience specialist; schedules experiments, advises Forseti.",
    reportsTo: "Forseti",
    staff: false,
  },
  Mimir: {
    title: "Rule Steward",
    summary: "Owns the rule catalog; grounds Forseti's judgments in current rules.",
    reportsTo: "Odin",
    staff: true,
  },
  Muninn: {
    title: "Memory",
    summary: "Memory / context store; supplies prior-incident context to Forseti and Bragi.",
    reportsTo: "Odin",
    staff: true,
  },
  Saga: {
    title: "Auditor",
    summary: "Append-only audit of every terminal state; materializes handoffs.",
    reportsTo: "Odin",
    staff: true,
  },
  Norns: {
    title: "Learner",
    summary: "Learns from audited outcomes and proposes rule revisions to Mimir.",
    reportsTo: "Odin",
    staff: true,
  },
};

/** One manager and its direct reports in the org-chart layout. */
export interface OrgLine {
  readonly manager: string;
  readonly reports: readonly string[];
}

/**
 * The org-chart layout skeleton: the root, the two operations/judgment
 * lines under it, and the staff cluster. Drives the hierarchical
 * "Org chart" view and the reporting-line overlay.
 */
export const ORG_CHART: {
  readonly root: string;
  readonly lines: readonly OrgLine[];
  readonly staff: readonly string[];
} = {
  root: "Odin",
  lines: [
    { manager: "Thor", reports: ["Vidar", "Bragi", "Var"] },
    { manager: "Forseti", reports: ["Huginn", "Heimdall", "Njord", "Freyr", "Loki"] },
  ],
  staff: ["Mimir", "Muninn", "Saga", "Norns"],
};

/**
 * Every incident (newest first) an agent participates in - the ticket lists
 * the agent in `involved_agents`. Powers the "click an agent to see its
 * events" focus panel.
 */
export function incidentsForAgent(state: AgentsState, agent: string): Incident[] {
  return state.incidentOrder
    .map((id) => state.incidents[id])
    .filter((inc): inc is Incident => inc !== undefined && inc.involved.includes(agent));
}

/**
 * Build the grounding context injected into the deck when an operator starts
 * a conversation about one agent. It summarizes the agent's role, live state,
 * and recent incidents (newest first) so the narrator can answer questions
 * about "what has this agent been doing" immediately, grounded in real
 * activity. English (L0 pipeline); `incidents` is expected to already be
 * scoped to this agent (see {@link incidentsForAgent}).
 */
export function agentChatContext(node: AgentNode, incidents: readonly Incident[]): string {
  const role = AGENT_ROLE[node.name];
  const lines: string[] = [];
  lines.push(
    `Context for a conversation about the FDAI agent ${node.name}` +
      (role ? ` (${role.title})` : "") +
      ".",
  );
  if (role) {
    lines.push(`Role: ${role.summary}`);
    if (role.reportsTo) {
      lines.push(`Reports to ${role.reportsTo}${role.staff ? " (staff)" : ""}.`);
    }
  }
  const task = STATE_TASK[node.state] ?? node.state;
  lines.push(`Current state: ${node.state} - ${task}.`);
  if (incidents.length === 0) {
    lines.push(`${node.name} has not participated in any incident yet.`);
  } else {
    lines.push(`Recent incidents ${node.name} worked (newest first):`);
    for (const inc of incidents.slice(0, 6)) {
      const ticket = inc.ticketId || inc.correlationId;
      const rca = inc.rca ? ` - RCA: ${inc.rca}` : "";
      lines.push(`- ${ticket} (${inc.status}, ${inc.severity}) ${inc.title}${rca}`);
    }
  }
  lines.push(
    `Answer the operator's questions about what ${node.name} has been doing, ` +
      "grounded in this activity.",
  );
  return lines.join("\n");
}
