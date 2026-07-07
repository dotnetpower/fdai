/**
 * Unit tests for the renderers.
 *
 * Each renderer is a pure function `Block[] -> format`; the same IR must map to
 * a valid CLI/text/Slack/Teams shape. Proves "one content, many renderers".
 */

import { describe, expect, it } from "vitest";

import { buildBriefing } from "../src/view-model/build-briefing.js";
import { sampleBriefing } from "../src/data/sample-briefing.js";
import { renderText } from "../src/renderers/text.js";
import { renderSlack } from "../src/renderers/slack.js";
import { renderTeams } from "../src/renderers/teams.js";
import { asciiBarChart } from "../src/renderers/shared/ascii-chart.js";
import { sparkline } from "../src/renderers/shared/sparkline.js";

const blocks = buildBriefing(sampleBriefing("needs-me"));

describe("renderText", () => {
  it("produces a plain string with the header and cards", () => {
    const out = renderText(blocks);
    expect(out).toContain("fdai operator-console");
    expect(out).toContain("[1/3]");
    expect(out).toContain("MEDIUM risk");
  });

  it("keeps a gap between an 11-char label and its value", () => {
    const out = renderText(blocks);
    expect(out).not.toMatch(/Confidence\S/); // never glued
  });
});

describe("renderSlack", () => {
  it("emits Block Kit blocks including a header and actions", () => {
    const msg = renderSlack(blocks);
    expect(Array.isArray(msg.blocks)).toBe(true);
    const kinds = msg.blocks.map((b) => b.type);
    expect(kinds).toContain("header");
    expect(kinds).toContain("actions");
  });

  it("marks the approve button primary and break-glass danger", () => {
    const msg = renderSlack(blocks);
    const actionRows = msg.blocks.filter((b) => b.type === "actions");
    const styles = actionRows
      .flatMap((row) => (row.elements as Array<Record<string, unknown>>) ?? [])
      .map((el) => el.style)
      .filter(Boolean);
    expect(styles).toContain("primary");
    expect(styles).toContain("danger");
  });
});

describe("renderTeams", () => {
  it("emits a valid Adaptive Card with a body", () => {
    const card = renderTeams(blocks);
    expect(card.type).toBe("AdaptiveCard");
    expect(card.version).toBe("1.5");
    expect(card.body.length).toBeGreaterThan(0);
  });

  it("wraps each HIL item in a styled Container with a FactSet", () => {
    const card = renderTeams(blocks);
    const containers = card.body.filter((b) => b.type === "Container");
    expect(containers.length).toBe(3);
    const first = containers[0] as { items: Array<{ type: string }> };
    expect(first.items.some((i) => i.type === "FactSet")).toBe(true);
  });
});

describe("shared chart helpers", () => {
  it("aligns axis labels under their columns (gutter width 7)", () => {
    const chart = asciiBarChart([1, 2, 3, 4], [{ at: 0, text: "00" }], 4);
    // labels line: 7-space gutter, then "00" at column 0
    expect(chart.labels.startsWith("       00")).toBe(true);
    // bar rows and the axis share the same column count
    expect(chart.rows[0].bars.length).toBe(4);
    expect(chart.axis.length).toBe(7 + 4);
  });

  it("sparkline is one glyph per sample within the block ramp", () => {
    const s = sparkline([0, 5, 10]);
    expect([...s]).toHaveLength(3);
    expect(s.at(-1)).toBe("\u2588"); // max -> full block
  });
});
