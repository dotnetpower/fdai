/**
 * Now > Agents route (Track B, Phase 2).
 *
 * An agent-centric, read-only view of the fixed pantheon. Fleet owns current
 * observed state; the role fallback owns reporting lines and object ownership.
 * Chronological audit and incident evidence remain on their dedicated routes.
 *
 * Pure read-only: no privileged calls. The SSE consumer
 * ({@link useAgentStream}) is a translator, never a judge.
 */

import { useEffect, useMemo, useReducer, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { AgentWorkspaceNav } from "../components/agent-workspace-nav";
import { UnavailableState } from "../components/ui";
import { agentStreamDescriptor, useAgentStream } from "../hooks/use-agent-stream";
import { observationSourceLabel } from "../hooks/observation-source";
import { t } from "../i18n";
import { currentRoute, navigate, replaceRouteState, routeHref } from "../router";
import { usePublishViewContext } from "../deck/context";
import { agentTerm, composeGlossary, TERMS } from "../deck/glossary";
import {
  PANTHEON,
  activeAgentCount,
  currentRuntimeCount,
  AGENT_ROLE,
  isEngaged,
  makeInitialState,
  reducer,
  type AgentNode,
} from "./agents.model";
import {
  agentRoleTitle,
  agentStateLabel,
  agentViewContextRecord,
  currentTask,
  rosterLayerOf,
  type AgentLayout,
  type RosterLayer,
  type RosterState,
} from "./agents.view-model";
import { AgentRoster } from "./agents.roster";
import { AgentOrganizationWorkspace } from "./agent-organization";

interface Props {
  readonly client: OperatorApiClient;
}

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
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

  const stream = useMemo(agentStreamDescriptor, []);

  const { status, source: streamSource } = useAgentStream({
    url: stream.url,
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (msg) => dispatch({ kind: "message", msg }),
  });

  // Fleet and hierarchical organization are separate workspace views.
  // Legacy `view=constellation` links map to organization in `layoutFromRoute`.
  const [layout, setLayout] = useState<AgentLayout>(layoutFromRoute);
  const [rosterLayer, setRosterLayer] = useState<RosterLayer>(initialRosterFilters.layer);
  const [rosterState, setRosterState] = useState<RosterState>(initialRosterFilters.state);
  const [rosterQuery, setRosterQuery] = useState(initialRosterFilters.query);

  useEffect(() => {
    if (layout !== "roster") {
      setSnapshotError(null);
      return undefined;
    }
    let cancelled = false;
    void client.listIncidents({ status: "all", limit: 30 }).then((page) => {
      if (!cancelled) {
        dispatch({ kind: "hydrate", incidents: page.items });
        setSnapshotError(null);
      }
    }).catch((error: unknown) => {
      if (!cancelled) setSnapshotError(error instanceof Error ? error.message : String(error));
    });
    return () => { cancelled = true; };
  }, [client, layout]);

  // Agent the operator clicked to focus - drives the "what events is this
  // agent in" side panel. Independent from the selected incident.
  const [selectedAgent, setSelectedAgent] = useState<string | null>(
    initialRoute.search.get("agent"),
  );
  const selectedAgentNode = selectedAgent ? (state.agents[selectedAgent] ?? null) : null;

  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
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
    nextLayout: AgentLayout = layout,
  ): void => {
    navigate(routeHref(nextLayout === "org" ? "pantheon" : "agents", {
      params: {
        agent,
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

  usePublishViewContext(
    () => ({
      routeId: layout === "org" ? "pantheon" : "agents",
      routeLabel: layout === "org" ? t("nav.panel.pantheon") : t("agents.workspace.fleet"),
      purpose: layout === "org" ? t("agents.org.contextPurpose") : t("agents.context.purpose"),
      glossary: composeGlossary(layout === "org"
        ? [agentTerm()]
        : [
            TERMS.correlationId,
            TERMS.hil,
            TERMS.outcome,
            TERMS.gateDecision,
            agentTerm(),
          ]),
      headline: layout === "org"
        ? t("agents.org.contextHeadline", { agents: PANTHEON.length })
        : t("agents.context.headline", {
            agents: active ?? t("agents.common.unknown"),
          }),
      capturedAt: new Date().toISOString(),
      facts: layout === "org" ? [
        { key: "agents", value: PANTHEON.length, group: "page" },
        { key: "selected_agent", value: selectedAgent ?? "-", group: "page" },
        { key: "stream_status", value: status, group: "runtime" },
      ] : [
        { key: "engaged", value: active, group: "page" },
        { key: "selected_agent", value: selectedAgent ?? "-", group: "page" },
        { key: "stream_status", value: status, group: "runtime" },
      ],
      records: {
        selected_agent: selectedAgentNode
          ? [agentViewContextRecord(selectedAgentNode, layout)]
          : [],
        conversation: [],
        incidents: [],
      },
    }),
    [status, active, selectedAgent, selectedAgentNode, layout],
  );

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

      {layout === "roster" && snapshotError ? (
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
            openFocus(name, "org");
          }}
        />
      ) : (
        <>
          {selectedAgent && !selectedAgentNode ? (
            <UnavailableState message={t("agents.error.unknownAgent", { agent: selectedAgent })} />
          ) : null}
          <AgentOrganizationWorkspace
            agents={state.agents}
            selectedAgent={selectedAgent}
            runtimeCurrent={runtimeCurrent}
            onSelectAgent={(agent) => openFocus(agent, "org")}
          />
        </>
      )}
    </div>
  );
}
