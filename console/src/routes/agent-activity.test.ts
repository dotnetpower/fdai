import { describe, expect, test } from "vitest";
import type { AuditItem } from "../types";
import {
  agentOf,
  entryConversation,
  layerOf,
  lifecycleOf,
  otherEntryFields,
} from "./agent-activity";

/**
 * These tests pin the Agent-activity panel's tolerance to the two audit
 * shapes it must render:
 *
 * - the enriched dev seed (pantheon `actor`, lifecycle + conversation), and
 * - a live control-loop row (dotted service `actor`, no lifecycle, no
 *   conversation) - proving the panel attributes and degrades gracefully in
 *   production instead of collapsing every core row into one bucket.
 */

function makeItem(partial: Partial<AuditItem> & { entry: Record<string, unknown> }): AuditItem {
  return {
    seq: 1,
    event_id: "00000000-0000-0000-0000-000000000001",
    correlation_id: "corr-a",
    actor: "fdai.core.control_loop",
    action_kind: "control_loop.abstain",
    mode: "shadow",
    entry_hash: "h1",
    previous_hash: "h0",
    recorded_at: "2026-07-06T10:00:00+00:00",
    ...partial,
  };
}

describe("agentOf attribution", () => {
  test("dev seed: a pantheon actor is used verbatim", () => {
    const item = makeItem({ actor: "Odin", entry: {} });
    expect(agentOf(item)).toBe("Odin");
    expect(layerOf(agentOf(item))).toBe("planning");
  });

  test("live: producer_principal (a known agent) wins over a service actor", () => {
    const item = makeItem({
      actor: "fdai.core.control_loop",
      entry: { producer_principal: "Forseti" },
    });
    expect(agentOf(item)).toBe("Forseti");
    expect(layerOf(agentOf(item))).toBe("judgment");
  });

  test("live: a dotted service actor is humanized, not bucketed as System", () => {
    const item = makeItem({ actor: "fdai.core.rca", entry: { stage: "t0", tier: "t0" } });
    expect(agentOf(item)).toBe("core.rca");
    // Unknown producers fall back to the neutral system layer colour.
    expect(layerOf(agentOf(item))).toBe("system");
  });

  test("an empty actor with no principal falls back to System", () => {
    const item = makeItem({ actor: "", entry: {} });
    expect(agentOf(item)).toBe("System");
  });

  test("a non-agent producer_principal string is used as-is", () => {
    const item = makeItem({ actor: "", entry: { producer_principal: "custom-worker" } });
    expect(agentOf(item)).toBe("custom-worker");
  });
});

describe("lifecycleOf graceful degradation", () => {
  test("dev seed: full send -> received -> started -> finished span", () => {
    const item = makeItem({
      actor: "Odin",
      entry: {
        event_ts: "2026-07-06T09:59:59.240+00:00",
        received_at: "2026-07-06T09:59:59.280+00:00",
        started_at: "2026-07-06T09:59:59.360+00:00",
        finished_at: "2026-07-06T10:00:00+00:00",
      },
    });
    const phases = lifecycleOf(item);
    expect(phases.map((p) => p.key)).toEqual(["sent", "received", "started", "finished"]);
    // Every hop after the first carries an elapsed-gap label.
    expect(phases[0]!.gapLabel).toBeNull();
    expect(phases[1]!.gapLabel).not.toBeNull();
  });

  test("live: a row with only recorded_at still renders one Finished node", () => {
    const item = makeItem({ entry: { stage: "t0", reason: "t0_no_match" } });
    const phases = lifecycleOf(item);
    expect(phases).toHaveLength(1);
    expect(phases[0]!.key).toBe("finished");
  });
});

describe("entryConversation", () => {
  test("dev seed: valid turns are parsed", () => {
    const item = makeItem({
      actor: "Odin",
      entry: {
        conversation: [
          { from: "Odin", to: "Njord", text: "cost delta?" },
          { from: "Njord", to: "Odin", text: "+540 USD/month" },
        ],
      },
    });
    expect(entryConversation(item)).toHaveLength(2);
  });

  test("live: no conversation field yields null (section is omitted)", () => {
    const item = makeItem({ entry: { stage: "t0" } });
    expect(entryConversation(item)).toBeNull();
  });

  test("malformed turns are filtered out", () => {
    const item = makeItem({
      actor: "Odin",
      entry: { conversation: [{ from: "Odin" }, { from: "Odin", to: "Var", text: "ok" }] },
    });
    expect(entryConversation(item)).toHaveLength(1);
  });
});

describe("otherEntryFields - nothing stored is hidden", () => {
  test("live executor row: rollback / blast_radius / resource_ref are surfaced", () => {
    // Shape mirrors ShadowExecutor._write_audit (src/fdai/core/executor/executor.py).
    const item = makeItem({
      actor: "fdai.core.executor.shadow",
      action_kind: "remediate.enable-encryption",
      entry: {
        outcome: "published",
        rule_id: "azure-encryption-at-rest-001",
        resource_ref: "vm-1",
        operation: "update",
        rollback_kind: "pr_revert",
        rollback_reference: "pr#482",
        stop_condition: "encryption_at_rest=on",
        citing_rule_ids: ["azure-encryption-at-rest-001"],
        blast_radius: { scope: "subscription", count: 1, rate_per_minute: 30 },
        pr_ref: "#482",
      },
    });
    const fields = new Map(otherEntryFields(item));
    // Curated fields (outcome) are NOT repeated here.
    expect(fields.has("outcome")).toBe(false);
    // The genuinely-stored executor fields are all visible.
    expect(fields.get("rule_id")).toBe("azure-encryption-at-rest-001");
    expect(fields.get("resource_ref")).toBe("vm-1");
    expect(fields.get("rollback_kind")).toBe("pr_revert");
    expect(fields.get("citing_rule_ids")).toBe("azure-encryption-at-rest-001");
    // Nested objects render as compact key: value.
    expect(fields.get("blast_radius")).toContain("count: 1");
    expect(fields.get("pr_ref")).toBe("#482");
  });

  test("curated + lifecycle + io keys are excluded (shown by their own sections)", () => {
    const item = makeItem({
      actor: "Odin",
      entry: {
        tier: "t2",
        outcome: "resolved",
        started_at: "2026-07-06T10:00:00+00:00",
        inputs: { a: "1" },
        conversation: [{ from: "Odin", to: "Var", text: "ok" }],
        custom_field: "keep-me",
      },
    });
    const keys = otherEntryFields(item).map(([k]) => k);
    expect(keys).toEqual(["custom_field"]);
  });

  test("empty / null values are dropped", () => {
    const item = makeItem({ entry: { a: "", b: null, c: "keep" } });
    expect(otherEntryFields(item).map(([k]) => k)).toEqual(["c"]);
  });
});
