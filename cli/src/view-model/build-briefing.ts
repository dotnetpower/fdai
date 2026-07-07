/**
 * The single compiler: briefing CONTRACT -> surface-neutral BLOCK IR.
 *
 * This is where "what the console says" is decided, exactly once. Every surface
 * renders the `Block[]` this returns, so CLI / Slack / Teams / text always show
 * the same content - only the rendering differs. Keep all wording and ordering
 * here; keep all colors and layout in the renderers.
 */

import type { Block, Tone } from "./blocks.js";
import type { BriefingPayload, HilItem } from "./contract.js";

function tierTone(tier: "T0" | "T1" | "T2"): Tone {
  return tier === "T0" ? "t0" : tier === "T1" ? "t1" : "t2";
}

function countPhrase(n: number): string {
  const words = ["zero", "One", "Two", "Three", "Four", "Five", "Six"];
  const word = words[n] ?? String(n);
  return n === 1 ? "One thing needs" : `${word} things need`;
}

function toDecisionCard(item: HilItem, index: number, total: number): Block {
  const safety = item.irreversible
    ? `${item.safety} (can't be undone)`
    : item.safety;
  return {
    type: "decisionCard",
    index,
    total,
    title: item.title,
    actionType: item.actionType,
    risk: item.risk,
    chip: item.chip,
    chipSideEffect: item.chipSideEffect,
    fields: [
      { label: "What", value: item.change },
      { label: "Why", value: item.why },
      { label: "Confidence", value: `${item.basis} (${item.basisTech})` },
      { label: "Safety", value: safety },
      { label: "How", value: item.how },
      { label: "Approval", value: item.who },
      { label: "Checked", value: item.check },
    ],
    actions: [
      { key: "a", label: "approve (opens a PR)", sideEffect: "approve" },
      { key: "r", label: "decline (logged, no change)", sideEffect: "read" },
      { key: "w", label: "explain", sideEffect: "read" },
    ],
    reference: item.reference,
    irreversible: item.irreversible,
  };
}

export function buildBriefing(p: BriefingPayload): Block[] {
  const blocks: Block[] = [];
  const peak = Math.max(...p.throughput);

  blocks.push({
    type: "header",
    title: "fdai operator-console",
    version: "v0.0.1",
    context: `${p.env} - read-only - ${p.clock}`,
  });

  blocks.push({
    type: "narration",
    text:
      `Good morning, ${p.operator}. Everything's running normally. ` +
      `Here's what happened over ${p.windowLabel}.`,
  });

  blocks.push({
    type: "barChart",
    title: "How busy things were - events handled every 5 minutes:",
    series: p.throughput,
    unit: "events / 5 min",
    caption: `busiest around ${p.peakHourLabel} - about ${peak} events / 5 min at peak`,
    axisLabels: [
      { at: 0, text: "00" },
      { at: 6, text: "06" },
      { at: 12, text: "12" },
      { at: 18, text: "18" },
    ],
    tone: "t0",
  });

  blocks.push({
    type: "statBars",
    title: "Most of it was handled by fixed rules - no AI needed:",
    rows: p.tiers.map((t) => ({
      label: t.name,
      sub: t.tier,
      pct: t.pct,
      tone: tierTone(t.tier),
    })),
  });

  blocks.push({
    type: "narration",
    text:
      `It handled ${p.autoResolved} of ${p.events} on its own. ` +
      `Nothing had to be undone. ${p.shadowCandidates} new rules are being ` +
      `trialed safely - watching only, not acting yet.`,
  });

  blocks.push({
    type: "summary",
    items: [
      { label: "events", value: String(p.events) },
      { label: "auto-resolved", value: String(p.autoResolved), tone: "good" },
      { label: "rolled back", value: String(p.rollbacks), tone: "good" },
      { label: "paused rules", value: String(p.overridesActive) },
      { label: "audit", value: "complete", tone: "t0" },
    ],
  });

  if (p.hil.length > 0) {
    blocks.push({
      type: "narration",
      text:
        `${countPhrase(p.hil.length)} your decision - ` +
        `they are above the risk level I act on by myself.`,
    });
    p.hil.forEach((item, i) =>
      blocks.push(toDecisionCard(item, i + 1, p.hil.length)),
    );
    blocks.push({
      type: "prompt",
      text: `open a card (1-${p.hil.length}), or type a question`,
      hint: "keys are illustrative - this is a design mock",
    });
  } else {
    blocks.push({
      type: "narration",
      text:
        "Nothing needs your sign-off right now. Everything is handled, " +
        "and every change can be undone.",
    });
    blocks.push({
      type: "narration",
      text: "Anything you want to look into? For example:",
      tone: "dim",
    });
    blocks.push({ type: "list", items: p.suggestions, tone: "t1" });
    blocks.push({
      type: "prompt",
      text: "type a question",
      hint: "I only look things up unless you ask me to act - and I'll confirm before anything changes",
    });
  }

  return blocks;
}
