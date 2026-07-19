import { openDeckWithPrompt } from "../deck/open-deck";
import { routeHref } from "../router";
import {
  AGENT_ROLE,
  STATE_TASK,
  type AgentNode,
  type Incident,
} from "./agents.model";
import { STATE_LABEL } from "./agents.view-model";

export function isAgentEventExpanded(
  correlationId: string,
  selectedIncidentId: string | null,
): boolean {
  return correlationId === selectedIncidentId;
}

/**
 * Focus panel shown when the operator clicks an agent. Answers "who is this
 * and what events is it working?" - the role title + one-line duty, its
 * reporting line, the live state, and every incident it participates in
 * (newest first, clickable to select that incident). Read-only.
 */
export function AgentFocus({
  node,
  incidents,
  selectedIncidentId,
  onClose,
  onChat,
  onPickIncident,
}: {
  readonly node: AgentNode;
  readonly incidents: readonly Incident[];
  readonly selectedIncidentId: string | null;
  readonly onClose: () => void;
  readonly onChat: () => void;
  readonly onPickIncident: (id: string) => void;
}) {
  const role = AGENT_ROLE[node.name];
  const task = STATE_TASK[node.state] ?? node.state;
  return (
    <div class={`agent-focus layer-${node.layer}`}>
      <div class="agent-focus-head">
        <div>
          <strong class="agent-focus-name">{node.name}</strong>
          {role && <span class="agent-focus-title">{role.title}</span>}
        </div>
        <button type="button" class="agent-focus-close" aria-label="Close agent focus" onClick={onClose}>
          {"\u00d7"}
        </button>
      </div>
      {role && <p class="agent-focus-summary">{role.summary}</p>}
      <div class="agent-focus-meta">
        {role?.reportsTo && (
          <span class="agent-focus-reports">
            Reports to <strong>{role.reportsTo}</strong>
            {role.staff ? " (staff)" : ""}
          </span>
        )}
        <span class={`agent-focus-state state-${node.state}`}>
          {STATE_LABEL[node.state] ?? node.state}
        </span>
      </div>
      <p class="agent-focus-task">{task}</p>
      <div class="agent-focus-actions">
        <button type="button" class="agent-focus-chat" onClick={onChat}>
          <span class="agent-focus-chat-glyph" aria-hidden="true">
            {"\u25c6"}
          </span>
          Chat with {node.name}
        </button>
        <a href={routeHref("agent-activity", {
          params: { agent: node.name, correlation: node.correlationId },
        })}>
          Activity
        </a>
      </div>
      <div class="agent-focus-events">
        <h4>
          Events <span class="agent-focus-count">{incidents.length}</span>
        </h4>
        {incidents.length === 0 ? (
          <p class="agents-empty">No incidents involve {node.name} yet.</p>
        ) : (
          <ul>
            {incidents.map((inc) => {
              const isOpen = isAgentEventExpanded(inc.correlationId, selectedIncidentId);
              return (
                <li key={inc.correlationId} class={`incident-item${isOpen ? " is-open" : ""}`}>
                  <button
                    type="button"
                    class={`incident-row sev-${inc.severity} status-${inc.status}${
                      isOpen ? " is-selected" : ""
                    }`}
                    aria-expanded={isOpen}
                    onClick={() => onPickIncident(inc.correlationId)}
                  >
                    <span class="incident-status">{inc.status}</span>
                    <span class="incident-title">{inc.title}</span>
                    <span class="incident-ticket">{inc.ticketId}</span>
                  </button>
                  {isOpen && <IncidentWorkflow incident={inc} />}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

export function IncidentWorkflow({ incident }: { incident: Incident | null }) {
  if (incident === null) {
    return (
      <div class="incident-workflow is-empty">
        <p>Select an incident to watch the agents collaborate.</p>
      </div>
    );
  }
  const steps: { readonly key: string; readonly label: string; readonly done: boolean }[] = [
    { key: "detect", label: "Detect", done: true },
    { key: "ticket", label: "Ticket", done: incident.ticketId !== "" },
    {
      key: "rca",
      label: "RCA",
      done: incident.status === "investigating" || incident.status === "resolved",
    },
    { key: "resolve", label: "Resolve", done: incident.status === "resolved" },
  ];
  return (
    <div class="incident-workflow">
      <div class="incident-workflow-head">
        <span class={`incident-status status-${incident.status}`}>{incident.status}</span>
        <span class="incident-workflow-title">{incident.title}</span>
        <span class="incident-ticket">{incident.ticketId}</span>
      </div>

      <div class="incident-deck-actions">
        <button
          type="button"
          class="incident-ask-deck"
          onClick={() =>
            openDeckWithPrompt(
              `About incident ${incident.ticketId} (${incident.correlationId}): what is the root cause and what are the agents doing?`,
            )
          }
        >
          Ask the deck about this incident
        </button>
        <span class="incident-deck-hint">
          Questions are read-only; a command opens a proposal (judged, never
          executed here).
        </span>
      </div>

      <nav class="incident-evidence-links" aria-label="Incident evidence">
        <a href={routeHref("incidents", { params: { status: "all", correlation: incident.correlationId } })}>Incident</a>
        <a href={routeHref("trace", { params: { correlation: incident.correlationId } })}>Trace</a>
        <a href={routeHref("audit", { params: { correlation: incident.correlationId } })}>Audit</a>
        <a href={routeHref("rca", { params: { correlation: incident.correlationId } })}>RCA</a>
      </nav>

      <ol class="incident-steps">
        {steps.map((s) => (
          <li key={s.key} class={s.done ? "step-done" : "step-pending"}>
            {s.label}
          </li>
        ))}
      </ol>

      <div class="incident-conversation" aria-label="agent conversation">
        {incident.turns.length === 0 ? (
          <p class="agents-empty">No conversation yet.</p>
        ) : (
          incident.turns.map((t, i) => (
            <div key={i} class={`turn kind-${t.kind}`}>
              <span class="turn-from">{t.from_agent}</span>
              <span class="turn-arrow" aria-hidden="true">
                {"->"}
              </span>
              <span class="turn-to">{t.to_agent}</span>
              <span class="turn-text">{t.text}</span>
            </div>
          ))
        )}
      </div>

      {incident.rca !== null && (
        <div class="incident-rca">
          <span class="incident-rca-label">Root cause</span>
          <p>{incident.rca}</p>
        </div>
      )}
    </div>
  );
}
