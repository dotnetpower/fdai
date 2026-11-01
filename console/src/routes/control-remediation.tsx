import { DetailSection } from "./rule-catalog-components";
import { ruleCatalogHref } from "./rule-catalog-state";
import { displayValue, t } from "./i18n/governance";
import type { ControlRemediation } from "./control-remediation.model";

export function ControlRemediationSection({ value }: { readonly value: ControlRemediation | null | undefined }) {
  const key = "governance.rules.remediation";
  return <DetailSection title={t(`${key}.title`)}>
    <p>{t(`${key}.${value?.status ?? "unavailable"}`)}</p>
    {value?.status === "governed_candidates" && value.candidates.length > 0 ? <ul>
      {value.candidates.map((candidate) => <li key={`${candidate.rule_id}:${candidate.action_type_ref}`}>
        <a href={ruleCatalogHref({ origin: "", category: "", severity: "", source: "", q: "" }, 0, { id: candidate.rule_id, origin: "active" })}>{candidate.rule_id}</a>
        {" - "}<code>{candidate.action_type_ref}</code>
      </li>)}
    </ul> : null}
    {value && value.limitations.length > 0 ? <ul>{value.limitations.map((limitation) => {
      const label = displayValue("remediationLimitation", limitation);
      return <li key={limitation}>{label === limitation ? limitation : `${label} (${limitation})`}</li>;
    })}</ul> : null}
    <p class="muted">{t(`${key}.boundary`)}</p>
  </DetailSection>;
}
