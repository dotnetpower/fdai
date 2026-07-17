import {
  ORG_CHART,
  STATE_TASK,
  type AgentNode,
  type EngagedGroup,
  type Incident,
} from "./agents.model";
import {
  STATE_LABEL,
  centroid,
  hueForIncident,
  pairsOf,
  type Geometry,
  type Point,
} from "./agents.view-model";

/**
 * SVG overlay that draws a connection-line mesh between every pair of
 * agents co-engaged on the same incident, so the operator can see which
 * ticket each agent is working on and with whom. One colour per incident;
 * the selected incident (or the hovered agent's links) is emphasised while
 * the rest fade back. Purely decorative - `pointer-events: none` so the
 * nodes underneath stay interactive; `aria-hidden` because the same
 * information is available as text in the incident list + hover card.
 */
export function ConstellationLinks({
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
export function AgentHoverCard({
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
          {STATE_LABEL[node.state] ?? node.state}
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
export function OrgReportingLines({ geometry }: { geometry: Geometry }) {
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
