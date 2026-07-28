import { useEffect, useRef } from "preact/hooks";
import { ErrorState, LoadingState, StatusPill, UnavailableState } from "../components/ui";
import { CONTROL_STATUS_PILL } from "./best-practice-controls-body";
import type { BestPracticeDetailState } from "./best-practice-controls";
import type { BestPracticeDetail } from "./best-practice-controls.model";
import { displayValue, t } from "./i18n/governance";
import { DetailRow, DetailSection } from "./rule-catalog-components";
import { SEVERITY_PILL } from "./rule-catalog-types";

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
        <StatusPill kind={SEVERITY_PILL[data.severity] ?? "neutral"} label={displayValue("severity", data.severity)} />
        <StatusPill kind="info" label={displayValue("controlPillar", data.pillar)} />
      </div>
      <section class="rule-overview">
        <h4 class="rule-overview-title">{data.title}</h4>
        <p class="rule-overview-desc">{data.rationale}</p>
      </section>
      <UnavailableState evidenceState="not-connected" message={t("governance.rules.controls.detail.notConnected")} />
      <dl class="detail-grid">
        <DetailRow label={t("governance.rules.controls.detail.framework")} value={data.framework} mono />
        <DetailRow label={t("governance.common.version")} value={data.version} mono />
        <DetailRow label={t("governance.rules.controls.detail.mode")} value={data.requirement_mode} />
        <DetailRow label={t("governance.rules.controls.column.owner")} value={data.owner ?? "-"} mono />
      </dl>
      <DetailSection title={t("governance.rules.controls.detail.requirements")}>
        <div class="control-requirement-list">
          {data.requirements.map((requirement) => (
            <article key={`${requirement.kind}:${requirement.ref}`} class="control-requirement-row">
              <div><span class="muted small">{requirement.kind}</span><code>{requirement.ref}</code></div>
              <StatusPill kind={CONTROL_STATUS_PILL[requirement.status]} label={displayValue("controlStatus", requirement.status)} />
            </article>
          ))}
        </div>
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
