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
const observations = readFileSync(
  fileURLToPath(new URL("./live.observations.tsx", import.meta.url)),
  "utf8",
);
const mockAlignedStyles = styles.slice(styles.indexOf("/* Mock-aligned Live cockpit"));

function ruleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return styles.match(new RegExp(`${escaped}\\s*\\{(?<body>[\\s\\S]*?)\\}`))
    ?.groups?.body ?? "";
}

function routeRuleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return routeStyles.match(new RegExp(`${escaped}\\s*\\{(?<body>[\\s\\S]*?)\\}`))
    ?.groups?.body ?? "";
}

describe("Live responsive header", () => {
  it("wraps controls against the available content width", () => {
    expect(ruleBody(".live .page-header")).toContain("flex-wrap: wrap");
    expect(ruleBody(".live .page-header-text")).toContain("flex: 1 1 280px");
    expect(ruleBody(".live .page-header-actions")).toContain("max-width: 100%");
    expect(styles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.live \.page-header-text\s*\{[^}]*flex: 0 1 auto;[^}]*width: 100%;[^}]*\}/,
    );
  });

  it("keeps the mock-aligned work grid and mobile queue bounded", () => {
    expect(styles).toMatch(/\.live-swarm\s*\{[^}]*grid-template-columns: repeat\(6/);
    expect(styles).toMatch(/\.live-tile\s*\{[^}]*min-height: 164px/);
    expect(styles).toMatch(/@media \(max-width: 1180px\)[\s\S]*?\.live-swarm\s*\{[^}]*repeat\(3/);
    expect(styles).toMatch(/@media \(max-width: 1100px\)[\s\S]*?\.live-kpis\s*\{[^}]*repeat\(2/);
    expect(styles).toMatch(/@media \(max-width: 900px\)[\s\S]*?\.live-swarm\s*\{[^}]*repeat\(2/);
    expect(styles).toMatch(/@media \(max-width: 800px\)[\s\S]*?\.live-kpis\s*\{[^}]*grid-template-columns: 1fr/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*?\.live-swarm\s*\{[^}]*grid-template-columns: 1fr/);
    expect(styles).toMatch(/\.live-queue\s*\{[^}]*min-width: 1080px/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*?\.live-queue\s*\{[^}]*min-width: 0/);
  });

  it("keeps the mock-aligned health grid responsive", () => {
    expect(mockAlignedStyles).toMatch(
      /@media \(max-width: 900px\)[\s\S]*?\.live-health\s*\{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/,
    );
    expect(mockAlignedStyles).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.live-health\s*\{[^}]*grid-template-columns: 1fr/,
    );
  });

  it("packs flow events sequentially while signaling semantic updates", () => {
    expect(panels).toContain("view.populatedTiles.map((tile)");
    expect(panels).toContain("key={tile.event_id}");
    expect(panels).not.toContain("state.tiles.map((tile, slotIndex)");
    expect(styles).toMatch(
      /\.live-tile\.is-content-updated \.live-tile-stage\s*\{[^}]*color: var\(--accent\)/,
    );
  });

  it("renders retained activity in compact selectable cards within bounded scroll", () => {
    expect(observations).toContain("export const LIVE_OBSERVATION_LIMIT = 500");
    expect(observations).not.toContain("items.slice(0,");
    expect(observations).toContain('class="live-observation-item live-work-card"');
    expect(observations).toContain('aria-haspopup="dialog"');
    expect(observations).not.toContain("activityHref");
    expect(routeRuleBody(".live .live-observation-grid")).toContain(
      "max-height: 480px",
    );
    expect(routeRuleBody(".live .live-observation-grid")).toContain(
      "overflow-y: auto",
    );
    expect(routeRuleBody(".live .live-observation-item")).toContain(
      "min-height: 112px",
    );
  });
});
