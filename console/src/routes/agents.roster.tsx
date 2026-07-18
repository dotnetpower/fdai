import type { ObservationSource } from "../hooks/observation-source";
import { observationSourceLabel } from "../hooks/observation-source";
import { routeHref } from "../router";
import { openDeckWithContext } from "../deck/open-deck";
import {
  AGENT_ROLE,
  AGENT_RUNTIME_BINDING,
  agentChatContext,
  incidentsForAgent,
  runtimeConsumerCount,
  type AgentNode,
  type AgentsState,
} from "./agents.model";
import {
  STATE_LABEL,
  agentIconUrl,
  currentTask,
  rosterLayerOf,
  stateTime,
  type RosterLayer,
  type RosterState,
} from "./agents.view-model";

export function AgentRoster({
  agents,
  state,
  layer,
  stateFilter,
  query,
  active,
  watching,
  idle,
  unobserved,
  runtimeCurrent,
  streamSource,
  onLayerChange,
  onStateChange,
  onQueryChange,
  onOpen,
}: {
  readonly agents: readonly AgentNode[];
  readonly state: AgentsState;
  readonly layer: RosterLayer;
  readonly stateFilter: RosterState;
  readonly query: string;
  readonly active: number | null;
  readonly watching: number | null;
  readonly idle: number | null;
  readonly unobserved: number;
  readonly runtimeCurrent: boolean;
  readonly streamSource: ObservationSource;
  readonly onLayerChange: (value: RosterLayer) => void;
  readonly onStateChange: (value: RosterState) => void;
  readonly onQueryChange: (value: string) => void;
  readonly onOpen: (name: string) => void;
}) {
  const recentTouches = Object.values(state.incidents).reduce(
    (total, incident) => total + incident.involved.length,
    0,
  );
  const latestSignalMs = [
    ...Object.values(state.agents).map((agent) => new Date(agent.since).getTime()),
    ...Object.values(state.incidents).map((incident) => new Date(incident.updatedAt).getTime()),
  ].reduce((latest, value) => Number.isFinite(value) ? Math.max(latest, value) : latest, 0);
  const latestSignal = latestSignalMs > 0 ? stateTime(new Date(latestSignalMs).toISOString()) : "No signal yet";
  return (
    <div class="agent-roster">
      <section class="agent-roster-note" aria-label="Roster interpretation">
        <strong>State is descriptive, not prescriptive.</strong>
        <span>
          Engaged counts agents handling a pipeline stage now, not every subscribed runtime
          loop. Idle agents wake on their topics. This console observes work; it does not
          approve or execute actions.
          {` Live delta source: ${observationSourceLabel(streamSource)}. Incident history comes from the durable audit projection.`}
        </span>
      </section>

      <section class="agent-discovery-note" aria-label="Resource discovery ownership">
        <div>
          <strong>Resource discovery</strong>
          <span>Huginn real-time ingress</span>
        </div>
        <p>
          Azure resource writes and deletes enter through Event Hubs and Huginn continuously.
          The Inventory sync job still runs Azure Resource Graph with ARM fallback every 6 hours
          to reconcile missed signals. Heimdall monitors freshness and coverage. The local harness
          does not run Azure discovery.
        </p>
      </section>

      <section class="agent-roster-summary" aria-label="Fleet summary">
        <RosterSummary
          label="Subscriber bindings"
          value={runtimeConsumerCount()}
          detail="declared, not health-probed"
          kind="consumers"
        />
        <RosterSummary label="Engaged" value={active ?? "-"} detail={runtimeCurrent ? "working now" : "live stream unavailable"} kind="engaged" />
        <RosterSummary label="Watching" value={watching ?? "-"} detail={runtimeCurrent ? "sensing signals" : "last state retained"} kind="watching" />
        <RosterSummary label="Idle" value={idle ?? "-"} detail={runtimeCurrent ? "ready to wake" : "last state retained"} kind="idle" />
        <RosterSummary label="Unobserved" value={unobserved} detail="no runtime signal" kind="idle" />
        <RosterSummary
          label="Incidents"
          value={state.incidentOrder.length}
          detail="retained collaborations"
          kind="incidents"
        />
        <RosterSummary
          label="Recent touches"
          value={recentTouches}
          detail={`last signal ${latestSignal}`}
          kind="activity"
        />
      </section>

      <section class="agent-roster-toolbar" aria-label="Roster filters">
        <RosterFilter
          label="Layer"
          values={["all", "governance", "pipeline", "domain"]}
          selected={layer}
          onSelect={(value) => onLayerChange(value as RosterLayer)}
        />
        <RosterFilter
          label="State"
          values={["all", "engaged", "watching", "idle", "unobserved"]}
          selected={stateFilter}
          onSelect={(value) => onStateChange(value as RosterState)}
        />
        <label class="agent-roster-search">
          <span class="sr-only">Filter agents</span>
          <input
            type="search"
            value={query}
            placeholder="Agent, role, or current work"
            onInput={(event) => onQueryChange(event.currentTarget.value)}
          />
        </label>
      </section>

      {agents.length === 0 ? (
        <div class="agent-roster-empty">
          <strong>No agents match these filters.</strong>
          <button
            type="button"
            onClick={() => {
              onLayerChange("all");
              onStateChange("all");
              onQueryChange("");
            }}
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div class="agent-roster-grid">
          {agents.map((node) => {
            const role = AGENT_ROLE[node.name];
            const incident = node.correlationId ? state.incidents[node.correlationId] : undefined;
            const agentIncidents = incidentsForAgent(state, node.name);
            const iconUrl = agentIconUrl(node.name);
            return (
              <article class={`agent-roster-card layer-${node.layer}`} key={node.name}>
                <header>
                  <span class="agent-roster-avatar" aria-hidden="true">
                    <span
                      class="agent-icon"
                      style={{ WebkitMaskImage: iconUrl, maskImage: iconUrl }}
                    />
                  </span>
                  <div>
                    <h3>{node.name}</h3>
                    <p>{role?.title ?? node.layer} · {rosterLayerOf(node.name)}</p>
                  </div>
                  <span class={`agent-roster-state state-${node.state}`}>
                    {STATE_LABEL[node.state] ?? node.state}
                  </span>
                </header>
                <p class="agent-roster-task">
                  <span>Current work</span>
                  <strong>{currentTask(node)}</strong>
                </p>
                <dl>
                  <div>
                    <dt>Active incident</dt>
                    <dd>{incident?.ticketId || "None"}</dd>
                  </div>
                  <div>
                    <dt>State since</dt>
                    <dd>{stateTime(node.since)}</dd>
                  </div>
                  <div>
                    <dt>Recent events</dt>
                    <dd>{agentIncidents.length}</dd>
                  </div>
                  <div>
                    <dt>Reports to</dt>
                    <dd>{role?.reportsTo ?? "-"}{role?.staff ? " (staff)" : ""}</dd>
                  </div>
                  <div>
                    <dt>Runtime binding</dt>
                    <dd>{AGENT_RUNTIME_BINDING[node.name] ?? "not configured"}</dd>
                  </div>
                  <div>
                    <dt>Authority</dt>
                    <dd>{node.name === "Thor" ? "Execute" : node.name === "Var" ? "Approve" : "Observe / advise"}</dd>
                  </div>
                </dl>
                <footer>
                  <button type="button" onClick={() => onOpen(node.name)}>Open</button>
                  <a href={routeHref("agent-activity", { params: { agent: node.name } })}>
                    Activity
                  </a>
                  <button
                    type="button"
                    class="is-primary"
                    onClick={() =>
                      openDeckWithContext({
                        sessionKey: `agent:${node.name}`,
                        sessionLabel: node.name,
                        contextNote: agentChatContext(node, agentIncidents),
                        prompt: `What has ${node.name} been working on?`,
                      })
                    }
                  >
                    Ask {node.name}
                  </button>
                </footer>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function RosterSummary({
  label,
  value,
  detail,
  kind,
}: {
  readonly label: string;
  readonly value: number | string;
  readonly detail: string;
  readonly kind: string;
}) {
  return (
    <article class={`agent-roster-kpi kind-${kind}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function RosterFilter({
  label,
  values,
  selected,
  onSelect,
}: {
  readonly label: string;
  readonly values: readonly string[];
  readonly selected: string;
  readonly onSelect: (value: string) => void;
}) {
  return (
    <div class="agent-roster-filter">
      <span>{label}</span>
      <div role="group" aria-label={`${label} filter`}>
        {values.map((value) => (
          <button
            type="button"
            key={value}
            class={selected === value ? "is-active" : undefined}
            aria-pressed={selected === value}
            onClick={() => onSelect(value)}
          >
            {value === "all" ? "All" : value[0]?.toUpperCase() + value.slice(1)}
          </button>
        ))}
      </div>
    </div>
  );
}
