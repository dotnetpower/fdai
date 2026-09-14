import { describe, expect, test } from "vitest";
import type { AuditItem } from "../types";
import {
  activityPresentationState,
  activityProvenanceCounts,
  agentActivityObservationSource,
  agentActivityExplanations,
  agentOf,
  auditProvenanceOf,
  entryConversation,
  isAgentActivitySelectionValid,
  layerOf,
  lifecycleOf,
  matchingLiveIncident,
  otherEntryFields,
  selectedAgentAuditEmptyBody,
  shouldRefreshAgentActivity,
  OPERATIONAL_ACTIVITY_LIMIT,
} from "./agent-activity";
import type { AgentNode, Incident } from "./agents.model";

describe("agent activity deep-link selection", () => {
  test("accepts fixed agents and grounded service producers only", () => {
    expect(isAgentActivitySelectionValid("Forseti", [])).toBe(true);
    expect(isAgentActivitySelectionValid("custom-worker", ["custom-worker"])).toBe(true);
    expect(isAgentActivitySelectionValid("not-a-real-agent", ["Forseti"])).toBe(false);
    expect(isAgentActivitySelectionValid(null, [])).toBe(true);
  });

  test("publishes selected-agent incident relationships through the common envelope", () => {
    const incident: Incident = {
      correlationId: "corr-1",
      ticketId: "ticket-1",
      title: "Memory pressure",
      severity: "high",
      status: "open",
      involved: ["Heimdall"],
      rca: null,
      turns: [],
      updatedAt: "2026-07-20T00:00:00Z",
    };

    expect(agentActivityExplanations("Heimdall", [incident])).toMatchObject({
      selection: { entity_kind: "Agent", entity_id: "Heimdall" },
      relationships: [{
        link: "participates_in",
        from: "Heimdall",
        neighbor: "corr-1",
      }],
      provenance: { authority: "agent_runtime_and_audit" },
    });
  });

  test("keeps live Huginn evidence visible when the durable audit timeline is empty", () => {
    const huginn: AgentNode = {
      name: "Huginn",
      layer: "sensing",
      state: "watching",
      detail: "Runtime agent initialized",
      correlationId: null,
      since: "2026-07-20T00:00:00Z",
      observed: true,
    };

    expect(activityPresentationState({
      totalAuditCount: 0,
      visibleAuditCount: 0,
      selected: "Huginn",
      selectionValid: true,
      hasSelectedNode: true,
    })).toEqual({
      showLiveSummary: true,
      emptyKind: "selected-audit",
    });
    expect(selectedAgentAuditEmptyBody(huginn, "runtime-observed")).toContain(
      "Huginn is watching",
    );
    expect(selectedAgentAuditEmptyBody(huginn, "runtime-observed")).toContain(
      "There is no active correlation or incident",
    );
  });
});

describe("agent activity durable refresh", () => {
  test("requests the full bounded operational activity page", () => {
    expect(OPERATIONAL_ACTIVITY_LIMIT).toBe(500);
  });

  test("does not reload durable projections for stream frames or opens", () => {
    expect(shouldRefreshAgentActivity("stream-frame")).toBe(false);
    expect(shouldRefreshAgentActivity("stream-open")).toBe(false);
  });

  test("reloads only for initial, operator, and gap recovery reads", () => {
    expect(shouldRefreshAgentActivity("initial")).toBe(true);
    expect(shouldRefreshAgentActivity("operator")).toBe(true);
    expect(shouldRefreshAgentActivity("gap")).toBe(true);
  });

  test("presents a durable operational projection as runtime-observed evidence", () => {
    expect(agentActivityObservationSource(
      "durable-operational-projection",
      "unknown",
    )).toBe("runtime-observed");
    expect(agentActivityObservationSource(
      "optional-source-unavailable",
      "replay",
    )).toBe("replay");
    expect(agentActivityObservationSource(
      "durable-operational-projection",
      "synthetic-dev",
    )).toBe("mixed");
    expect(agentActivityObservationSource(
      "durable-operational-projection",
      "mixed",
    )).toBe("mixed");
  });
});

describe("live incident evidence matching", () => {
  test("does not treat a correlation id alone as an Incident", () => {
    expect(matchingLiveIncident("corr-only", [])).toBeNull();
    expect(matchingLiveIncident(null, [])).toBeNull();
  });
});

describe("agent activity evidence provenance", () => {
  test("separates local seed rows from operational audit", () => {
    const sample = makeItem({
      actor: "Heimdall",
      entry: {
        fixture_source: "operator-api-dev-seed",
        observation_source: "synthetic-dev",
      },
    });
    const operational = makeItem({ actor: "Heimdall", entry: {} });

    expect(auditProvenanceOf(sample)).toBe("sample");
    expect(auditProvenanceOf(operational)).toBe("operational");
    expect(activityProvenanceCounts([sample, operational])).toEqual({
      operational: 1,
      sample: 1,
    });
  });
});

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

  test("live: an RCA service row is attributed to Forseti", () => {
    const item = makeItem({ actor: "fdai.core.rca", entry: { stage: "t0", tier: "t0" } });
    expect(agentOf(item)).toBe("Forseti");
    expect(layerOf(agentOf(item))).toBe("judgment");
  });

  test("live: trust routing and HIL rows map to their canonical owners", () => {
    const routed = makeItem({ entry: { stage: "trust_router" } });
    const hil = makeItem({
      actor: "fdai.core.hil_resume",
      action_kind: "hil.requested",
      entry: {},
    });
    expect(agentOf(routed)).toBe("Heimdall");
    expect(agentOf(hil)).toBe("Var");
  });

  test("an empty actor with no principal falls back to System", () => {
    const item = makeItem({ actor: "", entry: {} });
    expect(agentOf(item)).toBe("System");
  });

  test("the bare FDAI runtime actor is not presented as a custom agent", () => {
    const item = makeItem({ actor: "fdai", entry: {} });
    expect(agentOf(item)).toBe("System");
    expect(agentOf(makeItem({
      actor: "fdai.system",
      action_kind: "system.housekeeping",
      entry: {},
    }))).toBe("System");
  });

  test.each([
    ["inventory", "Huginn"],
    ["activity-log", "Huginn"],
    ["metrics", "Heimdall"],
    ["cost", "Njord"],
    ["recovery", "Vidar"],
  ])("attributes observation campaign %s transitions to %s", (domain, owner) => {
    const item = makeItem({
      actor: "fdai.system",
      action_kind: "observation-campaign.source-transition",
      entry: { domain, source_id: domain },
    });

    expect(agentOf(item)).toBe(owner);
  });

  test("prefers authenticated and accountable Pantheon identities", () => {
    expect(agentOf(makeItem({
      actor: "fdai.measurement",
      action_kind: "measurement.control_loop.v1",
      entry: { producer_principal: "Forseti", owner_agent: "Heimdall" },
    }))).toBe("Forseti");
    expect(agentOf(makeItem({
      actor: "fdai.system",
      action_kind: "observation-campaign.source-transition",
      entry: { owner_agent: "Freyr", domain: "metrics", source_id: "capacity-metrics" },
    }))).toBe("Freyr");
  });

  test("does not infer a legacy owner for a custom metrics source", () => {
    expect(agentOf(makeItem({
      actor: "fdai.system",
      action_kind: "observation-campaign.source-transition",
      entry: { domain: "metrics", source_id: "capacity-metrics" },
    }))).toBe("System");
  });

  test("does not treat inherited object keys as agents or legacy sources", () => {
    expect(agentOf(makeItem({
      actor: "fdai.system",
      action_kind: "observation-campaign.source-transition",
      entry: { domain: "metrics", source_id: "constructor" },
    }))).toBe("System");
    expect(agentOf(makeItem({
      actor: "fdai.system",
      action_kind: "system.housekeeping",
      entry: { owner_agent: "constructor" },
    }))).toBe("System");
  });

  test.each([
    ["fdai.core.rca", "rca.hypothesis", { producer_principal: "control-loop" }, "Forseti"],
    ["fdai.measurement", "measurement.control_loop.v1", {}, "Heimdall"],
    ["fdai.measurement", "measurement.control_loop.rejected.v1", {}, "Heimdall"],
    [
      "fdai.system",
      "audit.record",
      {
        principal: "Thor",
        topic: "object.action-run",
        payload_digest: "sha256:one",
        payload: {},
      },
      "Saga",
    ],
    ["runtime.startup", "startup_readiness.audit_probe", {}, "Saga"],
  ])("restores legacy %s %s ownership from %j to %s", (actor, actionKind, entry, owner) => {
    expect(agentOf(makeItem({
      actor,
      action_kind: actionKind,
      entry,
    }))).toBe(owner);
  });

  test("does not turn an unrelated generic audit row into Saga activity", () => {
    expect(agentOf(makeItem({
      actor: "fdai.system",
      action_kind: "audit.record",
      entry: { status: "recorded" },
    }))).toBe("System");
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
    // Shape mirrors ShadowExecutor._write_audit (services/core-control-plane/src/fdai/core/executor/executor.py).
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
