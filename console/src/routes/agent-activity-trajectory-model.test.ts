import { describe, expect, test } from "vitest";
import type { AuditItem } from "../types";
import { agentOf } from "./agent-activity-semantics";
import {
  buildAgentTrajectories,
  filterAgentTrajectories,
  formatOutcomeLabel,
  outcomeTone,
  presentReasonLabel,
  presentResourceTypeLabel,
  presentStepSummary,
  presentTrajectoryTitle,
  stepCategory,
  trajectoryPhases,
  trajectoryScale,
  trajectorySubtitle,
  trajectoryTitle,
  uncorrelatedAuditCount,
} from "./agent-activity-trajectory-model";

function item(
  seq: number,
  actor: string,
  actionKind: string,
  recordedAt: string,
  entry: Record<string, unknown> = {},
  correlation: string | null = "corr-change",
): AuditItem {
  return {
    seq,
    event_id: `event-${seq}`,
    correlation_id: correlation,
    actor,
    action_kind: actionKind,
    mode: "shadow",
    entry,
    entry_hash: `hash-${seq}`,
    previous_hash: `hash-${seq - 1}`,
    recorded_at: recordedAt,
  };
}

const CHANGE = [
  item(4, "Var", "hil.requested", "2026-07-15T10:04:00Z", { outcome: "hil_pending", summary: "Approval requested" }),
  item(1, "Huginn", "event.normalized", "2026-07-15T10:00:00.100Z", { summary: "Change normalized", duration_ms: 100 }),
  item(3, "Forseti", "risk_gate.evaluated", "2026-07-15T10:00:02Z", {
    outcome: "hil",
    tier: "t1",
    summary: "Risk class high",
    conversation: [{ from: "Forseti", to: "Var", text: "Approval required." }],
  }),
  item(2, "Heimdall", "inventory.current_state.read", "2026-07-15T10:00:01Z", {
    started_at: "2026-07-15T10:00:00.400Z",
    outputs: { records: "3", stale: "metrics" },
  }),
];

describe("agent trajectory projection", () => {
  test("groups correlated audit steps in recorded order and keeps uncorrelated rows out", () => {
    const rows = [...CHANGE, item(9, "Saga", "audit.record", "2026-07-15T10:05:00Z", {}, null)];
    const [trajectory, ...rest] = buildAgentTrajectories(rows, agentOf);

    expect(rest).toEqual([]);
    expect(trajectory!.correlationId).toBe("corr-change");
    expect(trajectory!.steps.map((step) => step.seq)).toEqual([1, 2, 3, 4]);
    expect(trajectory!.agents).toEqual(["Huginn", "Heimdall", "Forseti", "Var"]);
    expect(trajectory!.handoffs).toBe(3);
    expect(trajectory!.title).toBe("Change normalized");
    expect(uncorrelatedAuditCount(rows)).toBe(1);
  });

  test("titles a trajectory with prose before a readable machine value", () => {
    const machine = buildAgentTrajectories([
      item(1, "fdai.observer", "observation-campaign.source-transition", "2026-07-15T10:00:00Z", {}, "corr-a"),
      item(2, "fdai.observer", "observer.refresh", "2026-07-15T10:00:01Z", { summary: "current_evidence" }, "corr-b"),
    ], agentOf);
    expect(machine.map((value) => value.title).sort()).toEqual([
      "Current evidence",
      "Observation campaign \u00b7 source transition",
    ]);
    const [prose] = buildAgentTrajectories(CHANGE, agentOf);
    expect(trajectoryTitle(prose!.steps)).toBe("Change normalized");
  });

  test("uses recorded timing without inventing durations", () => {
    const [trajectory] = buildAgentTrajectories(CHANGE, agentOf);
    const [intake, read, risk] = trajectory!.steps;

    expect(intake!.durationMs).toBe(100);
    expect(intake!.endMs - intake!.startMs).toBe(100);
    expect(read!.durationMs).toBe(600);
    expect(read!.outputs).toEqual([["records", "3"], ["stale", "metrics"]]);
    expect(risk!.durationMs).toBeNull();
    expect(risk!.startMs).toBe(risk!.endMs);
    expect(risk!.tier).toBe("T1");
  });

  test("reports the latest recorded outcome without asserting completion", () => {
    const [trajectory] = buildAgentTrajectories(CHANGE, agentOf);

    expect(trajectory!.latestOutcome).toBe("hil_pending");
    expect(trajectory!.tone).toBe("attention");
    expect(trajectory!.flaggedSteps).toBe(2);
    expect(buildAgentTrajectories([item(1, "Huginn", "event.normalized", "2026-07-15T10:00:00Z")], agentOf)[0]!
      .latestOutcome).toBeNull();
  });

  test("leaves phases without records unrecorded instead of skipped", () => {
    const [trajectory] = buildAgentTrajectories(CHANGE, agentOf);

    expect(trajectoryPhases(trajectory!)).toEqual([
      { id: "intake", state: "recorded", steps: 1 },
      { id: "evidence", state: "recorded", steps: 1 },
      { id: "judgment", state: "attention", steps: 1 },
      { id: "authorization", state: "attention", steps: 1 },
      { id: "execution", state: "unrecorded", steps: 0 },
      { id: "outcome", state: "unrecorded", steps: 0 },
    ]);
  });

  test("classifies steps from recorded action fields only", () => {
    expect(stepCategory(item(1, "Huginn", "event.normalized", "2026-07-15T10:00:00Z"))).toBe("intake");
    expect(stepCategory(item(2, "fdai.core", "control_loop.decided", "2026-07-15T10:00:00Z", { stage: "trust_router" })))
      .toBe("decision");
    expect(stepCategory(item(3, "Thor", "action.dispatch", "2026-07-15T10:00:00Z"))).toBe("action");
    expect(stepCategory(item(4, "Vidar", "rollback.completed", "2026-07-15T10:00:00Z"))).toBe("recovery");
    expect(stepCategory(item(5, "Heimdall", "effect.verified", "2026-07-15T10:00:00Z"))).toBe("verification");
    expect(stepCategory(item(6, "Odin", "custom.note", "2026-07-15T10:00:00Z"))).toBe("activity");
  });

  test("maps outcome tone only from recorded outcome text", () => {
    expect(outcomeTone("failed")).toBe("bad");
    expect(outcomeTone("timed_out")).toBe("bad");
    expect(outcomeTone("hil_pending")).toBe("attention");
    expect(outcomeTone("degraded")).toBe("attention");
    expect(outcomeTone("verified")).toBe("good");
    expect(outcomeTone("compliant")).toBe("good");
    expect(outcomeTone("recorded")).toBe("neutral");
    expect(outcomeTone(null, null)).toBe("neutral");
  });

  test("extracts nested payload summaries, outcomes, and resources and prioritizes multi-step trajectories", () => {
    const mirror = item(10, "Saga", "audit.record", "2026-07-15T10:10:00Z", {
      principal: "Saga",
      topic: "object.audit-entry",
      payload_digest: "sha256:one",
      payload: {
        kind: "normalized_ingress_retention",
        event_type: "inventory.resource_observed",
        resource_id: "scope-1/resource-group/rg-1/providers/microsoft.compute/virtualmachines/vm-alpha",
        judgment_state: "retained_for_replay",
      },
    }, "inventory-snapshot:alpha");
    const analyzer = [
      item(11, "Forseti", "control_loop.compliant", "2026-07-15T10:05:00Z", {
        reason: "no_rule_denied",
        resource_type: "compute.vm-scale-set",
      }, "analyzer:one"),
      item(12, "Heimdall", "measurement.control_loop.v1", "2026-07-15T10:05:01Z", {
        event_type: "analyzer.host_cpu.observed",
        resource_type: "compute.vm-scale-set",
        terminal_outcome: "compliant",
        tier: "t0",
      }, "analyzer:one"),
    ];
    const trajectories = buildAgentTrajectories([mirror, ...analyzer], agentOf);

    expect(trajectories.map((entry) => entry.correlationId)).toEqual([
      "analyzer:one",
      "inventory-snapshot:alpha",
    ]);
    expect(trajectories[0]!.title).toBe("No rule denied \u00b7 compute.vm-scale-set");
    expect(trajectories[0]!.latestOutcome).toBe("compliant");
    expect(trajectories[0]!.tone).toBe("good");
    expect(trajectorySubtitle(trajectories[0]!, "en")).toContain("Policy compliance evaluation");
    expect(trajectorySubtitle(trajectories[0]!, "ko")).toContain("가상 머신 확장 집합(VMSS)");
    expect(presentTrajectoryTitle(trajectories[0]!, "ko")).toBe(
      "가상 머신 확장 집합(VMSS) 호스트 CPU 메트릭 점검 - 이상 및 규칙 위반 없음",
    );
    expect(presentTrajectoryTitle(trajectories[0]!, "en")).toBe(
      "VM Scale Set (VMSS) host CPU metric check - compliant",
    );
    expect(trajectories[1]!.title).toBe("Inventory \u00b7 resource observed \u00b7 vm-alpha");
    expect(trajectories[1]!.latestOutcome).toBe("retained_for_replay");
    expect(presentTrajectoryTitle(trajectories[1]!, "ko")).toBe(
      "가상 머신(VM) (vm-alpha) 인벤토리 관측 상태 감사 보존",
    );
    expect(presentTrajectoryTitle(trajectories[1]!, "en")).toBe(
      "Virtual Machine (VM) (vm-alpha) inventory observation retained in audit",
    );
    expect(formatOutcomeLabel("hil_pending", "en")).toBe("Awaiting Approval (HIL)");
    expect(formatOutcomeLabel("hil_pending", "ko")).toBe("운영자 승인 대기 (HIL)");
    expect(formatOutcomeLabel("retained_for_replay", "en")).toBe("Audit Retained");
    expect(formatOutcomeLabel("retained_for_replay", "ko")).toBe("감사 보존됨");
  });

  test("synthesizes bilingual problem-oriented titles and step summaries for RCA, HIL, and abstain flows", () => {
    const rcaFlow = buildAgentTrajectories([
      item(21, "Forseti", "rca.hypothesis", "2026-07-15T10:20:00Z", {
        rule_id: "compute.vm.environment-tag.required",
        rca_outcome: "grounded",
        rca_reason: "grounded",
        rca_remediation_ref: "remediate.tag-add",
        rca_impact: [{
          evidence_ref: "finding:compute.vm.environment-tag.required::1.0.0::scope-1/resource-group/rg-1/providers/microsoft.compute/virtualmachines/vm-prod-01::evt-21",
        }],
      }, "corr-rca"),
      item(22, "Var", "hil.requested", "2026-07-15T10:20:01Z", {
        rule_id: "compute.vm.environment-tag.required",
        action_type: "remediate.tag-add",
      }, "corr-rca"),
    ], agentOf)[0]!;

    expect(presentTrajectoryTitle(rcaFlow, "ko")).toBe(
      "가상 머신(VM) 환경(environment) 필수 태그 누락 점검 (vm-prod-01) - 필수 거버넌스 태그 추가 승인 대기",
    );
    expect(presentTrajectoryTitle(rcaFlow, "en")).toBe(
      "Virtual Machine required environment tag check (vm-prod-01) - awaiting approval (Add required governance tag)",
    );
    expect(presentStepSummary(rcaFlow.steps[0]!, "ko")).toContain("필수 거버넌스 태그 추가 조치 권고");
    expect(presentStepSummary(rcaFlow.steps[1]!, "en")).toContain("Created human approval (HIL) request");
    expect(presentReasonLabel("inventory_baseline_no_rule_match", "ko")).toBe(
      "해당 리소스 유형에 적용할 정책 규칙 없음",
    );
    expect(presentResourceTypeLabel("authorization.role-assignment", "ko")).toBe("IAM 역할 할당");
  });

  test("filters by participating agent, conversation recipient, and recorded text", () => {
    const trajectories = buildAgentTrajectories([
      ...CHANGE,
      item(20, "Njord", "cost.advisory", "2026-07-15T09:00:00Z", { summary: "Advisory" }, "corr-cost"),
    ], agentOf);

    expect(filterAgentTrajectories(trajectories, "Var", "").map((value) => value.correlationId))
      .toEqual(["corr-change"]);
    expect(filterAgentTrajectories(trajectories, null, "advisory").map((value) => value.correlationId))
      .toEqual(["corr-cost"]);
    expect(filterAgentTrajectories(trajectories, null, "approval required").map((value) => value.correlationId))
      .toEqual(["corr-change"]);
    expect(filterAgentTrajectories(trajectories, "Thor", "")).toEqual([]);
  });

  test("compresses long idle gaps while keeping recorded work linear", () => {
    const [trajectory] = buildAgentTrajectories(CHANGE, agentOf);
    const scale = trajectoryScale(trajectory!);

    expect(scale.breaks).toHaveLength(1);
    expect(scale.breaks[0]!.realMs).toBe(238_000);
    expect(scale.x(trajectory!.startMs)).toBe(0);
    expect(scale.x(trajectory!.endMs)).toBe(100);
    expect(scale.x(Date.parse("2026-07-15T10:00:02Z"))).toBeGreaterThan(50);
  });
});
