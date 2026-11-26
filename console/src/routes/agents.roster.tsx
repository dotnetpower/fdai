import { useState } from "preact/hooks";
import type { ObservationSource } from "../hooks/observation-source";
import { observationSourceLabel } from "../hooks/observation-source";
import { useContentUpdatePulse } from "../hooks/use-content-update-pulse";
import {
  AgentRosterTable,
  type AgentRosterStateKind,
  type AgentRosterTableRow,
} from "../components/agent-roster-table";
import { FilterToolbar, SearchInput, SegmentedControl } from "../components/form-controls";
import { StatusBadge } from "../components/status-badge";
import { getLocale, t } from "../i18n";
import { routeHref } from "../router";
import { openDeckWithContext } from "../deck/open-deck";
import {
  AGENT_CONTRACT,
  AGENT_ROLE,
  agentChatContext,
  agentConversationBriefing,
  incidentsForAgent,
  isEngaged,
  type AgentNode,
  type AgentsState,
} from "./agents.model";
import {
  agentIconUrl,
  agentRoleTitle,
  agentRuntimeBindingLabel,
  agentRoleSummary,
  agentStateLabel,
  currentTask,
  rosterLayerOf,
  stateTime,
  type RosterLayer,
  type RosterState,
} from "./agents.view-model";

type RosterDisplayMode = "table" | "cards";

function rosterStateKindOf(node: AgentNode): AgentRosterStateKind {
  if (!node.observed) return "unobserved";
  if (isEngaged(node)) return "engaged";
  if (node.state === "watching") return "watching";
  return "idle";
}

function rosterDisplayCopy(): {
  readonly viewModeLabel: string;
  readonly tableMode: string;
  readonly cardsMode: string;
  readonly clearSearch: string;
  readonly tableAria: string;
  readonly agentColumn: string;
  readonly actionsColumn: string;
} {
  if (getLocale() === "ko") {
    return {
      viewModeLabel: "에이전트 표시 형식",
      tableMode: "표",
      cardsMode: "카드",
      clearSearch: "검색어 지우기",
      tableAria: "에이전트 현황 목록 표",
      agentColumn: "에이전트",
      actionsColumn: "작업",
    };
  }
  return {
    viewModeLabel: "Agent display mode",
    tableMode: "Table",
    cardsMode: "Cards",
    clearSearch: "Clear search",
    tableAria: "Agent fleet table",
    agentColumn: "Agent",
    actionsColumn: "Actions",
  };
}

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
  const [displayMode, setDisplayMode] = useState<RosterDisplayMode>("table");
  const displayCopy = rosterDisplayCopy();
  const activeFilters = (layer !== "all" ? 1 : 0)
    + (stateFilter !== "all" ? 1 : 0)
    + (query.trim().length > 0 ? 1 : 0);

  const openAgentConversation = (node: AgentNode) => {
    const agentIncidents = incidentsForAgent(state, node.name);
    openDeckWithContext({
      sessionLabel: node.name,
      newConversation: true,
      targetAgent: node.name,
      contextNote: agentChatContext(node, agentIncidents),
      openingBriefing: agentConversationBriefing(node, agentIncidents),
      prompt: `What has ${node.name} been working on?`,
    });
  };

  const tableRows: readonly AgentRosterTableRow[] = agents.map((node) => {
    const role = AGENT_ROLE[node.name];
    const contract = AGENT_CONTRACT[node.name];
    const incident = node.correlationId ? state.incidents[node.correlationId] : undefined;
    const agentIncidents = incidentsForAgent(state, node.name);
    const flags: string[] = [];
    if (contract?.hotPathLlm) flags.push(t("pantheon.hotPathLlm"));
    if (contract?.offPathLlm) flags.push(t("pantheon.offPathLlm"));
    if (contract?.hardDependency) flags.push(t("pantheon.hardDependency"));
    return {
      name: node.name,
      layerKey: node.layer,
      layerLabel: t(`agents.layer.${rosterLayerOf(node.name)}`),
      roleTitle: agentRoleTitle(node.name) ?? node.layer,
      roleSummary: agentRoleSummary(node.name) ?? null,
      stateKind: rosterStateKindOf(node),
      stateLabel: agentStateLabel(node),
      observed: node.observed,
      currentWork: currentTask(node),
      activeIncident: incident?.ticketId || t("agents.common.none"),
      stateSince: stateTime(node.since),
      reportsTo: `${role?.reportsTo ?? "-"}${role?.staff ? ` (${t("agents.common.staff")})` : ""}`,
      runtimeBinding: agentRuntimeBindingLabel(node.name),
      authorityLabel: node.name === "Thor"
        ? t("agents.authority.execute")
        : node.name === "Var"
          ? t("agents.authority.approve")
          : t("agents.authority.advise"),
      recentEventsCount: agentIncidents.length,
      owns: contract?.owns ?? [],
      flags,
      iconUrl: agentIconUrl(node.name),
      activityHref: routeHref("agent-activity", { params: { agent: node.name } }),
      openRoleLabel: t("agents.action.open"),
      activityLabel: t("agents.workspace.activity"),
      askLabel: t("agents.action.ask", { agent: node.name }),
    };
  });

  const clearAllFilters = () => {
    onLayerChange("all");
    onStateChange("all");
    onQueryChange("");
  };

  return (
    <div class="agent-roster">
      <section class="agent-roster-context" aria-label={t("agents.roster.interpretationLabel")}>
        <span><strong>{t("agents.roster.contextTitle")}</strong> {t("agents.roster.contextBody")}</span>
        <span>{t("agents.roster.contextSource", { source: observationSourceLabel(streamSource) })}</span>
      </section>

      <section class="agent-roster-summary" aria-label={t("agents.roster.summaryLabel")}>
        <RosterSummary href={routeHref("agents", { params: { state: "engaged" } })} label={t("agents.roster.metric.engaged")} value={active ?? "-"} detail={runtimeCurrent ? t("agents.roster.metric.workingNow") : t("agents.roster.metric.streamUnavailable")} kind="engaged" />
        <RosterSummary href={routeHref("agents", { params: { state: "watching" } })} label={t("agents.roster.metric.watching")} value={watching ?? "-"} detail={runtimeCurrent ? t("agents.roster.metric.sensingSignals") : t("agents.roster.metric.lastStateRetained")} kind="watching" />
        <RosterSummary href={routeHref("agents", { params: { state: "idle" } })} label={t("agents.roster.metric.idle")} value={idle ?? "-"} detail={runtimeCurrent ? t("agents.roster.metric.readyToWake") : t("agents.roster.metric.lastStateRetained")} kind="idle" />
        <RosterSummary href={routeHref("agents", { params: { state: "unobserved" } })} label={t("agents.roster.metric.unobserved")} value={unobserved} detail={t("agents.roster.metric.noRuntimeSignal")} kind="idle" />
      </section>

      <FilterToolbar
        ariaLabel={t("agents.filter.toolbarLabel")}
        activeFilterCount={activeFilters}
        onReset={clearAllFilters}
        resetLabel={t("agents.filter.clear")}
        className="agent-roster-toolbar"
        actions={(
          <SegmentedControl
            ariaLabel={displayCopy.viewModeLabel}
            value={displayMode}
            options={[
              { value: "table", label: displayCopy.tableMode },
              { value: "cards", label: displayCopy.cardsMode },
            ]}
            onChange={setDisplayMode}
          />
        )}
      >
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
        <SearchInput
          label={t("agents.filter.searchLabel")}
          hideLabel
          value={query}
          placeholder={t("agents.filter.searchPlaceholder")}
          clearLabel={displayCopy.clearSearch}
          size="sm"
          className="agent-roster-search"
          onInput={onQueryChange}
        />
      </FilterToolbar>

      {agents.length === 0 ? (
        <div class="agent-roster-empty">
          <strong>{t("agents.filter.empty")}</strong>
          <button
            type="button"
            class="cs-control-button"
            onClick={clearAllFilters}
          >
            {t("agents.filter.clear")}
          </button>
        </div>
      ) : displayMode === "table" ? (
        <AgentRosterTable
          ariaLabel={displayCopy.tableAria}
          rows={tableRows}
          labels={{
            agent: displayCopy.agentColumn,
            layer: t("agents.filter.layer"),
            state: t("agents.filter.state"),
            currentWork: t("agents.card.currentWork"),
            activeIncident: t("agents.card.activeIncident"),
            stateSince: t("agents.card.stateSince"),
            actions: displayCopy.actionsColumn,
            details: t("agents.card.details"),
            owns: t("agents.card.owns"),
            reportsTo: t("agents.card.reportsTo"),
            runtimeBinding: t("agents.card.runtimeBinding"),
            authority: t("agents.card.authority"),
            recentEvents: t("agents.card.recentEvents"),
          }}
          onOpenRole={onOpen}
          onAskAgent={(agentName) => {
            const target = agents.find((node) => node.name === agentName);
            if (target) openAgentConversation(target);
          }}
        />
      ) : (
        <div class="agent-roster-grid">
          {agents.map((node) => (
            <AgentRosterCard
              key={node.name}
              node={node}
              state={state}
              onOpen={onOpen}
              onAsk={() => openAgentConversation(node)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AgentRosterCard({
  node,
  state,
  onOpen,
  onAsk,
}: {
  readonly node: AgentNode;
  readonly state: AgentsState;
  readonly onOpen: (name: string) => void;
  readonly onAsk: () => void;
}) {
  const role = AGENT_ROLE[node.name];
  const contract = AGENT_CONTRACT[node.name];
  const incident = node.correlationId ? state.incidents[node.correlationId] : undefined;
  const agentIncidents = incidentsForAgent(state, node.name);
  const iconUrl = agentIconUrl(node.name);
  const contentUpdated = useContentUpdatePulse([
    node.state,
    node.detail ?? "",
    node.correlationId ?? "",
    incident?.ticketId ?? "",
    agentIncidents.length,
  ].join("|"));
  const stateTone = !node.observed
    ? "neutral"
    : isEngaged(node)
      ? "live"
      : node.state === "watching"
        ? "info"
        : "neutral";

  return (
    <article class={`agent-roster-card layer-${node.layer}${contentUpdated ? " is-content-updated" : ""}`}>
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
        <StatusBadge tone={stateTone} label={agentStateLabel(node)} />
      </header>
      <p class="agent-roster-task">
        <span>{t("agents.card.currentWork")}</span>
        <strong>{currentTask(node)}</strong>
      </p>
      <dl class="agent-roster-metrics">
        <div>
          <dt>{t("agents.card.activeIncident")}</dt>
          <dd>{incident?.ticketId || t("agents.common.none")}</dd>
        </div>
        <div>
          <dt>{t("agents.card.stateSince")}</dt>
          <dd>{node.observed ? stateTime(node.since) : "-"}</dd>
        </div>
      </dl>
      <details class="agent-roster-details">
        <summary>{t("agents.card.details")}</summary>
        {agentRoleSummary(node.name) ? (
          <p class="agent-roster-role-summary">{agentRoleSummary(node.name)}</p>
        ) : null}
        <dl>
          <div class="agent-roster-owns">
            <dt>{t("agents.card.owns")}</dt>
            <dd>{contract?.owns.map((item) => <code key={item}>{item}</code>) ?? "-"}</dd>
          </div>
          <div>
            <dt>{t("agents.card.recentEvents")}</dt>
            <dd>{node.observed ? agentIncidents.length : "-"}</dd>
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
        <div class="agent-roster-flags">
          {contract?.hotPathLlm ? <span>{t("pantheon.hotPathLlm")}</span> : null}
          {contract?.offPathLlm ? <span>{t("pantheon.offPathLlm")}</span> : null}
          {contract?.hardDependency ? <span>{t("pantheon.hardDependency")}</span> : null}
        </div>
      </details>
      <footer>
        <button type="button" onClick={() => onOpen(node.name)}>{t("agents.action.open")}</button>
        <a href={routeHref("agent-activity", { params: { agent: node.name } })}>
          {t("agents.workspace.activity")}
        </a>
        <button
          type="button"
          class="is-primary"
          onClick={onAsk}
        >
          {t("agents.action.ask", { agent: node.name })}
        </button>
      </footer>
    </article>
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
  const contentUpdated = useContentUpdatePulse(`${value}|${detail}`);
  return (
    <a class={`agent-roster-kpi kind-${kind}${contentUpdated ? " is-content-updated" : ""}`} href={href}>
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
      <span class="cs-field-label">{label}</span>
      <SegmentedControl
        ariaLabel={t("agents.filter.groupLabel", { label })}
        value={selected}
        options={values.map((value) => ({
          value,
          label: t(`agents.filter.option.${value}`),
        }))}
        onChange={onSelect}
      />
    </div>
  );
}
