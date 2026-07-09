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
import { t } from "../i18n/index.js";

function tierTone(tier: "T0" | "T1" | "T2"): Tone {
  return tier === "T0" ? "t0" : tier === "T1" ? "t1" : "t2";
}

function toDecisionCard(item: HilItem, index: number, total: number): Block {
  const safety = item.irreversible
    ? t("card.cantUndo", "en", { value: item.safety })
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
      { label: t("card.fieldWhat"), value: item.change },
      { label: t("card.fieldWhy"), value: item.why },
      { label: t("card.fieldConfidence"), value: `${item.basis} (${item.basisTech})` },
      { label: t("card.fieldSafety"), value: safety },
      { label: t("card.fieldHow"), value: item.how },
      { label: t("card.fieldApproval"), value: item.who },
      { label: t("card.fieldChecked"), value: item.check },
    ],
    actions: [
      { key: "a", label: t("card.actionApprove"), sideEffect: "approve" },
      { key: "r", label: t("card.actionDecline"), sideEffect: "read" },
      { key: "w", label: t("card.actionExplain"), sideEffect: "read" },
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
    text: t("briefing.greeting", "en", {
      operator: p.operator,
      window: p.windowLabel,
    }),
  });

  blocks.push({
    type: "barChart",
    title: t("briefing.busyTitle"),
    series: p.throughput,
    unit: t("briefing.busyUnit"),
    caption: t("briefing.busyCaption", "en", {
      peak: p.peakHourLabel,
      count: peak,
    }),
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
    title: t("briefing.tiersTitle"),
    rows: p.tiers.map((t) => ({
      label: t.name,
      sub: t.tier,
      pct: t.pct,
      tone: tierTone(t.tier),
    })),
  });

  blocks.push({
    type: "narration",
    text: t("briefing.autoNarration", "en", {
      auto: p.autoResolved,
      events: p.events,
      shadow: p.shadowCandidates,
    }),
  });

  blocks.push({
    type: "summary",
    items: [
      { label: t("briefing.sumEvents"), value: String(p.events) },
      { label: t("briefing.sumAutoResolved"), value: String(p.autoResolved), tone: "good" },
      { label: t("briefing.sumRolledBack"), value: String(p.rollbacks), tone: "good" },
      { label: t("briefing.sumPausedRules"), value: String(p.overridesActive) },
      { label: t("briefing.sumAudit"), value: t("briefing.auditComplete"), tone: "t0" },
    ],
  });

  if (p.hil.length > 0) {
    const n = p.hil.length;
    const words = ["zero", "One", "Two", "Three", "Four", "Five", "Six"];
    blocks.push({
      type: "narration",
      text:
        n === 1
          ? t("briefing.hilOne")
          : t("briefing.hilMany", "en", { word: words[n] ?? String(n), count: n }),
    });
    p.hil.forEach((item, i) =>
      blocks.push(toDecisionCard(item, i + 1, p.hil.length)),
    );
    blocks.push({
      type: "prompt",
      text: t("briefing.openCard", "en", { max: p.hil.length }),
      hint: t("briefing.promptHintMock"),
    });
  } else {
    blocks.push({
      type: "narration",
      text: t("briefing.nothingSignoff"),
    });
    blocks.push({
      type: "narration",
      text: t("briefing.lookInto"),
      tone: "dim",
    });
    blocks.push({ type: "list", items: p.suggestions, tone: "t1" });
    blocks.push({
      type: "prompt",
      text: t("briefing.typeQuestion"),
      hint: t("briefing.typeQuestionHint"),
    });
  }

  return blocks;
}
