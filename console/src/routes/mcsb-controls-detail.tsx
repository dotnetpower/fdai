import { useEffect, useRef, useState } from "preact/hooks";
import { CopyButton, ErrorState, LoadingState, StatusPill } from "../components/ui";
import { displayValue, t } from "./i18n/governance";
import { MCSB_COVERAGE_PILL, MCSB_SATISFACTION_PILL, mcsbAssessmentSummaryText } from "./mcsb-controls-body";
import type { McsbDetailState } from "./mcsb-controls";
import type { McsbControlDetail } from "./mcsb-controls.model";
import { DetailRow, DetailSection } from "./rule-catalog-components";
import { ruleCatalogHref, type RuleFilters } from "./rule-catalog-state";
import { FrameworkGuidanceContent } from "./framework-guidance";
import { IllustratedGuidanceContent } from "./wara-guidance";
import { buildMcsbV2Guidance, resolveMcsbAiTaxonomy } from "./mcsb-v2-guidance";
import { ControlEnablementSection } from "./control-enablement";
import { ControlRemediationSection } from "./control-remediation";

const EMPTY_RULE_FILTERS: RuleFilters = { origin: "", category: "", severity: "", source: "", q: "" };

export function McsbControlDrawer({
  detail,
  onClose,
}: {
  readonly detail: McsbDetailState;
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
      <aside id="mcsb-control-detail" ref={panelRef} tabIndex={-1} class={`rule-drawer wara-drawer${expanded ? " is-expanded" : ""}`} role="dialog" aria-modal="true" aria-label={t("governance.rules.mcsb.detail.aria")} onClick={(event) => event.stopPropagation()} onKeyDown={trapFocus}>
        <header class="rule-drawer-head">
          <h3 class="mono">{detail.status === "ready" ? detail.data.control_id : t("governance.rules.mcsb.detail.title")}</h3>
          <div class="rule-drawer-actions">
            {detail.status === "ready" ? <CopyButton text={detail.data.control_id} label={t("governance.common.copyId")} /> : null}
            <CopyButton text={window.location.href} label={t("governance.common.copyLink")} />
            <button type="button" class="btn" onClick={onClose} aria-label={t("governance.common.close")}>{t("governance.common.close")}</button>
          </div>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? <LoadingState label={t("governance.rules.mcsb.detail.loading")} /> : detail.status === "error" ? <ErrorState message={t("governance.rules.mcsb.detail.loadFailed", { message: detail.message })} /> : <McsbControlDetailContent data={detail.data} expanded={expanded} onExpand={() => setExpanded((value) => !value)} />}
        </div>
      </aside>
    </div>
  );
}

function ReferenceList({ values, linkRules = false }: { readonly values: readonly string[]; readonly linkRules?: boolean }) {
  return values.length > 0 ? (
    <div class="mcsb-reference-list">
      {values.map((value) =>
        linkRules ? (
          <a
            key={value}
            href={ruleCatalogHref(EMPTY_RULE_FILTERS, 0, { id: value, origin: "active" })}
            aria-label={t("governance.rules.controls.detail.openRule", { id: value })}
          >
            <code>{value}</code>
          </a>
        ) : (
          <code key={value}>{value}</code>
        )
      )}
    </div>
  ) : (
    <p class="muted">{t("governance.rules.mcsb.detail.none")}</p>
  );
}

function McsbControlDetailContent({ data, expanded, onExpand }: { readonly data: McsbControlDetail; readonly expanded: boolean; readonly onExpand: () => void }) {
  const source = Object.fromEntries(
    Object.entries(data.source).filter(([, value]) => typeof value === "string" && value.length > 0),
  ) as Readonly<Record<string, string>>;
  const sourceRevision = typeof source["resolved_ref"] === "string" ? source["resolved_ref"] : "";
  return (
    <div class="stack">
      {data.benchmark_version === "v2-preview" && !data.guidance ? (
        <IllustratedGuidanceContent
          control={{
            id: data.control_id,
            title: data.title,
            description: t("governance.rules.mcsb.detail.boundary"),
            guidance: buildMcsbV2Guidance(data),
            source_version: sourceRevision,
          }}
          expanded={expanded}
          onExpand={onExpand}
          prefix="framework"
        />
      ) : (
        <FrameworkGuidanceContent guidance={data.guidance} controlId={data.control_id} title={data.title} description={t("governance.rules.mcsb.detail.boundary")} expanded={expanded} onExpand={onExpand} unavailableReason={data.guidance_unavailable_reason} />
      )}
      <h3 id="framework-runtime" tabIndex={-1}>{t("governance.rules.wara.guidance.runtime")}</h3>
      <ControlEnablementSection value={data.enablement} severitySource={data.severity_source} />
      <ControlRemediationSection value={data.remediation} />
      <div class="pill-row">
        <StatusPill kind={MCSB_COVERAGE_PILL[data.coverage]} label={displayValue("mcsbCoverage", data.coverage)} />
        <StatusPill kind="info" label={displayValue("mcsbDomain", data.domain)} />
        <StatusPill kind="neutral" label={data.benchmark_version} />
        {resolveMcsbAiTaxonomy(data.control_id) ? (
          <>
            <StatusPill kind="warning" label={resolveMcsbAiTaxonomy(data.control_id)!.owaspLlmRef} />
            <StatusPill kind="info" label={resolveMcsbAiTaxonomy(data.control_id)!.mitreAtlasRef} />
          </>
        ) : null}
      </div>
      <p class="muted">{t("governance.rules.mcsb.detail.boundary")}</p>
      {data.benchmark_version === "v1" ? <McsbAssessmentSection data={data} /> : null}
      <DetailSection title={t("governance.rules.mcsb.detail.rules")}>
        <ReferenceList values={data.rule_ids} linkRules />
      </DetailSection>
      <DetailSection title={t("governance.rules.mcsb.detail.runtime")}>
        <ReferenceList values={data.runtime_observation_ids} />
      </DetailSection>
      <DetailSection title={t("governance.rules.mcsb.detail.manual")}>
        <ReferenceList values={data.manual_evidence_refs} />
      </DetailSection>
      <DetailSection title={t("governance.rules.detail.provenance")}>
        <dl class="detail-grid">
          {Object.entries(source).map(([key, value]) => (
            <DetailRow key={key} label={displayValue("provenanceKey", key)} value={value} mono />
          ))}
        </dl>
      </DetailSection>
    </div>
  );
}

function McsbAssessmentSection({ data }: { readonly data: McsbControlDetail }) {
  const assessment = data.assessment;
  return (
    <DetailSection title={t("governance.rules.mcsb.detail.assessment")}>
      {assessment === null ? (
        <p class="muted">
          {data.assessment_summary?.status === "evaluated"
            ? t("governance.rules.mcsb.detail.assessmentNone")
            : mcsbAssessmentSummaryText(data.assessment_summary)}
        </p>
      ) : (
        <div class="stack">
          <div class="pill-row">
            <StatusPill
              kind={MCSB_SATISFACTION_PILL[assessment.satisfaction]}
              label={displayValue("controlStatus", assessment.satisfaction)}
            />
            <StatusPill kind="neutral" label={displayValue("controlEvaluation", assessment.evaluation_status)} />
          </div>
          <p class="muted">{t("governance.rules.mcsb.detail.assessmentBoundary")}</p>
          <dl class="detail-grid">
            <DetailRow label={t("governance.rules.mcsb.detail.evaluatedAt")} value={assessment.evaluated_at ?? "-"} mono />
          </dl>
          {assessment.requirements.length > 0 ? (
            <ul class="mcsb-assessment-requirements" aria-label={t("governance.rules.mcsb.detail.requirements")}>
              {assessment.requirements.map((requirement) => (
                <li key={`${requirement.kind}:${requirement.ref}`}>
                  {requirement.kind === "rule" ? (
                    <a
                      href={ruleCatalogHref(EMPTY_RULE_FILTERS, 0, { id: requirement.ref, origin: "active" })}
                      aria-label={t("governance.rules.controls.detail.openRule", { id: requirement.ref })}
                    >
                      <code>{requirement.ref}</code>
                    </a>
                  ) : (
                    <code>{requirement.ref}</code>
                  )}
                  <span class="pill-row">
                    <StatusPill
                      kind={requirement.evidence_role === "decisive" ? "info" : "neutral"}
                      label={displayValue("mcsbEvidenceRole", requirement.evidence_role)}
                    />
                    <StatusPill
                      kind={MCSB_SATISFACTION_PILL[requirement.status]}
                      label={displayValue("controlStatus", requirement.status)}
                    />
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </DetailSection>
  );
}
