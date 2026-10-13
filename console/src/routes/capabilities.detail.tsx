import {
  CopyButton,
  ExternalLink,
  StatusPill,
  type PillKind,
} from "../components/ui";
import { routeHref } from "../router";
import {
  capabilityDestination,
  capabilityRequestPath,
  isMutatingCapability,
  type Capability,
  type CapabilityRoleMatch,
} from "./capabilities.model";
import { t } from "./i18n/capabilities";

export function CapabilityDetail({
  capability,
  roleMatch,
  onClose,
}: {
  readonly capability: Capability;
  readonly roleMatch: CapabilityRoleMatch | "loading";
  readonly onClose: () => void;
}) {
  const destination = capabilityDestination(capability);
  const role = roleMatchPresentation(roleMatch);
  const requestPath = capabilityRequestPath(capability.side_effect_class);
  return (
    <section id="capability-detail" class="capability-detail stack-section">
      <header class="section-header">
        <div><h3>{capability.name}</h3><code>{capability.capability_id}</code></div>
        <div class="cluster">
          <CopyButton text={capability.capability_id} label={t("governance.common.copyId")} />
          <button type="button" onClick={onClose}>{t("governance.common.close")}</button>
        </div>
      </header>
      <p>{capability.summary}</p>
      <div
        class="capability-state-grid"
        aria-label={t("governance.capabilities.state.aria")}
      >
        <CapabilityState
          label={t("governance.capabilities.state.declaration")}
          kind="success"
          value={t("governance.capabilities.state.declared")}
        />
        <CapabilityState
          label={t("governance.capabilities.state.runtime")}
          kind="neutral"
          value={t("governance.capabilities.state.notMeasured")}
        />
        <CapabilityState
          label={t("governance.capabilities.state.binding")}
          kind="neutral"
          value={t("governance.capabilities.state.notMeasured")}
        />
        <CapabilityState
          label={t("governance.capabilities.state.role")}
          kind={role.kind}
          value={role.label}
        />
        <CapabilityState
          label={t("governance.capabilities.state.execution")}
          kind="neutral"
          value={t("governance.capabilities.state.notGranted")}
        />
      </div>
      <dl class="capability-contract">
        <div><dt>{t("governance.capabilities.detail.category")}</dt><dd>{capability.category}</dd></div>
        <div><dt>{t("governance.capabilities.detail.sideEffect")}</dt><dd>{capability.side_effect_class}</dd></div>
        <div><dt>{t("governance.capabilities.detail.defaultMode")}</dt><dd>{capability.default_mode}</dd></div>
        <div><dt>{t("governance.capabilities.detail.requiredRole")}</dt><dd>{capability.required_role}</dd></div>
        <div><dt>{t("governance.capabilities.detail.operatorPath")}</dt><dd>{t(`governance.capabilities.operatorPath.${requestPath.key}`)}</dd></div>
        <div><dt>{t("governance.capabilities.detail.tags")}</dt><dd>{capability.tags.join(", ") || "-"}</dd></div>
      </dl>
      <div class="capability-destinations">
        {isMutatingCapability(capability.side_effect_class) ? (
          <a href={routeHref("promotion-gates")}>
            {t("governance.capabilities.detail.openPromotionEvidence")}
          </a>
        ) : null}
        <a href={routeHref(destination.routeId)}>
          {t("governance.capabilities.detail.openRelated", {
            surface: t(`governance.capabilities.destination.${destination.labelKey}`),
          })}
        </a>
        <a href={routeHref("settings-iam")}>
          {t("governance.capabilities.detail.openAccess")}
        </a>
      </div>
      <details class="capability-provenance">
        <summary>{t("governance.capabilities.provenance.title")}</summary>
        <dl>
          <div>
            <dt>{t("governance.capabilities.provenance.implementation")}</dt>
            <dd>{t(`governance.capabilities.parity.${capability.parity}`)}</dd>
          </div>
          {capability.slide_ref ? (
            <div>
              <dt>{t("governance.capabilities.provenance.reference")}</dt>
              <dd>{capability.slide_ref}</dd>
            </div>
          ) : null}
        </dl>
        {capability.official_source ? (
          <ExternalLink href={capability.official_source}>
            {t("governance.capabilities.provenance.officialSource")}
          </ExternalLink>
        ) : null}
        <div>
          <strong>{t("governance.capabilities.provenance.evidence")}</strong>
          {capability.evidence_refs.length > 0 ? (
            <ul>{capability.evidence_refs.map((reference) => (
              <li key={reference}><code>{reference}</code></li>
            ))}</ul>
          ) : (
            <p class="muted">{t("governance.capabilities.provenance.noEvidence")}</p>
          )}
        </div>
      </details>
    </section>
  );
}

function CapabilityState({
  label,
  kind,
  value,
}: {
  readonly label: string;
  readonly kind: PillKind;
  readonly value: string;
}) {
  return <div><span>{label}</span><StatusPill kind={kind} label={value} /></div>;
}

function roleMatchPresentation(
  match: CapabilityRoleMatch | "loading",
): { readonly kind: PillKind; readonly label: string } {
  if (match === "meets") {
    return { kind: "success", label: t("governance.capabilities.state.roleMeets") };
  }
  if (match === "does-not-meet") {
    return { kind: "warning", label: t("governance.capabilities.state.roleMissing") };
  }
  if (match === "loading") {
    return { kind: "neutral", label: t("governance.capabilities.state.roleLoading") };
  }
  return { kind: "neutral", label: t("governance.capabilities.state.roleUnavailable") };
}
