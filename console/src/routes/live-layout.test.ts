import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const styles = readFileSync(
  fileURLToPath(new URL("../styles.css", import.meta.url)),
  "utf8",
);
const routeStyles = readFileSync(
  fileURLToPath(new URL("./live.css", import.meta.url)),
  "utf8",
);
const panels = readFileSync(
  fileURLToPath(new URL("./live.panels.tsx", import.meta.url)),
  "utf8",
);
const route = readFileSync(
  fileURLToPath(new URL("./live.tsx", import.meta.url)),
  "utf8",
);
const liveStream = readFileSync(
  fileURLToPath(new URL("../hooks/use-live-stream.ts", import.meta.url)),
  "utf8",
);
const observations = readFileSync(
  fileURLToPath(new URL("./live.observations.tsx", import.meta.url)),
  "utf8",
);
const activity = readFileSync(
  fileURLToPath(new URL("./live.activity.tsx", import.meta.url)),
  "utf8",
);
const tiles = readFileSync(
  fileURLToPath(new URL("./live.tiles.tsx", import.meta.url)),
  "utf8",
);
const detailShell = readFileSync(
  fileURLToPath(new URL("./live.detail-shell.tsx", import.meta.url)),
  "utf8",
);
const detailStyles = readFileSync(
  fileURLToPath(new URL("./live.detail.css", import.meta.url)),
  "utf8",
);

function ruleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return styles.match(new RegExp(`${escaped}\\s*\\{(?<body>[\\s\\S]*?)\\}`))
    ?.groups?.body ?? "";
}

function routeRuleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matches = [...routeStyles.matchAll(
    new RegExp(`${escaped}\\s*\\{(?<body>[\\s\\S]*?)\\}`, "g"),
  )];
  return matches.at(-1)?.groups?.body ?? "";
}

describe("Live responsive header", () => {
  it("loads the route-owned visual contract", () => {
    expect(route).toContain('import "./live.css"');
    expect(detailShell).toContain('import "./live.detail.css"');
    expect(detailShell).toContain("createPortal(dialog, document.fullscreenElement ?? document.body)");
    expect(ruleBody(".live-detail-backdrop")).toContain("z-index: 120");
    expect(detailStyles).toMatch(
      /\.live-detail-panel\s*\{[^}]*width: min\(560px, 100%\)/,
    );
  });

  it("wraps controls against the available content width", () => {
    expect(ruleBody(".live .page-header")).toContain("flex-wrap: wrap");
    expect(ruleBody(".live .page-header-text")).toContain("flex: 1 1 280px");
    expect(ruleBody(".live .page-header-actions")).toContain("max-width: 100%");
    expect(styles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.live \.page-header-text\s*\{[^}]*flex: 0 1 auto;[^}]*width: 100%;[^}]*\}/,
    );
  });

  it("keeps the unified activity grid bounded by card count and page flow", () => {
    expect(routeStyles).toMatch(
      /\.live-activity-grid\s*\{[^}]*grid-template-columns: repeat\(4/,
    );
    expect(routeStyles).not.toMatch(
      /\.live-activity-grid\s*\{[^}]*overflow-y: auto/,
    );
    expect(activity).toContain("export const LIVE_ACTIVITY_VISIBLE_LIMIT = 15");
    expect(activity).toContain("visibleLiveActivityItems");
    expect(routeStyles).toMatch(
      /\.live \.live-work-card\s*\{[^}]*min-height: 164px/,
    );
    expect(routeStyles).toMatch(
      /@container \(max-width: 1180px\)[\s\S]*?\.live-activity-grid\s*\{[^}]*repeat\(3/,
    );
    expect(routeStyles).toMatch(
      /@container \(max-width: 900px\)[\s\S]*?\.live-activity-grid\s*\{[^}]*repeat\(2/,
    );
    expect(routeStyles).toMatch(
      /@container \(max-width: 620px\)[\s\S]*?\.live-activity-grid\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\)/,
    );
    expect(routeRuleBody('.live-activity-grid[data-view="queue"]')).toContain(
      "grid-template-columns: minmax(0, 1fr)",
    );
  });

  it("keeps the mock-aligned health grid responsive", () => {
    expect(panels).toContain('<div class="live-status-rail">');
    expect(panels).toContain('<section class="grid live-kpis">');
    expect(panels).not.toContain("hasWindowMetrics");
    expect(panels).toContain("lastSignalAt");
    expect(liveStream).toContain("lastSignalValueRef.current = Date.now()");
    expect(liveStream).toContain("setLastSignalAt(lastSignalValueRef.current)");
    expect(routeStyles).toMatch(
      /\.live-status-rail\s*\{[^}]*grid-template-columns: minmax\(0, auto\) minmax\(220px, 1fr\)/,
    );
    expect(panels).toContain('<section class="live-sample-scenario"');
    expect(panels).toContain('selectEvent("sample-event-001")');
    expect(routeStyles).toMatch(
      /\.live-sample-scenario-steps\s*\{[^}]*grid-template-columns: repeat\(6/,
    );
  });

  it("packs flow events sequentially while signaling semantic updates", () => {
    expect(panels).toContain("<LiveActivityWorkspace");
    expect(activity).toContain("composeLiveActivityItems");
    expect(activity).toContain("right.observedAt - left.observedAt");
    expect(activity).not.toContain("slotIndex");
    expect(styles).toMatch(
      /\.live-tile\.is-content-updated \.live-tile-stage\s*\{[^}]*color: var\(--accent\)/,
    );
  });

  it("renders current activity in shared cards and keeps retained history separate", () => {
    expect(observations).toContain("export const LIVE_OBSERVATION_LIMIT = 500");
    expect(observations).not.toContain("items.slice(0,");
    expect(observations).toContain("live-observation-item live-work-card");
    expect(observations).toContain('aria-haspopup="dialog"');
    expect(observations).not.toContain("activityHref");
    expect(observations).toContain('class="live-activity-kind"');
    expect(observations).toContain('class="live-detail-technical"');
    expect(routeStyles).not.toContain(".live-observation-grid");
    expect(routeStyles).toMatch(
      /\.live \.live-observation-item\s*\{[^}]*min-height: 164px/,
    );
  });

  it("matches card geometry and makes outcomes readable without persistent animation", () => {
    const card = routeStyles.match(/\.live \.live-work-card\s*\{([^}]+)\}/)?.[1];
    expect(card).toContain("border-radius: 9px");
    expect(card).toContain("animation: none");
    expect(card).toContain("opacity: 1");
    expect(card).toContain("box-shadow: none");
    expect(routeStyles).toMatch(/\.live \.live-observation-meta\s*\{[^}]*margin-top: auto/);
    expect(routeRuleBody(".live .live-tile-bar")).toContain("height: 3px");
    expect(tiles).toContain('aria-controls="live-detail-panel"');
    expect(tiles).toContain("aria-expanded={selected}");
    expect(tiles).toContain("{statusLabel}");
    expect(activity).not.toContain("orderLiveActivityItems");
    expect(activity).toContain("parsedTime(tile.first_ts, tile.first_seen_at)");
  });
});
