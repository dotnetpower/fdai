import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "../i18n";

import type { OperatorApiClient } from "../api";
import {
  adjacentDetectionCoverageView,
  decodeDetectionReadiness,
  decodeLifecycle,
  detectionCoverageViewFromHash,
  loadDetectionReadinessState,
  findingAssessmentTitle,
} from "./detection-readiness";
import {
  parseResourceRefDisplay,
  resourceKindLabel,
  resourceTypeLabel,
  resourceEvaluationTitle,
  resourceEvaluationDescription,
} from "./detection-coverage-view";
import PINNED from "./fixtures/detection-lifecycle-projection.json";

afterEach(() => setLocale("en"));

describe("grounded descriptive detection titles", () => {
  test.each([
    ["en", "Evaluation could not complete", "Analyzer timed out", "Host CPU threshold: Metrics missing"],
    ["ko", "평가를 완료하지 못했습니다", "분석기 시간 초과", "호스트 CPU 임계값: 메트릭 누락"],
  ] as const)("describes recorded outcomes in %s without asserting resource health", (locale, title, reason, finding) => {
    setLocale(locale);
    expect(resourceEvaluationTitle({ evaluation_state: "evaluation_error" })).toBe(title);
    const description = resourceEvaluationDescription({
      evaluation_state: "evaluation_error", error_codes: ["analyzer_timeout"],
    });
    expect(description).toContain(reason);
    expect(description).toContain(locale === "en" ? "not proof" : "뜻은 아닙니다");
    expect(resourceEvaluationDescription({
      evaluation_state: "evaluated_no_finding", error_codes: [],
    })).toContain(locale === "en" ? "does not establish resource health" : "정상이라는 뜻은 아닙니다");
    expect(resourceEvaluationTitle({ evaluation_state: "unsupported" }))
      .toContain(locale === "en" ? "unsupported" : "지원되지 않는");
    expect(resourceEvaluationTitle({ evaluation_state: "finding" }))
      .toContain(locale === "en" ? "finding" : "발견 사항");
    expect(findingAssessmentTitle({ signal: "host_cpu", current_state: "metrics_missing" })).toBe(finding);
    expect(findingAssessmentTitle({ signal: "custom_signal", current_state: "custom_state" }))
      .toBe(locale === "en"
        ? "Recorded analyzer finding: Recorded state needs review"
        : "분석기가 기록한 발견 사항: 기록된 상태를 검토해야 합니다");
  });
});

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
    retained_from: "2026-07-24T00:55:08Z",
    receipt_count: 2,
    receipt_limit: 500,
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

describe("detection readiness views", () => {
  test("maps deep links and keyboard navigation to the matching view", () => {
    expect(detectionCoverageViewFromHash("#detection-targets")).toBe("resources");
    expect(detectionCoverageViewFromHash("#detection-lifecycle-records")).toBe("findings");
    expect(detectionCoverageViewFromHash("#pod-detection-lifecycle")).toBe("resources");
    expect(adjacentDetectionCoverageView("coverage", "previous")).toBe("findings");
    expect(adjacentDetectionCoverageView("findings", "next")).toBe("coverage");
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

  test("parses structured scope and ARM resource references and maps canonical types", () => {
    const vmssRef = "scope-ddcc51d93c16973d/resource-group/mc_rg-fdai-dev-wus3_aks-fdai-dev-wus3_westus3/providers/microsoft.compute/virtualmachinescalesets/aks-runtime-60095787-vmss";
    expect(parseResourceRefDisplay(vmssRef)).toEqual({
      fullRef: vmssRef,
      shortName: "aks-runtime-60095787-vmss",
      resourceGroup: "mc_rg-fdai-dev-wus3_aks-fdai-dev-wus3_westus3",
      scopeId: "scope-ddcc51d93c16973d",
      providerType: "microsoft.compute/virtualmachinescalesets",
      hasStructuredScope: true,
    });
    expect(parseResourceRefDisplay("resource/mysql")).toEqual({
      fullRef: "resource/mysql",
      shortName: "resource/mysql",
      resourceGroup: null,
      scopeId: null,
      providerType: null,
      hasStructuredScope: false,
    });
    expect(resourceTypeLabel("compute.vm-scale-set")).toBe("Virtual machine scale set (VMSS)");
    expect(resourceTypeLabel("compute.vm")).toBe("Virtual machine (VM)");
    expect(resourceKindLabel("virtual_machine_scale_set")).toBe("Virtual machine scale set");
  });
});
