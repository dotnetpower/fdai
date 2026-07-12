/**
 * Now > Agents route (Track B, Phase 2).
 *
 * An agent-centric, read-only view of the pantheon: all 15 agents as a
 * constellation with a live status ring, that lights up the involved
 * agents when an incident (e.g. a chaos experiment) fires and renders the
 * collaboration (detect -> ticket -> RCA conversation -> resolve) as it
 * streams over `GET /agents/stream`.
 *
 * Pure read-only: no privileged calls. The SSE consumer
 * ({@link useAgentStream}) is a translator, never a judge.
 */

import { useEffect, useMemo, useReducer, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { loadConfig } from "../config";
import { useAgentStream } from "../hooks/use-agent-stream";
import { usePublishViewContext } from "../deck/context";
import { agentTerm, composeGlossary, TERMS } from "../deck/glossary";
import { openDeckWithPrompt } from "../deck/open-deck";
import {
  PANTHEON,
  activeAgentCount,
  makeInitialState,
  reducer,
  type Incident,
} from "./agents.model";

interface Props {
  readonly client: ReadApiClient;
}

const _STATE_LABEL: Record<string, string> = {
  idle: "idle",
  watching: "watching",
  collecting: "collecting",
  analyzing: "analyzing",
  deciding: "deciding",
  executing: "executing",
  approving: "approving",
  auditing: "auditing",
};

export function AgentsRoute({ client: _client }: Props) {
  const [state, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const url = useMemo(() => {
    const cfg = loadConfig();
    const base =
      cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/agents/stream`;
  }, []);

  const { status } = useAgentStream({
    url,
    onEvent: (msg) => dispatch({ kind: "message", msg }),
  });

  // Auto-follow the newest incident until the operator picks one.
  const [pinned, setPinned] = useState(false);
  useEffect(() => {
    if (!pinned && state.incidentOrder.length > 0) {
      const first = state.incidentOrder[0];
      if (first) setSelectedId(first);
    }
  }, [state.incidentOrder, pinned]);

  const selected: Incident | null = selectedId ? (state.incidents[selectedId] ?? null) : null;
  const involved = useMemo(
    () => new Set(selected?.involved ?? []),
    [selected],
  );

  const active = activeAgentCount(state);

  usePublishViewContext(
    () => ({
      routeId: "agents",
      routeLabel: "Agents",
      purpose:
        "The 15-agent pantheon, live. Each incident (correlation id) is one " +
        "collaboration: Huginn/Heimdall sense, Forseti judges, Var queues a HIL " +
        "approval, Thor executes, Saga records. Read-only - ask the deck about " +
        "the selected incident, or propose a runtime action (it is judged, never " +
        "executed from here).",
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.hil,
        TERMS.outcome,
        TERMS.gateDecision,
        agentTerm(),
      ]),
      headline: selected
        ? `${selected.title} (${selected.status}) - ${selected.involved.length} agent(s), ${selected.turns.length} turn(s)`
        : `${state.incidentOrder.length} incident(s) - ${active} agent(s) engaged`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "incidents", value: state.incidentOrder.length, group: "page" },
        { key: "engaged", value: active, group: "page" },
        { key: "selected", value: selected?.ticketId ?? "-", group: "incident" },
        { key: "status", value: selected?.status ?? "-", group: "incident" },
        { key: "severity", value: selected?.severity ?? "-", group: "incident" },
      ],
      records: {
        // The selected incident's agent-to-agent conversation so the deck can
        // answer "what's the root cause / who's involved / what did they say"
        // grounded in the live thread. Empty when nothing is selected.
        conversation: (selected?.turns ?? []).slice(-40).map((t) => ({
          from_agent: t.from_agent,
          to_agent: t.to_agent,
          kind: t.kind,
          text: t.text,
          at: t.ts,
        })),
        incidents: state.incidentOrder.map((id) => {
          const inc = state.incidents[id];
          return {
            ticket: inc?.ticketId ?? id,
            title: inc?.title ?? "-",
            status: inc?.status ?? "-",
            severity: inc?.severity ?? "-",
            correlation_id: id,
          };
        }),
      },
    }),
    [state, selected, active],
  );

  return (
    <div class="agents-route">
      <header class="agents-head">
        <div>
          <h2>Agents</h2>
          <p class="agents-sub">
            The 15-agent pantheon, live. An incident lights up the agents that
            collaborate to detect, ticket, and resolve it. Wire:{" "}
            <code>GET /agents/stream</code>.
          </p>
        </div>
        <div class="agents-meta">
          <span class={`agents-conn conn-${status}`}>{status}</span>
          <span class="agents-active">
            <strong>{active}</strong> engaged
          </span>
        </div>
      </header>

      <div class="agents-layout">
        <section class="agents-constellation" aria-label="agent constellation">
          {PANTHEON.map(({ name }) => {
            const node = state.agents[name];
            if (!node) return null;
            const isInvolved = involved.has(name);
            const dim = selected !== null && !isInvolved;
            return (
              <div
                key={name}
                class={`agent-node layer-${node.layer} state-${node.state}${
                  isInvolved ? " is-involved" : ""
                }${dim ? " is-dim" : ""}`}
                title={`${name} - ${_STATE_LABEL[node.state] ?? node.state}`}
              >
                <span class="agent-ring" aria-hidden="true" />
                <span class="agent-name">{name}</span>
                <span class="agent-state">{_STATE_LABEL[node.state] ?? node.state}</span>
              </div>
            );
          })}
        </section>

        <aside class="agents-side">
          <div class="agents-incident-list" aria-label="incidents">
            <h3>Incidents</h3>
            {state.incidentOrder.length === 0 ? (
              <p class="agents-empty">No incidents - autonomy holding.</p>
            ) : (
              <ul>
                {state.incidentOrder.map((id) => {
                  const inc = state.incidents[id];
                  if (!inc) return null;
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        class={`incident-row sev-${inc.severity} status-${inc.status}${
                          id === selectedId ? " is-selected" : ""
                        }`}
                        onClick={() => {
                          setSelectedId(id);
                          setPinned(true);
                        }}
                      >
                        <span class="incident-status">{inc.status}</span>
                        <span class="incident-title">{inc.title}</span>
                        <span class="incident-ticket">{inc.ticketId}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <IncidentWorkflow incident={selected} />
        </aside>
      </div>
    </div>
  );
}

function IncidentWorkflow({ incident }: { incident: Incident | null }) {
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
