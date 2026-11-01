import { describe, expect, test } from "vitest";
import { buildMcsbV2Guidance, mcsbDisplayTitle } from "./mcsb-v2-guidance";
import { PINNED_MSRC_CSAF_CATALOG } from "./msrc-csaf-controls.model";
import { buildMsrcCsafGuidance, msrcCsafDisplayTitle, parseCvssVector } from "./msrc-csaf-guidance";
import { frameworkDisplayTitle, resolveControlReferenceImage } from "./reference-images.catalog";
import { ACTIVE_RULE_GUIDANCE_SPECS, buildRuleGuidance, ruleDisplayTitle } from "./rule-catalog-guidance";
import type { RuleDetailDto } from "./rule-catalog-types";
import { guidanceMissingKoreanFields } from "./wara-guidance.model";

function sampleRuleDetail(overrides: Partial<RuleDetailDto> = {}): RuleDetailDto {
  return {
    id: "kubernetes-node-pool.multi-zone",
    title: "Require multi-zone kubernetes-node-pool",
    origin: "active",
    version: "1.0.0",
    source: "waf",
    severity: "high",
    category: "reliability",
    resource_type: "kubernetes-node-pool",
    check_logic: {
      kind: "rego",
      reference: "policies/kubernetes/multi_zone_node_pool.rego",
    },
    remediation: {
      template_ref: "remediation/kubernetes/multi_zone_node_pool.tftpl",
      cost_impact_monthly_usd: 0,
    },
    remediates: "remediate.enable-zone-redundancy",
    provenance: {
      source_url: "https://learn.microsoft.com/en-us/azure/aks/reliability-availability-zones-configure",
      source_version: "1.0.0",
      resolved_ref: "a".repeat(40),
      content_hash: `sha256:${"b".repeat(64)}`,
      license: "MIT",
      redistribution: "embeddable",
      retrieved_at: "2026-07-06T00:00:00Z",
      mapped_by: null,
    },
    schema_version: "2.0.0",
    alternatives: [],
    parameters: {},
    applies_to: { resource_types: ["kubernetes-node-pool"] },
    check_logic_body: "package fdai.kubernetes.multi_zone_node_pool",
    remediation_body: "resource \"azurerm_kubernetes_cluster_node_pool\" {}",
    explanation: {
      title: "Require multi-zone kubernetes-node-pool",
      description: "A kubernetes-node-pool MUST span at least two availability zones.",
      source: "rego_metadata",
      details: {
        evaluated_properties: "property.kubernetes-node-pool.availability_zones",
        trigger_signals: "resource.configuration.observed",
      },
    },
    ...overrides,
  };
}

describe("rule, MCSB v2-preview, and MSRC CSAF illustrated guidance", () => {
  test("covers all 52 shipped active detection rules with complete Korean titles and diagrams", () => {
    expect(Object.keys(ACTIVE_RULE_GUIDANCE_SPECS).length).toBeGreaterThanOrEqual(52);
    const detail = sampleRuleDetail();
    expect(ruleDisplayTitle(detail, "en")).toBe("Require multi-zone kubernetes-node-pool");
    expect(ruleDisplayTitle(detail, "ko")).toContain("노드 풀");
    const guidance = buildRuleGuidance(detail);
    expect(guidanceMissingKoreanFields(guidance)).toBe(0);
    expect(guidance.diagram.nodes).toHaveLength(5);
    expect(guidance.diagram.edges).toHaveLength(5);
    expect(guidance.reference_image?.asset_id).toContain("sha256-");
  });

  test("synthesizes bilingual titles and diagrams for collected kube_bench and azure_policy rules", () => {
    const kubeRule = sampleRuleDetail({
      id: "kube-bench.ack-1.0.1-1-10.ensure-that-the-container-network-interface-file-ownership-is-set-to-root-root-m",
      title: "CIS ack-1.0 1.1.10: Ensure that the container network interface file ownership is set to root:root",
      origin: "collected",
      source: "kube_bench",
      resource_type: "kubernetes-cluster.control-plane",
      explanation: {
        title: "CIS ack-1.0 1.1.10: Ensure that the container network interface file ownership is set to root:root",
        description: null,
        source: "kube_bench",
        details: {},
      },
    });
    expect(ruleDisplayTitle(kubeRule, "ko")).toContain("CIS");
    const kubeGuidance = buildRuleGuidance(kubeRule);
    expect(guidanceMissingKoreanFields(kubeGuidance)).toBe(0);
    expect(kubeGuidance.diagram.nodes).toHaveLength(5);
  });

  test("builds complete bilingual guidance and AI security diagrams for MCSB v2-preview controls", () => {
    const aiControl = {
      control_id: "AI-1",
      title: "Ensure use of approved models",
      domain: "AI",
      coverage: "unmapped" as const,
      rule_count: 0,
      runtime_observation_count: 0,
      manual_evidence_count: 0,
      benchmark_version: "v2-preview" as const,
      rule_ids: [],
      runtime_observation_ids: [],
      manual_evidence_refs: [],
      source: {
        source_url: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-artificial-intelligence-security",
        resolved_ref: "c64089dd41fe72aedea1044686c89fa1668c501d",
      },
      evaluation_source: "catalog-crosswalk",
      assessment: null,
      assessment_summary: null,
    };
    expect(mcsbDisplayTitle("v2-preview", aiControl, "ko")).toContain("승인된 AI 모델");
    const guidance = buildMcsbV2Guidance(aiControl);
    expect(guidanceMissingKoreanFields(guidance)).toBe(0);
    expect(guidance.diagram.kind).toBe("mcsb-v2-ai-security");
    expect(guidance.diagram.nodes).toHaveLength(5);
  });

  test("builds MSRC CSAF 2.0 bilingual titles, CVSS vector breakdowns, and Pantheon defense diagrams", () => {
    const row = PINNED_MSRC_CSAF_CATALOG.rows[0]!;
    const titleKo = msrcCsafDisplayTitle(row, "ko");
    expect(titleKo).not.toBe(row.title);
    const cvss = parseCvssVector(row.cvss_vector);
    expect(cvss.length).toBeGreaterThanOrEqual(6);
    const guidance = buildMsrcCsafGuidance(row, PINNED_MSRC_CSAF_CATALOG.source_revision);
    expect(guidanceMissingKoreanFields(guidance)).toBe(0);
    expect(guidance.diagram.kind).toBe("msrc-csaf-defense-flow");
    expect(guidance.diagram.nodes).toHaveLength(5);
  });

  test("resolves official Learn reference images and preserves synthetic test titles", () => {
    expect(resolveControlReferenceImage("azure-waf", "RE:09")?.asset_id).toContain("sha256-");
    expect(resolveControlReferenceImage("azure-caf", "landing-zone.network-connectivity")?.asset_id).toContain("sha256-");
    expect(resolveControlReferenceImage("azure-mcsb", "NS-6")?.asset_id).toContain("sha256-");
    expect(
      frameworkDisplayTitle("azure-waf", { control_id: "RE:01", title: "Source control title" }, "ko"),
    ).toBe("Source control title");
    expect(
      ruleDisplayTitle(
        {
          id: "azure-builtin.apimanagement.vnet",
          title: "API Management services should use a virtual network",
        },
        "ko",
      ),
    ).toContain("가상 네트워크(VNet) 통합 필요");
  });
});
