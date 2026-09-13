import { t } from "../i18n";
import { tDashboard } from "./i18n/dashboard-essential";

/** Keeps absent or empty evidence discoverable without reserving chart space. */
export function EvidenceSummary({ label, href, state = "unavailable", description }: {
  readonly label: string;
  readonly href: string;
  readonly state?: "unavailable" | "empty";
  readonly description?: string | undefined;
}) {
  return (
    <a class="overview-evidence-row" href={href} data-evidence-state={state}>
      <span class="overview-evidence-label">{label}</span>
      <span class="overview-evidence-state">
        {state === "empty" ? tDashboard("noRecordedEntries") : t("overview.evidence.unavailable")}
      </span>
      <span class="overview-evidence-action">{tDashboard("viewEvidence")}</span>
      {description && <small class="overview-evidence-description">{description}</small>}
    </a>
  );
}

/** Indicates an in-flight optional read, never a missing or fabricated value. */
export function EvidenceLoading({ label }: { readonly label: string }) {
  return (
    <span class="overview-evidence-loading" role="status" aria-busy="true">
      <span class="sr-only">{t("shared.loadingResource", { resource: label })}</span>
      <span class="skeleton-shimmer" aria-hidden="true" />
    </span>
  );
}
