/**
 * Shared Console route frame.
 *
 * Every route renders inside one of two content frames so the page edge, title, and first
 * content row stay on the same vertical lines while an operator moves between menus:
 *  - `standard` - a centered reading and workspace column (Calm Slate token `--cs-route-width`).
 *  - `wide`     - dense master-detail, graph, or canvas routes that need the full workspace
 *                 (`--cs-route-width-wide`).
 * Routes opt into `wide` here instead of carrying their own page `max-width`; forks and
 * extra panels default to `standard`.
 */

export type RouteFrame = "standard" | "wide";

const WIDE_FRAME_PANEL_IDS: ReadonlySet<string> = new Set([
  "agents",
  "pantheon",
  "agent-activity",
  "live",
  "incidents",
  "audit",
  "trace",
  "architecture",
  "ontology",
  "dashboard-v2",
  "detection-readiness",
  "rules",
]);

export function routeFrameFor(panelId: string): RouteFrame {
  return WIDE_FRAME_PANEL_IDS.has(panelId) ? "wide" : "standard";
}

export function wideFramePanelIds(): readonly string[] {
  return [...WIDE_FRAME_PANEL_IDS];
}
