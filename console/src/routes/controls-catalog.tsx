import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { currentRoute } from "../router";
import { BestPracticeControlsRoute } from "./best-practice-controls";
import { bestPracticeHref } from "./best-practice-controls.model";
import { CafControlsRoute } from "./caf-controls";
import { cafHref } from "./caf-controls.model";
import { t } from "./i18n/governance";
import { McsbControlsRoute } from "./mcsb-controls";
import { mcsbControlsHref } from "./mcsb-controls.model";
import { MsrcCsafControlsRoute } from "./msrc-csaf-controls";
import { EMPTY_MSRC_CSAF_FILTERS, msrcCsafHref } from "./msrc-csaf-controls.model";
import { WaraControlsRoute } from "./wara-controls";
import { waraHref } from "./wara-controls.model";

type ControlFramework =
  | "azure-waf"
  | "azure-caf"
  | "azure-wara"
  | "mcsb-v1"
  | "mcsb-v2-preview"
  | "msrc-csaf";

function controlFramework(): ControlFramework {
  const value = currentRoute().search.get("framework");
  if (value === "azure-caf") return value;
  if (value === "azure-wara") return value;
  if (value === "mcsb-v1" || value === "mcsb-v2-preview") return value;
  if (value === "msrc-csaf") return value;
  return "azure-waf";
}

export function ControlsCatalogRoute({ client }: { readonly client: OperatorApiClient }) {
  const [framework, setFramework] = useState(controlFramework());
  useEffect(() => {
    const onRouteChange = () => setFramework(controlFramework());
    window.addEventListener("popstate", onRouteChange);
    window.addEventListener("fdai:route-changed", onRouteChange);
    return () => {
      window.removeEventListener("popstate", onRouteChange);
      window.removeEventListener("fdai:route-changed", onRouteChange);
    };
  }, []);
  return (
    <div class="stack controls-catalog-view">
      <nav class="control-framework-tabs" aria-label={t("governance.rules.controls.framework.aria")}>
        <a class={framework === "azure-waf" ? "is-active" : undefined} aria-current={framework === "azure-waf" ? "page" : undefined} href={bestPracticeHref({ pillar: "", status: "", q: "" }, null)}>{t("governance.rules.controls.framework.waf")}</a>
        <a class={framework === "azure-caf" ? "is-active" : undefined} aria-current={framework === "azure-caf" ? "page" : undefined} href={cafHref(EMPTY_CAF_FILTERS, null)}>{t("governance.rules.controls.framework.caf")}</a>
        <a class={framework === "azure-wara" ? "is-active" : undefined} aria-current={framework === "azure-wara" ? "page" : undefined} href={waraHref(EMPTY_WARA_FILTERS, null)}>{t("governance.rules.controls.framework.wara")}</a>
        <a class={framework === "mcsb-v1" ? "is-active" : undefined} aria-current={framework === "mcsb-v1" ? "page" : undefined} href={mcsbControlsHref("v1", { domain: "", coverage: "", q: "" }, null)}>{t("governance.rules.controls.framework.mcsbV1")}</a>
        <a class={framework === "mcsb-v2-preview" ? "is-active" : undefined} aria-current={framework === "mcsb-v2-preview" ? "page" : undefined} href={mcsbControlsHref("v2-preview", { domain: "", coverage: "", q: "" }, null)}>{t("governance.rules.controls.framework.mcsbV2")}</a>
        <a class={framework === "msrc-csaf" ? "is-active" : undefined} aria-current={framework === "msrc-csaf" ? "page" : undefined} href={msrcCsafHref(EMPTY_MSRC_CSAF_FILTERS, null)}>{t("governance.rules.controls.framework.msrcCsaf")}</a>
      </nav>
      {framework === "azure-waf" ? (
        <BestPracticeControlsRoute client={client} />
      ) : framework === "azure-caf" ? (
        <CafControlsRoute client={client} />
      ) : framework === "azure-wara" ? (
        <WaraControlsRoute client={client} />
      ) : framework === "msrc-csaf" ? (
        <MsrcCsafControlsRoute />
      ) : (
        <McsbControlsRoute client={client} />
      )}
    </div>
  );
}

const EMPTY_CAF_FILTERS = {
  area: "",
  mapping_state: "",
  applicability: "",
  evaluation_status: "",
  satisfaction: "",
  owner_slot: "",
  q: "",
} as const;

const EMPTY_WARA_FILTERS = {
  resource_type: "",
  recommendation_control: "",
  impact: "",
  lifecycle: "",
  product_group_verified: "",
  automation_available: "",
  mapping_disposition: "",
  applicability: "",
  evaluation_status: "",
  satisfaction: "",
  q: "",
} as const;
