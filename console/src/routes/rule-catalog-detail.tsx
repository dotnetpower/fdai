import { useEffect, useRef } from "preact/hooks";
import { architectureHref } from "../components/architecture-map.model";
import {
  CopyButton,
  ErrorState,
  ExternalLink,
  LoadingState,
  StatusPill,
} from "../components/ui";
import { routeHref } from "../router";
import { t } from "./i18n/governance";
import { DetailRow, DetailSection } from "./rule-catalog-components";
import {
  SEVERITY_PILL,
  type DetailState,
  type FindingsState,
  type RuleDetailDto,
} from "./rule-catalog-types";

interface RuleDetailDrawerProps {
  readonly detail: DetailState;
  readonly findings: FindingsState;
  readonly onClose: () => void;
}

export function RuleDetailDrawer({ detail, findings, onClose }: RuleDetailDrawerProps) {
  // WCAG dialog behaviour: move focus into the drawer on open, restore
  // it to the trigger on close, and trap Tab within the drawer.
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => previouslyFocused?.focus?.();
  }, []);

  function trapFocus(e: KeyboardEvent): void {
    if (e.key === "Escape") {
      // Handle Escape on the drawer itself so it closes regardless of
      // which focusable inside it currently holds focus.
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || panelRef.current === null) return;
    const focusables = panelRef.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) return;
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return (
    <div class="drawer-overlay" onClick={onClose}>
      <aside
        ref={panelRef}
        tabIndex={-1}
        class="rule-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={t("governance.rules.detail.aria")}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={trapFocus}
      >
        <header class="rule-drawer-head">
          <h3 class="mono">
            {detail.status === "ready" ? detail.data.id : t("governance.rules.detail.title")}
          </h3>
          <div class="rule-drawer-actions">
            <CopyButton text={window.location.href} label={t("governance.common.copyLink")} />
            <button type="button" class="btn" onClick={onClose} aria-label={t("governance.common.close")}>
              {t("governance.common.close")}
            </button>
          </div>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? (
            <LoadingState label={t("governance.rules.detail.loading")} />
          ) : detail.status === "unavailable" ? (
            <div class="state-block state-unavailable rule-citation-unavailable" role="alert">
              <span class="state-icon" aria-hidden="true">?</span>
              <div>
                <strong>{t("governance.rules.detail.historicalUnavailable")}</strong>
                <p>{t("governance.rules.detail.historicalBody", { id: detail.ruleId })}</p>
                <a href={routeHref("rules", { params: { q: detail.ruleId } })}>
                  {t("governance.rules.detail.searchCurrent")}
                </a>
              </div>
            </div>
          ) : detail.status === "error" ? (
            <ErrorState message={t("governance.rules.detail.loadFailed", { message: detail.message })} />
          ) : (
            <RuleDetailContent data={detail.data} findings={findings} />
          )}
        </div>
      </aside>
    </div>
  );
}

function RuleDetailContent({
  data,
  findings,
}: {
  readonly data: RuleDetailDto;
  readonly findings: FindingsState;
}) {
  return (
    <div class="stack">
      <div class="pill-row">
        <StatusPill kind={data.origin === "active" ? "enforce" : "neutral"} label={data.origin} />
        <StatusPill kind={SEVERITY_PILL[data.severity] ?? "neutral"} label={data.severity} />
        <StatusPill kind="info" label={data.category} />
      </div>

      <RuleOverview data={data} />

      <AffectedResources findings={findings} />

      <dl class="detail-grid">
        <DetailRow label={t("governance.rules.detail.source")} value={data.source} />
        <DetailRow label={t("governance.rules.detail.resourceType")} value={data.resource_type} mono />
        <DetailRow label={t("governance.common.version")} value={data.version} mono />
        <DetailRow label={t("governance.rules.detail.remediates")} value={data.remediates} mono />
        {data.alternatives.length > 0 ? (
          <DetailRow label={t("governance.rules.detail.alternatives")} value={data.alternatives.join(", ")} mono />
        ) : null}
        <DetailRow
          label={t("governance.rules.detail.costImpact")}
          value={
            data.remediation.cost_impact_monthly_usd == null
              ? "-"
              : `$${data.remediation.cost_impact_monthly_usd.toFixed(2)}`
          }
        />
      </dl>

      <DetailSection
        title={t("governance.rules.detail.checkLogic")}
        subtitle={`${data.check_logic.kind} - ${data.check_logic.reference}`}
        action={
          data.check_logic_body !== null ? <CopyButton text={data.check_logic_body} /> : null
        }
      >
        {data.check_logic_body !== null ? (
          <pre class="mono code-block drawer-code">{data.check_logic_body}</pre>
        ) : (
          <p class="muted footnote">
            {t("governance.rules.detail.noCheckBody", { kind: data.check_logic.kind })}
          </p>
        )}
      </DetailSection>

      <DetailSection
        title={t("governance.rules.detail.fix")}
        subtitle={data.remediation.template_ref}
        action={
          data.remediation_body !== null ? <CopyButton text={data.remediation_body} /> : null
        }
      >
        {data.remediation_body !== null ? (
          <pre class="mono code-block drawer-code">{data.remediation_body}</pre>
        ) : (
          <p class="muted footnote">{t("governance.rules.detail.noFixBody")}</p>
        )}
      </DetailSection>

      {Object.keys(data.parameters).length > 0 ? (
        <DetailSection title={t("governance.rules.detail.parameters")}>
          <pre class="mono small entry-json">{JSON.stringify(data.parameters, null, 2)}</pre>
        </DetailSection>
      ) : null}

      <DetailSection title={t("governance.rules.detail.provenance")}>
        <dl class="detail-grid">
          <DetailRow
            label={t("governance.rules.detail.sourceUrl")}
            value={<ExternalLink href={data.provenance.source_url}>{data.provenance.source_url}</ExternalLink>}
          />
          <DetailRow label={t("governance.rules.detail.license")} value={data.provenance.license} />
          <DetailRow label={t("governance.rules.detail.redistribution")} value={data.provenance.redistribution} />
          <DetailRow label={t("governance.rules.detail.contentHash")} value={data.provenance.content_hash} mono />
          <DetailRow label={t("governance.rules.detail.resolvedRef")} value={data.provenance.resolved_ref} mono />
          <DetailRow label={t("governance.rules.detail.retrievedAt")} value={data.provenance.retrieved_at} mono />
        </dl>
      </DetailSection>
    </div>
  );
}

function RuleOverview({ data }: { readonly data: RuleDetailDto }) {
  const { explanation } = data;
  const heading = explanation.title ?? data.id;
  const detailEntries = Object.entries(explanation.details ?? {});
  return (
    <section class="rule-overview">
      <h4 class="rule-overview-title">{heading}</h4>
      <p class={`risk-line risk-${data.severity}`}>
        {t(`governance.rules.severityRisk.${data.severity}`) === `governance.rules.severityRisk.${data.severity}`
          ? t("governance.rules.detail.severityFallback", { severity: data.severity })
          : t(`governance.rules.severityRisk.${data.severity}`)}
      </p>
      {explanation.description ? (
        <p class="rule-overview-desc">{explanation.description}</p>
      ) : (
        <p class="muted footnote">
          {t("governance.rules.detail.noDescription")}
        </p>
      )}
      {detailEntries.length > 0 ? (
        <dl class="detail-grid">
          {detailEntries.map(([key, value]) => (
            <DetailRow key={key} label={key.replace(/_/g, " ")} value={String(value)} mono />
          ))}
        </dl>
      ) : null}
    </section>
  );
}

function AffectedResources({ findings }: { readonly findings: FindingsState }) {
  if (findings.status === "loading") {
    return (
      <DetailSection title={t("governance.rules.detail.affected")}>
        <LoadingState label={t("governance.rules.detail.evaluatingAffected")} />
      </DetailSection>
    );
  }
  if (findings.status === "error") {
    return (
      <DetailSection title={t("governance.rules.detail.affected")}>
        <ErrorState message={t("governance.rules.detail.affectedFailed", { message: findings.message })} />
      </DetailSection>
    );
  }

  const { data } = findings;
  if (!data.evaluated) {
    return (
      <DetailSection title={t("governance.rules.detail.affected")}>
        <p class="muted footnote">{t("governance.rules.detail.inventoryUnavailable")}</p>
      </DetailSection>
    );
  }
  if (data.findings.length === 0) {
    return (
      <DetailSection title={t("governance.rules.detail.affected")}>
        <p class="muted footnote">{t("governance.rules.detail.noViolations")}</p>
      </DetailSection>
    );
  }

  return (
    <DetailSection title={t("governance.rules.detail.affectedCount", { count: data.finding_count ?? data.findings.length })}>
      <ul class="finding-list">
        {data.findings.map((finding, index) => (
          <li key={finding.resource_id + index} class="finding-item">
            <div class="finding-head">
              <span class="mono finding-res">{finding.resource_name ?? finding.resource_id}</span>
              <a class="finding-architecture-link" href={architectureHref(finding.resource_id)}>
                {t("governance.rules.detail.viewArchitecture")}
              </a>
              {finding.severity ? (
                <StatusPill kind={SEVERITY_PILL[finding.severity] ?? "neutral"} label={finding.severity} />
              ) : null}
            </div>
            {finding.problem ? <p class="finding-problem">{finding.problem}</p> : null}
            {finding.resource_name && finding.resource_name !== finding.resource_id ? (
              <p class="muted footnote mono">{finding.resource_id}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </DetailSection>
  );
}
