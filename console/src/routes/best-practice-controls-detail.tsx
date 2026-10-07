import { useEffect, useRef } from "preact/hooks";
import { ErrorState, LoadingState, StatusPill, UnavailableState } from "../components/ui";
import { CONTROL_STATUS_PILL } from "./best-practice-controls-body";
import type { BestPracticeDetailState } from "./best-practice-controls";
import type { BestPracticeDetail } from "./best-practice-controls.model";
import { displayValue, t } from "./i18n/governance";
import { DetailRow, DetailSection } from "./rule-catalog-components";
import { ruleCatalogHref, type RuleFilters } from "./rule-catalog-state";
import { SEVERITY_PILL } from "./rule-catalog-types";

const EMPTY_RULE_FILTERS: RuleFilters = { origin: "", category: "", severity: "", source: "", q: "" };

export function BestPracticeDrawer({
  detail,
  onClose,
}: {
  readonly detail: BestPracticeDetailState;
  readonly onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => previous?.focus?.();
  }, []);

  function trapFocus(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || panelRef.current === null) return;
    const focusables = panelRef.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div class="drawer-overlay" onClick={onClose}>
      <aside ref={panelRef} tabIndex={-1} class="rule-drawer" role="dialog" aria-modal="true" aria-label={t("governance.rules.controls.detail.aria")} onClick={(event) => event.stopPropagation()} onKeyDown={trapFocus}>
        <header class="rule-drawer-head">
          <h3 class="mono">{detail.status === "ready" ? detail.data.control_id : t("governance.rules.controls.detail.title")}</h3>
          <button type="button" class="btn" onClick={onClose} aria-label={t("governance.common.close")}>{t("governance.common.close")}</button>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? <LoadingState label={t("governance.rules.controls.detail.loading")} /> : detail.status === "error" ? <ErrorState message={t("governance.rules.controls.detail.loadFailed", { message: detail.message })} /> : <BestPracticeDetailContent data={detail.data} />}
        </div>
      </aside>
    </div>
  );
}

function BestPracticeDetailContent({ data }: { readonly data: BestPracticeDetail }) {
  const provenance = Object.fromEntries(
    Object.entries(data.provenance).filter(([, value]) => typeof value === "string" && value.length > 0),
  ) as Readonly<Record<string, string>>;
  return (
    <div class="stack">
      <div class="pill-row">
        <StatusPill kind={CONTROL_STATUS_PILL[data.status]} label={displayValue("controlStatus", data.status)} />
        <StatusPill kind="info" label={displayValue("controlMapping", data.mapping_status)} />
        <StatusPill kind="neutral" label={displayValue("controlEvaluation", data.evaluation_status)} />
        <StatusPill kind={SEVERITY_PILL[data.severity] ?? "neutral"} label={displayValue("severity", data.severity)} />
        <StatusPill kind="info" label={displayValue("controlPillar", data.pillar)} />
      </div>
      <section class="rule-overview">
        <h4 class="rule-overview-title">{data.title}</h4>
        <p class="rule-overview-desc">{data.rationale}</p>
      </section>
      {data.evaluation_status === "not_evaluated" ? (
        <UnavailableState evidenceState="not-connected" message={t("governance.rules.controls.detail.notConnected")} />
      ) : null}
      <dl class="detail-grid">
        <DetailRow label={t("governance.rules.controls.detail.framework")} value={data.framework} mono />
        <DetailRow label={t("governance.common.version")} value={data.version} mono />
        <DetailRow label={t("governance.rules.controls.detail.mode")} value={data.requirement_mode} />
        <DetailRow label={t("governance.rules.controls.column.catalog")} value={data.catalog_status} />
        <DetailRow label={t("governance.rules.controls.column.mapping")} value={displayValue("controlMapping", data.mapping_status)} />
        <DetailRow label={t("governance.rules.controls.column.evaluation")} value={displayValue("controlEvaluation", data.evaluation_status)} />
        <DetailRow label={t("governance.rules.controls.column.applicability")} value={displayValue("controlStatus", data.applicability)} />
        <DetailRow label={t("governance.rules.controls.column.satisfaction")} value={displayValue("controlStatus", data.satisfaction)} />
        <DetailRow label={t("governance.rules.controls.detail.scope")} value={data.evaluation_scope ?? "-"} mono />
        <DetailRow label={t("governance.rules.controls.detail.evaluatedAt")} value={data.evaluated_at ?? "-"} mono />
        <DetailRow label={t("governance.rules.controls.column.owner")} value={data.owner ?? "-"} mono />
        <DetailRow label={t("governance.rules.controls.detail.cadence")} value={t("governance.rules.controls.detail.cadenceDays", { days: data.cadence_days })} />
        <DetailRow label={t("governance.rules.controls.detail.profile")} value={data.profile_id ?? "-"} mono />
        <DetailRow label={t("governance.rules.controls.detail.profileDigest")} value={data.profile_digest ?? "-"} mono />
      </dl>
      {data.approved_exception ? (
        <DetailSection title={t("governance.rules.controls.detail.approvedException")}>
          <dl class="detail-grid">
            <DetailRow label={t("governance.rules.controls.detail.justification")} value={data.approved_exception.justification} />
            <DetailRow label={t("governance.rules.controls.detail.approvedBy")} value={data.approved_exception.approved_by} mono />
            <DetailRow label={t("governance.rules.controls.detail.expiresAt")} value={data.approved_exception.expires_at} mono />
          </dl>
        </DetailSection>
      ) : null}
      <DetailSection title={t("governance.rules.controls.detail.requirements")}>
        <p class="muted footnote">{t("governance.rules.controls.detail.requirementsHint")}</p>
        <div class="control-requirement-list">
          {data.requirements.map((requirement) => (
            <article key={`${requirement.kind}:${requirement.ref}`} class="control-requirement-row">
              <div>
                <span class="muted small">{displayValue("controlRequirementKind", requirement.kind)}</span>
                {requirement.kind === "rule" ? (
                  <a
                    href={ruleCatalogHref(EMPTY_RULE_FILTERS, 0, { id: requirement.ref, origin: "active" })}
                    aria-label={t("governance.rules.controls.detail.openRule", { id: requirement.ref })}
                  >
                    <code>{requirement.ref}</code>
                  </a>
                ) : <code>{requirement.ref}</code>}
                {requirement.limitations.length > 0 ? (
                  <ul class="control-requirement-limitations" aria-label={t("governance.rules.controls.detail.requirementLimitations")}>
                    {requirement.limitations.map((code) => (
                      <li key={code} class="muted small">{displayValue("requirementLimitation", code)}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <StatusPill kind={CONTROL_STATUS_PILL[requirement.status]} label={displayValue("controlStatus", requirement.status)} />
            </article>
          ))}
        </div>
      </DetailSection>
      <DetailSection title={t("governance.rules.controls.detail.evidence")}>
        <dl class="detail-grid">
          <DetailRow label={t("governance.rules.controls.detail.evidenceRefs")} value={data.evidence_refs.join(", ") || "-"} mono />
          <DetailRow label={t("governance.rules.controls.detail.evidenceDigests")} value={data.evidence_digests.join(", ") || "-"} mono />
          <DetailRow label={t("governance.rules.controls.detail.limitations")} value={data.limitations.join(", ") || "-"} />
        </dl>
      </DetailSection>
      <DetailSection title={t("governance.rules.detail.provenance")}>
        <dl class="detail-grid">
          {Object.entries(provenance).map(([key, value]) => (
            <DetailRow key={key} label={key.replace(/_/g, " ")} value={value} mono />
          ))}
        </dl>
      </DetailSection>
    </div>
  );
}
