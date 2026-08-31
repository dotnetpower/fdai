import { describe, expect, test } from "vitest";

import type { OperatorApiClient } from "../api";
import { decodeDetectionReadiness, decodeLifecycle, loadDetectionReadinessState } from "./detection-readiness";
import PINNED from "./fixtures/detection-lifecycle-projection.json";

const RESPONSE = {
  source: "muninn-state-snapshot",
  observed_at: "2026-07-24T01:00:00Z",
  target_count: 1,
  counts: { ready: 0, partial: 1, blocked: 0, stale: 0, unauthorized: 0, unknown: 0 },
  targets: [{
    resource_ref: "cluster/example",
    generated_at: "2026-07-24T01:00:00Z",
    decision: "partial",
    authority_ceiling: "shadow",
    observations: [{ dimension: "discovered", status: "passed" }],
    missing_dimensions: ["collector_configured"],
    stale_dimensions: [],
  }],
  lifecycle: {
    source: "postgresql:state_kv:analyzer-finding-receipt",
    observed_at: "2026-07-24T01:00:10Z",
    target_count: 1,
    assessment_count: 2,
    evidence_counts: { complete: 1, incomplete: 0, conflicting: 0, missed: 1 },
    targets: [{
      resource_ref: "cluster/example/pod/orders",
      current: {
        idempotency_key: "analyzer:orders:pod_replacement:1",
        resource_ref: "cluster/example/pod/orders",
        resource_kind: "kubernetes_pod",
        signal: "pod_replacement",
        occurred_at: "2026-07-24T01:00:00Z",
        recorded_at: "2026-07-24T01:00:10Z",
        current_state: "running",
        detection_latency_seconds: 10,
        evidence_complete: true,
        evidence_state: "complete",
        publication: {
          current: "duplicate_suppressed",
          attempts: ["published", "duplicate_suppressed"],
          duplicate_observed: true,
        },
        recovery_state: "verified",
        evidence_refs: ["pod-old", "pod-new"],
        cause_claim_supported: false,
        execution_authority: false,
      },
      history: [{
        idempotency_key: "analyzer:orders:insufficient_evidence:0",
        resource_ref: "cluster/example/pod/orders",
        resource_kind: "kubernetes_pod",
        signal: "insufficient_evidence",
        occurred_at: "2026-07-24T00:55:00Z",
        recorded_at: "2026-07-24T00:55:08Z",
        current_state: "unknown",
        detection_latency_seconds: 8,
        evidence_complete: false,
        evidence_state: "missed",
        publication: {
          current: "published",
          attempts: ["published"],
          duplicate_observed: false,
        },
        recovery_state: "open",
        evidence_refs: ["pod-old"],
        cause_claim_supported: false,
        execution_authority: false,
      }],
    }],
  },
};

describe("detection readiness decoder", () => {
  test("decodes agent-owned snapshots", () => {
    const view = decodeDetectionReadiness(RESPONSE);
    expect(view.targets[0]?.decision).toBe("partial");
    expect(view.targets[0]?.observations[0]?.dimension).toBe("discovered");
    expect(view.lifecycle.targets[0]?.current.current_state).toBe("running");
    expect(view.lifecycle.targets[0]?.history[0]?.evidence_state).toBe("missed");
    expect(view.lifecycle.targets[0]?.current.publication.duplicate_observed).toBe(true);
  });

  test("rejects totals that do not reconcile", () => {
    expect(() => decodeDetectionReadiness({ ...RESPONSE, target_count: 2 })).toThrow(/totals do not reconcile/);
  });

  test("rejects duplicate dimensions", () => {
    const target = RESPONSE.targets[0]!;
    expect(() => decodeDetectionReadiness({
      ...RESPONSE,
      targets: [{ ...target, observations: [target.observations[0], target.observations[0]] }],
    })).toThrow(/duplicate detection readiness dimension/);
  });

  test("turns a malformed successful response into an error state", async () => {
    const client = {
      panel: async () => ({ ...RESPONSE, target_count: 2 }),
    } as unknown as OperatorApiClient;

    await expect(loadDetectionReadinessState(client)).resolves.toEqual({
      status: "error",
      message: "invalid Operator API response: detection readiness totals do not reconcile",
    });
  });

  test("rejects widened lifecycle authority and inconsistent publication history", () => {
    const target = RESPONSE.lifecycle.targets[0]!;
    expect(() => decodeDetectionReadiness({
      ...RESPONSE,
      lifecycle: {
        ...RESPONSE.lifecycle,
        targets: [{
          ...target,
          current: { ...target.current, execution_authority: true },
        }],
      },
    })).toThrow(/widened its read-only boundary/);
    expect(() => decodeDetectionReadiness({
      ...RESPONSE,
      lifecycle: {
        ...RESPONSE.lifecycle,
        targets: [{
          ...target,
          current: {
            ...target.current,
            publication: {
              current: "published",
              attempts: ["published"],
              duplicate_observed: true,
            },
          },
        }],
      },
    })).toThrow(/publication history is inconsistent/);
  });
});

describe("pod lifecycle detection decoder", () => {
  test("keeps the four answers separable at the pinned revision", () => {
    const view = decodeLifecycle(PINNED);

    expect(view.status).toBe("available");
    expect(view.counts).toEqual({ recovered: 2, failing: 0, unknown: 1 });
    expect(view.recovery_counts).toEqual({ verified: 2, not_verified: 0, unknown: 1 });
    expect(view.failure_total).toBe(3);
    expect(view.gap_target_count).toBe(1);

    const restart = view.targets[0]!;
    expect(restart.current_signal).toBe("container_restart");
    expect(restart.recovery_state).toBe("verified");
    expect(restart.evidence_gaps).toEqual([]);
    expect(restart.delivery_counts.published).toBe(1);

    const replacement = view.targets[1]!;
    expect(replacement.current_signal).toBe("pod_replacement");
    expect(replacement.recovery_state).toBe("verified");

    const gap = view.targets[2]!;
    expect(gap.current_state).toBe("unknown");
    expect(gap.recovery_state).toBe("unknown");
    expect(gap.recovery_verified_at).toBeNull();
    expect(gap.evidence_gaps).toEqual(["incomplete_evidence"]);
    expect(gap.failure_count).toBe(1);
  });

  test("reports an absent section as unavailable instead of failing the route", () => {
    expect(decodeDetectionReadiness(RESPONSE).pod_lifecycle).toEqual(
      expect.objectContaining({ status: "unavailable", unavailable_reason: "section_absent" }),
    );
  });

  test("carries a named unavailable reason instead of an empty projection", () => {
    const view = decodeLifecycle({
      schema_version: 1,
      status: "unavailable",
      unavailable_reason: "conflicting_evidence",
      cause_claim_supported: false,
      execution_authority: false,
    });

    expect(view.status).toBe("unavailable");
    expect(view.unavailable_reason).toBe("conflicting_evidence");
    expect(view.targets).toEqual([]);
  });

  test("rejects a cause claim", () => {
    expect(() => decodeLifecycle({ ...PINNED, cause_claim_supported: true })).toThrow(/claims a cause/);
  });

  test("rejects an authority claim", () => {
    expect(() => decodeLifecycle({ ...PINNED, execution_authority: true })).toThrow(/claims authority/);
  });

  test("rejects a recovery that is not independently verified", () => {
    const targets = structuredClone(PINNED.targets);
    targets[0]!.recovery_state = "unknown";
    targets[0]!.recovery_verified_at = null;

    expect(() => decodeLifecycle({ ...PINNED, targets })).toThrow(/not independently verified/);
  });

  test("rejects stale evidence that still reports a state", () => {
    const targets = structuredClone(PINNED.targets);
    targets[0]!.stale = true;

    expect(() => decodeLifecycle({ ...PINNED, targets })).toThrow(/reports no gap/);
  });

  test("rejects totals that do not reconcile with the retained history", () => {
    expect(() => decodeLifecycle({ ...PINNED, failure_total: 4 })).toThrow(/totals do not reconcile/);
  });
});
