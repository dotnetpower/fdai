import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import type { FrameworkGuidance, GuidanceFramework } from "../../src/routes/framework-guidance.model";

const digest = `sha256:${"b".repeat(64)}`;
const benchmark = {
  benchmark_version: "v1", title: "Microsoft Cloud Security Benchmark v1", status: "stable",
  control_import_status: "complete", control_count: 86, coverage_counts: { partial: 1 },
  policy_profiles: [{ profile_id: "mcsb-v1", policy_ref_count: 1 }],
};

export function frameworkFixture(framework: GuidanceFramework) {
  const controlId = framework === "azure-waf" ? "RE:01" : framework === "azure-mcsb" ? "NS-1" : "strategy";
  const indexUrl = new URL("../../../packages/service-contracts/src/fdai_service_contracts/data/framework-guidance.json", import.meta.url);
  const index = JSON.parse(readFileSync(indexUrl, "utf8")) as { shards: { file: string }[] };
  const guide = index.shards.flatMap((shard) => {
    const data = JSON.parse(readFileSync(new URL(shard.file, indexUrl), "utf8")) as { entries: FrameworkGuidance[] };
    return data.entries;
  }).find((entry) => entry.framework_id === framework && entry.control_id === controlId);
  if (!guide) throw new Error(`Missing packaged framework guide: ${framework}/${controlId}`);
  const common = {
    title: "Source control title", evaluation_status: "not_evaluated", applicability: "unknown", satisfaction: "unknown",
    evaluated_at: null, evaluation_scope: null, profile_id: null, profile_digest: null, approved_exception: null,
    evidence_complete: false, evidence_refs: [], evidence_digests: [], limitations: ["control_disabled"],
    execution_authority: false, control_id: controlId, guidance: guide,
    source_revision: "a".repeat(40),
    guidance_source_revision: guide.source_revision, guidance_source_digest: guide.source_digest,
    enablement: { severity: "medium", default_enabled: true, enabled: false, source: "profile_override", mode: "shadow", execution_authority: false },
    severity_source: framework === "azure-waf" ? "source" : "fdai_default",
    remediation: {
      status: framework === "azure-caf" ? "manual_guidance" : "governed_candidates",
      candidates: framework === "azure-caf" ? [] : [{ rule_id: "storage.https-only", action_type_ref: "storage.enable-https" }],
      limitations: [], execution_authority: false,
    },
  };
  const detail = framework === "azure-waf" ? {
    ...common, id: "azure-waf.reliability.re-01", version: "1.0.0", framework, rationale: "Source explanation",
    severity: "medium", category: "reliability", pillar: "reliability", requirement_mode: "all", requirement_count: 0,
    owner: "reliability-owner", cadence_days: 30, catalog_status: "present", mapping_status: "unmapped",
    status: "unknown", satisfied_requirement_count: 0, evaluation_source: "not_connected", tradeoffs: [],
    requirements: [], provenance: {},
  } : framework === "azure-mcsb" ? {
    ...common, benchmark_version: "v1", domain: "NS", coverage: "partial", rule_count: 0,
    runtime_observation_count: 0, manual_evidence_count: 1, rule_ids: [], runtime_observation_ids: [],
    manual_evidence_refs: ["reviewed-network-segmentation"], source: { source_url: "https://learn.microsoft.com/security/benchmark/azure/" },
    evaluation_source: "catalog_crosswalk",
    assessment: { evaluation_status: "not_evaluated", satisfaction: "unknown", evaluated_at: null, evidence_complete: false, limitations: ["control_disabled"], requirements: [] },
    assessment_summary: { status: "not_evaluated", last_evaluated_at: null, satisfaction_counts: { unknown: 86 }, execution_authority: false },
  } : {
    ...common, description: "Source explanation", area: "methodology", reference_state: "present", mapping_state: "unmapped",
    owner_slot: "strategy-owner", cadence_days: 90, source_url: "https://learn.microsoft.com/azure/cloud-adoption-framework/",
    source_version: "2026-08-31", evidence_specifications: [], crosswalk: [],
  };
  const total = framework === "azure-waf" ? 59 : framework === "azure-mcsb" ? 86 : 15;
  const pagination = { total, filtered_total: 1, offset: 0, limit: 100, controls: [detail] };
  const list = framework === "azure-waf" ? {
    ...pagination, facets: { by_pillar: { reliability: 1 }, by_status: { unknown: 1 }, by_severity: { medium: 1 } }, evaluation_source: "not_connected",
  } : framework === "azure-mcsb" ? {
    ...pagination, benchmark, versions: [benchmark], facets: { by_domain: { NS: 1 }, by_coverage: { partial: 1 } },
    evaluation_source: "catalog_crosswalk",
  } : {
    ...pagination, facets: { by_area: { methodology: 1 }, by_applicability: { unknown: 1 }, by_satisfaction: { unknown: 1 } },
    evaluation_source: "not_connected", framework_id: framework, framework_version: "2026-08-31", catalog_digest: digest,
    source_revision_digest: digest, last_profile_id: null, last_evaluated_at: null,
  };
  const api = framework === "azure-waf" ? "/best-practices" : framework === "azure-mcsb" ? "/mcsb-controls" : "/caf-controls";
  const params = new URLSearchParams({
    view: "controls", framework: framework === "azure-mcsb" ? "mcsb-v1" : framework, q: "source", locale: "en",
    [framework === "azure-caf" ? "caf_control" : "control"]: "id" in detail ? detail.id : controlId,
  });
  return { framework, guide, detail, list, api, params };
}

export async function installFrameworkFixture(page: Page, fixture: ReturnType<typeof frameworkFixture>, mutate?: (value: typeof fixture.detail) => unknown, beforeDetail?: () => Promise<void>) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route(/\/(?:api\/)?(?:best-practices|mcsb-controls|caf-controls|rules|incidents)(?:[/?]|$)/, async (route) => {
    if (route.request().resourceType() === "document") return route.continue();
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === fixture.api) return route.fulfill({ json: fixture.list });
    if (path.startsWith(`${fixture.api}/`)) {
      await beforeDetail?.();
      return route.fulfill({ json: mutate ? mutate(fixture.detail) : fixture.detail });
    }
    return route.fulfill({ status: 404, json: { detail: "Not mocked in the isolated framework fixture" } });
  });
}
