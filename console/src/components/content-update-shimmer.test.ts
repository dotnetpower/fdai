import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8");
}

describe("content update top-edge shimmer contract", () => {
  test("keeps the shared effect edge-only and motion-aware", () => {
    const styles = source("../../../ui/calm-slate-primitives.css");
    const mockRuntime = source("../../../mocks/ui/assets/calm-slate.js");
    const shimmerStart = styles.indexOf(".is-content-updated::after");
    const shimmerEnd = styles.indexOf("@keyframes calm-slate-content-update");
    const shimmer = styles.slice(shimmerStart, shimmerEnd);

    expect(shimmerStart).toBeGreaterThan(-1);
    expect(shimmer).toContain("height: 2px");
    expect(shimmer).toContain("linear-gradient(90deg");
    expect(shimmer.match(/linear-gradient/g)).toHaveLength(1);
    expect(styles).toContain(".is-content-updated::after { animation: none; }");
    expect(mockRuntime).toContain('event.animationName === "calm-slate-content-update"');
    expect(mockRuntime).toContain("}, 1500)");
  });

  test("provides a shared KPI API and wires the live card surfaces", () => {
    const ui = source("./ui.tsx");
    const roster = source("../routes/agents.roster.tsx");
    const pantheon = source("../routes/pantheon.tsx");
    const livePanels = source("../routes/live.panels.tsx");
    const liveTiles = source("../routes/live.tiles.tsx");

    expect(ui).toContain("readonly updateKey?: ContentUpdateKey");
    expect(ui).toContain("useContentUpdatePulse(semanticUpdateKey)");
    for (const cardSource of [roster, pantheon, livePanels, liveTiles]) {
      expect(cardSource).toContain("useContentUpdatePulse");
      expect(cardSource).toContain("is-content-updated");
    }

    const tileKey = liveTiles.slice(
      liveTiles.indexOf("export function liveTileUpdateKey"),
      liveTiles.indexOf("export function LiveTile"),
    );
    expect(tileKey).not.toContain("now");
  });

  test("keeps the UI guidance aligned with semantic update feedback", () => {
    const instructions = source("../../../.github/instructions/app-shape.instructions.md");
    const evidenceGuide = source("../../../docs/roadmap/interfaces/console-evidence-and-resilience.md");

    expect(instructions).toContain("shared top-edge shimmer");
    expect(instructions).toContain("skip first render");
    expect(instructions).toContain("clock-, age-, or timestamp-only updates");
    expect(evidenceGuide).toContain("complex live cards provide a semantic update key");
    expect(evidenceGuide).toContain("reduced-motion preferences disable the animation");
  });
});
