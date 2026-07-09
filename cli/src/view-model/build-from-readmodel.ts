/**
 * Compile a live read-API snapshot into the shared BLOCK IR.
 *
 * The counterpart to `build-briefing.ts`: same output type (`Block[]`), so every
 * renderer (Ink / text / Slack / Teams) works unchanged - only the data source
 * differs. Everything here is derived from what the read API actually exposes
 * (KPI counts, the HIL queue, the audit tail); nothing is fabricated.
 */

import type { Block, RiskLevel, Tone } from "./blocks.js";
import type { ReadModelSnapshot } from "../data/read-api.js";
import { t, type Locale } from "../i18n/index.js";

// Tier labels are sourced from the i18n catalog (English is the source of
// truth; a locale falls back to English). The default locale keeps the
// rendered output byte-identical to the previous hard-coded labels.
function tierMeta(
  locale: Locale,
): Record<string, { label: string; tone: Tone; order: number }> {
  return {
    t0: { label: t("tier.t0", locale), tone: "t0", order: 0 },
    t1: { label: t("tier.t1", locale), tone: "t1", order: 1 },
    t2: { label: t("tier.t2", locale), tone: "t2", order: 2 },
    abstain: { label: t("tier.abstain", locale), tone: "dim", order: 3 },
  };
}

function humanize(actionKind: string): string {
  const words = actionKind.replace(/[-_.]/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function pct(part: number, whole: number): number {
  if (whole <= 0) return 0;
  return Math.round((part / whole) * 100);
}

/** HIL items are human-escalated; infer a conservative risk for display. */
function inferRisk(actionKind: string): RiskLevel {
  const k = actionKind.toLowerCase();
  if (/(key|rotate|delete|destroy|network|break|prod|secret)/.test(k)) return "HIGH";
  if (/(scale|restart|restrict|disable|quota)/.test(k)) return "MEDIUM";
  return "LOW";
}

function decisionCard(
  h: ReadModelSnapshot["hil"][number],
  index: number,
  total: number,
  locale: Locale,
): Block {
  return {
    type: "decisionCard",
    index,
    total,
    title: humanize(h.action_kind),
    actionType: h.action_kind,
    risk: inferRisk(h.action_kind),
    chip: t("card.chip", locale),
    chipSideEffect: "approve",
    fields: [
      { label: t("card.fieldWhat", locale), value: humanize(h.action_kind) },
      { label: t("card.fieldWhy", locale), value: h.reason },
      { label: t("card.fieldRequested", locale), value: h.requested_at },
      { label: t("card.fieldCorrelation", locale), value: h.correlation_id ?? "-" },
    ],
    actions: [
      { key: "a", label: t("card.actionApprove", locale), sideEffect: "approve" },
      { key: "r", label: t("card.actionDecline", locale), sideEffect: "read" },
      { key: "w", label: t("card.actionExplain", locale), sideEffect: "read" },
    ],
    reference: h.idempotency_key,
    irreversible: false,
  };
}

export function buildFromReadModel(
  snap: ReadModelSnapshot,
  env: string,
  locale: Locale = "en",
): Block[] {
  const { kpi, hil, audit } = snap;
  const blocks: Block[] = [];

  blocks.push({
    type: "header",
    title: "fdai operator-console",
    version: "v0.0.1",
    context: t("console.context", locale, { env }),
  });

  blocks.push({
    type: "narration",
    text: t("console.connected", locale, {
      events: kpi.event_count,
      pending: kpi.hil_pending,
    }),
  });

  blocks.push({
    type: "summary",
    items: [
      { label: t("console.summaryEvents", locale), value: String(kpi.event_count) },
      { label: t("console.summaryShadow", locale), value: `${pct(kpi.shadow_share, 1)}%`, tone: "t0" },
      { label: t("console.summaryEnforce", locale), value: `${pct(kpi.enforce_share, 1)}%`, tone: "warn" },
      { label: t("console.summaryAwaiting", locale), value: String(kpi.hil_pending) },
      { label: t("console.summaryLast", locale), value: kpi.last_recorded_at ?? "-" },
    ],
  });

  const tiers = Object.entries(kpi.by_tier);
  if (tiers.length > 0) {
    const metaByTier = tierMeta(locale);
    blocks.push({
      type: "narration",
      text: t("console.mostlyNoAi", locale),
    });
    blocks.push({
      type: "statBars",
      title: t("console.trustTiers", locale),
      rows: tiers
        .map(([tier, count]) => {
          const meta = metaByTier[tier] ?? {
            label: humanize(tier),
            tone: "neutral" as Tone,
            order: 9,
          };
          return {
            label: meta.label,
            sub: `${tier.toUpperCase()} - ${count}`,
            pct: pct(count, kpi.event_count),
            tone: meta.tone,
            order: meta.order,
          };
        })
        .sort((a, b) => a.order - b.order)
        .map(({ label, sub, pct: p, tone }) => ({ label, sub, pct: p, tone })),
    });
  }

  const outcomes = Object.entries(kpi.by_outcome);
  if (outcomes.length > 0) {
    blocks.push({
      type: "statBars",
      title: t("console.outcomes", locale),
      rows: outcomes.map(([name, count]) => ({
        label: humanize(name),
        sub: String(count),
        pct: pct(count, kpi.event_count),
        tone: "t0",
      })),
    });
  }

  if (audit.length > 0) {
    blocks.push({ type: "narration", text: t("console.recentActivity", locale), tone: "dim" });
    blocks.push({
      type: "list",
      items: audit
        .slice(0, 6)
        .map((a) => `#${a.seq} ${a.action_kind} (${a.mode}) - ${a.actor}`),
      tone: "dim",
    });
  }

  if (hil.length > 0) {
    blocks.push({
      type: "narration",
      text: t(
        hil.length === 1 ? "console.hilPendingOne" : "console.hilPendingMany",
        locale,
        { count: hil.length },
      ),
    });
    hil.forEach((h, i) => blocks.push(decisionCard(h, i + 1, hil.length, locale)));
  } else {
    blocks.push({
      type: "narration",
      text: t("console.nothingPending", locale),
    });
  }

  return blocks;
}
