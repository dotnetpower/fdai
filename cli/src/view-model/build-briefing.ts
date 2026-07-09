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
import { t, type Locale } from "../i18n/index.js";

function tierTone(tier: "T0" | "T1" | "T2"): Tone {
  return tier === "T0" ? "t0" : tier === "T1" ? "t1" : "t2";
}

function toDecisionCard(
  item: HilItem,
  index: number,
  total: number,
  locale: Locale,
): Block {
  const safety = item.irreversible
    ? t("card.cantUndo", locale, { value: item.safety })
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
      { label: t("card.fieldWhat", locale), value: item.change },
      { label: t("card.fieldWhy", locale), value: item.why },
      { label: t("card.fieldConfidence", locale), value: `${item.basis} (${item.basisTech})` },
      { label: t("card.fieldSafety", locale), value: safety },
      { label: t("card.fieldHow", locale), value: item.how },
      { label: t("card.fieldApproval", locale), value: item.who },
      { label: t("card.fieldChecked", locale), value: item.check },
    ],
    actions: [
      { key: "a", label: t("card.actionApprove", locale), sideEffect: "approve" },
      { key: "r", label: t("card.actionDecline", locale), sideEffect: "read" },
      { key: "w", label: t("card.actionExplain", locale), sideEffect: "read" },
    ],
    reference: item.reference,
    irreversible: item.irreversible,
  };
}

export function buildBriefing(
  p: BriefingPayload,
  locale: Locale = "en",
): Block[] {
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
    text: t("briefing.greeting", locale, {
      operator: p.operator,
      window: p.windowLabel,
    }),
  });

  blocks.push({
    type: "barChart",
    title: t("briefing.busyTitle", locale),
    series: p.throughput,
    unit: t("briefing.busyUnit", locale),
    caption: t("briefing.busyCaption", locale, {
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
    title: t("briefing.tiersTitle", locale),
    rows: p.tiers.map((t) => ({
      label: t.name,
      sub: t.tier,
      pct: t.pct,
      tone: tierTone(t.tier),
    })),
  });

  blocks.push({
    type: "narration",
    text: t("briefing.autoNarration", locale, {
      auto: p.autoResolved,
      events: p.events,
      shadow: p.shadowCandidates,
    }),
  });

  blocks.push({
    type: "summary",
    items: [
      { label: t("briefing.sumEvents", locale), value: String(p.events) },
      { label: t("briefing.sumAutoResolved", locale), value: String(p.autoResolved), tone: "good" },
      { label: t("briefing.sumRolledBack", locale), value: String(p.rollbacks), tone: "good" },
      { label: t("briefing.sumPausedRules", locale), value: String(p.overridesActive) },
      { label: t("briefing.sumAudit", locale), value: t("briefing.auditComplete", locale), tone: "t0" },
    ],
  });

  if (p.hil.length > 0) {
    const n = p.hil.length;
    const words = ["zero", "One", "Two", "Three", "Four", "Five", "Six"];
    blocks.push({
      type: "narration",
      text:
        n === 1
          ? t("briefing.hilOne", locale)
          : t("briefing.hilMany", locale, { word: words[n] ?? String(n), count: n }),
    });
    p.hil.forEach((item, i) =>
      blocks.push(toDecisionCard(item, i + 1, p.hil.length, locale)),
    );
    blocks.push({
      type: "prompt",
      text: t("briefing.openCard", locale, { max: p.hil.length }),
      hint: t("briefing.promptHintMock", locale),
    });
  } else {
    blocks.push({
      type: "narration",
      text: t("briefing.nothingSignoff", locale),
    });
    blocks.push({
      type: "narration",
      text: t("briefing.lookInto", locale),
      tone: "dim",
    });
    blocks.push({ type: "list", items: p.suggestions, tone: "t1" });
    blocks.push({
      type: "prompt",
      text: t("briefing.typeQuestion", locale),
      hint: t("briefing.typeQuestionHint", locale),
    });
  }

  return blocks;
}
