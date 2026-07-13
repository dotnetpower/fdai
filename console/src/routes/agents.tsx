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
import { loadConfig } from "../config";
import { useAgentStream } from "../hooks/use-agent-stream";
import { usePublishViewContext } from "../deck/context";
import { agentTerm, composeGlossary, TERMS } from "../deck/glossary";
import { openDeckWithPrompt, openDeckWithContext } from "../deck/open-deck";
import {
  PANTHEON,
  activeAgentCount,
  AGENT_ROLE,
  agentChatContext,
  engagedGroups,
  incidentsForAgent,
  isEngaged,
  makeInitialState,
  ORG_CHART,
  reducer,
  STATE_TASK,
  type AgentNode,
  type EngagedGroup,
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

/** A node's measured centre within the constellation, in local px. */
interface Point {
  readonly x: number;
  readonly y: number;
}

interface Geometry {
  readonly centers: Record<string, Point>;
  readonly w: number;
  readonly h: number;
}

const EMPTY_GEOMETRY: Geometry = { centers: {}, w: 0, h: 0 };

/** How many incidents the side list shows before the "All" toggle. */
const INCIDENT_PREVIEW = 10;

/**
 * CSS `mask-image` url for an agent's line icon (served from `public/
 * agent-icons/<name>.svg`). The SVGs are monochrome `currentColor` strokes,
 * so they are painted via a mask tinted to the agent's accent colour rather
 * than an `<img>` (which cannot inherit CSS `color`). Base-path aware so the
 * console still finds them when mounted under a subpath.
 */
function agentIconUrl(name: string): string {
  return `url("${import.meta.env.BASE_URL}agent-icons/${name.toLowerCase()}.svg")`;
}

/** Stable hue (0-360) for an incident so its links + label share a colour. */
function hueForIncident(correlationId: string): number {
  let h = 0;
  for (let i = 0; i < correlationId.length; i++) {
    h = (h * 31 + correlationId.charCodeAt(i)) % 360;
  }
  return h;
}

/** All unordered pairs of a list - the mesh of links inside one incident. */
function pairsOf(names: readonly string[]): [string, string][] {
  const out: [string, string][] = [];
  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      out.push([names[i]!, names[j]!]);
    }
  }
  return out;
}

/** Centroid of the measured points, used to anchor the ticket label. */
function centroid(points: readonly Point[]): Point | null {
  if (points.length === 0) return null;
  const sum = points.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }), { x: 0, y: 0 });
  return { x: sum.x / points.length, y: sum.y / points.length };
}

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

  // Incident list shows the most recent `INCIDENT_PREVIEW` (newest first);
  // the "All" toggle expands to the full retained history.
  const [showAllIncidents, setShowAllIncidents] = useState(false);

  // Layout mode: the free "constellation" grid, or the hierarchical "org"
  // chart that shows who reports to whom. Both share the same live nodes.
  // Defaults to the org chart so the pantheon's roles + reporting lines are
  // the first thing an operator sees.
  const [layout, setLayout] = useState<"constellation" | "org">("org");

  // Agent the operator clicked to focus - drives the "what events is this
  // agent in" side panel. Independent from the selected incident.
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const selectedAgentNode = selectedAgent ? (state.agents[selectedAgent] ?? null) : null;
  const selectedAgentIncidents = useMemo(
    () => (selectedAgent ? incidentsForAgent(state, selectedAgent) : []),
    [state, selectedAgent],
  );

  const selected: Incident | null = selectedId ? (state.incidents[selectedId] ?? null) : null;
  const involved = useMemo(
    () => new Set(selected?.involved ?? []),
    [selected],
  );

  const active = activeAgentCount(state);

  // Agents currently co-engaged, grouped by the incident they work on.
  // Drives the connection lines: one group == one ticket == one link mesh.
  const groups = useMemo(() => engagedGroups(state), [state.agents, state.incidents]);

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
        selected_agent: selectedAgentNode
          ? [{
              agent: selectedAgentNode.name,
              state: selectedAgentNode.state,
              task: selectedAgentNode.detail ?? STATE_TASK[selectedAgentNode.state],
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
    const engaged = isEngaged(node);
    const incident = node.correlationId ? (state.incidents[node.correlationId] ?? null) : null;
    const role = AGENT_ROLE[name];
    const subLabel = layout === "org" && role ? role.title : (_STATE_LABEL[node.state] ?? node.state);
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
        onClick={() => setSelectedAgent((cur) => (cur === name ? null : name))}
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
      <header class="agents-head">
        <div>
          <h2>Agents</h2>
          <p class="agents-sub">
            The 15-agent pantheon, live. Switch to the <strong>Org chart</strong>{" "}
            to see who reports to whom and each agent's role; click an agent to
            see the events it is working. Wire: <code>GET /agents/stream</code>.
          </p>
        </div>
        <div class="agents-meta">
          <div class="agents-layout-toggle" role="group" aria-label="layout mode">
            <button
              type="button"
              class={layout === "constellation" ? "is-active" : ""}
              aria-pressed={layout === "constellation"}
              onClick={() => setLayout("constellation")}
            >
              Constellation
            </button>
            <button
              type="button"
              class={layout === "org" ? "is-active" : ""}
              aria-pressed={layout === "org"}
              onClick={() => setLayout("org")}
            >
              Org chart
            </button>
          </div>
          <span class={`agents-conn conn-${status}`}>{status}</span>
          <span class="agents-active">
            <strong>{active}</strong> engaged
          </span>
        </div>
      </header>

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
          {selectedAgentNode && (
            <AgentFocus
              node={selectedAgentNode}
              incidents={selectedAgentIncidents}
              onClose={() => setSelectedAgent(null)}
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
                setSelectedId(id);
                setPinned(true);
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
                          setPinned(true);
                          // Toggle: click an open row to collapse it, another to open.
                          setSelectedId((cur) => (cur === id ? null : id));
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
    </div>
  );
}

/**
 * SVG overlay that draws a connection-line mesh between every pair of
 * agents co-engaged on the same incident, so the operator can see which
 * ticket each agent is working on and with whom. One colour per incident;
 * the selected incident (or the hovered agent's links) is emphasised while
 * the rest fade back. Purely decorative - `pointer-events: none` so the
 * nodes underneath stay interactive; `aria-hidden` because the same
 * information is available as text in the incident list + hover card.
 */
function ConstellationLinks({
  groups,
  geometry,
  selectedId,
  hoveredAgent,
}: {
  readonly groups: readonly EngagedGroup[];
  readonly geometry: Geometry;
  readonly selectedId: string | null;
  readonly hoveredAgent: string | null;
}) {
  if (geometry.w === 0 || groups.length === 0) return null;
  const { centers } = geometry;
  const anySelected = selectedId !== null;

  return (
    <svg
      class="agents-links"
      width={geometry.w}
      height={geometry.h}
      viewBox={`0 0 ${geometry.w} ${geometry.h}`}
      aria-hidden="true"
    >
      {groups.map((g) => {
        const hue = hueForIncident(g.correlationId);
        const stroke = `hsl(${hue} 80% 62%)`;
        const isSelected = g.correlationId === selectedId;
        const measured = g.agents.map((n) => centers[n]).filter((p): p is Point => Boolean(p));
        const mid = centroid(measured);
        return (
          <g key={g.correlationId}>
            {pairsOf(g.agents).map(([a, b]) => {
              const ca = centers[a];
              const cb = centers[b];
              if (!ca || !cb) return null;
              const touchesHover =
                hoveredAgent !== null && (a === hoveredAgent || b === hoveredAgent);
              const emphasis = isSelected || touchesHover;
              const opacity = anySelected && !emphasis ? 0.1 : emphasis ? 0.7 : 0.32;
              return (
                <line
                  key={`${a}-${b}`}
                  class={`agent-link${emphasis ? " is-emphasis" : ""}`}
                  x1={ca.x}
                  y1={ca.y}
                  x2={cb.x}
                  y2={cb.y}
                  stroke={stroke}
                  stroke-width={emphasis ? 2 : 1.2}
                  stroke-opacity={opacity}
                />
              );
            })}
            {mid && g.incident && (
              <text
                class={`agent-link-label${isSelected ? " is-emphasis" : ""}`}
                x={mid.x}
                y={mid.y}
                fill={stroke}
                fill-opacity={anySelected && !isSelected ? 0.35 : 0.9}
                text-anchor="middle"
              >
                {g.incident.ticketId || "incident"}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * Hover card revealed when the pointer is over an agent node. Answers the
 * operator's "what is this agent doing right now?" - it shows the coarse
 * state, a plain-language task description, the streamed `detail` when
 * present, and the incident (ticket + title) the agent is engaged on.
 */
function AgentHoverCard({
  node,
  incident,
}: {
  readonly node: AgentNode;
  readonly incident: Incident | null;
}) {
  const task = STATE_TASK[node.state] ?? node.state;
  return (
    <div class="agent-tooltip" role="tooltip">
      <div class="agent-tooltip-head">
        <strong>{node.name}</strong>
        <span class={`agent-tooltip-state state-${node.state}`}>
          {_STATE_LABEL[node.state] ?? node.state}
        </span>
      </div>
      <p class="agent-tooltip-task">{task}</p>
      {node.detail && <p class="agent-tooltip-detail">{node.detail}</p>}
      {incident ? (
        <div class="agent-tooltip-incident">
          <span class="agent-tooltip-ticket">{incident.ticketId || "incident"}</span>
          <span class="agent-tooltip-title">{incident.title}</span>
        </div>
      ) : (
        <p class="agent-tooltip-idle">Not engaged on any incident.</p>
      )}
    </div>
  );
}

/**
 * Static SVG overlay for the org-chart layout: draws the reporting lines
 * (each report -> its manager, each manager + staff -> Odin). Structural
 * and faint, so the live incident-collaboration lines drawn on top stay
 * the eye-catching layer. `pointer-events: none` + `aria-hidden` - the
 * reporting structure is also text in each agent's focus panel + hover card.
 */
function OrgReportingLines({ geometry }: { geometry: Geometry }) {
  if (geometry.w === 0) return null;
  const c = geometry.centers;
  const edges: { readonly from: string; readonly to: string; readonly staff: boolean }[] = [];
  for (const line of ORG_CHART.lines) {
    edges.push({ from: line.manager, to: ORG_CHART.root, staff: false });
    for (const r of line.reports) edges.push({ from: r, to: line.manager, staff: false });
  }
  for (const s of ORG_CHART.staff) edges.push({ from: s, to: ORG_CHART.root, staff: true });
  return (
    <svg
      class="agents-org-lines"
      width={geometry.w}
      height={geometry.h}
      viewBox={`0 0 ${geometry.w} ${geometry.h}`}
      aria-hidden="true"
    >
      {edges.map(({ from, to, staff }) => {
        const a = c[from];
        const b = c[to];
        if (!a || !b) return null;
        return (
          <line
            key={`${from}-${to}`}
            class={`org-edge${staff ? " is-staff" : ""}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
          />
        );
      })}
    </svg>
  );
}

/**
 * Focus panel shown when the operator clicks an agent. Answers "who is this
 * and what events is it working?" - the role title + one-line duty, its
 * reporting line, the live state, and every incident it participates in
 * (newest first, clickable to select that incident). Read-only.
 */
function AgentFocus({
  node,
  incidents,
  onClose,
  onChat,
  onPickIncident,
}: {
  readonly node: AgentNode;
  readonly incidents: readonly Incident[];
  readonly onClose: () => void;
  readonly onChat: () => void;
  readonly onPickIncident: (id: string) => void;
}) {
  const role = AGENT_ROLE[node.name];
  const task = STATE_TASK[node.state] ?? node.state;
  return (
    <div class={`agent-focus layer-${node.layer}`}>
      <div class="agent-focus-head">
        <div>
          <strong class="agent-focus-name">{node.name}</strong>
          {role && <span class="agent-focus-title">{role.title}</span>}
        </div>
        <button type="button" class="agent-focus-close" aria-label="Close agent focus" onClick={onClose}>
          {"\u00d7"}
        </button>
      </div>
      {role && <p class="agent-focus-summary">{role.summary}</p>}
      <div class="agent-focus-meta">
        {role?.reportsTo && (
          <span class="agent-focus-reports">
            Reports to <strong>{role.reportsTo}</strong>
            {role.staff ? " (staff)" : ""}
          </span>
        )}
        <span class={`agent-focus-state state-${node.state}`}>
          {_STATE_LABEL[node.state] ?? node.state}
        </span>
      </div>
      <p class="agent-focus-task">{task}</p>
      <button type="button" class="agent-focus-chat" onClick={onChat}>
        <span class="agent-focus-chat-glyph" aria-hidden="true">
          {"\u25c6"}
        </span>
        Chat with {node.name}
      </button>
      <div class="agent-focus-events">
        <h4>
          Events <span class="agent-focus-count">{incidents.length}</span>
        </h4>
        {incidents.length === 0 ? (
          <p class="agents-empty">No incidents involve {node.name} yet.</p>
        ) : (
          <ul>
            {incidents.map((inc) => (
              <li key={inc.correlationId}>
                <button
                  type="button"
                  class={`incident-row sev-${inc.severity} status-${inc.status}`}
                  onClick={() => onPickIncident(inc.correlationId)}
                >
                  <span class="incident-status">{inc.status}</span>
                  <span class="incident-title">{inc.title}</span>
                  <span class="incident-ticket">{inc.ticketId}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
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
