import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { DisclosurePanel } from "./disclosure-panel";
import {
  ActionProposalCard,
  ConversationTurnItem,
  CorrelationTimeline,
  HashChainBadge,
  KnowledgeSourceCard,
  TimelineStepList,
} from "./domain-primitives";
import { FilterToolbar, SegmentedControl } from "./form-controls";
import { LiveDecisionTicker, SignalRail, SparkMetricCard } from "./overview-telemetry";
import { PromotionReadinessBadge, StatusBadge } from "./status-badge";

const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

function read(relPath: string): string {
  return readFileSync(`${REPO_ROOT}${relPath}`, "utf8");
}

describe("Wave 0 shared UI invariants", () => {
  test("enforces >= 12px typography floor across tokens, primitives, styles, and Wave 0 CSS", () => {
    const files = [
      "ui/calm-slate-tokens.css",
      "console/src/styles.css",
      "console/src/components/wave0-primitives.css",
    ];
    for (const file of files) {
      const css = read(file);
      const pxMatches = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px\b/g)]
        .filter((m) => Number.parseFloat(m[1] ?? "12") < 12)
        .map((m) => `${file}: ${m[0]}`);
      const remMatches = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)rem\b/g)]
        .filter((m) => Number.parseFloat(m[1] ?? "0.75") < 0.75)
        .map((m) => `${file}: ${m[0]}`);
      expect(pxMatches).toEqual([]);
      expect(remMatches).toEqual([]);
    }
    expect(read("ui/calm-slate-tokens.css")).toContain("--cs-type-caption-size: 12px;");
  });

  test("prohibits colored left/top accent bars and enforces custom select chevron and chat contrast", () => {
    const wave0Css = read("console/src/components/wave0-primitives.css");
    const primitivesCss = read("ui/calm-slate-primitives.css");
    const stylesCss = read("console/src/styles.css");

    expect(wave0Css).not.toMatch(/border-(left|top):\s*[2-9]px\s+solid/);
    expect(primitivesCss).toContain("appearance: none;");
    expect(primitivesCss).toContain("padding-right: 38px;");
    expect(primitivesCss).toContain("background-image: var(--cs-select-chevron);");
    expect(wave0Css).toContain("padding: 0 38px 0 12px;");
    expect(wave0Css).toContain("background-image: var(--cs-select-chevron);");

    // User questions carry neutral fill; agent replies stay transparent.
    expect(primitivesCss).toMatch(/\.cs-deck-user-bubble\s*\{[^}]*background:\s*var\(--cs-shade\)/s);
    expect(primitivesCss).toMatch(/\.cs-deck-agent-turn\s*\{[^}]*background:\s*transparent/s);
    expect(stylesCss).toMatch(/\.wf-msg-bot \.wf-msg-body\s*\{[^}]*background:\s*transparent/s);
    expect(stylesCss).toMatch(/\.wf-msg-op \.wf-msg-body\s*\{[^}]*background:\s*var\(--cs-shade\)/s);
    expect(wave0Css).toMatch(/\.cs-conv-turn--operator \.cs-conv-body\s*\{[^}]*background:\s*var\(--cs-shade\)/s);
    expect(wave0Css).toMatch(/\.cs-conv-turn--assistant \.cs-conv-body\s*\{[^}]*background:\s*transparent/s);
  });
});

describe("Wave 0 shared components", () => {
  test("StatusBadge and PromotionReadinessBadge render 5px badge semantics with localized dots", () => {
    const badge = JSON.stringify(StatusBadge({ tone: "live", label: "Active" }));
    expect(badge).toContain("cs-status-badge--live");
    expect(badge).toContain("cs-status-dot");
    expect(badge).toContain("Active");

    const promo = JSON.stringify(PromotionReadinessBadge({ stage: "enforce" }));
    expect(promo).toContain("Enforce");
    expect(promo).toContain("live");
  });

  test("SparkMetricCard never substitutes unmeasured state with zero", () => {
    const unmeasured = JSON.stringify(
      SparkMetricCard({
        label: "Observed resources",
        value: 0,
        evidenceState: "unavailable",
        unmeasuredLabel: "Unavailable",
        spark: { kind: "area", values: [1, 2, 3], ariaLabel: "trend" },
      }),
    );
    expect(unmeasured).toContain("cs-spark-unmeasured");
    expect(unmeasured).toContain("Unavailable");
    expect(unmeasured).toContain('"children":"-"');
    expect(unmeasured).not.toContain("<svg");

    const measured = JSON.stringify(
      SparkMetricCard({
        label: "Detected risks",
        value: 14,
        evidenceState: "measured",
        spark: { kind: "dual-bar", values: [2, 3, 4], secondaryValues: [1, 1, 2], ariaLabel: "risks" },
      }),
    );
    expect(measured).toContain("cs-spark-svg");
    expect(measured).toContain("14");
  });

  test("SegmentedControl and FilterToolbar expose accessible roles and active filter counts", () => {
    const seg = JSON.stringify(
      SegmentedControl({
        ariaLabel: "View mode",
        role: "tablist",
        value: "scatter",
        onChange: () => {},
        options: [
          { value: "scatter", label: "Scatter", count: 12 },
          { value: "stacked", label: "Stacked" },
        ],
      }),
    );
    expect(seg).toContain('"role":"tablist"');
    expect(seg).toContain('"role":"tab"');
    expect(seg).toContain('"aria-selected":"true"');

    const bar = JSON.stringify(
      FilterToolbar({
        activeFilterCount: 2,
        onReset: () => {},
        resetLabel: "Reset",
        children: "controls",
      }),
    );
    expect(bar).toContain('"role":"search"');
    expect(bar).toContain("Reset");
    expect(bar).toContain("2");
  });

  test("DisclosurePanel, SignalRail, LiveDecisionTicker, and domain primitives preserve contracts", () => {
    const disclosure = JSON.stringify(
      DisclosurePanel({ title: "Technical provenance", summaryMeta: "2 items", children: "body" }),
    );
    expect(disclosure).toContain('"type":"details"');
    expect(disclosure).toContain("Technical provenance");

    const rail = JSON.stringify(
      SignalRail({
        caption: "Signals",
        items: [{ id: "1", category: "sec", label: "Key rotation overdue" }],
      }),
    );
    expect(rail).toContain("Key rotation overdue");

    const ticker = JSON.stringify(
      LiveDecisionTicker({
        timestamp: "12:04:01",
        category: "auto",
        categoryLabel: "Auto",
        message: "Suppressed transient probe spike",
      }),
    );
    expect(ticker).toContain('"aria-live":"polite"');
    expect(ticker).toContain("Suppressed transient probe spike");

    const proposal = JSON.stringify(
      ActionProposalCard({
        title: "Scale worker pool",
        statusTone: "human",
        statusLabel: "Pending",
        authorityLabel: "Request-only",
        authorityNotice: "Approval required in HIL queue",
        evidenceFacts: [{ label: "Target", value: "aks-prod-01" }],
      }),
    );
    expect(proposal).toContain("cs-proposal-readonly");
    expect(proposal).toContain("cs-proposal-boundary");
    expect(proposal).toContain("Approval required in HIL queue");

    const hash = JSON.stringify(
      HashChainBadge({ status: "verified", entryHash: "abcdef1234567890abcdef1234567890" }),
    );
    expect(hash).toContain("abcdef123456...7890");

    const timeline = JSON.stringify(
      CorrelationTimeline({
        variant: "phases",
        ariaLabel: "Audit phases",
        items: [{ id: "intent", title: "Intent", stateLabel: "Done", tone: "live", current: true }],
      }),
    );
    expect(timeline).toContain('"aria-current":"step"');

    const knowledge = JSON.stringify(
      KnowledgeSourceCard({ title: "GitHub Runbooks", statusTone: "live", statusLabel: "Synced" }),
    );
    expect(knowledge).toContain("cs-knowledge-panel");

    const steps = JSON.stringify(
      TimelineStepList({
        ariaLabel: "Trajectory",
        entries: [{
          id: "s1",
          timestamp: "12:00:00",
          actor: "Heimdall",
          summary: "Observed scale event",
          statusTone: "live",
          statusLabel: "Observed",
        }],
      }),
    );
    expect(steps).toContain("Heimdall");

    const opTurn = JSON.stringify(
      ConversationTurnItem({ role: "operator", authorLabel: "Operator", content: "Check status" }),
    );
    const agentTurn = JSON.stringify(
      ConversationTurnItem({ role: "assistant", authorLabel: "Bragi", content: "All healthy" }),
    );
    expect(opTurn).toContain("cs-conv-turn--operator");
    expect(agentTurn).toContain("cs-conv-turn--assistant");
  });
});
