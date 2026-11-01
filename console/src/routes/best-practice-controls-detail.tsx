import { useEffect, useRef, useState } from "preact/hooks";
import { CopyButton, ErrorState, LoadingState, type PillKind, StatusPill, UnavailableState } from "../components/ui";
import { CONTROL_STATUS_PILL } from "./best-practice-controls-body";
import type { BestPracticeDetailState } from "./best-practice-controls";
import type {
  BestPracticeDetail,
  RequirementRuleCoverage,
  RuleCoverageSummary,
} from "./best-practice-controls.model";
import { displayValue, t } from "./i18n/governance";
import { DetailRow, DetailSection } from "./rule-catalog-components";
import { ruleCatalogHref, type RuleFilters } from "./rule-catalog-state";
import { SEVERITY_PILL } from "./rule-catalog-types";
import { FrameworkGuidanceContent } from "./framework-guidance";
import { formatGuidanceMarkdownBrief } from "./wara-guidance";
import { getLocale } from "../i18n";
import { ControlEnablementSection } from "./control-enablement";
import { ControlRemediationSection } from "./control-remediation";

const EMPTY_RULE_FILTERS: RuleFilters = { origin: "", category: "", severity: "", source: "", q: "" };

export function BestPracticeDrawer({
  detail,
  onClose,
}: {
  readonly detail: BestPracticeDetailState;
  readonly onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => previous?.focus?.();
  }, []);
  const selectedControlId = detail.status === "ready" ? detail.data.control_id : "";
  useEffect(() => {
    const body = panelRef.current?.querySelector<HTMLElement>(".rule-drawer-body");
    if (body) body.scrollTop = 0;
  }, [selectedControlId]);

  function trapFocus(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || panelRef.current === null) return;
    const focusables = Array.from(
      panelRef.current.querySelectorAll<HTMLElement>(
        'summary, a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => {
      const closed = element.closest("details:not([open])");
      return element.getClientRects().length > 0 && (closed === null || element === closed.querySelector(":scope > summary"));
    });
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div class="drawer-overlay" onClick={onClose}>
      <aside id="best-practice-control-detail" ref={panelRef} tabIndex={-1} class={`rule-drawer wara-drawer${expanded ? " is-expanded" : ""}`} role="dialog" aria-modal="true" aria-label={t("governance.rules.controls.detail.aria")} onClick={(event) => event.stopPropagation()} onKeyDown={trapFocus}>
        <header class="rule-drawer-head">
          <h3 class="mono">{detail.status === "ready" ? detail.data.control_id : t("governance.rules.controls.detail.title")}</h3>
          <div class="rule-drawer-actions">
            {detail.status === "ready" ? (
              <>
                <CopyButton text={detail.data.control_id} label={t("governance.common.copyId")} />
                {detail.data.guidance ? (
                  <CopyButton
                    text={formatGuidanceMarkdownBrief(detail.data.control_id, detail.data.guidance, getLocale())}
                    label={t("governance.common.copyBrief")}
                  />
                ) : null}
              </>
            ) : null}
            <CopyButton text={window.location.href} label={t("governance.common.copyLink")} />
            <button type="button" class="btn" onClick={onClose} aria-label={t("governance.common.close")}>{t("governance.common.close")}</button>
          </div>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? <LoadingState label={t("governance.rules.controls.detail.loading")} /> : detail.status === "error" ? <ErrorState message={t("governance.rules.controls.detail.loadFailed", { message: detail.message })} /> : <BestPracticeDetailContent data={detail.data} expanded={expanded} onExpand={() => setExpanded((value) => !value)} />}
        </div>
      </aside>
    </div>
  );
}

function BestPracticeDetailContent({ data, expanded, onExpand }: { readonly data: BestPracticeDetail; readonly expanded: boolean; readonly onExpand: () => void }) {
  const provenance = Object.fromEntries(
    Object.entries(data.provenance).filter(([, value]) => typeof value === "string" && value.length > 0),
  ) as Readonly<Record<string, string>>;
  return (
    <div class="stack">
      <FrameworkGuidanceContent guidance={data.guidance} controlId={data.control_id} title={data.title} description={data.rationale} expanded={expanded} onExpand={onExpand} unavailableReason={data.guidance_unavailable_reason} />
      <h3 id="framework-runtime" tabIndex={-1}>{t("governance.rules.wara.guidance.runtime")}</h3>
      <ControlEnablementSection value={data.enablement} severitySource={data.severity_source} />
      <ControlRemediationSection value={data.remediation} />
      <div class="pill-row">
        <StatusPill kind={CONTROL_STATUS_PILL[data.status]} label={displayValue("controlStatus", data.status)} />
        <StatusPill kind="info" label={displayValue("controlMapping", data.mapping_status)} />
        <StatusPill kind="neutral" label={displayValue("controlEvaluation", data.evaluation_status)} />
        <StatusPill kind={SEVERITY_PILL[data.severity] ?? "neutral"} label={displayValue("severity", data.severity)} />
        <StatusPill kind="info" label={displayValue("controlPillar", data.pillar)} />
      </div>
      {data.evaluation_status === "not_evaluated" ? (
        <UnavailableState evidenceState="not-connected" message={t("governance.rules.controls.detail.notConnected")} />
      ) : null}
      <dl class="detail-grid">
        <DetailRow label={t("governance.rules.controls.detail.framework")} value={data.framework} mono />
        <DetailRow label={t("governance.common.version")} value={data.version} mono />
        <DetailRow label={t("governance.rules.controls.detail.mode")} value={displayValue("requirementMode", data.requirement_mode)} />
        <DetailRow label={t("governance.rules.controls.column.catalog")} value={displayValue("catalogStatus", data.catalog_status)} />
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
      {data.rule_coverage ? <RuleCoverageSection coverage={data.rule_coverage} /> : null}
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
                {requirement.coverage
                  && (requirement.coverage.activated || !requirement.limitations.includes("rule_not_activated")) ? (
                  <RequirementCoverage id={requirement.ref} coverage={requirement.coverage} />
                ) : null}
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
          <DetailRow label={t("governance.rules.controls.detail.limitations")} value={data.limitations.map((code) => displayValue("requirementLimitation", code)).join(", ") || "-"} />
        </dl>
      </DetailSection>
      <DetailSection title={t("governance.rules.detail.provenance")}>
        <dl class="detail-grid">
          {Object.entries(provenance).map(([key, value]) => (
            <DetailRow key={key} label={displayValue("provenanceKey", key)} value={value} mono />
          ))}
        </dl>
      </DetailSection>
    </div>
  );
}

const COVERAGE_STATUS_PILL: Readonly<Record<RuleCoverageSummary["status"], PillKind>> = {
  current: "success",
  stale: "warning",
  unavailable: "neutral",
};

function RuleCoverageSection({ coverage }: { readonly coverage: RuleCoverageSummary }) {
  return (
    <DetailSection title={t("governance.rules.controls.detail.ruleCoverage")}>
      <p class="muted footnote">{t("governance.rules.controls.detail.ruleCoverageHint")}</p>
      <div class="pill-row">
        <StatusPill kind={COVERAGE_STATUS_PILL[coverage.status]} label={displayValue("ruleCoverageStatus", coverage.status)} />
      </div>
      {coverage.reason ? <p class="muted small">{displayValue("ruleCoverageReason", coverage.reason)}</p> : null}
      {coverage.matches_assessment_scope === false ? (
        <p class="muted small">{t("governance.rules.controls.detail.ruleCoverageOtherScope")}</p>
      ) : null}
      {coverage.scope_digest ? (
        <dl class="detail-grid">
          <DetailRow label={t("governance.rules.controls.detail.ruleCoverageScope")} value={coverage.scope_digest} mono />
          <DetailRow label={t("governance.rules.controls.detail.ruleCoverageResources")} value={String(coverage.resource_count ?? "-")} />
          <DetailRow label={t("governance.rules.controls.detail.ruleCoverageInventory")} value={coverage.inventory_generation ?? "-"} mono />
          <DetailRow label={t("governance.rules.controls.detail.ruleCoverageActivation")} value={coverage.rule_activation_generation_id ?? "-"} mono />
          <DetailRow label={t("governance.rules.controls.detail.ruleCoverageRecordedAt")} value={coverage.recorded_at ?? "-"} mono />
        </dl>
      ) : null}
    </DetailSection>
  );
}

function RequirementCoverage({
  id,
  coverage,
}: {
  readonly id: string;
  readonly coverage: RequirementRuleCoverage;
}) {
  if (!coverage.activated) {
    return (
      <p class="muted small control-requirement-coverage" aria-label={t("governance.rules.controls.detail.ruleCoverageAria", { id })}>
        {t("governance.rules.controls.detail.ruleCoverageNotActivated")}
      </p>
    );
  }
  const anomalies = coverage.duplicate + coverage.conflicting + coverage.unexpected + coverage.revision_mismatch;
  return (
    <div class="control-requirement-coverage" aria-label={t("governance.rules.controls.detail.ruleCoverageAria", { id })}>
      <p class="small">
        {t("governance.rules.controls.detail.ruleCoverageCounts", {
          eligible: coverage.eligible,
          compliant: coverage.compliant,
          violated: coverage.violated,
          held: coverage.held_for_review,
          missing: coverage.missing,
        })}
      </p>
      {anomalies > 0 ? (
        <p class="muted small">
          {t("governance.rules.controls.detail.ruleCoverageAnomalies", {
            duplicate: coverage.duplicate,
            conflicting: coverage.conflicting,
            unexpected: coverage.unexpected,
            revision: coverage.revision_mismatch,
          })}
        </p>
      ) : null}
    </div>
  );
}
