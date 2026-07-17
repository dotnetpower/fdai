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
        aria-label="Rule detail"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={trapFocus}
      >
        <header class="rule-drawer-head">
          <h3 class="mono">
            {detail.status === "ready" ? detail.data.id : "Rule detail"}
          </h3>
          <div class="rule-drawer-actions">
            <CopyButton text={window.location.href} label="Copy link" />
            <button type="button" class="btn" onClick={onClose} aria-label="Close">
              Close
            </button>
          </div>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? (
            <LoadingState label="Loading rule detail..." />
          ) : detail.status === "unavailable" ? (
            <div class="state-block state-unavailable rule-citation-unavailable" role="alert">
              <span class="state-icon" aria-hidden="true">?</span>
              <div>
                <strong>Historical rule citation unavailable</strong>
                <p>
                  <code>{detail.ruleId}</code> is not in the current rule catalog. It may have
                  been retired, renamed, or excluded from this deployment.
                </p>
                <a href={routeHref("rules", { params: { q: detail.ruleId } })}>
                  Search current catalog
                </a>
              </div>
            </div>
          ) : detail.status === "error" ? (
            <ErrorState message={`Failed to load rule detail: ${detail.message}`} />
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
        <DetailRow label="Source" value={data.source} />
        <DetailRow label="Resource type" value={data.resource_type} mono />
        <DetailRow label="Version" value={data.version} mono />
        <DetailRow label="Remediates" value={data.remediates} mono />
        {data.alternatives.length > 0 ? (
          <DetailRow label="Alternatives" value={data.alternatives.join(", ")} mono />
        ) : null}
        <DetailRow
          label="Cost impact / mo"
          value={
            data.remediation.cost_impact_monthly_usd == null
              ? "-"
              : `$${data.remediation.cost_impact_monthly_usd.toFixed(2)}`
          }
        />
      </dl>

      <DetailSection
        title="Check logic"
        subtitle={`${data.check_logic.kind} - ${data.check_logic.reference}`}
        action={
          data.check_logic_body !== null ? <CopyButton text={data.check_logic_body} /> : null
        }
      >
        {data.check_logic_body !== null ? (
          <pre class="mono code-block drawer-code">{data.check_logic_body}</pre>
        ) : (
          <p class="muted footnote">
            No inline body - this check is an external reference ({data.check_logic.kind}).
          </p>
        )}
      </DetailSection>

      <DetailSection
        title="Remediation"
        subtitle={data.remediation.template_ref}
        action={
          data.remediation_body !== null ? <CopyButton text={data.remediation_body} /> : null
        }
      >
        {data.remediation_body !== null ? (
          <pre class="mono code-block drawer-code">{data.remediation_body}</pre>
        ) : (
          <p class="muted footnote">No inline remediation template body available.</p>
        )}
      </DetailSection>

      {Object.keys(data.parameters).length > 0 ? (
        <DetailSection title="Parameters">
          <pre class="mono small entry-json">{JSON.stringify(data.parameters, null, 2)}</pre>
        </DetailSection>
      ) : null}

      <DetailSection title="Provenance">
        <dl class="detail-grid">
          <DetailRow
            label="Source URL"
            value={<ExternalLink href={data.provenance.source_url}>{data.provenance.source_url}</ExternalLink>}
          />
          <DetailRow label="License" value={data.provenance.license} />
          <DetailRow label="Redistribution" value={data.provenance.redistribution} />
          <DetailRow label="Content hash" value={data.provenance.content_hash} mono />
          <DetailRow label="Resolved ref" value={data.provenance.resolved_ref} mono />
          <DetailRow label="Retrieved at" value={data.provenance.retrieved_at} mono />
        </dl>
      </DetailSection>
    </div>
  );
}

const SEVERITY_RISK: Readonly<Record<string, string>> = {
  critical: "Critical - a violation is an immediate, high-impact exposure.",
  high: "High - a violation is a serious risk that should be fixed promptly.",
  medium: "Medium - a violation weakens posture and should be scheduled.",
  low: "Low - a violation is a minor or best-practice gap.",
};

function RuleOverview({ data }: { readonly data: RuleDetailDto }) {
  const { explanation } = data;
  const heading = explanation.title ?? data.id;
  const detailEntries = Object.entries(explanation.details ?? {});
  return (
    <section class="rule-overview">
      <h4 class="rule-overview-title">{heading}</h4>
      <p class={`risk-line risk-${data.severity}`}>
        {SEVERITY_RISK[data.severity] ?? `Severity: ${data.severity}`}
      </p>
      {explanation.description ? (
        <p class="rule-overview-desc">{explanation.description}</p>
      ) : (
        <p class="muted footnote">
          No authored description for this rule. See the check logic and remediation below for
          what it enforces and how to fix it.
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
      <DetailSection title="Affected resources">
        <LoadingState label="Evaluating affected resources..." />
      </DetailSection>
    );
  }
  if (findings.status === "error") {
    return (
      <DetailSection title="Affected resources">
        <ErrorState message={`Failed to load affected resources: ${findings.message}`} />
      </DetailSection>
    );
  }

  const { data } = findings;
  if (!data.evaluated) {
    return (
      <DetailSection title="Affected resources">
        <p class="muted footnote">
          No inventory evaluation is wired on this deployment. When this rule runs against your
          inventory, each affected resource and the exact attribute at fault (the deny reason)
          appears here.
        </p>
      </DetailSection>
    );
  }
  if (data.findings.length === 0) {
    return (
      <DetailSection title="Affected resources">
        <p class="muted footnote">No resources currently violate this rule.</p>
      </DetailSection>
    );
  }

  return (
    <DetailSection title={`Affected resources (${data.finding_count ?? data.findings.length})`}>
      <ul class="finding-list">
        {data.findings.map((finding, index) => (
          <li key={finding.resource_id + index} class="finding-item">
            <div class="finding-head">
              <span class="mono finding-res">{finding.resource_name ?? finding.resource_id}</span>
              <a class="finding-architecture-link" href={architectureHref(finding.resource_id)}>
                View on architecture
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
