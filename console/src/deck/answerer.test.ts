import { describe, expect, test } from "vitest";
import { answer } from "./answerer";
import type { ViewSnapshot } from "./context";
import { TERMS, agentTerm, composeGlossary } from "./glossary";

/**
 * These tests pin the two questions the console deck used to fail on - "what
 * is corr-j" (a value chip) and "why did this start" (a causal question) - and
 * prove the answerer resolves them from the screen's own declared glossary +
 * records on ANY route, including screens with no bespoke enhancer. This is
 * the screen-agnostic contract: a screen becomes explainable by declaring
 * purpose/glossary and keeping causal fields in its records, not by adding a
 * per-route branch.
 */

const RESTORE_DETAIL =
  "A point-in-time restore of prod-pg-01 was proposed after a suspected " +
  "logical corruption; it is data-plane and irreversible, so it parks in the " +
  "HIL queue for a human approver rather than auto-executing.";

/** An Agent-activity-shaped snapshot carrying the seed corr-j incident. */
function agentActivitySnapshot(): ViewSnapshot {
  return {
    routeId: "agent-activity",
    routeLabel: "Agent activity",
    purpose: "Per-agent timeline reconstructed from the audit log.",
    glossary: composeGlossary([
      TERMS.correlationId,
      TERMS.waterfall,
      TERMS.tier,
      TERMS.mode,
      agentTerm(),
    ]),
    headline: "5 audit row(s) across 3 agent(s)",
    capturedAt: "2026-07-06T11:12:30+00:00",
    facts: [{ key: "rows", value: 5, group: "page" }],
    records: {
      activity: [
        {
          agent: "Njord",
          action_kind: "cost-anomaly.detect",
          mode: "shadow",
          recorded_at: "2026-07-06T11:00:00+00:00",
          correlation_id: "corr-f",
          event_id: "00000000-0000-0000-0000-000000000001",
          tier: "t0",
          outcome: "flagged",
          summary: "Cost anomaly on vmss-web",
          detail: "Sampled 14 days of utilization; flagged a right-size candidate.",
          reason: "-",
        },
        {
          agent: "Var",
          action_kind: "restore-from-backup",
          mode: "shadow",
          recorded_at: "2026-07-06T11:12:00+00:00",
          correlation_id: "corr-j",
          event_id: "00000000-0000-0000-0000-000000000010",
          tier: "t2",
          outcome: "awaiting_approval",
          summary: "High-risk restore queued for a human approver",
          detail: RESTORE_DETAIL,
          reason: "-",
        },
      ],
    },
  };
}

describe("value-chip resolution (what is corr-j)", () => {
  test("names the term and summarises the incident it identifies", () => {
    const a = answer("what is corr-j", agentActivitySnapshot());
    expect(a.text).toMatch(/correlation id/i);
    expect(a.text).toContain("corr-j");
    // It should also surface the recorded 'why' for that incident.
    expect(a.text).toMatch(/logical corruption/);
  });

  test("Korean phrasing resolves the same chip", () => {
    const a = answer("corr-j\uac00 \ubb50\uc57c", agentActivitySnapshot());
    expect(a.text).toMatch(/correlation id/i);
    expect(a.text).toContain("corr-j");
  });
});

describe("causal resolution (why did this start)", () => {
  test("quotes the recorded detail narrative for the newest incident", () => {
    const a = answer("why did this start", agentActivitySnapshot());
    expect(a.text).toMatch(/logical corruption/);
    expect(a.text).toMatch(/corr-j/);
  });

  test("a quoted correlation scopes the causal answer to that incident", () => {
    const a = answer("why did corr-f start", agentActivitySnapshot());
    expect(a.text).toMatch(/right-size candidate/);
    expect(a.text).toContain("corr-f");
  });

  test("Korean causal phrasing works", () => {
    const a = answer("\uc65c \uc774\uac8c \uc2dc\uc791\ub410\uc5b4", agentActivitySnapshot());
    expect(a.text).toMatch(/logical corruption/);
  });
});

describe("term definition (what is X)", () => {
  test("explains a declared term from its plain text", () => {
    const a = answer("what is the waterfall", agentActivitySnapshot());
    expect(a.text).toMatch(/hand-off|timeline|incident/i);
  });
});

describe("screen-agnostic (no bespoke enhancer)", () => {
  /** A minimal snapshot for a route with no per-route answerer. */
  function pantheonSnapshot(): ViewSnapshot {
    return {
      routeId: "pantheon",
      routeLabel: "Agent pantheon",
      purpose: "The 15 fixed agents and how they hand work off.",
      glossary: composeGlossary([TERMS.tier, TERMS.hil, agentTerm()]),
      headline: "15 agents",
      capturedAt: "2026-07-06T11:00:00+00:00",
      facts: [{ key: "agents", value: 15, group: "page" }],
      records: {},
    };
  }

  test("answers a term question on a screen the answerer has no branch for", () => {
    const a = answer("what is a tier", pantheonSnapshot());
    expect(a.text).toMatch(/trust tier/i);
  });

  test("falls back to headline + purpose + offered terms, never a shrug", () => {
    const a = answer("tell me something", pantheonSnapshot());
    expect(a.text).not.toMatch(/do not have a specific answerer/);
    expect(a.text).toContain("Agent pantheon");
  });
});
