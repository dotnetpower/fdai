import { readFileSync } from "node:fs";
import { fixtureControl } from "../../src/routes/wara-guidance.fixture";
import type { WaraControl } from "../../src/routes/wara-controls.model";
import type { WaraGuidance } from "../../src/routes/wara-guidance.model";

interface PublicControl {
  id: string; title: string; description: string;
  wara: { control: string; impact: string; state: string; resource_type: string; product_group_verified: boolean; automation_available: boolean; potential_benefits: string; learn_more_name: string; learn_more_url: string; source_path: string; source_digest: string };
}
interface PublicCatalog {
  areas: { resolved_ref: string; source_version: string; retrieved_at: string; controls: PublicControl[] }[];
}

export function waraCorpusControls(): WaraControl[] {
  const catalog = JSON.parse(readFileSync(new URL("../../../rule-catalog/collected/wara-aprl/azure-wara.json", import.meta.url), "utf8")) as PublicCatalog;
  const all = catalog.areas.flatMap((area) => area.controls.map((control) => ({ area, control })));
  const indexUrl = new URL("../../../packages/service-contracts/src/fdai_service_contracts/data/wara-guidance.json", import.meta.url);
  const index = JSON.parse(readFileSync(indexUrl, "utf8")) as { shards: { path: string; count: number }[] };
  const entries = index.shards.flatMap((shard) => {
    if (!/^wara-guidance-\d{2}\.json$/.test(shard.path)) throw new Error("Invalid installed WARA guidance shard path");
    const data = JSON.parse(readFileSync(new URL(shard.path, indexUrl), "utf8")) as { entries: WaraGuidance[] };
    if (data.entries.length !== shard.count) throw new Error("Installed WARA guidance shard count does not reconcile");
    return data.entries;
  });
  return all.map(({ control, area }) => {
    const guidance = entries.find((entry) => entry.recommendation_id === control.id);
    if (!guidance) throw new Error(`Missing installed guidance for ${control.title}`);
    const maintenance = control.title.startsWith("Use maintenance configurations for the Dedicated");
    const lifecycle = control.wara.state.toLowerCase();
    if (lifecycle !== "active" && lifecycle !== "disabled") throw new Error("Unsupported public WARA lifecycle");
    return {
      ...fixtureControl(), id: control.id, title: control.title, title_ko: guidance.title.ko ?? null, description: control.description,
      potential_benefits: control.wara.potential_benefits, recommendation_control: control.wara.control,
      impact: control.wara.impact, resource_type: control.wara.resource_type,
      product_group_verified: control.wara.product_group_verified, automation_available: control.wara.automation_available,
      lifecycle,
      evaluation_status: maintenance ? "blocked" : "not_evaluated",
      mapping_disposition: maintenance ? "ambiguous_or_blocked" : "manual_evidence",
      source_revision: area.resolved_ref, source_version: area.source_version, retrieved_at: area.retrieved_at,
      source_path: control.wara.source_path, source_digest: control.wara.source_digest,
      source_url: `https://github.com/Azure/Azure-Proactive-Resiliency-Library-v2/blob/${area.resolved_ref}/${control.wara.source_path}`,
      learn_more_name: control.wara.learn_more_name, learn_more_url: control.wara.learn_more_url,
      limitations: maintenance ? ["automatic_assessment_blocked_scope_requires_review"] : ["manual_evidence_required"],
      guidance,
    };
  });
}

export function waraPilotControls(): WaraControl[] {
  const all = waraCorpusControls();
  return [
    "Use virtual network links to link global Private DNS Zones",
    "Use maintenance configurations for the Dedicated",
    "Deploy AOAI Service in multiple regions",
  ].map((title) => {
    const control = all.find((item) => item.title.startsWith(title));
    if (!control) throw new Error(`Missing public WARA pilot: ${title}`);
    return control;
  });
}
