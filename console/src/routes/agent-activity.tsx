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
import type { ReadApiClient } from "../api";
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
import { agentStreamDescriptor, useAgentStream, type AgentStreamStatus } from "../hooks/use-agent-stream";
import { observationSourceLabel, type ObservationSource } from "../hooks/observation-source";
import { t } from "../i18n";
import { currentRoute, navigate, replaceRouteState, routeHref } from "../router";
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
  ActivityToolbar,
  filterAgentActivity,
  GroupedAgentActivity,
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
  liveActivityForAgent,
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

interface Props {
  readonly client: ReadApiClient;
}
/** Number of audit rows pulled to build the timeline (newest first). */
const TIMELINE_LIMIT = 200;

interface Data {
  readonly items: readonly AuditItem[];
  readonly olderAvailable: boolean;
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

function activityFiltersFromRoute(): ActivityFilters {
  return activityFiltersFromSearch(currentRoute().search);
}

export function AgentActivityRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Data>>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [lastEventAt, setLastEventAt] = useState<string | null>(null);
  const [runtime, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const requestGeneration = useRef(0);
  const lastStreamRefresh = useRef(0);
  const stream = useMemo(agentStreamDescriptor, []);

  async function loadAudit(showLoading: boolean): Promise<void> {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    if (showLoading) setState({ status: "loading" });
    else setRefreshing(true);
    try {
      const page = await client.listAudit({ limit: TIMELINE_LIMIT });
      if (requestGeneration.current === generation) {
        setState({
          status: "ready",
          data: { items: page.items, olderAvailable: page.next_cursor !== null },
        });
      }
    } catch (err) {
      if (requestGeneration.current === generation) {
        setState({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    } finally {
      if (requestGeneration.current === generation) setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadAudit(true);
    return () => {
      requestGeneration.current += 1;
    };
  }, [client]);

  const { status: streamStatus, source: streamSource } = useAgentStream({
    url: stream.url,
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (message) => {
      dispatch({ kind: "message", msg: message });
      setLastEventAt(message.ts);
      const now = Date.now();
      if (now - lastStreamRefresh.current < 1500) return;
      lastStreamRefresh.current = now;
      void loadAudit(false);
    },
  });

  return (
    <div class="stack">
      <AgentWorkspaceNav />
      <PageHeader
        title={t("route.agentActivity")}
        subtitle={t("nav.panelSub.agentActivity")}
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
        window: filters.window === "24h" ? null : filters.window,
        layer: filters.layer === "all" ? null : filters.layer,
        verb: filters.verb === "all" ? null : filters.verb,
        q: filters.query || null,
      },
    }));
  };
  const openFilters = (next: ActivityFilters): void => {
    const href = routeHref("agent-activity", {
      params: {
        agent: selected,
        view: view === "activity" ? null : view,
        step: view === "waterfall" ? currentRoute().search.get("step") : null,
        window: next.window === "24h" ? null : next.window,
        layer: next.layer === "all" ? null : next.layer,
        verb: next.verb === "all" ? null : next.verb,
        q: next.query || null,
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
  const perAgent = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of filtered) {
      const agent = agentOf(item);
      counts.set(agent, (counts.get(agent) ?? 0) + 1);
    }
    // Order: known pantheon agents first (by count), then service producers
    // (by count), then the System catch-all last.
    return [...counts.entries()].sort((a, b) => {
      const ra = agentActivityRank(a[0]);
      const rb = agentActivityRank(b[0]);
      if (ra !== rb) return ra - rb;
      return b[1] - a[1];
    });
  }, [filtered]);

  const visible = useMemo(
    () =>
      selected === null
        ? filtered
        : filtered.filter((item) => agentOf(item) === selected),
    [filtered, selected],
  );
  const selectionValid = isAgentActivitySelectionValid(
    selected,
    perAgent.map(([agent]) => agent),
  );
  const selectedNode = selected ? runtime.agents[selected] : undefined;
  const selectedIncidents = useMemo(
    () => selected ? incidentsForAgent(runtime, selected) : [],
    [runtime, selected],
  );
  const liveActivity = useMemo(
    () => liveActivityForAgent(runtime.liveActivity, selected),
    [runtime.liveActivity, selected],
  );
  const provenanceCounts = useMemo(
    () => activityProvenanceCounts(visible),
    [visible],
  );
  const presentation = activityPresentationState({
    totalAuditCount: data.items.length,
    visibleAuditCount: visible.length,
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
        { key: "agents", value: perAgent.length, group: "page" },
        { key: "filter", value: selected ?? "all", group: "page" },
        { key: "older_available", value: data.olderAvailable, group: "page" },
        { key: "stream_status", value: streamStatus, group: "runtime" },
        { key: "stream_source", value: observationSourceLabel(streamSource), group: "runtime" },
        { key: "live_agents", value: liveAgents, group: "runtime" },
        { key: "operational_audit_rows", value: provenanceCounts.operational, group: "evidence" },
        { key: "sample_audit_rows", value: provenanceCounts.sample, group: "evidence" },
        { key: "window", value: filters.window, group: "filters" },
        { key: "layer", value: filters.layer, group: "filters" },
        { key: "verb", value: filters.verb, group: "filters" },
      ],
      records: {
        by_agent: perAgent.map(([agent, count]) => ({ agent, count })),
        // The visible timeline rows (respecting the agent filter) so the deck
        // can answer "what did this agent do / what happened when / why did
        // this start?" from real activity. The causal fields (`summary`,
        // `detail`, `reason`, `tier`, `outcome`) are kept - NOT projected away -
        // so the narrator can quote the recorded "why" instead of shrugging.
        // Newest-first; capped so the snapshot stays lean.
        activity: visible.slice(0, 40).map((item) => ({
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
      perAgent,
      selected,
      selectedIncidents,
      visible,
      streamStatus,
      streamSource,
      liveAgents,
      provenanceCounts,
      filters,
    ],
  );

  return (
    <div class="stack">
      <ActivityToolbar
        filters={filters}
        onChange={openFilters}
        streamStatus={streamStatus}
        streamSource={streamSource}
        liveAgents={liveAgents}
        lastEventAt={lastEventAt}
        refreshing={refreshing}
      />
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
          streamSource={streamSource}
        />
      ) : null}
      <LiveActivityJournal events={liveActivity} selectedAgent={selected} />
      {data.olderAvailable ? (
        <p class="muted footnote">{t("agentActivity.main.latestRows", { count: data.items.length })}</p>
      ) : null}
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

      {presentation.emptyKind !== null ? (
        <EmptyState
          title={presentation.emptyKind === "selected-audit" && selected
            ? t("agentActivity.main.noSelectedAudit", { agent: selected })
            : presentation.emptyKind === "all-audit"
              ? t("agentActivity.main.noAudit")
              : t("agentActivity.main.noMatches")}
          body={presentation.emptyKind === "selected-audit"
            ? selectedAgentAuditEmptyBody(selectedNode, streamSource)
            : presentation.emptyKind === "all-audit"
              ? t("agentActivity.main.noAuditBody")
              : t("agentActivity.main.noMatchesBody")}
        />
      ) : !selectionValid ? null : view === "activity" ? (
        <GroupedAgentActivity items={visible} agentOf={agentOf} layerOf={layerOf} />
      ) : (
        <ActivityWaterfall items={waterfallItems} selected={selected} />
      )}
    </div>
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
        <a href={routeHref("agents", { params: { view: "org", agent: node.name, correlation: node.correlationId } })}>
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
                <a href={routeHref("agents", {
                  params: { view: "org", agent: node.name, correlation: incident.correlationId },
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
