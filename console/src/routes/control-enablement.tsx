import { StatusPill } from "../components/ui";
import { DetailRow, DetailSection } from "./rule-catalog-components";
import type { ControlEnablement, SeveritySource } from "./control-enablement.model";
import { displayValue, t } from "./i18n/governance";

const key = "governance.rules.enablement";

export function ControlEnablementBadge({ value }: { readonly value: ControlEnablement | null | undefined }) {
  return <StatusPill kind="neutral" label={t(`${key}.${value ? value.enabled ? "enabled" : "disabled" : "unknown"}`)} />;
}

export function ControlEnablementSection({ value, severitySource }: {
  readonly value: ControlEnablement | null | undefined;
  readonly severitySource: SeveritySource | null | undefined;
}) {
  return <DetailSection title={t(`${key}.title`)}>
    {value ? <>
      <dl class="detail-grid">
        <DetailRow label={t(`${key}.severity`)} value={displayValue("severity", value.severity)} />
        <DetailRow label={t(`${key}.severitySource`)} value={t(`${key}.severitySources.${severitySource ?? "unknown"}`)} />
        <DetailRow label={t(`${key}.effective`)} value={t(`${key}.${value.enabled ? "enabled" : "disabled"}`)} />
        <DetailRow label={t(`${key}.default`)} value={t(`${key}.${value.default_enabled ? "enabled" : "disabled"}`)} />
        <DetailRow label={t(`${key}.source`)} value={t(`${key}.sources.${value.source}`)} />
        <DetailRow label={t(`${key}.available`)} value={t(`${key}.${value.available === undefined ? "unknown" : value.available ? "availableYes" : "availableNo"}`)} />
        {value.unavailable_reason ? <DetailRow label={t(`${key}.unavailableReason`)} value={value.unavailable_reason} /> : null}
        <DetailRow label={t(`${key}.mode`)} value="shadow" mono />
      </dl>
      <p class="muted">{t(`${key}.boundary`)}</p>
      {!value.enabled ? <p class="muted" role="note">{t(`${key}.disabledBoundary`)}</p> : null}
    </> : <p class="muted" role="status">{t(`${key}.unavailable`)}</p>}
    <p class="muted">{t(`${key}.profileOnly`)}</p>
  </DetailSection>;
}
