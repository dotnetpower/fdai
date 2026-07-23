import type { ObservationSource } from "../hooks/observation-source";
import { observationSourceLabel } from "../hooks/observation-source";
import { t } from "../i18n";
import { routeHref } from "../router";
import { openDeckWithContext } from "../deck/open-deck";
import {
  AGENT_ROLE,
  agentChatContext,
  incidentsForAgent,
  runtimeConsumerCount,
  type AgentNode,
  type AgentsState,
} from "./agents.model";
import {
  agentIconUrl,
  agentRoleTitle,
  agentRuntimeBindingLabel,
  agentStateLabel,
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
  const latestSignal = latestSignalMs > 0
    ? stateTime(new Date(latestSignalMs).toISOString())
    : t("agents.common.noSignalYet");
  return (
    <div class="agent-roster">
      <section class="agent-roster-note" aria-label={t("agents.roster.interpretationLabel")}>
        <strong>{t("agents.roster.interpretationTitle")}</strong>
        <span>
          {t("agents.roster.interpretationBody", {
            source: observationSourceLabel(streamSource),
          })}
        </span>
      </section>

      <section class="agent-discovery-note" aria-label={t("agents.roster.discoveryLabel")}>
        <div>
          <strong>{t("agents.roster.discoveryTitle")}</strong>
          <span>{t("agents.roster.discoverySource")}</span>
        </div>
        <p>{t("agents.roster.discoveryBody")}</p>
      </section>

      <section class="agent-roster-summary" aria-label={t("agents.roster.summaryLabel")}>
        <RosterSummary
          href={routeHref("agent-activity")}
          label={t("agents.roster.metric.bindings")}
          value={runtimeConsumerCount()}
          detail={t("agents.roster.metric.bindingsDetail")}
          kind="consumers"
        />
        <RosterSummary href={routeHref("agents", { params: { state: "engaged" } })} label={t("agents.roster.metric.engaged")} value={active ?? "-"} detail={runtimeCurrent ? t("agents.roster.metric.workingNow") : t("agents.roster.metric.streamUnavailable")} kind="engaged" />
        <RosterSummary href={routeHref("agents", { params: { state: "watching" } })} label={t("agents.roster.metric.watching")} value={watching ?? "-"} detail={runtimeCurrent ? t("agents.roster.metric.sensingSignals") : t("agents.roster.metric.lastStateRetained")} kind="watching" />
        <RosterSummary href={routeHref("agents", { params: { state: "idle" } })} label={t("agents.roster.metric.idle")} value={idle ?? "-"} detail={runtimeCurrent ? t("agents.roster.metric.readyToWake") : t("agents.roster.metric.lastStateRetained")} kind="idle" />
        <RosterSummary href={routeHref("agents", { params: { state: "unobserved" } })} label={t("agents.roster.metric.unobserved")} value={unobserved} detail={t("agents.roster.metric.noRuntimeSignal")} kind="idle" />
        <RosterSummary
          href={routeHref("incidents", { params: { status: "all" } })}
          label={t("agents.roster.metric.incidents")}
          value={state.incidentOrder.length}
          detail={t("agents.roster.metric.retainedCollaborations")}
          kind="incidents"
        />
        <RosterSummary
          href={routeHref("agent-activity")}
          label={t("agents.roster.metric.recentTouches")}
          value={recentTouches}
          detail={t("agents.roster.metric.lastSignal", { time: latestSignal })}
          kind="activity"
        />
      </section>

      <section class="agent-roster-toolbar" aria-label={t("agents.filter.toolbarLabel")}>
        <RosterFilter
          label={t("agents.filter.layer")}
          values={["all", "governance", "pipeline", "domain"]}
          selected={layer}
          onSelect={(value) => onLayerChange(value as RosterLayer)}
        />
        <RosterFilter
          label={t("agents.filter.state")}
          values={["all", "engaged", "watching", "idle", "unobserved"]}
          selected={stateFilter}
          onSelect={(value) => onStateChange(value as RosterState)}
        />
        <label class="agent-roster-search">
          <span class="sr-only">{t("agents.filter.searchLabel")}</span>
          <input
            type="search"
            value={query}
            placeholder={t("agents.filter.searchPlaceholder")}
            onInput={(event) => onQueryChange(event.currentTarget.value)}
          />
        </label>
      </section>

      {agents.length === 0 ? (
        <div class="agent-roster-empty">
          <strong>{t("agents.filter.empty")}</strong>
          <button
            type="button"
            onClick={() => {
              onLayerChange("all");
              onStateChange("all");
              onQueryChange("");
            }}
          >
            {t("agents.filter.clear")}
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
                    <p>{agentRoleTitle(node.name) ?? node.layer} - {t(`agents.layer.${rosterLayerOf(node.name)}`)}</p>
                  </div>
                  <span class={`agent-roster-state state-${node.state}`}>
                    {agentStateLabel(node)}
                  </span>
                </header>
                <p class="agent-roster-task">
                  <span>{t("agents.card.currentWork")}</span>
                  <strong>{currentTask(node)}</strong>
                </p>
                <dl>
                  <div>
                    <dt>{t("agents.card.activeIncident")}</dt>
                    <dd>{incident?.ticketId || t("agents.common.none")}</dd>
                  </div>
                  <div>
                    <dt>{t("agents.card.stateSince")}</dt>
                    <dd>{stateTime(node.since)}</dd>
                  </div>
                  <div>
                    <dt>{t("agents.card.recentEvents")}</dt>
                    <dd>{agentIncidents.length}</dd>
                  </div>
                  <div>
                    <dt>{t("agents.card.reportsTo")}</dt>
                    <dd>{role?.reportsTo ?? "-"}{role?.staff ? ` (${t("agents.common.staff")})` : ""}</dd>
                  </div>
                  <div>
                    <dt>{t("agents.card.runtimeBinding")}</dt>
                    <dd>{agentRuntimeBindingLabel(node.name)}</dd>
                  </div>
                  <div>
                    <dt>{t("agents.card.authority")}</dt>
                    <dd>{node.name === "Thor" ? t("agents.authority.execute") : node.name === "Var" ? t("agents.authority.approve") : t("agents.authority.advise")}</dd>
                  </div>
                </dl>
                <footer>
                  <button type="button" onClick={() => onOpen(node.name)}>{t("agents.action.open")}</button>
                  <a href={routeHref("agent-activity", { params: { agent: node.name } })}>
                    {t("agents.workspace.activity")}
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
                    {t("agents.action.ask", { agent: node.name })}
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
  href,
  label,
  value,
  detail,
  kind,
}: {
  readonly href: string;
  readonly label: string;
  readonly value: number | string;
  readonly detail: string;
  readonly kind: string;
}) {
  return (
    <a class={`agent-roster-kpi kind-${kind}`} href={href}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </a>
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
      <div role="group" aria-label={t("agents.filter.groupLabel", { label })}>
        {values.map((value) => (
          <button
            type="button"
            key={value}
            class={selected === value ? "is-active" : undefined}
            aria-pressed={selected === value}
            onClick={() => onSelect(value)}
          >
            {t(`agents.filter.option.${value}`)}
          </button>
        ))}
      </div>
    </div>
  );
}
