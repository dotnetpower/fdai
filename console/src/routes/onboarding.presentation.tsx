import type { ComponentChildren } from "preact";

import {
  ErrorState,
  StatusPill,
  UnavailableState,
  kpiEvidenceLabel,
} from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import type { OnboardingResponse } from "./onboarding";

export function OnboardingLoadingState() {
  return (
    <div class="onboarding-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span class="sr-only">
        {t("shared.loadingResource", { resource: t("onboardingView.resourceLabel") })}
      </span>
      <div class="onboarding-skeleton-layout" aria-hidden="true">
        <div class="onboarding-skeleton-summary">
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
        </div>
        <span class="skeleton-shimmer onboarding-skeleton-actions" />
        <div class="onboarding-skeleton-details">
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
        </div>
      </div>
    </div>
  );
}

export function OnboardingBody({
  data,
  checkedAt,
  dataMode,
}: {
  readonly data: OnboardingResponse;
  readonly checkedAt: string | null;
  readonly dataMode: ConsoleDataMode;
}) {
  const observed = data.probe_mode === "configured" && data.error === null;
  const resourceGapCount = data.missing_resources.length;
  const roleGapCount = data.missing_role_assignments.length;
  usePublishViewContext(
    () => ({
      routeId: "onboarding",
      routeLabel: t("route.onboarding"),
      purpose: t("onboardingView.viewPurpose"),
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: !observed
        ? t("onboardingView.headlineUnavailable")
        : data.ready
        ? t("onboardingView.headlineReady")
        : t("onboardingView.headlineBlocked", {
            resources: resourceGapCount,
            roles: roleGapCount,
          }),
      capturedAt: checkedAt ?? new Date().toISOString(),
      facts: [
        { key: "data_mode", value: dataMode, group: "readiness" },
        { key: "probe_mode", value: data.probe_mode, group: "readiness" },
        { key: "ready", value: observed ? data.ready : null, group: "readiness" },
        {
          key: "resources_observed",
          value: observed ? data.present_resource_count : null,
          group: "readiness",
        },
        {
          key: "roles_observed",
          value: observed ? data.present_role_count : null,
          group: "readiness",
        },
        { key: "probe_error", value: data.error, group: "readiness" },
      ],
      records: {
        [observed ? "missing_resources" : "required_resources"]:
          data.missing_resources.map((resource) => ({ resource })),
        [observed ? "missing_role_assignments" : "required_role_assignments"]:
          data.missing_role_assignments.map(([principal, role, target]) => ({
            principal,
            role,
            target,
          })),
      },
    }),
    [checkedAt, data, dataMode],
  );
  return (
    <div class="onboarding-content">
      {data.probe_mode === "not-configured" ? (
        <UnavailableState
          evidenceState="not-connected"
          message={t("onboardingView.notConfigured")}
        />
      ) : null}
      {data.error !== null ? (
        <ErrorState message={`${t("onboardingView.probeFailed")} ${data.error}`} />
      ) : null}
      <section class="onboarding-summary" aria-label={t("onboardingView.summaryLabel")}>
        <OnboardingSummaryItem
          href={routeHref("provision")}
          label={t("onboardingView.readiness")}
          value={observed
            ? (
                <StatusPill
                  kind={data.ready ? "success" : "danger"}
                  label={t(data.ready ? "onboardingView.ready" : "onboardingView.blocked")}
                />
              )
            : kpiEvidenceLabel("not-connected")}
          hint={observed
            ? t(data.ready ? "onboardingView.headlineReady" : "onboardingView.headlineBlocked", {
                resources: resourceGapCount,
                roles: roleGapCount,
              })
            : t("onboardingView.headlineUnavailable")}
          evidenceState={summaryEvidenceState(dataMode, observed)}
        />
        <OnboardingSummaryItem
          href={routeHref("architecture")}
          label={t("onboardingView.resourcesObserved")}
          value={observed
            ? data.present_resource_count.toLocaleString()
            : kpiEvidenceLabel("not-connected")}
          hint={t(
            observed ? "onboardingView.resourceGapCount" : "onboardingView.requiredResourceCount",
            { count: resourceGapCount },
          )}
          evidenceState={summaryEvidenceState(dataMode, observed)}
        />
        <OnboardingSummaryItem
          href={routeHref("settings-iam", { segments: ["requests"] })}
          label={t("onboardingView.rolesObserved")}
          value={observed
            ? data.present_role_count.toLocaleString()
            : kpiEvidenceLabel("not-connected")}
          hint={t(
            observed ? "onboardingView.roleGapCount" : "onboardingView.requiredRoleCount",
            { count: roleGapCount },
          )}
          evidenceState={summaryEvidenceState(dataMode, observed)}
        />
        <OnboardingSummaryItem
          href={routeHref("provision")}
          label={t("onboardingView.lastChecked")}
          value={!observed
            ? kpiEvidenceLabel("not-connected")
            : checkedAt === null
            ? kpiEvidenceLabel("not-measured")
            : formatConsoleTimestamp(checkedAt)}
          hint={t(observed ? "onboardingView.requestCompleted" : "onboardingView.noObservation")}
          evidenceState={summaryEvidenceState(dataMode, observed && checkedAt !== null)}
        />
      </section>
      <nav class="onboarding-actions" aria-label={t("onboardingView.drilldowns")}>
        <strong>{t("onboardingView.resolveInOwningSurface")}</strong>
        <div class="onboarding-action-links">
          <a class="btn secondary" href={routeHref("provision")}>
            {t("onboardingView.openProvisioning")}
          </a>
          <a
            class="btn secondary"
            href={routeHref("settings-iam", { segments: ["requests"] })}
          >
            {t("onboardingView.reviewAccess")}
          </a>
        </div>
      </nav>
      <div class="onboarding-details">
        <ResourceRequirements resources={data.missing_resources} observed={observed} />
        <RoleRequirements assignments={data.missing_role_assignments} observed={observed} />
      </div>
      <OnboardingSource dataMode={dataMode} observed={observed} />
    </div>
  );
}

function ResourceRequirements({
  resources,
  observed,
}: {
  readonly resources: readonly string[];
  readonly observed: boolean;
}) {
  return (
    <section class="onboarding-section" aria-labelledby="onboarding-resource-title">
      <header class="onboarding-section-header">
        <h3 id="onboarding-resource-title">
          {t(observed ? "onboardingView.missingResources" : "onboardingView.requiredResources")}
        </h3>
        <span class="onboarding-count">{resources.length}</span>
      </header>
      {resources.length > 0 ? (
        <ul class="onboarding-resource-list">
          {resources.map((resource) => {
            const copy = onboardingResourceCopy(resource);
            return (
              <li key={resource}>
                <span class="onboarding-gap-icon" aria-hidden="true">{observed ? "!" : "i"}</span>
                <span class="onboarding-resource-copy">
                  <strong>{copy.label}</strong>
                  <small>{copy.description}</small>
                </span>
                <code>{resource}</code>
              </li>
            );
          })}
        </ul>
      ) : <p class="onboarding-empty muted">{t("onboardingView.none")}</p>}
    </section>
  );
}

function RoleRequirements({
  assignments,
  observed,
}: {
  readonly assignments: readonly (readonly [string, string, string])[];
  readonly observed: boolean;
}) {
  return (
    <section class="onboarding-section" aria-labelledby="onboarding-role-title">
      <header class="onboarding-section-header">
        <h3 id="onboarding-role-title">
          {t(observed ? "onboardingView.missingRoles" : "onboardingView.requiredRoles")}
        </h3>
        <span class="onboarding-count">{assignments.length}</span>
      </header>
      {assignments.length > 0 ? (
        <div class="onboarding-role-table-wrap">
          <table class="onboarding-role-table">
            <caption class="sr-only">
              {t(observed ? "onboardingView.missingRoleCaption" : "onboardingView.requiredRoleCaption")}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("onboardingView.principal")}</th>
                <th scope="col">{t("onboardingView.role")}</th>
                <th scope="col">{t("onboardingView.target")}</th>
                <th scope="col">{t("onboardingView.status")}</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map(([principal, role, target]) => (
                <tr key={`${principal}:${role}:${target}`}>
                  <td data-label={t("onboardingView.principal")}>
                    <strong>{onboardingPrincipalLabel(principal)}</strong>
                    <code>{principal}</code>
                  </td>
                  <td data-label={t("onboardingView.role")}>
                    <span>{onboardingRoleLabel(role)}</span>
                    <code>{role}</code>
                  </td>
                  <td data-label={t("onboardingView.target")}>
                    <span>{onboardingResourceCopy(target).label}</span>
                    <code>{target}</code>
                  </td>
                  <td data-label={t("onboardingView.status")}>
                    <StatusPill
                      kind={observed ? "danger" : "neutral"}
                      label={t(observed ? "onboardingView.missing" : "onboardingView.required")}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p class="onboarding-empty muted">{t("onboardingView.none")}</p>}
    </section>
  );
}

function OnboardingSource({
  dataMode,
  observed,
}: {
  readonly dataMode: ConsoleDataMode;
  readonly observed: boolean;
}) {
  const source = dataMode === "sample"
    ? "Sample"
    : observed
    ? "Observed"
    : "Baseline";
  return (
    <aside class="onboarding-source" aria-label={t("onboardingView.sourceDetails")}>
      <StatusPill
        kind={source === "Observed" ? "info" : "neutral"}
        label={t(`onboardingView.source${source}`)}
      />
      <span>{t(`onboardingView.source${source}Description`)}</span>
    </aside>
  );
}

type OnboardingSummaryEvidence = "measured" | "not-connected" | "synthetic";

function summaryEvidenceState(
  dataMode: ConsoleDataMode,
  observed: boolean,
): OnboardingSummaryEvidence {
  if (dataMode === "sample") return "synthetic";
  return observed ? "measured" : "not-connected";
}

function OnboardingSummaryItem({
  href,
  label,
  value,
  hint,
  evidenceState,
}: {
  readonly href: string;
  readonly label: string;
  readonly value: ComponentChildren;
  readonly hint: string;
  readonly evidenceState: OnboardingSummaryEvidence;
}) {
  return (
    <a
      class="onboarding-summary-item"
      data-evidence-state={evidenceState}
      href={href}
    >
      <span class="onboarding-summary-label">{label}</span>
      <span class="onboarding-summary-value">{value}</span>
      <span class="onboarding-summary-hint">{hint}</span>
    </a>
  );
}

const KNOWN_ONBOARDING_RESOURCES = new Set([
  "executor_identity",
  "runtime",
  "container_registry",
  "state_store",
  "event_bus",
  "secret_store",
  "observability_logs",
  "observability_apm",
]);

function onboardingResourceCopy(
  resource: string,
): { readonly label: string; readonly description: string } {
  if (!KNOWN_ONBOARDING_RESOURCES.has(resource)) {
    return {
      label: formatMachineLabel(resource),
      description: t("onboardingView.resourceRequirement"),
    };
  }
  return {
    label: t(`onboardingView.resources.${resource}.label`),
    description: t(`onboardingView.resources.${resource}.description`),
  };
}

function onboardingPrincipalLabel(principal: string): string {
  return principal === "executor"
    ? t("onboardingView.principals.executor")
    : formatMachineLabel(principal);
}

function onboardingRoleLabel(role: string): string {
  return role === "event_bus_data_owner" || role === "secret_reader"
    ? t(`onboardingView.roles.${role}`)
    : formatMachineLabel(role);
}

function formatMachineLabel(value: string): string {
  const words = value.split(/[_-]+/).filter(Boolean);
  if (words.length === 0) return value;
  return words
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ");
}
