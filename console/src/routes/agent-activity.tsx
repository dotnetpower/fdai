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
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { agentStreamDescriptor, useAgentStream, type AgentStreamStatus } from "../hooks/use-agent-stream";
import { observationSourceLabel, type ObservationSource } from "../hooks/observation-source";
import { t } from "../i18n";
import { currentRoute, navigate, replaceRouteState, routeHref } from "../router";
import {
  agentActivityRank,
  agentOf,
  entryStr,
  isAgentActivitySelectionValid,
  layerOf,
  outcomeOf,
  summaryOf,
  tierOf,
} from "./agent-activity-semantics";
export {
  agentOf,
  entryConversation,
  isAgentActivitySelectionValid,
  layerOf,
  lifecycleOf,
  otherEntryFields,
} from "./agent-activity-semantics";
import { ActivityWaterfall } from "./agent-activity-waterfall";
import {
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
  AGENT_ROLE,
  incidentsForAgent,
  makeInitialState,
  reducer,
  STATE_TASK,
  type AgentNode,
  type AgentsState,
  type Incident,
} from "./agents.model";

interface Props {
  readonly client: ReadApiClient;
}
/** Number of audit rows pulled to build the timeline (newest first). */
const TIMELINE_LIMIT = 200;

interface Data {
  readonly items: readonly AuditItem[];
  readonly olderAvailable: boolean;
}

type ActivityView = "activity" | "waterfall";

function activityFiltersFromRoute(): ActivityFilters {
  const search = currentRoute().search;
  const window = search.get("window");
  const layer = search.get("layer");
  const verb = search.get("verb");
  return {
    window: window === "15m" || window === "1h" || window === "7d" ? window : "24h",
    layer: layer === "governance" || layer === "pipeline" || layer === "domain" ? layer : "all",
    verb: verb === "execute" || verb === "approve" || verb === "reject" ||
      verb === "rollback" || verb === "abstain" || verb === "audit" ? verb : "all",
    query: search.get("q") ?? "",
  };
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
        subtitle="Per-agent runtime state and audit timeline - which agent did what, when, and how. Read-only projection with frame-owned source provenance."
      />
      <AsyncBoundary state={state} resourceLabel="agent activity">
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
  const selectedAuditCount = selected
    ? (perAgent.find(([agent]) => agent === selected)?.[1] ?? 0)
    : filtered.length;

  usePublishViewContext(
    () => ({
      routeId: "agent-activity",
      routeLabel: "Agent activity",
      purpose:
        "Per-agent timeline reconstructed from the audit log - which pantheon " +
        "agent did what, when, and why. Each incident (correlation id) is one " +
        "hand-off cascade: Huginn senses, Forseti judges, Thor opens a " +
        "remediation PR, Var queues an approval, Saga records it. Read-only.",
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.waterfall,
        TERMS.actionKind,
        TERMS.tier,
        TERMS.mode,
        TERMS.outcome,
        agentTerm(),
      ]),
      headline: `${data.items.length} audit row(s) across ${perAgent.length} agent(s)${
        selected ? ` - filtered to ${selected}` : ""
      }${data.olderAvailable ? " - older activity available" : ""}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "rows", value: data.items.length, group: "page" },
        { key: "agents", value: perAgent.length, group: "page" },
        { key: "filter", value: selected ?? "all", group: "page" },
        { key: "older_available", value: data.olderAvailable, group: "page" },
        { key: "stream_status", value: streamStatus, group: "runtime" },
        { key: "stream_source", value: observationSourceLabel(streamSource), group: "runtime" },
        { key: "live_agents", value: liveAgents, group: "runtime" },
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
        })),
      },
    }),
    [
      data.items,
      data.olderAvailable,
      perAgent,
      selected,
      visible,
      streamStatus,
      streamSource,
      liveAgents,
      filters,
    ],
  );

  if (data.items.length === 0) {
    return (
      <EmptyState
        title="No agent activity yet"
        body="Once the control loop records decisions, each agent's work appears here as a timeline."
      />
    );
  }

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
      {!selectionValid && selected ? (
        <UnavailableState message={`Agent ${selected} is not in the fixed pantheon or the loaded audit activity.`} />
      ) : null}
      {selectedNode ? (
        <LiveAgentActivity
          node={selectedNode}
          incidents={selectedIncidents}
          auditCount={selectedAuditCount}
          streamStatus={streamStatus}
        />
      ) : null}
      {data.olderAvailable ? (
        <p class="muted footnote">Showing the latest {data.items.length} audit rows; older activity is available in the Audit log.</p>
      ) : null}
      <div class="agent-filter" role="group" aria-label="Filter by agent">
        <button
          type="button"
          class={`agent-chip ${selected === null ? "agent-chip-on" : ""}`}
          aria-pressed={selected === null}
          onClick={() => openActivity(null, view)}
        >
          All
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

      <div class="view-toggle" role="group" aria-label="Activity view">
        <button
          type="button"
          class="view-toggle-btn"
          aria-pressed={view === "activity"}
          onClick={() => openActivity(selected, "activity")}
        >
          Activity
        </button>
        <button
          type="button"
          class="view-toggle-btn"
          aria-pressed={view === "waterfall"}
          onClick={() => openActivity(selected, "waterfall")}
        >
          Waterfall
        </button>
      </div>

      {!selectionValid ? null : visible.length === 0 ? (
        <EmptyState
          title={selected ? `No recorded audit activity for ${selected}` : "No activity matches these filters"}
          body={selected
            ? "Live state is shown above. This agent has no attributed audit row in the current window yet."
            : "Widen the window or clear the layer, verb, agent, and search filters."}
        />
      ) : view === "activity" ? (
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
  auditCount,
  streamStatus,
}: {
  readonly node: AgentNode;
  readonly incidents: readonly Incident[];
  readonly auditCount: number;
  readonly streamStatus: AgentStreamStatus;
}) {
  const role = AGENT_ROLE[node.name];
  const activeIncident = node.correlationId
    ? incidents.find((incident) => incident.correlationId === node.correlationId)
    : undefined;
  return (
    <section class="aa-selected-agent" aria-label={`${node.name} live activity`}>
      <header>
        <div>
          <span>{node.observed ? "Live now" : "Runtime not observed"}</span>
          <h3>{node.name} <small>{role?.title ?? node.layer}</small></h3>
        </div>
        <span class={`aa-selected-state state-${node.observed ? node.state : "unobserved"}`}>
          {node.observed ? node.state : "unobserved"}
        </span>
      </header>
      <p>{node.observed ? node.detail ?? STATE_TASK[node.state] : "No runtime signal observed for this agent."}</p>
      <dl>
        <div><dt>Stream</dt><dd>{streamStatus}</dd></div>
        <div><dt>Active incident</dt><dd>{activeIncident?.ticketId ?? node.correlationId ?? "None"}</dd></div>
        <div><dt>Live incidents</dt><dd>{incidents.length}</dd></div>
        <div><dt>Audit rows</dt><dd>{auditCount}</dd></div>
      </dl>
      <nav aria-label={`${node.name} evidence links`}>
        <a href={routeHref("agents", { params: { view: "org", agent: node.name, correlation: node.correlationId } })}>
          Open live detail
        </a>
        {node.correlationId ? (
          <>
            <a href={routeHref("incidents", { params: { status: "all", correlation: node.correlationId } })}>Incident</a>
            <a href={routeHref("trace", { params: { correlation: node.correlationId } })}>Trace</a>
          </>
        ) : null}
      </nav>
      {incidents.length > 0 ? (
        <div class="aa-selected-incidents">
          <strong>Recent live incidents</strong>
          <ul>
            {incidents.slice(0, 5).map((incident) => (
              <li key={incident.correlationId}>
                <a href={routeHref("agents", {
                  params: { view: "org", agent: node.name, correlation: incident.correlationId },
                })}>
                  <span>{incident.ticketId || "Incident"}</span>
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
