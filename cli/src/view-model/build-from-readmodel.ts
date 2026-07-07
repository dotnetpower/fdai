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

const TIER_META: Record<string, { label: string; tone: Tone; order: number }> = {
  t0: { label: "Handled by fixed rules", tone: "t0", order: 0 },
  t1: { label: "Matched a past case", tone: "t1", order: 1 },
  t2: { label: "Needed AI reasoning", tone: "t2", order: 2 },
  abstain: { label: "Abstained", tone: "dim", order: 3 },
};

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
): Block {
  return {
    type: "decisionCard",
    index,
    total,
    title: humanize(h.action_kind),
    actionType: h.action_kind,
    risk: inferRisk(h.action_kind),
    chip: "needs your decision",
    chipSideEffect: "approve",
    fields: [
      { label: "What", value: humanize(h.action_kind) },
      { label: "Why", value: h.reason },
      { label: "Requested", value: h.requested_at },
      { label: "Correlation", value: h.correlation_id ?? "-" },
    ],
    actions: [
      { key: "a", label: "approve (opens a PR)", sideEffect: "approve" },
      { key: "r", label: "decline (logged, no change)", sideEffect: "read" },
      { key: "w", label: "explain", sideEffect: "read" },
    ],
    reference: h.idempotency_key,
    irreversible: false,
  };
}

export function buildFromReadModel(
  snap: ReadModelSnapshot,
  env: string,
): Block[] {
  const { kpi, hil, audit } = snap;
  const blocks: Block[] = [];

  blocks.push({
    type: "header",
    title: "fdai operator-console",
    version: "v0.0.1",
    context: `${env} - read-only - live read API`,
  });

  blocks.push({
    type: "narration",
    text:
      `Connected to the read API. ${kpi.event_count} events recorded, ` +
      `${kpi.hil_pending} awaiting your decision.`,
  });

  blocks.push({
    type: "summary",
    items: [
      { label: "events", value: String(kpi.event_count) },
      { label: "shadow", value: `${pct(kpi.shadow_share, 1)}%`, tone: "t0" },
      { label: "enforce", value: `${pct(kpi.enforce_share, 1)}%`, tone: "warn" },
      { label: "awaiting you", value: String(kpi.hil_pending) },
      { label: "last", value: kpi.last_recorded_at ?? "-" },
    ],
  });

  const tiers = Object.entries(kpi.by_tier);
  if (tiers.length > 0) {
    blocks.push({
      type: "narration",
      text: "Most of it was handled without AI reasoning:",
    });
    blocks.push({
      type: "statBars",
      title: "Trust tiers:",
      rows: tiers
        .map(([tier, count]) => {
          const meta = TIER_META[tier] ?? {
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
      title: "Outcomes so far:",
      rows: outcomes.map(([name, count]) => ({
        label: humanize(name),
        sub: String(count),
        pct: pct(count, kpi.event_count),
        tone: "t0",
      })),
    });
  }

  if (audit.length > 0) {
    blocks.push({ type: "narration", text: "Most recent activity:", tone: "dim" });
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
      text:
        `${hil.length} ${hil.length === 1 ? "item needs" : "items need"} your ` +
        `decision - escalated to a human by the risk gate.`,
    });
    hil.forEach((h, i) => blocks.push(decisionCard(h, i + 1, hil.length)));
  } else {
    blocks.push({
      type: "narration",
      text: "Nothing is awaiting your sign-off right now.",
    });
  }

  return blocks;
}
