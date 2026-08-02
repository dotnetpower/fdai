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
import type { OperatorApiClient } from "../api";
import { AgentWorkspaceNav } from "../components/agent-workspace-nav";
import { UnavailableState } from "../components/ui";
import { agentStreamDescriptor, useAgentStream } from "../hooks/use-agent-stream";
import { observationSourceLabel } from "../hooks/observation-source";
import { t } from "../i18n";
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
  agentConversationBriefing,
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
  agentIconUrl,
  agentRoleTitle,
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
  OrgReportingLines,
} from "./agents.constellation";
import { AgentFocus, IncidentWorkflow } from "./agents.detail";

interface Props {
  readonly client: OperatorApiClient;
}

/** How many incidents the side list shows before the "All" toggle. */
const INCIDENT_PREVIEW = 10;

function layoutFromRoute(): AgentLayout {
  const route = currentRoute();
  if (route.panelId === "pantheon") return "org";
  const view = route.search.get("view");
  return view === "org" || view === "constellation" ? "org" : "roster";
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

  // Fleet and hierarchical organization are separate workspace views.
  // Legacy `view=constellation` links map to organization in `layoutFromRoute`.
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
    navigate(routeHref(nextLayout === "org" ? "pantheon" : "agents", {
      params: {
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
        return [
          node.name,
          agentStateLabel(node),
          node.detail,
          role?.title,
          agentRoleTitle(node.name),
          currentTask(node),
        ]
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

  // Which agent the pointer is over - reveals its current-work hover card.
  const [hoveredAgent, setHoveredAgent] = useState<string | null>(null);

  // Measured node centres let the organization overlay track responsive nodes.
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
      routeLabel: layout === "org" ? t("agents.workspace.org") : t("agents.workspace.fleet"),
      purpose: layout === "org" ? t("agents.org.contextPurpose") : t("agents.context.purpose"),
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.hil,
        TERMS.outcome,
        TERMS.gateDecision,
        agentTerm(),
      ]),
      headline: selected
        ? t("agents.context.selectedHeadline", {
            title: selected.title,
            status: selected.status,
            agents: selected.involved.length,
            turns: selected.turns.length,
          })
        : t("agents.context.headline", {
            incidents: state.incidentOrder.length,
            agents: active ?? t("agents.common.unknown"),
          }),
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
    [state, selected, active, selectedAgentNode, layout],
  );

  // Render one keyboard-reachable organization node with live runtime state.
  const renderNode = (name: string): VNode | null => {
    const node = state.agents[name];
    if (!node) return null;
    const isInvolved = involved.has(name);
    const dim = selected !== null && !isInvolved;
    const engaged = runtimeCurrent && isEngaged(node);
    const incident = node.correlationId ? (state.incidents[node.correlationId] ?? null) : null;
    const role = AGENT_ROLE[name];
    const subLabel = role ? agentRoleTitle(name) : agentStateLabel(node);
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
          <span class="agents-eyebrow">
            {layout === "org" ? t("agents.org.eyebrow") : t("agents.header.eyebrow")}
          </span>
          <h2>{layout === "org" ? t("agents.org.title") : t("agents.header.title")}</h2>
          <p class="agents-sub">
            {layout === "org" ? (
              t("agents.org.description")
            ) : (
              <>
                {t("agents.header.descriptionLead")} <code>GET /incidents</code>
                {t("agents.header.descriptionMiddle")} <code>GET /agents/stream</code>
                {t("agents.header.descriptionTail")}
              </>
            )}
          </p>
        </div>
        <div class="agents-meta">
          <span class={`agents-conn conn-${status}`}>{t(`agents.connection.${status}`)}</span>
          <span class="status-pill status-pill-neutral">
            {observationSourceLabel(streamSource)}
          </span>
          <span class="agents-active">
            {t("agents.header.engaged", { count: active ?? "-" })}
          </span>
        </div>
      </header>

      {snapshotError ? (
        <UnavailableState message={t("agents.error.historyUnavailable", { error: snapshotError })} />
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
            openFocus(name, selectedId, "org");
          }}
        />
      ) : (
      <div class="agents-layout">
        <section
          class={`agents-stage layout-${layout}`}
          aria-label={t("agents.org.chartLabel")}
          ref={constellationRef}
        >
          {layout === "org" && <OrgReportingLines geometry={geometry} />}
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
                  <div class="org-staff-label">{t("agents.layout.staffToOdin")}</div>
                  <div class="org-reports">{ORG_CHART.staff.map((n) => renderNode(n))}</div>
                </div>
              </div>
          </div>
        </section>

        <aside class="agents-side">
          {selectedAgent && !selectedAgentNode ? (
            <UnavailableState message={t("agents.error.unknownAgent", { agent: selectedAgent })} />
          ) : null}
          {selectedId && !selected ? (
            <UnavailableState message={t("agents.error.unknownIncident", { incident: selectedId })} />
          ) : null}
          {selectedAgentNode && (
            <AgentFocus
              node={selectedAgentNode}
              incidents={selectedAgentIncidents}
              selectedIncidentId={selectedId}
              onClose={() => openFocus(null, selectedId)}
              onChat={() =>
                openDeckWithContext({
                  sessionLabel: selectedAgentNode.name,
                  newConversation: true,
                  targetAgent: selectedAgentNode.name,
                  contextNote: agentChatContext(selectedAgentNode, selectedAgentIncidents),
                  openingBriefing: agentConversationBriefing(
                    selectedAgentNode,
                    selectedAgentIncidents,
                  ),
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
          <div class="agents-incident-list" aria-label={t("agents.incidents.label")}>
            <div class="agents-incident-head">
              <h3>{t("agents.incidents.title")}</h3>
              {state.incidentOrder.length > INCIDENT_PREVIEW && (
                <button
                  type="button"
                  class={`agents-incident-all${showAllIncidents ? " is-active" : ""}`}
                  aria-pressed={showAllIncidents}
                  onClick={() => setShowAllIncidents((v) => !v)}
                >
                  {showAllIncidents
                    ? t("agents.incidents.recent")
                    : t("agents.incidents.all", { count: state.incidentOrder.length })}
                </button>
              )}
            </div>
            {state.incidentOrder.length === 0 ? (
              <p class="agents-empty">{t("agents.incidents.empty")}</p>
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
                      {isOpen && (
                        <IncidentWorkflow agent={selectedAgent} incident={inc} />
                      )}
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
