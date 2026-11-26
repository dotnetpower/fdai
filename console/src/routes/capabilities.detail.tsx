import {
  CapabilityDetailDrawer,
  type CapabilityDrawerLink,
} from "../components/capability-detail-drawer";
import type { BadgeTone } from "../components/status-badge";
import { ExternalLink } from "../components/ui";
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
  const links: CapabilityDrawerLink[] = [
    ...(isMutatingCapability(capability.side_effect_class)
      ? [{
        href: routeHref("promotion-gates"),
        label: t("governance.capabilities.detail.openPromotionEvidence"),
      }]
      : []),
    {
      href: routeHref(destination.routeId),
      label: t("governance.capabilities.detail.openRelated", {
        surface: t(`governance.capabilities.destination.${destination.labelKey}`),
      }),
    },
    {
      href: routeHref("settings-iam"),
      label: t("governance.capabilities.detail.openAccess"),
    },
  ];
  return (
    <CapabilityDetailDrawer
      id="capability-detail"
      className="capability-detail"
      heading={capability.name}
      identifier={capability.capability_id}
      copyIdentifierLabel={t("governance.common.copyId")}
      summary={capability.summary}
      closeLabel={t("governance.common.close")}
      onClose={onClose}
      stateGridLabel={t("governance.capabilities.state.aria")}
      stateBadges={[
        {
          label: t("governance.capabilities.state.declaration"),
          tone: "live",
          value: t("governance.capabilities.state.declared"),
        },
        {
          label: t("governance.capabilities.state.runtime"),
          tone: "neutral",
          value: t("governance.capabilities.state.notMeasured"),
        },
        {
          label: t("governance.capabilities.state.binding"),
          tone: "neutral",
          value: t("governance.capabilities.state.notMeasured"),
        },
        {
          label: t("governance.capabilities.state.role"),
          tone: role.tone,
          value: role.label,
        },
        {
          label: t("governance.capabilities.state.execution"),
          tone: "neutral",
          value: t("governance.capabilities.state.notGranted"),
        },
      ]}
      facts={[
        { label: t("governance.capabilities.detail.category"), value: capability.category },
        { label: t("governance.capabilities.detail.sideEffect"), value: capability.side_effect_class },
        { label: t("governance.capabilities.detail.defaultMode"), value: capability.default_mode },
        { label: t("governance.capabilities.detail.requiredRole"), value: capability.required_role },
        {
          label: t("governance.capabilities.detail.operatorPath"),
          value: t(`governance.capabilities.operatorPath.${requestPath.key}`),
        },
        {
          label: t("governance.capabilities.detail.tags"),
          value: capability.tags.join(", ") || "-",
        },
      ]}
      links={links}
      provenance={(
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
      )}
    />
  );
}

function roleMatchPresentation(
  match: CapabilityRoleMatch | "loading",
): { readonly tone: BadgeTone; readonly label: string } {
  if (match === "meets") {
    return { tone: "live", label: t("governance.capabilities.state.roleMeets") };
  }
  if (match === "does-not-meet") {
    return { tone: "sre", label: t("governance.capabilities.state.roleMissing") };
  }
  if (match === "loading") {
    return { tone: "neutral", label: t("governance.capabilities.state.roleLoading") };
  }
  return { tone: "neutral", label: t("governance.capabilities.state.roleUnavailable") };
}
