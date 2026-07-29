import { useEffect, useRef } from "preact/hooks";
import { ErrorState, LoadingState, StatusPill } from "../components/ui";
import { displayValue, t } from "./i18n/governance";
import { MCSB_COVERAGE_PILL } from "./mcsb-controls-body";
import type { McsbDetailState } from "./mcsb-controls";
import type { McsbControlDetail } from "./mcsb-controls.model";
import { DetailRow, DetailSection } from "./rule-catalog-components";

export function McsbControlDrawer({
  detail,
  onClose,
}: {
  readonly detail: McsbDetailState;
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
      <aside ref={panelRef} tabIndex={-1} class="rule-drawer" role="dialog" aria-modal="true" aria-label={t("governance.rules.mcsb.detail.aria")} onClick={(event) => event.stopPropagation()} onKeyDown={trapFocus}>
        <header class="rule-drawer-head">
          <h3 class="mono">{detail.status === "ready" ? detail.data.control_id : t("governance.rules.mcsb.detail.title")}</h3>
          <button type="button" class="btn" onClick={onClose} aria-label={t("governance.common.close")}>{t("governance.common.close")}</button>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? <LoadingState label={t("governance.rules.mcsb.detail.loading")} /> : detail.status === "error" ? <ErrorState message={t("governance.rules.mcsb.detail.loadFailed", { message: detail.message })} /> : <McsbControlDetailContent data={detail.data} />}
        </div>
      </aside>
    </div>
  );
}

function ReferenceList({ values }: { readonly values: readonly string[] }) {
  return values.length > 0 ? (
    <div class="mcsb-reference-list">
      {values.map((value) => <code key={value}>{value}</code>)}
    </div>
  ) : (
    <p class="muted">{t("governance.rules.mcsb.detail.none")}</p>
  );
}

function McsbControlDetailContent({ data }: { readonly data: McsbControlDetail }) {
  const source = Object.fromEntries(
    Object.entries(data.source).filter(([, value]) => typeof value === "string" && value.length > 0),
  ) as Readonly<Record<string, string>>;
  return (
    <div class="stack">
      <div class="pill-row">
        <StatusPill kind={MCSB_COVERAGE_PILL[data.coverage]} label={displayValue("mcsbCoverage", data.coverage)} />
        <StatusPill kind="info" label={displayValue("mcsbDomain", data.domain)} />
        <StatusPill kind="neutral" label={data.benchmark_version} />
      </div>
      <section class="rule-overview">
        <h4 class="rule-overview-title">{data.title}</h4>
        <p class="rule-overview-desc">{t("governance.rules.mcsb.detail.boundary")}</p>
      </section>
      <DetailSection title={t("governance.rules.mcsb.detail.rules")}>
        <ReferenceList values={data.rule_ids} />
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
            <DetailRow key={key} label={key.replace(/_/g, " ")} value={value} mono />
          ))}
        </dl>
      </DetailSection>
    </div>
  );
}
