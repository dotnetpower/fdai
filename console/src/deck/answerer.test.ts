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

  test("reconstructs the ordered hand-off chain for a multi-step incident", () => {
    const snap: ViewSnapshot = {
      routeId: "agent-activity",
      routeLabel: "Agent activity",
      purpose: "Per-agent timeline.",
      glossary: composeGlossary([TERMS.correlationId, agentTerm()]),
      headline: "2 rows",
      capturedAt: "2026-07-06T11:02:00+00:00",
      facts: [],
      records: {
        activity: [
          {
            agent: "Thor",
            action_kind: "right_size",
            recorded_at: "2026-07-06T11:01:00+00:00",
            correlation_id: "corr-f",
            outcome: "shadow_pr_opened",
            detail: "Rendered the Terraform diff and opened PR #486 in shadow.",
          },
          {
            agent: "Njord",
            action_kind: "cost-anomaly.detect",
            recorded_at: "2026-07-06T11:00:00+00:00",
            correlation_id: "corr-f",
            outcome: "flagged",
            detail: "Sampled 14 days of utilization; flagged a right-size candidate.",
          },
        ],
      },
    };
    const a = answer("why did corr-f start", snap);
    // Root cause is the EARLIEST step (Njord), then the chain in time order.
    expect(a.text).toMatch(/right-size candidate/);
    expect(a.text).toMatch(/Hand-off chain:/);
    expect(a.text).toMatch(/1\. Njord cost-anomaly\.detect -> flagged/);
    expect(a.text).toMatch(/2\. Thor right_size -> shadow_pr_opened/);
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

describe("no-snapshot fallback (static universal glossary)", () => {
  test("answers 'what is HIL' with no snapshot from static glossary", () => {
    const a = answer("what is HIL?", null);
    expect(a.text.toLowerCase()).toContain("human-in-the-loop");
  });

  test("answers 'what is a correlation id' with no snapshot", () => {
    const a = answer("what is a correlation id?", null);
    expect(a.text.toLowerCase()).toContain("incident key");
  });

  test("Korean 'what is HIL' resolves with no snapshot", () => {
    const a = answer("HIL\uc774 \ubb54\uc9c0?", null);
    expect(a.text.toLowerCase()).toContain("human-in-the-loop");
  });

  test("bare non-concept query with no snapshot returns intro with follow-ups", () => {
    const a = answer("hello", null);
    expect(a.text).toMatch(/No route has published/);
    expect(a.followUps.length).toBeGreaterThan(0);
    expect(a.followUps.some((f) => /HIL/i.test(f))).toBe(true);
  });
});

describe("deck-meta (help / what can I do here)", () => {
  function liveSnap(): ViewSnapshot {
    return {
      routeId: "live",
      routeLabel: "Live cockpit",
      headline: "60 tiles",
      capturedAt: "2026-07-06T11:00:00+00:00",
      facts: [],
      records: {},
    };
  }

  test("'help' describes the deck itself and offers concept follow-ups", () => {
    const a = answer("help", liveSnap());
    expect(a.text.toLowerCase()).toContain("read-only");
    expect(a.text.toLowerCase()).toContain("screen-aware");
    expect(a.followUps.some((f) => /HIL/i.test(f))).toBe(true);
  });

  test("'?' also triggers deck help", () => {
    const a = answer("?", liveSnap());
    expect(a.text.toLowerCase()).toContain("read-only");
  });

  test("'what can I do here?' gives the per-route action hint", () => {
    const a = answer("what can I do here?", liveSnap());
    expect(a.text.toLowerCase()).toContain("live cockpit");
    expect(a.text.toLowerCase()).toContain("read-only");
  });

  test("'how do I search?' hints at header search + detail drawer", () => {
    const a = answer("how do I search?", {
      ...liveSnap(),
      routeId: "rules",
      routeLabel: "Rules",
    });
    expect(a.text.toLowerCase()).toContain("search");
  });

  test("a data question on the same page does NOT match deck-meta", () => {
    const a = answer("how many tiles need attention?", liveSnap());
    // Falls through to answerLive - answer must NOT be the deck-meta help text.
    expect(a.text.toLowerCase()).not.toContain("read-only");
  });
});

describe("catalog list resolvers (list agents / tiers / roles / verticals)", () => {
  test("'list the agents' returns the 15 pantheon members", () => {
    const a = answer("list the agents", null);
    expect(a.text).toContain("Odin");
    expect(a.text).toContain("Forseti");
    expect(a.text).toContain("Bragi");
    // All 15 named.
    for (const name of ["Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Var", "Vidar", "Bragi", "Saga", "Mimir", "Norns", "Muninn", "Njord", "Freyr", "Loki"]) {
      expect(a.text).toContain(name);
    }
  });

  test("'list the tiers' returns T0/T1/T2 with definitions", () => {
    const a = answer("list the tiers", null);
    expect(a.text).toContain("T0");
    expect(a.text).toContain("T1");
    expect(a.text).toContain("T2");
    expect(a.text).toMatch(/70-80/);
  });

  test("'list all roles' returns the 5 RBAC roles", () => {
    const a = answer("list all roles", null);
    for (const r of ["Reader", "Contributor", "Approver", "Owner", "BreakGlass"]) {
      expect(a.text).toContain(r);
    }
  });

  test("'list the verticals' returns Change/Resilience/Cost", () => {
    const a = answer("list the verticals", null);
    for (const v of ["Change Safety", "Resilience", "Cost Governance"]) {
      expect(a.text).toContain(v);
    }
  });

  test("'list the safety invariants' returns all four", () => {
    const a = answer("list the safety invariants", null);
    expect(a.text).toMatch(/stop-condition/i);
    expect(a.text).toMatch(/rollback/i);
    expect(a.text).toMatch(/blast-radius/i);
    expect(a.text).toMatch(/audit/i);
  });

  test("'list ActionType roles' returns the 5 bound roles", () => {
    const a = answer("list actiontype roles", null);
    expect(a.text).toContain("initiators");
    expect(a.text).toContain("executor");
    expect(a.text).toContain("approver");
  });

  test("'list rules' on the rules route does NOT hit the catalog list", () => {
    const snap: ViewSnapshot = {
      routeId: "rules",
      routeLabel: "Rules",
      headline: "10 rules",
      capturedAt: "2026-07-06T11:00:00+00:00",
      facts: [],
      records: {
        rules: [
          { id: "r-1", severity: "high", category: "network", source: "azure-waf" },
        ],
      },
    };
    const a = answer("list rules", snap);
    // Falls through to answerRules (not the catalog Roles list).
    expect(a.text).not.toContain("Reader");
    expect(a.text).not.toContain("Owner");
  });
});

describe("static glossary false-positive guard (round 5)", () => {
  test("'what is dark mode?' does NOT hijack to shadow-vs-enforce", () => {
    const a = answer("what is dark mode?", null);
    // Ambiguous generic terms ("mode") are excluded from the static
    // universal glossary so they don't hijack unrelated questions.
    expect(a.text.toLowerCase()).not.toContain("shadow");
    expect(a.text).toMatch(/No route has published/);
  });

  test("'what is HIL?' still resolves (high-signal term)", () => {
    const a = answer("what is HIL?", null);
    expect(a.text.toLowerCase()).toContain("human-in-the-loop");
  });

  test("'what is an agent?' does NOT hijack via generic 'agent'", () => {
    const a = answer("what is an agent?", null);
    expect(a.text).toMatch(/No route has published/);
  });

  test("'what is my tier?' does NOT hijack via generic 'tier'", () => {
    const a = answer("what is my tier?", null);
    expect(a.text).toMatch(/No route has published/);
  });
});
