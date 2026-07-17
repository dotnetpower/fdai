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

import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "preact/hooks";
import type { VNode } from "preact";
import type { ReadApiClient } from "../api";
import { AgentWorkspaceNav } from "../components/agent-workspace-nav";
import { UnavailableState } from "../components/ui";
import { agentStreamDescriptor, useAgentStream } from "../hooks/use-agent-stream";
import { observationSourceLabel } from "../hooks/observation-source";
import { currentRoute, navigate, replaceRouteState, routeHref } from "../router";
import { usePublishViewContext } from "../deck/context";
import { agentTerm, composeGlossary, TERMS } from "../deck/glossary";
import { openDeckWithContext } from "../deck/open-deck";
import {
  PANTHEON,
  activeAgentCount,
  currentRuntimeCount,
  AGENT_ROLE,
  agentChatContext,
  engagedGroups,
  incidentsForAgent,
  isEngaged,
  makeInitialState,
  ORG_CHART,
  reducer,
  type AgentNode,
  type Incident,
} from "./agents.model";
import {
  EMPTY_GEOMETRY,
  STATE_LABEL,
  agentIconUrl,
  agentStateLabel,
  currentTask,
  rosterLayerOf,
  type AgentLayout,
  type Geometry,
  type Point,
  type RosterLayer,
  type RosterState,
} from "./agents.view-model";
import { AgentRoster } from "./agents.roster";
import {
  AgentHoverCard,
  ConstellationLinks,
  OrgReportingLines,
} from "./agents.constellation";
import { AgentFocus, IncidentWorkflow } from "./agents.detail";

interface Props {
  readonly client: ReadApiClient;
}

/** How many incidents the side list shows before the "All" toggle. */
const INCIDENT_PREVIEW = 10;

function layoutFromRoute(): AgentLayout {
  const view = currentRoute().search.get("view");
  return view === "org" || view === "constellation" ? view : "roster";
}

function rosterFiltersFromRoute(): {
  readonly layer: RosterLayer;
  readonly state: RosterState;
  readonly query: string;
} {
  const search = currentRoute().search;
  const layer = search.get("layer");
  const state = search.get("state");
  return {
    layer: layer === "governance" || layer === "pipeline" || layer === "domain" ? layer : "all",
    state: state === "engaged" || state === "watching" || state === "idle" || state === "unobserved"
      ? state
      : "all",
    query: search.get("q") ?? "",
  };
}

export function AgentsRoute({ client }: Props) {
  const initialRoute = currentRoute();
  const initialRosterFilters = rosterFiltersFromRoute();
  const [state, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const [selectedId, setSelectedId] = useState<string | null>(
    initialRoute.search.get("correlation"),
  );
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

  const stream = useMemo(agentStreamDescriptor, []);

  const { status, source: streamSource } = useAgentStream({
    url: stream.url,
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (msg) => dispatch({ kind: "message", msg }),
  });

  useEffect(() => {
    let cancelled = false;
    void client.listIncidents({ status: "all", limit: 30 }).then((page) => {
      if (!cancelled) {
        dispatch({ kind: "hydrate", incidents: page.items });
        setSnapshotError(null);
      }
    }).catch((error: unknown) => {
      if (!cancelled) {
        setSnapshotError(error instanceof Error ? error.message : String(error));
      }
    });
    return () => { cancelled = true; };
  }, [client]);

  // Auto-follow the newest incident until the operator picks one.
  const [pinned, setPinned] = useState(initialRoute.search.has("correlation"));
  useEffect(() => {
    if (!pinned && state.incidentOrder.length > 0) {
      const first = state.incidentOrder[0];
      if (first) setSelectedId(first);
    }
  }, [state.incidentOrder, pinned]);

  // Incident list shows the most recent `INCIDENT_PREVIEW` (newest first);
  // the "All" toggle expands to the full retained history.
  const [showAllIncidents, setShowAllIncidents] = useState(false);

  // Layout mode: the free "constellation" grid, or the hierarchical "org"
  // chart that shows who reports to whom. Both share the same live nodes.
  // Defaults to the org chart so the pantheon's roles + reporting lines are
  // the first thing an operator sees.
  const [layout, setLayout] = useState<AgentLayout>(layoutFromRoute);
  const [rosterLayer, setRosterLayer] = useState<RosterLayer>(initialRosterFilters.layer);
  const [rosterState, setRosterState] = useState<RosterState>(initialRosterFilters.state);
  const [rosterQuery, setRosterQuery] = useState(initialRosterFilters.query);

  // Agent the operator clicked to focus - drives the "what events is this
  // agent in" side panel. Independent from the selected incident.
  const [selectedAgent, setSelectedAgent] = useState<string | null>(
    initialRoute.search.get("agent"),
  );
  const selectedAgentNode = selectedAgent ? (state.agents[selectedAgent] ?? null) : null;
  const selectedAgentIncidents = useMemo(
    () => (selectedAgent ? incidentsForAgent(state, selectedAgent) : []),
    [state, selectedAgent],
  );

  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const correlation = route.search.get("correlation");
      setSelectedId(correlation);
      setPinned(correlation !== null);
      setSelectedAgent(route.search.get("agent"));
      setLayout(layoutFromRoute());
      const filters = rosterFiltersFromRoute();
      setRosterLayer(filters.layer);
      setRosterState(filters.state);
      setRosterQuery(filters.query);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  const openFocus = (
    agent: string | null,
    correlation: string | null,
    nextLayout: AgentLayout = layout,
  ): void => {
    navigate(routeHref("agents", {
      params: {
        view: nextLayout === "roster" ? null : nextLayout,
        agent,
        correlation,
        layer: rosterLayer === "all" ? null : rosterLayer,
        state: rosterState === "all" ? null : rosterState,
        q: rosterQuery || null,
      },
    }));
  };

  const openRosterFilters = (
    layer: RosterLayer,
    stateFilter: RosterState,
    query: string,
    replace = false,
  ): void => {
    const href = routeHref("agents", {
      params: {
        view: layout === "roster" ? null : layout,
        agent: selectedAgent,
        correlation: selectedId,
        layer: layer === "all" ? null : layer,
        state: stateFilter === "all" ? null : stateFilter,
        q: query || null,
      },
    });
    if (replace) {
      setRosterLayer(layer);
      setRosterState(stateFilter);
      setRosterQuery(query);
      replaceRouteState(href);
      return;
    }
    navigate(href);
  };

  const selectLayout = (nextLayout: AgentLayout): void => {
    setLayout(nextLayout);
    openFocus(selectedAgent, selectedId, nextLayout);
  };

  const selected: Incident | null = selectedId ? (state.incidents[selectedId] ?? null) : null;
  const involved = useMemo(
    () => new Set(selected?.involved ?? []),
    [selected],
  );

  const runtimeCurrent = status === "open";
  const active = currentRuntimeCount(runtimeCurrent, activeAgentCount(state));
  const rosterAgents = useMemo(() => {
    const query = rosterQuery.trim().toLocaleLowerCase();
    return PANTHEON
      .map(({ name }) => state.agents[name])
      .filter((node): node is AgentNode => node !== undefined)
      .filter((node) => rosterLayer === "all" || rosterLayerOf(node.name) === rosterLayer)
      .filter((node) => {
        if (rosterState === "all") return true;
        if (rosterState === "engaged") return runtimeCurrent && isEngaged(node);
        if (rosterState === "unobserved") return !node.observed;
        return node.observed && node.state === rosterState;
      })
      .filter((node) => {
        if (!query) return true;
        const role = AGENT_ROLE[node.name];
        return [node.name, agentStateLabel(node), node.detail, role?.title, currentTask(node)]
          .filter(Boolean)
          .join(" ")
          .toLocaleLowerCase()
          .includes(query);
      });
  }, [runtimeCurrent, state.agents, rosterLayer, rosterState, rosterQuery]);
  const watching = currentRuntimeCount(runtimeCurrent, Object.values(state.agents).filter(
    (node) => node.observed && node.state === "watching",
  ).length);
  const idle = currentRuntimeCount(runtimeCurrent, Object.values(state.agents).filter(
    (node) => node.observed && node.state === "idle",
  ).length);
  const unobserved = Object.values(state.agents).filter((node) => !node.observed).length;

  // Agents currently co-engaged, grouped by the incident they work on.
  // Drives the connection lines: one group == one ticket == one link mesh.
  const groups = useMemo(
    () => runtimeCurrent ? engagedGroups(state) : [],
    [runtimeCurrent, state.agents, state.incidents],
  );

  // Which agent the pointer is over - emphasises its links and shows the
  // hover card. Kept in state (not just CSS) so the SVG links react too.
  const [hoveredAgent, setHoveredAgent] = useState<string | null>(null);

  // Measured node centres so the SVG overlay can draw links between the
  // real rendered positions of the constellation grid. Re-measured after
  // every layout change and on resize (ResizeObserver), so the lines track
  // reflow without hard-coding a layout.
  const constellationRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef(new Map<string, HTMLElement>());
  const [geometry, setGeometry] = useState<Geometry>(EMPTY_GEOMETRY);

  useLayoutEffect(() => {
    const container = constellationRef.current;
    if (!container || typeof ResizeObserver === "undefined") return undefined;
    const measure = (): void => {
      const box = container.getBoundingClientRect();
      const centers: Record<string, Point> = {};
      for (const [name, el] of nodeRefs.current) {
        const ring = (el.querySelector(".agent-ring") as HTMLElement | null) ?? el;
        const r = ring.getBoundingClientRect();
        centers[name] = {
          x: r.left - box.left + r.width / 2,
          y: r.top - box.top + r.height / 2,
        };
      }
      setGeometry({ centers, w: box.width, h: box.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(container);
    return () => ro.disconnect();
    // Re-measure whenever the set of agent nodes changes (a state message
    // rebuilds `state.agents`) or the layout switches, because both reflow
    // node positions the overlays draw from.
  }, [state.agents, layout]);

  usePublishViewContext(
    () => ({
      routeId: "agents",
      routeLabel: "Agents",
      purpose:
        "The 15-agent pantheon, live. Each incident (correlation id) is one " +
        "collaboration: Huginn/Heimdall sense, Forseti judges, Var queues an approval " +
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
        : `${state.incidentOrder.length} incident(s) - ${active ?? "unknown"} agent(s) engaged`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "incidents", value: state.incidentOrder.length, group: "page" },
        { key: "engaged", value: active, group: "page" },
        { key: "selected", value: selected?.ticketId ?? "-", group: "incident" },
        { key: "status", value: selected?.status ?? "-", group: "incident" },
        { key: "severity", value: selected?.severity ?? "-", group: "incident" },
      ],
      records: {
        selected_agent: selectedAgentNode
          ? [{
              agent: selectedAgentNode.name,
              state: agentStateLabel(selectedAgentNode),
              task: currentTask(selectedAgentNode),
              correlation_id: selectedAgentNode.correlationId,
            }]
          : [],
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
    [state, selected, active, selectedAgentNode],
  );

  // Render one agent node - shared by the constellation grid and the org
  // chart so both carry the live ring, hover card, and click-to-focus. A
  // button so the whole node is a keyboard-reachable focus target.
  const renderNode = (name: string): VNode | null => {
    const node = state.agents[name];
    if (!node) return null;
    const isInvolved = involved.has(name);
    const dim = selected !== null && !isInvolved;
    const engaged = runtimeCurrent && isEngaged(node);
    const incident = node.correlationId ? (state.incidents[node.correlationId] ?? null) : null;
    const role = AGENT_ROLE[name];
    const subLabel = layout === "org" && role ? role.title : (STATE_LABEL[node.state] ?? node.state);
    const iconUrl = agentIconUrl(name);
    return (
      <button
        key={name}
        type="button"
        ref={(el) => {
          if (el) nodeRefs.current.set(name, el as HTMLElement);
          else nodeRefs.current.delete(name);
        }}
        class={`agent-node layer-${node.layer} state-${node.state}${
          isInvolved ? " is-involved" : ""
        }${dim ? " is-dim" : ""}${engaged ? " is-engaged" : ""}${
          hoveredAgent === name ? " is-hovered" : ""
        }${selectedAgent === name ? " is-agent-selected" : ""}`}
        onMouseEnter={() => setHoveredAgent(name)}
        onMouseLeave={() => setHoveredAgent((cur) => (cur === name ? null : cur))}
        onClick={() => openFocus(selectedAgent === name ? null : name, selectedId)}
      >
        <span class="agent-ring" aria-hidden="true">
          <span
            class="agent-icon"
            style={{ WebkitMaskImage: iconUrl, maskImage: iconUrl }}
          />
        </span>
        <span class="agent-name">{name}</span>
        <span class="agent-state">{subLabel}</span>
        <AgentHoverCard node={node} incident={incident} />
      </button>
    );
  };

  return (
    <div class="agents-route">
      <AgentWorkspaceNav />
      <header class="agents-head">
        <div>
          <span class="agents-eyebrow">Read-only live status</span>
          <h2>Agent fleet</h2>
          <p class="agents-sub">
            Live work across the fixed 15-agent pantheon. Inspect current tasks,
            open each agent's evidence timeline, or ask about its grounded context.
            State combines the durable <code>GET /incidents</code> snapshot with live
            deltas from <code>GET /agents/stream</code>.
          </p>
        </div>
        <div class="agents-meta">
          <div class="agents-layout-toggle" role="group" aria-label="layout mode">
            <button
              type="button"
              class={layout === "roster" ? "is-active" : ""}
              aria-pressed={layout === "roster"}
              onClick={() => selectLayout("roster")}
            >
              Roster
            </button>
            <button
              type="button"
              class={layout === "constellation" ? "is-active" : ""}
              aria-pressed={layout === "constellation"}
              onClick={() => selectLayout("constellation")}
            >
              Constellation
            </button>
            <button
              type="button"
              class={layout === "org" ? "is-active" : ""}
              aria-pressed={layout === "org"}
              onClick={() => selectLayout("org")}
            >
              Org chart
            </button>
          </div>
          <span class={`agents-conn conn-${status}`}>{status}</span>
          <span class="status-pill status-pill-neutral">
            {observationSourceLabel(streamSource)}
          </span>
          <span class="agents-active">
            <strong>{active ?? "-"}</strong> engaged
          </span>
        </div>
      </header>

      {snapshotError ? (
        <UnavailableState message={`Durable incident history is unavailable: ${snapshotError}`} />
      ) : null}

      {layout === "roster" ? (
        <AgentRoster
          agents={rosterAgents}
          state={state}
          layer={rosterLayer}
          stateFilter={rosterState}
          query={rosterQuery}
          active={active}
          watching={watching}
          idle={idle}
          unobserved={unobserved}
          runtimeCurrent={runtimeCurrent}
          streamSource={streamSource}
          onLayerChange={(next) => openRosterFilters(next, rosterState, rosterQuery)}
          onStateChange={(next) => openRosterFilters(rosterLayer, next, rosterQuery)}
          onQueryChange={(next) => openRosterFilters(rosterLayer, rosterState, next, true)}
          onOpen={(name) => {
            setLayout("org");
            openFocus(name, selectedId, "org");
          }}
        />
      ) : (
      <div class="agents-layout">
        <section
          class={`agents-stage layout-${layout}`}
          aria-label="agent pantheon"
          ref={constellationRef}
        >
          {layout === "org" && <OrgReportingLines geometry={geometry} />}
          <ConstellationLinks
            groups={groups}
            geometry={geometry}
            selectedId={selectedId}
            hoveredAgent={hoveredAgent}
          />
          {layout === "constellation" ? (
            <div class="agents-constellation">{PANTHEON.map((a) => renderNode(a.name))}</div>
          ) : (
            <div class="agents-org">
              <div class="org-tier org-root">{renderNode(ORG_CHART.root)}</div>
              <div class="org-tier org-branches">
                {ORG_CHART.lines.map((line) => (
                  <div class="org-branch" key={line.manager}>
                    <div class="org-manager">{renderNode(line.manager)}</div>
                    <div class="org-reports">{line.reports.map((n) => renderNode(n))}</div>
                  </div>
                ))}
                <div class="org-branch org-staff-branch">
                  <div class="org-staff-label">Staff to Odin</div>
                  <div class="org-reports">{ORG_CHART.staff.map((n) => renderNode(n))}</div>
                </div>
              </div>
            </div>
          )}
        </section>

        <aside class="agents-side">
          {selectedAgent && !selectedAgentNode ? (
            <UnavailableState message={`Agent ${selectedAgent} is not in the fixed pantheon.`} />
          ) : null}
          {selectedId && !selected ? (
            <UnavailableState message={`Incident ${selectedId} is not present in the retained agent stream.`} />
          ) : null}
          {selectedAgentNode && (
            <AgentFocus
              node={selectedAgentNode}
              incidents={selectedAgentIncidents}
              onClose={() => openFocus(null, selectedId)}
              onChat={() =>
                openDeckWithContext({
                  sessionKey: `agent:${selectedAgentNode.name}`,
                  sessionLabel: selectedAgentNode.name,
                  contextNote: agentChatContext(selectedAgentNode, selectedAgentIncidents),
                  prompt: `What has ${selectedAgentNode.name} been working on?`,
                })
              }
              onPickIncident={(id) => {
                // If the target sits past the recent-10 window, expand the
                // full list so its inline card is actually visible.
                if (state.incidentOrder.indexOf(id) >= INCIDENT_PREVIEW) {
                  setShowAllIncidents(true);
                }
                openFocus(selectedAgent, id);
              }}
            />
          )}
          <div class="agents-incident-list" aria-label="incidents">
            <div class="agents-incident-head">
              <h3>Incidents</h3>
              {state.incidentOrder.length > INCIDENT_PREVIEW && (
                <button
                  type="button"
                  class={`agents-incident-all${showAllIncidents ? " is-active" : ""}`}
                  aria-pressed={showAllIncidents}
                  onClick={() => setShowAllIncidents((v) => !v)}
                >
                  {showAllIncidents ? "Recent" : `All (${state.incidentOrder.length})`}
                </button>
              )}
            </div>
            {state.incidentOrder.length === 0 ? (
              <p class="agents-empty">No incidents - autonomy holding.</p>
            ) : (
              <ul>
                {(showAllIncidents
                  ? state.incidentOrder
                  : state.incidentOrder.slice(0, INCIDENT_PREVIEW)
                ).map((id) => {
                  const inc = state.incidents[id];
                  if (!inc) return null;
                  const isOpen = id === selectedId;
                  return (
                    <li key={id} class={`incident-item${isOpen ? " is-open" : ""}`}>
                      <button
                        type="button"
                        class={`incident-row sev-${inc.severity} status-${inc.status}${
                          isOpen ? " is-selected" : ""
                        }`}
                        aria-expanded={isOpen}
                        onClick={() => {
                          // Toggle: click an open row to collapse it, another to open.
                          openFocus(selectedAgent, isOpen ? null : id);
                        }}
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
        </aside>
      </div>
      )}
    </div>
  );
}
