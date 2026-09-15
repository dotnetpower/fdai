import {
  ORG_CHART,
} from "./agents.model";
import {
  type Geometry,
} from "./agents.view-model";

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
