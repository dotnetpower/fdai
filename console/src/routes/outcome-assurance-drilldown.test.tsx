import { describe, expect, it } from "vitest";
import { decodeOutcomeAssuranceProjection } from "../api-outcome-assurance";
import { OutcomeAssuranceDrilldown } from "./outcome-assurance-drilldown";

const COMPLETE = {
  type: "outcome-assurance.projection",
  schema_version: "1.0.0",
  state: "complete",
  reason: null,
  scope: {
    scope_ref: "scope.checkout",
    service_refs: [],
    workload_refs: [],
    vertical: "change_safety",
  },
  window: {
    start: "2026-10-03T00:00:00Z",
    end: "2026-10-04T00:00:00Z",
    label: "1d",
    scenario_set_version: null,
  },
  sources: [{
    name: "outcome-assurance-measurement",
    state: "complete",
    reason: null,
    observed_at: "2026-10-04T00:00:00Z",
    expires_at: "2026-10-04T01:00:00Z",
    evidence_refs: ["measurement:change-safety"],
  }],
  readiness: [{
    facet: "measurement",
    state: "ready",
    reason: null,
    observed_at: "2026-10-04T00:00:00Z",
    expires_at: "2026-10-04T01:00:00Z",
    evidence_refs: ["readiness:measurement"],
  }],
  alignment: {
    state: "attributed",
    finalized_events: 1,
    attributed_events: 1,
    unattributed_events: 0,
    coverage: 1,
    objective_refs: ["objective.change-failure-rate@1.0.0"],
    workflow_refs: [],
    action_type_ids: [],
    evidence_refs: ["audit:event-1"],
    reason: null,
  },
  outcomes: [{
    objective_ref: "objective.change-failure-rate@1.0.0",
    metric: "change_failure_rate",
    state: "measured",
    reason: null,
    current_value: 0.02,
    baseline_value: 0.03,
    target_value: 0.025,
    unit: "ratio",
    sample_size: 48,
    confidence_interval: { low: 0.01, high: 0.03 },
    source_time: "2026-10-04T00:00:00Z",
    evidence_refs: ["measurement:change-failure-rate"],
  }],
  guards: {
    state: "healthy",
    reason: null,
    guard_evaluations: [],
    policy_escape_count: 0,
    evidence_refs: ["promotion:change-safety"],
  },
  provenance: {
    as_of: "2026-10-04T00:00:00Z",
    generated_at: "2026-10-04T00:00:00Z",
    source_names: ["outcome-assurance-measurement"],
    synthetic: false,
  },
  principal_scoped: true,
  execution_authority: false,
  approval_authority: false,
  promotion_authority: false,
} as const;

describe("Outcome Assurance drill-down", () => {
  it("decodes authority-free complete projections", () => {
    const projection = decodeOutcomeAssuranceProjection(COMPLETE);

    expect(projection.state).toBe("complete");
    expect(projection.execution_authority).toBe(false);
    expect(projection.approval_authority).toBe(false);
    expect(projection.promotion_authority).toBe(false);
    expect(projection.outcomes[0]?.current_value).toBe(0.02);
  });

  it("rejects stale metrics that carry synthetic zero values", () => {
    const stale = {
      ...COMPLETE,
      state: "stale",
      reason: "source_stale",
      outcomes: [{
        ...COMPLETE.outcomes[0],
        state: "stale",
        reason: "source_stale",
        current_value: 0,
        baseline_value: null,
        target_value: null,
        unit: null,
        sample_size: null,
        confidence_interval: null,
        source_time: null,
      }],
    };

    expect(() => decodeOutcomeAssuranceProjection(stale)).toThrow(
      "Unavailable Outcome Assurance metric cannot carry values",
    );
  });

  it("renders missing source as explicitly unavailable", () => {
    const view = OutcomeAssuranceDrilldown({ projection: null });
    const unavailable = childAt(view, 0);

    expect(unavailable.props["message"]).toContain("Outcome Assurance is not connected");
    expect(unavailable.props["evidenceState"]).toBe("not-connected");
  });

  it("renders stale projection without measured values", () => {
    const projection = decodeOutcomeAssuranceProjection({
      ...COMPLETE,
      state: "stale",
      reason: "source_stale",
      sources: [{ ...COMPLETE.sources[0], state: "stale", reason: "source_stale" }],
      outcomes: [{
        ...COMPLETE.outcomes[0],
        state: "stale",
        reason: "source_stale",
        current_value: null,
        baseline_value: null,
        target_value: null,
        unit: null,
        sample_size: null,
        confidence_interval: null,
        source_time: null,
      }],
      guards: {
        ...COMPLETE.guards,
        state: "stale",
        reason: "source_stale",
        policy_escape_count: 0,
      },
    });

    const view = OutcomeAssuranceDrilldown({ projection });
    const unavailable = childAt(view, 1);
    const table = childAt(view, 3);
    const rows = table.props["rows"];

    expect(unavailable.props["message"]).toContain("Outcome Assurance evidence is stale");
    expect(rows).toEqual([
      expect.objectContaining({
        current_value: null,
        display_value: "Unavailable",
        sample_size: null,
      }),
    ]);
  });
});

interface VNodeLike {
  readonly props: Readonly<Record<string, unknown>>;
}

function childAt(node: VNodeLike, index: number): VNodeLike {
  const children = node.props["children"];
  const child = Array.isArray(children) ? children[index] : index === 0 ? children : undefined;
  if (!isVNodeLike(child)) throw new Error("Expected child vnode");
  return child;
}

function isVNodeLike(value: unknown): value is VNodeLike {
  return typeof value === "object" && value !== null && "props" in value;
}
