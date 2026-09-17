/**
 * Agent activity - a per-agent timeline reconstructed from the audit log.
 *
 * The Audit and Trace panels answer "what terminal decisions were
 * recorded" and "reconstruct one correlation id". Neither answers the
 * operator's other natural question: **which agent did what work, when,
 * and how**. This panel projects the same append-only audit stream into
 * an agent-attributed timeline so an operator can watch the pantheon at
 * work (Huginn ingests, Forseti judges, Thor opens a remediation PR,
 * Var queues a HIL approval, Saga records it).
 *
 * Read-only: it reuses the GET-only `/audit` projection (no new
 * back-channel) and derives the acting agent from each entry's `actor`
 * (== the producing principal in the pantheon lifecycle). Entries whose
 * actor is not a known agent are grouped under "System".
 */

import { useEffect, useMemo, useReducer, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import type { AuditItem } from "../types";
import { AgentWorkspaceNav } from "../components/agent-workspace-nav";
import {
  AsyncBoundary,
  EmptyState,
  PageHeader,
  UnavailableState,
  type AsyncState,
} from "../components/ui";
import {
  type ViewExplanations,
  usePublishViewContext,
} from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import {
  agentActivityTimestamp,
  agentStreamDescriptor,
  useAgentStream,
  type AgentActivityMessage,
  type AgentStreamStatus,
} from "../hooks/use-agent-stream";
import {
  mergeObservationSource,
  normalizeObservationSource,
  observationSourceLabel,
  type ObservationSource,
} from "../hooks/observation-source";
import { t } from "../i18n";
import {
  currentRoute,
  navigate,
  replaceRouteState,
  ROUTE_STATE_EVENT,
  routeHref,
} from "../router";
import {
  activityPresentationState,
  activityProvenanceCounts,
  agentActivityRank,
  agentOf,
  auditProvenanceOf,
  entryStr,
  isAgentActivitySelectionValid,
  layerOf,
  outcomeOf,
  summaryOf,
  tierOf,
} from "./agent-activity-semantics";
export {
  activityPresentationState,
  activityProvenanceCounts,
  agentOf,
  auditProvenanceOf,
  entryConversation,
  isAgentActivitySelectionValid,
  layerOf,
  lifecycleOf,
  otherEntryFields,
} from "./agent-activity-semantics";
import { ActivityWaterfall } from "./agent-activity-waterfall";
import {
  activityFiltersFromSearch,
  activityRouteFilterParams,
  ActivityToolbar,
  filterAgentActivity,
  filterAgentActivityLog,
  type ActivityFilters,
  type ActivityLayer,
  type ActivityVerb,
  type ActivityWindow,
} from "./agent-activity-groups";
import {
  activeAgentCount,
  AGENT_RUNTIME_BINDING,
  AGENT_ROLE,
  incidentsForAgent,
  makeInitialState,
  reducer,
  type AgentNode,
  type AgentsState,
  type Incident,
} from "./agents.model";
import {
  agentStateClass,
  agentStateLabel,
  currentTask,
  stateTime,
} from "./agents.view-model";
import { LiveActivityJournal } from "./agent-live-activity";
import { AgentOrganizationDialog } from "./agent-organization";

interface Props {
  readonly client: OperatorApiClient;
}
/** Number of audit rows pulled to build the timeline (newest first). */
const TIMELINE_LIMIT = 200;
export const OPERATIONAL_ACTIVITY_LIMIT = 500;
const STREAM_RENDER_INTERVAL_MS = 100;
const STREAM_PENDING_LIMIT = 1_024;

interface Data {
  readonly items: readonly AuditItem[];
  readonly olderAvailable: boolean;
  readonly operationalSource: string;
}

export function agentActivityExplanations(
  selectedAgent: string | null,
  incidents: readonly Incident[],
): ViewExplanations | undefined {
  if (selectedAgent === null) return undefined;
  return {
    selection: {
      entity_kind: "Agent",
      entity_id: selectedAgent,
      label: selectedAgent,
    },
    relationships: incidents.map((incident) => ({
      link: "participates_in",
      from: selectedAgent,
      to: incident.correlationId,
      neighbor: incident.correlationId,
      direction: "outgoing",
      detail: `${incident.title} (${incident.status}, ${incident.severity})`,
    })),
    provenance: {
      authority: "agent_runtime_and_audit",
      refs: [
        `Agent:${selectedAgent}`,
        ...incidents.map((incident) => `Incident:${incident.correlationId}`),
      ],
    },
  };
}

type ActivityView = "activity" | "waterfall";

function agentCounts(items: readonly AuditItem[]): readonly (readonly [string, number])[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    const agent = agentOf(item);
    counts.set(agent, (counts.get(agent) ?? 0) + 1);
  }
  return [...counts.entries()].sort((left, right) => {
    const rankDifference = agentActivityRank(left[0]) - agentActivityRank(right[0]);
    return rankDifference || right[1] - left[1];
  });
}

function activityFiltersFromRoute(): ActivityFilters {
  return activityFiltersFromSearch(currentRoute().search);
}

export function shouldRefreshAgentActivity(
  trigger: "initial" | "operator" | "stream-frame" | "stream-open" | "gap",
): boolean {
  return trigger === "initial" || trigger === "operator" || trigger === "gap";
}

export function agentActivityObservationSource(
  operationalSource: string,
  streamSource: ObservationSource,
): ObservationSource {
  const durableSource = operationalSource === "durable-operational-projection"
    ? "runtime-observed"
    : normalizeObservationSource(operationalSource);
  return streamSource === "mixed"
    ? "mixed"
    : mergeObservationSource(durableSource, streamSource);
}

export function AgentActivityRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Data>>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [lastEventAt, setLastEventAt] = useState<string | null>(null);
  const [runtime, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const requestGeneration = useRef(0);
  const refreshButtonRef = useRef<HTMLButtonElement>(null);
  const pendingStreamMessagesRef = useRef<AgentActivityMessage[]>([]);
  const streamFlushTimerRef = useRef<number | null>(null);
  const stream = useMemo(agentStreamDescriptor, []);

  const flushStreamMessages = (): void => {
    if (streamFlushTimerRef.current !== null) {
      window.clearTimeout(streamFlushTimerRef.current);
      streamFlushTimerRef.current = null;
    }
    const messages = pendingStreamMessagesRef.current;
    if (messages.length === 0) return;
    pendingStreamMessagesRef.current = [];
    dispatch({ kind: "messages", messages });
    setLastEventAt(agentActivityTimestamp(messages[messages.length - 1]!));
  };

  const enqueueStreamMessage = (message: AgentActivityMessage): void => {
    pendingStreamMessagesRef.current.push(message);
    if (pendingStreamMessagesRef.current.length >= STREAM_PENDING_LIMIT) {
      flushStreamMessages();
      return;
    }
    if (streamFlushTimerRef.current === null) {
      streamFlushTimerRef.current = window.setTimeout(
        flushStreamMessages,
        STREAM_RENDER_INTERVAL_MS,
      );
    }
  };

  async function loadAudit(
    showLoading: boolean,
    restoreRefreshFocus = false,
  ): Promise<void> {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    if (showLoading) setState({ status: "loading" });
    else setRefreshing(true);
    try {
      const [page, operational] = await Promise.all([
        client.listAudit({ limit: TIMELINE_LIMIT }),
        client.listAgentActivity(OPERATIONAL_ACTIVITY_LIMIT),
      ]);
      if (requestGeneration.current === generation) {
        dispatch({ kind: "hydrate-activity", activities: operational.items });
        if (operational.items[0]) setLastEventAt(operational.items[0].observed_at);
        setState({
          status: "ready",
          data: {
            items: page.items,
            olderAvailable: page.next_cursor !== null,
            operationalSource: operational.source,
          },
        });
      }
    } catch (err) {
      if (requestGeneration.current === generation) {
        setState({
          status: isOptionalOperatorApiUnavailable(err) ? "unavailable" : "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    } finally {
      if (requestGeneration.current === generation) {
        setRefreshing(false);
        if (restoreRefreshFocus) {
          window.requestAnimationFrame(() => refreshButtonRef.current?.focus());
        }
      }
    }
  }

  useEffect(() => {
    void loadAudit(true);
    return () => {
      requestGeneration.current += 1;
    };
  }, [client]);

  useEffect(() => () => {
    if (streamFlushTimerRef.current !== null) {
      window.clearTimeout(streamFlushTimerRef.current);
    }
    streamFlushTimerRef.current = null;
    pendingStreamMessagesRef.current = [];
  }, []);

  const { status: streamStatus, source: streamSource } = useAgentStream({
    url: stream.url,
    enabled: state.status === "ready",
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: enqueueStreamMessage,
    onGap: () => {
      void loadAudit(false);
    },
  });

  return (
    <div class="stack">
      <AgentWorkspaceNav />
      <PageHeader
        title={t("route.agentActivity")}
        subtitle={t("nav.panelSub.agentActivity")}
        actions={(
          <button
            ref={refreshButtonRef}
            type="button"
            class="cs-control-button"
            disabled={refreshing}
            aria-busy={refreshing}
            onClick={() => { void loadAudit(false, true); }}
          >
            {t(
              refreshing
                ? "agentActivity.toolbar.refreshing"
                : "agentActivity.main.refresh",
            )}
          </button>
        )}
      />
      <AsyncBoundary state={state} resourceLabel={t("route.agentActivity")}>
        {(data) => (
          <ActivityBody
            data={data}
            runtime={runtime}
            streamStatus={streamStatus}
            streamSource={streamSource}
            liveAgents={activeAgentCount(runtime)}
            lastEventAt={lastEventAt}
            refreshing={refreshing}
          />
        )}
      </AsyncBoundary>
      <AgentOrganizationRouteOverlay
        agents={runtime.agents}
        runtimeCurrent={streamStatus === "open"}
      />
    </div>
  );
}
interface BodyProps {
  readonly data: Data;
  readonly runtime: AgentsState;
  readonly streamStatus: AgentStreamStatus;
  readonly streamSource: ObservationSource;
  readonly liveAgents: number;
  readonly lastEventAt: string | null;
  readonly refreshing: boolean;
}

function ActivityBody({
  data,
  runtime,
  streamStatus,
  streamSource,
  liveAgents,
  lastEventAt,
  refreshing,
}: BodyProps) {
  const [selected, setSelected] = useState<string | null>(
    () => currentRoute().search.get("agent"),
  );
  const [view, setView] = useState<ActivityView>(
    () => currentRoute().search.get("view") === "waterfall" ? "waterfall" : "activity",
  );
  const [filters, setFilters] = useState<ActivityFilters>(activityFiltersFromRoute);
  const activitySource = agentActivityObservationSource(
    data.operationalSource,
    streamSource,
  );

  const filtered = useMemo(
    () => filterAgentActivity(data.items, filters, agentOf),
    [data.items, filters],
  );
  const requestedStep = Number(currentRoute().search.get("step"));
  const waterfallItems = useMemo(() => {
    if (!Number.isInteger(requestedStep) || requestedStep <= 0) return filtered;
    if (filtered.some((item) => item.seq === requestedStep)) return filtered;
    const requested = data.items.find((item) => item.seq === requestedStep);
    return requested ? [requested, ...filtered] : filtered;
  }, [data.items, filtered, requestedStep]);

  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      setSelected(route.search.get("agent"));
      setView(route.search.get("view") === "waterfall" ? "waterfall" : "activity");
      setFilters(activityFiltersFromRoute());
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  const openActivity = (agent: string | null, nextView: ActivityView): void => {
    navigate(routeHref("agent-activity", {
      params: {
        agent,
        view: nextView === "activity" ? null : nextView,
        step: nextView === "waterfall" ? currentRoute().search.get("step") : null,
        ...activityRouteFilterParams(filters, nextView === "waterfall"),
      },
    }));
  };
  const openFilters = (next: ActivityFilters): void => {
    const href = routeHref("agent-activity", {
      params: {
        agent: selected,
        view: view === "activity" ? null : view,
        step: view === "waterfall" ? currentRoute().search.get("step") : null,
        ...activityRouteFilterParams(next, view === "waterfall"),
      },
    });
    if (next.query !== filters.query) {
      setFilters(next);
      replaceRouteState(href);
      return;
    }
    navigate(href);
  };

  // Newest first: the audit projection already returns newest-first, so
  // preserve that order for the timeline.
  // Order: known pantheon agents first (by count), then service producers
  // (by count), then the System catch-all last.
  const perAgent = useMemo(() => agentCounts(filtered), [filtered]);

  const visible = useMemo(
    () =>
      selected === null
        ? filtered
        : filtered.filter((item) => agentOf(item) === selected),
    [filtered, selected],
  );
  const activityAudit = useMemo(
    () => filterAgentActivityLog(data.items, selected, filters.query, agentOf),
    [data.items, selected, filters.query],
  );
  const activityAgentCounts = useMemo(
    () => agentCounts(filterAgentActivityLog(data.items, null, filters.query, agentOf)),
    [data.items, filters.query],
  );
  const presentedAudit = view === "activity" ? activityAudit : visible;
  const presentedAgentCounts = view === "activity" ? activityAgentCounts : perAgent;
  const selectionValid = isAgentActivitySelectionValid(
    selected,
    [...new Set(data.items.map(agentOf))],
  );
  const selectedNode = selected ? runtime.agents[selected] : undefined;
  const selectedIncidents = useMemo(
    () => selected ? incidentsForAgent(runtime, selected) : [],
    [runtime, selected],
  );
  const provenanceCounts = useMemo(
    () => activityProvenanceCounts(presentedAudit),
    [presentedAudit],
  );
  const presentation = activityPresentationState({
    totalAuditCount: data.items.length,
    visibleAuditCount: presentedAudit.length,
    selected,
    selectionValid,
    hasSelectedNode: selectedNode !== undefined,
  });

  usePublishViewContext(
    () => {
      const explanations = agentActivityExplanations(selected, selectedIncidents);
      return {
      routeId: "agent-activity",
      routeLabel: t("route.agentActivity"),
      purpose: t("nav.panelSub.agentActivity"),
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.waterfall,
        TERMS.actionKind,
        TERMS.tier,
        TERMS.mode,
        TERMS.outcome,
        agentTerm(),
      ]),
      headline: t("agentActivity.main.latestRows", { count: data.items.length }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "rows", value: data.items.length, group: "page" },
        { key: "agents", value: presentedAgentCounts.length, group: "page" },
        { key: "filter", value: selected ?? "all", group: "page" },
        { key: "older_available", value: data.olderAvailable, group: "page" },
        { key: "stream_status", value: streamStatus, group: "runtime" },
        { key: "stream_source", value: observationSourceLabel(streamSource), group: "runtime" },
        {
          key: "activity_source",
          value: observationSourceLabel(activitySource),
          group: "evidence",
        },
        { key: "live_agents", value: liveAgents, group: "runtime" },
        { key: "operational_audit_rows", value: provenanceCounts.operational, group: "evidence" },
        { key: "sample_audit_rows", value: provenanceCounts.sample, group: "evidence" },
        { key: "window", value: filters.window, group: "filters" },
        { key: "layer", value: filters.layer, group: "filters" },
        { key: "verb", value: filters.verb, group: "filters" },
      ],
      records: {
        by_agent: presentedAgentCounts.map(([agent, count]) => ({ agent, count })),
        // The visible timeline rows (respecting the agent filter) so the deck
        // can answer "what did this agent do / what happened when / why did
        // this start?" from real activity. The causal fields (`summary`,
        // `detail`, `reason`, `tier`, `outcome`) are kept - NOT projected away -
        // so the narrator can quote the recorded "why" instead of shrugging.
        // Newest-first; capped so the snapshot stays lean.
        activity: presentedAudit.slice(0, 40).map((item) => ({
          agent: agentOf(item),
          action_kind: item.action_kind,
          mode: item.mode,
          recorded_at: item.recorded_at,
          correlation_id: item.correlation_id ?? "-",
          event_id: item.event_id,
          tier: tierOf(item) ?? "-",
          outcome: outcomeOf(item) ?? "-",
          summary: summaryOf(item) ?? "-",
          detail: entryStr(item, "detail") ?? "-",
          reason: entryStr(item, "reason") ?? "-",
          provenance: auditProvenanceOf(item),
        })),
      },
        ...(explanations ? { explanations } : {}),
      };
    },
    [
      data.items,
      data.olderAvailable,
      presentedAgentCounts,
      selected,
      selectedIncidents,
      presentedAudit,
      streamStatus,
      streamSource,
      activitySource,
      liveAgents,
      provenanceCounts,
      filters,
    ],
  );

  return (
    <div class="stack">
      {view === "waterfall" ? (
        <ActivityToolbar
          filters={filters}
          onChange={openFilters}
          streamStatus={streamStatus}
          streamSource={activitySource}
          liveAgents={liveAgents}
          lastEventAt={lastEventAt}
          refreshing={refreshing}
        />
      ) : null}
      <div class="view-toggle" role="group" aria-label={t("agentActivity.main.viewLabel")}>
        <button
          type="button"
          class="view-toggle-btn"
          aria-pressed={view === "activity"}
          onClick={() => openActivity(selected, "activity")}
        >
          {t("agents.workspace.activity")}
        </button>
        <button
          type="button"
          class="view-toggle-btn"
          aria-pressed={view === "waterfall"}
          onClick={() => openActivity(selected, "waterfall")}
        >
          {t("agentActivity.main.waterfall")}
        </button>
      </div>
      {provenanceCounts.sample > 0 ? (
        <div class="callout" role="status">
          <strong>{t("agentActivity.main.sampleTitle")}</strong> - {t("agentActivity.main.sampleBody", { count: provenanceCounts.sample })}
        </div>
      ) : null}
      {!selectionValid && selected ? (
        <UnavailableState message={t("agentActivity.main.unknownAgent", { agent: selected })} />
      ) : null}
      {presentation.showLiveSummary && selectedNode ? (
        <LiveAgentActivity
          node={selectedNode}
          incidents={selectedIncidents}
          operationalAuditCount={provenanceCounts.operational}
          sampleAuditCount={provenanceCounts.sample}
          streamStatus={streamStatus}
          streamSource={activitySource}
        />
      ) : null}
      {view === "activity" ? (
        <LiveActivityJournal
          events={runtime.liveActivity}
          auditItems={activityAudit}
          selectedAgent={selected}
          query={filters.query}
          streamStatus={streamStatus}
          streamSource={activitySource}
          lastEventAt={lastEventAt}
          onSelectedAgentChange={(agent) => openActivity(agent, "activity")}
          onQueryChange={(query) => openFilters({ ...filters, query })}
        />
      ) : null}
      {view === "activity" && data.olderAvailable ? (
        <p class="muted footnote">{t("agentActivity.main.latestRows", { count: data.items.length })}</p>
      ) : null}
      {view === "waterfall" ? (
        <div class="agent-filter" role="group" aria-label={t("agentActivity.main.agentFilterLabel")}>
        <button
          type="button"
          class={`agent-chip ${selected === null ? "agent-chip-on" : ""}`}
          aria-pressed={selected === null}
          onClick={() => openActivity(null, view)}
        >
          {t("agentActivity.filter.all")}
          <span class="agent-chip-count">{filtered.length}</span>
        </button>
        {perAgent.map(([agent, count]) => (
          <button
            key={agent}
            type="button"
            class={`agent-chip ${selected === agent ? "agent-chip-on" : ""}`}
            aria-pressed={selected === agent}
            data-layer={layerOf(agent)}
            onClick={() => openActivity(selected === agent ? null : agent, view)}
          >
            <span class="agent-dot" data-layer={layerOf(agent)} aria-hidden="true" />
            {agent}
            <span class="agent-chip-count">{count}</span>
          </button>
        ))}
        {selectionValid && selected && !perAgent.some(([agent]) => agent === selected) ? (
          <button
            type="button"
            class="agent-chip agent-chip-on"
            aria-pressed="true"
            data-layer={layerOf(selected)}
            onClick={() => openActivity(null, view)}
          >
            <span class="agent-dot" data-layer={layerOf(selected)} aria-hidden="true" />
            {selected}
            <span class="agent-chip-count">0</span>
          </button>
        ) : null}
        </div>
      ) : null}

      {view !== "waterfall" ? null : presentation.emptyKind !== null ? (
        <EmptyState
          title={presentation.emptyKind === "selected-audit" && selected
            ? t("agentActivity.main.noSelectedAudit", { agent: selected })
            : presentation.emptyKind === "all-audit"
              ? t("agentActivity.main.noAudit")
              : t("agentActivity.main.noMatches")}
          body={presentation.emptyKind === "selected-audit"
            ? selectedAgentAuditEmptyBody(selectedNode, activitySource)
            : presentation.emptyKind === "all-audit"
              ? t("agentActivity.main.noAuditBody")
              : t("agentActivity.main.noMatchesBody")}
        />
      ) : !selectionValid ? null : (
        <ActivityWaterfall items={waterfallItems} selected={selected} />
      )}
    </div>
  );
}

function roleOverlayHref(open: boolean, roleAgent: string | null): string {
  const url = new URL(window.location.href);
  if (open) {
    url.searchParams.set("roles", "1");
    if (roleAgent) url.searchParams.set("roleAgent", roleAgent);
    else url.searchParams.set("roleAgent", "");
  } else {
    url.searchParams.delete("roles");
    url.searchParams.delete("roleAgent");
  }
  return `${url.pathname}${url.search}`;
}

function AgentOrganizationRouteOverlay({
  agents,
  runtimeCurrent,
}: {
  readonly agents: Readonly<Record<string, AgentNode>>;
  readonly runtimeCurrent: boolean;
}) {
  const readRoute = () => {
    const route = currentRoute();
    const roleAgent = route.search.has("roleAgent")
      ? route.search.get("roleAgent") || null
      : route.search.get("agent");
    return {
      open: route.panelId === "agent-activity" && route.search.get("roles") === "1",
      agent: roleAgent,
    };
  };
  const initial = readRoute();
  const [open, setOpen] = useState(initial.open);
  const [roleAgent, setRoleAgent] = useState<string | null>(initial.agent);
  const openRef = useRef(initial.open);
  const closingRef = useRef(false);
  const restoreFocus = () => window.setTimeout(() => {
    document.getElementById("agent-roles-trigger")?.focus();
  }, 0);

  useEffect(() => {
    const sync = () => {
      const next = readRoute();
      const shouldRestoreFocus = openRef.current && !next.open;
      openRef.current = next.open;
      if (!next.open) closingRef.current = false;
      setOpen(next.open);
      setRoleAgent(next.agent);
      if (shouldRestoreFocus) restoreFocus();
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, []);

  if (!open) return null;

  const close = () => {
    if (closingRef.current) return;
    closingRef.current = true;
    if (window.history.state?.fdaiAgentRolesOverlay === true) {
      window.addEventListener("popstate", restoreFocus, { once: true });
      window.history.back();
      return;
    }
    setOpen(false);
    replaceRouteState(roleOverlayHref(false, null));
    restoreFocus();
  };
  const selectAgent = (agent: string | null) => {
    setRoleAgent(agent);
    replaceRouteState(roleOverlayHref(true, agent));
  };

  return (
    <AgentOrganizationDialog
      agents={agents}
      selectedAgent={roleAgent}
      runtimeCurrent={runtimeCurrent}
      onSelectAgent={selectAgent}
      onClose={close}
    />
  );
}

function LiveAgentActivity({
  node,
  incidents,
  operationalAuditCount,
  sampleAuditCount,
  streamStatus,
  streamSource,
}: {
  readonly node: AgentNode;
  readonly incidents: readonly Incident[];
  readonly operationalAuditCount: number;
  readonly sampleAuditCount: number;
  readonly streamStatus: AgentStreamStatus;
  readonly streamSource: ObservationSource;
}) {
  const role = AGENT_ROLE[node.name];
  const activeIncident = matchingLiveIncident(node.correlationId, incidents);
  return (
    <section class="aa-selected-agent" aria-label={t("agentActivity.main.liveActivityLabel", { agent: node.name })}>
      <header>
        <div>
          <span>{t(node.observed ? "agentActivity.main.liveEvidence" : "agentActivity.main.runtimeUnobserved")}</span>
          <h3>{node.name} <small>{role?.title ?? node.layer}</small></h3>
        </div>
        <span class={`aa-selected-state state-${agentStateClass(node)}`}>
          {agentStateLabel(node)}
        </span>
      </header>
      <p><strong>{t("agents.card.currentWork")}</strong><span>{currentTask(node)}</span></p>
      <dl>
        <div><dt>{t("agents.card.runtimeBinding")}</dt><dd>{AGENT_RUNTIME_BINDING[node.name] ?? t("agents.common.notConfigured")}</dd></div>
        <div><dt>{t("agents.card.stateSince")}</dt><dd>{stateTime(node.since)}</dd></div>
        <div><dt>{t("agentActivity.main.stream")}</dt><dd>{streamStatus} - {observationSourceLabel(streamSource)}</dd></div>
        <div><dt>{t("agentActivity.main.activeCorrelation")}</dt><dd>{node.correlationId ?? t("agents.common.none")}</dd></div>
        <div><dt>{t("agents.card.activeIncident")}</dt><dd>{activeIncident?.ticketId ?? t("agents.common.none")}</dd></div>
        <div><dt>{t("agentActivity.main.liveIncidents")}</dt><dd>{incidents.length}</dd></div>
        <div><dt>{t("agentActivity.main.operationalAudit")}</dt><dd>{operationalAuditCount}</dd></div>
        <div><dt>{t("agentActivity.main.localSamples")}</dt><dd>{sampleAuditCount}</dd></div>
      </dl>
      <nav aria-label={t("agentActivity.main.evidenceLinks", { agent: node.name })}>
        <a href={routeHref("pantheon", { params: { agent: node.name } })}>
          {t("agentActivity.main.openDetail")}
        </a>
        {node.correlationId ? (
          <>
            {activeIncident ? (
              <a href={routeHref("incidents", { params: { status: "all", correlation: node.correlationId } })}>{t("route.incidents")}</a>
            ) : null}
            <a href={routeHref("trace", { params: { correlation: node.correlationId } })}>{t("route.ruleTrace")}</a>
          </>
        ) : null}
      </nav>
      {incidents.length > 0 ? (
        <div class="aa-selected-incidents">
          <strong>{t("agentActivity.main.recentIncidents")}</strong>
          <ul>
            {incidents.slice(0, 5).map((incident) => (
              <li key={incident.correlationId}>
                <a href={routeHref("incidents", {
                  params: { status: "all", correlation: incident.correlationId },
                })}>
                  <span>{incident.ticketId || t("route.incidents")}</span>
                  <span>{incident.title}</span>
                  <small>{incident.status}</small>
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

export function selectedAgentAuditEmptyBody(
  node: AgentNode | undefined,
  streamSource: ObservationSource,
): string {
  if (node === undefined) {
    return t("agentActivity.main.noSelectionEvidence");
  }
  const liveState = node.observed
    ? t("agentActivity.main.liveState", {
        agent: node.name,
        state: agentStateLabel(node),
        source: observationSourceLabel(streamSource),
      })
    : t("agentActivity.main.noRuntimeFrame", { agent: node.name });
  const correlation = node.correlationId === null
    ? t("agentActivity.main.noActiveCorrelation")
    : t("agentActivity.main.noCorrelationAudit", { correlation: node.correlationId });
  return `${liveState} ${correlation} ${t("agentActivity.main.noDurableAudit")}`;
}

export function matchingLiveIncident(
  correlationId: string | null,
  incidents: readonly Incident[],
): Incident | null {
  if (correlationId === null) return null;
  return incidents.find((incident) => incident.correlationId === correlationId) ?? null;
}
