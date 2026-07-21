import { openDeckWithContext } from "../deck/open-deck";
import { t } from "../i18n";
import { routeHref } from "../router";
import {
  AGENT_ROLE,
  type AgentNode,
  type Incident,
} from "./agents.model";
import {
  agentRoleSummary,
  agentRoleTitle,
  agentStateLabel,
  stateTaskLabel,
} from "./agents.view-model";

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
  const task = node.detail ?? stateTaskLabel(node.state);
  return (
    <section
      class={`agent-focus layer-${node.layer}`}
      aria-labelledby={`agent-focus-name-${node.name}`}
    >
      <div class="agent-focus-head">
        <div>
          <strong id={`agent-focus-name-${node.name}`} class="agent-focus-name">
            {node.name}
          </strong>
          {role && <span class="agent-focus-title">{agentRoleTitle(node.name)}</span>}
        </div>
        <button type="button" class="agent-focus-close" aria-label={t("agents.focus.closeLabel")} onClick={onClose}>
          {"\u00d7"}
        </button>
      </div>
      {role && <p class="agent-focus-summary">{agentRoleSummary(node.name)}</p>}
      <div class="agent-focus-meta">
        {role?.reportsTo && (
          <span class="agent-focus-reports">
            {t("agents.card.reportsTo")} <strong>{role.reportsTo}</strong>
            {role.staff ? ` (${t("agents.common.staff")})` : ""}
          </span>
        )}
        <span class={`agent-focus-state state-${node.state}`}>
          {agentStateLabel(node)}
        </span>
      </div>
      <p class="agent-focus-task">{task}</p>
      <div class="agent-focus-actions">
        <button type="button" class="agent-focus-chat" onClick={onChat}>
          <span class="agent-focus-chat-glyph" aria-hidden="true">
            {"\u25c6"}
          </span>
          {t("agents.focus.chat", { agent: node.name })}
        </button>
        <a href={routeHref("agent-activity", {
          params: { agent: node.name, correlation: node.correlationId },
        })}>
          {t("agents.workspace.activity")}
        </a>
      </div>
      <div class="agent-focus-events">
        <h4>
          {t("agents.focus.events")} <span class="agent-focus-count">{incidents.length}</span>
        </h4>
        {incidents.length === 0 ? (
          <p class="agents-empty">{t("agents.focus.noIncidents", { agent: node.name })}</p>
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
                  {isOpen && <IncidentWorkflow agent={node.name} incident={inc} />}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

export function IncidentWorkflow({
  agent,
  incident,
}: {
  readonly agent: string | null;
  readonly incident: Incident | null;
}) {
  if (incident === null) {
    return (
      <div class="incident-workflow is-empty">
        <p>{t("agents.workflow.selectIncident")}</p>
      </div>
    );
  }
  const steps: { readonly key: string; readonly label: string; readonly done: boolean }[] = [
    { key: "detect", label: t("agents.workflow.step.detect"), done: true },
    { key: "ticket", label: t("agents.workflow.step.ticket"), done: incident.ticketId !== "" },
    {
      key: "rca",
      label: t("agents.workflow.step.rca"),
      done: incident.status === "investigating" || incident.status === "resolved",
    },
    { key: "resolve", label: t("agents.workflow.step.resolve"), done: incident.status === "resolved" },
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
            openDeckWithContext({
              sessionKey: agent
                ? `agent:${agent}:incident:${incident.correlationId}`
                : `incident:${incident.correlationId}`,
              sessionLabel: agent ? `${agent} / ${incident.ticketId}` : incident.ticketId,
              contextNote:
                `Selected incident ${incident.ticketId} (${incident.correlationId}) ` +
                (agent ? `from ${agent}'s Events view.` : "from the incident list."),
              prompt: "What is the root cause status, and what are the involved agents doing?",
              binding: {
                kind: "incident",
                incidentId: incident.ticketId,
                correlationId: incident.correlationId,
                ...(agent ? { selectedAgent: agent } : {}),
              },
            })
          }
        >
          {t("agents.workflow.ask")}
        </button>
        <span class="incident-deck-hint">
          {t("agents.workflow.askHint")}
        </span>
      </div>

      <nav class="incident-evidence-links" aria-label={t("agents.workflow.evidenceLabel")}>
        <a href={routeHref("incidents", { params: { status: "all", correlation: incident.correlationId } })}>{t("route.incidents")}</a>
        <a href={routeHref("trace", { params: { correlation: incident.correlationId } })}>{t("route.ruleTrace")}</a>
        <a href={routeHref("audit", { params: { correlation: incident.correlationId } })}>{t("route.audit")}</a>
        <a href={routeHref("rca", { params: { correlation: incident.correlationId } })}>{t("route.rca")}</a>
      </nav>

      <ol class="incident-steps">
        {steps.map((s) => (
          <li key={s.key} class={s.done ? "step-done" : "step-pending"}>
            {s.label}
          </li>
        ))}
      </ol>

      <div class="incident-conversation" aria-label={t("agents.workflow.conversationLabel")}>
        {incident.turns.length === 0 ? (
          <p class="agents-empty">{t("agents.workflow.noConversation")}</p>
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
          <span class="incident-rca-label">{t("agents.workflow.rootCause")}</span>
          <p>{incident.rca}</p>
        </div>
      )}
    </div>
  );
}
