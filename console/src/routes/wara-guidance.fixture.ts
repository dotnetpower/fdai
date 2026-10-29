import { createHash } from "node:crypto";
import type { WaraControl } from "./wara-controls.model";
import type { WaraGuidance } from "./wara-guidance.model";

export function fixtureControl(): WaraControl {
  return {
    id: "00000000-0000-0000-0000-000000000001", title: "Illustrated reliability guidance",
    description: "Base explanation from the pinned source.", potential_benefits: "Bounded reliability improvement.",
    recommendation_control: "HighAvailability", impact: "Medium", resource_type: "Microsoft.Compute/virtualMachines",
    lifecycle: "active", product_group_verified: true, automation_available: false,
    mapping_disposition: "manual_evidence", mapping_state: "unmapped", applicability: "unknown",
    evaluation_status: "not_evaluated", satisfaction: "unknown", evaluation_scope: null, evaluated_at: null,
    evidence_complete: false, evidence_refs: [], evidence_digests: [],
    source_url: `https://github.com/Azure/Azure-Proactive-Resiliency-Library-v2/blob/${"1".repeat(40)}/azure-resources/example/recommendations.yaml`,
    source_revision: "1".repeat(40), source_version: "2026-08-24", retrieved_at: "2026-08-31T00:00:00Z",
    source_path: "azure-resources/example/recommendations.yaml", source_digest: `sha256:${"a".repeat(64)}`,
    source_license: "MIT", learn_more_name: "Reliability guidance", learn_more_url: "https://learn.microsoft.com/azure/reliability/",
    query_digest: null, evaluator_ref: null, manual_evidence: null, workload_tags: [],
    limitations: ["manual_evidence_required"], execution_authority: false,
  };
}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => [key, sorted(item)]));
  }
  return value;
}

export function signFixtureGuidance(value: Omit<WaraGuidance, "content_digest">): WaraGuidance {
  const { content_digest: _previousDigest, ...material } = value as WaraGuidance;
  const canonical = JSON.stringify(sorted(material)).replace(/[\u007f-\uffff]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
  return { ...material, content_digest: `sha256:${createHash("sha256").update(canonical).digest("hex")}` };
}

export function fixtureGuidance(control = fixtureControl()): WaraGuidance {
  return signFixtureGuidance({
    schema_version: "1.0.0", recommendation_id: control.id,
    source_revision: control.source_revision, source_digest: control.source_digest, lifecycle: control.lifecycle,
    title: { en: control.title, ko: "복원력 권고 안내" },
    summary: { en: "Design a bounded recovery path.", ko: "범위가 제한된 복구 경로를 설계합니다." },
    benefits: { en: "Reduce the impact of a failure.", ko: "장애의 영향을 줄입니다." },
    rationale: { en: "Independent verification is still required.", ko: "독립적인 검증은 여전히 필요합니다." },
    applicability: [{ en: "Review the exact workload." }, { en: "Confirm supported capabilities." }],
    configuration: { before: [{ en: "A single dependency." }, { en: "No tested recovery path." }], after: [{ en: "Independent dependencies." }, { en: "A tested recovery path." }] },
    implementation_steps: [{ en: "Record the current configuration." }, { en: "Review the proposed configuration." }, { en: "Apply only after approval." }],
    verification_steps: [{ en: "Read back the configuration." }, { en: "Run an approved bounded test." }, { en: "Retain the independent result." }],
    cautions: [{ en: "This is not runtime evidence." }, { en: "No execution authority is granted." }],
    diagram: {
      id: "recovery-path", kind: "regional-failover", title: { en: "Bounded recovery path", ko: "범위가 제한된 복구 경로" },
      description: { en: "A workload reaches the primary dependency; recovery is conditional.", ko: "워크로드는 주 의존 요소에 연결되며 복구는 조건부입니다." },
      nodes: [
        { id: "workload", label: { en: "Workload" }, detail: { en: "Approved request scope." }, role: "subject" },
        { id: "primary", label: { en: "Primary dependency" }, detail: { en: "Normal request path." }, role: "configuration" },
        { id: "secondary", label: { en: "Recovery dependency" }, detail: { en: "Requires an approved recovery plan." }, role: "dependency" },
      ],
      edges: [
        { from: "workload", to: "primary", label: { en: "Normal request path" }, style: "solid" },
        { from: "workload", to: "secondary", label: { en: "Approved conditional recovery" }, style: "dashed" },
      ],
    },
    sources: [{ label: { en: "Pinned APRL recommendation" }, url: control.source_url, kind: "aprl" }],
  });
}
