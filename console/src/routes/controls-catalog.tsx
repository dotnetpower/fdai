import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { currentRoute } from "../router";
import { BestPracticeControlsRoute } from "./best-practice-controls";
import { bestPracticeHref } from "./best-practice-controls.model";
import { t } from "./i18n/governance";
import { McsbControlsRoute } from "./mcsb-controls";
import { mcsbControlsHref } from "./mcsb-controls.model";

type ControlFramework = "azure-waf" | "mcsb-v1" | "mcsb-v2-preview";

function controlFramework(): ControlFramework {
  const value = currentRoute().search.get("framework");
  if (value === "mcsb-v1" || value === "mcsb-v2-preview") return value;
  return "azure-waf";
}

export function ControlsCatalogRoute({ client }: { readonly client: ReadApiClient }) {
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
        <a class={framework === "mcsb-v1" ? "is-active" : undefined} aria-current={framework === "mcsb-v1" ? "page" : undefined} href={mcsbControlsHref("v1", { domain: "", coverage: "", q: "" }, null)}>{t("governance.rules.controls.framework.mcsbV1")}</a>
        <a class={framework === "mcsb-v2-preview" ? "is-active" : undefined} aria-current={framework === "mcsb-v2-preview" ? "page" : undefined} href={mcsbControlsHref("v2-preview", { domain: "", coverage: "", q: "" }, null)}>{t("governance.rules.controls.framework.mcsbV2")}</a>
      </nav>
      {framework === "azure-waf" ? (
        <BestPracticeControlsRoute client={client} />
      ) : (
        <McsbControlsRoute client={client} />
      )}
    </div>
  );
}
