/**
 * Plain-text renderer: `Block[] -> string`.
 *
 * The simplest surface - no color, no deps. Handy for piping, logs, and
 * snapshot tests, and proof that a renderer is just a pure fold over the IR.
 */

import type { Block } from "../view-model/blocks.js";
import { asciiBarChart } from "./shared/ascii-chart.js";

function bar(pct: number, width = 22): string {
  const on = Math.round((pct / 100) * width);
  return "\u2588".repeat(on) + "\u2591".repeat(width - on);
}

export function renderText(blocks: readonly Block[]): string {
  const out: string[] = [];

  for (const b of blocks) {
    switch (b.type) {
      case "header":
        out.push(`${b.title}  ${b.version}`);
        out.push(b.context);
        out.push("");
        break;
      case "narration":
        out.push(`> ${b.text}`);
        out.push("");
        break;
      case "barChart": {
        out.push(b.title);
        const c = asciiBarChart(b.series, b.axisLabels);
        for (const r of c.rows) out.push(r.gutter + r.bars);
        out.push(c.axis);
        out.push(`${c.labels}   (hour, UTC)`);
        out.push(`  ${b.caption}`);
        out.push("");
        break;
      }
      case "statBars":
        out.push(b.title);
        for (const r of b.rows) {
          const label = `${r.label}${r.sub ? ` (${r.sub})` : ""}`.padEnd(30);
          out.push(`  ${label} ${bar(r.pct)} ${String(r.pct).padStart(3)}%`);
        }
        out.push("");
        break;
      case "summary":
        out.push("  " + b.items.map((i) => `${i.label} ${i.value}`).join("  |  "));
        out.push("");
        break;
      case "list":
        for (const item of b.items) out.push(`   ${b.ordered ? "-" : "\u2022"} ${item}`);
        out.push("");
        break;
      case "decisionCard": {
        out.push(
          `[${b.index}/${b.total}] ${b.title}  (${b.actionType})   ${b.risk} risk`,
        );
        out.push(`  ${b.chip}`);
        for (const f of b.fields) out.push(`  ${f.label.padEnd(11)} ${f.value}`);
        out.push(
          "  " + b.actions.map((a) => `[${a.key}] ${a.label}`).join("   "),
        );
        out.push(`  logged as ${b.reference}`);
        out.push("");
        break;
      }
      case "prompt":
        out.push(`> ${b.text}`);
        if (b.hint) out.push(`  (${b.hint})`);
        break;
      case "divider":
        out.push("-".repeat(48));
        break;
    }
  }

  return out.join("\n");
}
