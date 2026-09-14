import type { ComponentChildren } from "preact";
import { routeHref } from "../router";
import { t } from "./i18n/evidence";
import { TraceFact, TraceMetric } from "./rule-trace-layout";

interface Props {
  readonly correlationId: string;
  readonly message?: string;
  readonly status: "idle" | "loading" | "unavailable" | "error";
  readonly toolbar: ComponentChildren;
}

export function RuleTracePlaceholder({
  correlationId,
  message,
  status,
  toolbar,
}: Props) {
  const auditHref = routeHref("audit", {
    params: correlationId ? { correlation: correlationId } : {},
  });
  const statusLabel = t(`evidence.trace.placeholder.state.${status}`);
  const detailTitle = t(`evidence.trace.placeholder.title.${status}`);
  const detailBody = message ?? t(`evidence.trace.placeholder.body.${status}`);

  return (
    <div class="trace-ready-workspace trace-placeholder-workspace">
      <section class="trace-metrics" aria-label={t("evidence.trace.summaryLabel")}>
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.summary.decision")}
          value={t("evidence.trace.notLoaded")}
          hint={t("evidence.trace.placeholder.metricDecision")}
        />
        <TraceMetric
          href={routeHref("rca", {
            params: correlationId ? { correlation: correlationId } : {},
          })}
          label={t("evidence.trace.summary.rootCause")}
          value={t("evidence.trace.notLoaded")}
          hint={t("evidence.trace.placeholder.metricRootCause")}
        />
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.summary.pipelineStages")}
          value={t("evidence.trace.notLoaded")}
          hint={t("evidence.trace.placeholder.metricStages")}
        />
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.steps")}
          value={t("evidence.trace.notLoaded")}
          hint={t("evidence.trace.placeholder.metricSteps")}
        />
      </section>

      {toolbar}

      <section
        class="trace-workbench trace-workbench-placeholder"
        aria-label={t("evidence.trace.workbenchLabel")}
        aria-busy={status === "loading"}
      >
        <aside class="trace-stage-rail">
          <header class="trace-pane-head">
            <div>
              <h3>{t("evidence.trace.recordedStages")}</h3>
              <p>{t("evidence.trace.recordedOrder")}</p>
            </div>
            <span>{t("evidence.trace.notLoaded")}</span>
          </header>
          <div class="trace-stage-empty">
            <span aria-hidden="true">-</span>
            <strong>{t("evidence.trace.placeholder.railTitle")}</strong>
            <p>{t("evidence.trace.placeholder.railBody")}</p>
          </div>
        </aside>

        <div
          class={`trace-step-detail trace-placeholder-detail is-${status}`}
          id="trace-selected-stage-detail"
          role={status === "error" ? "alert" : "status"}
          aria-live={status === "error" ? "assertive" : "polite"}
        >
          <header class="trace-step-head">
            <div>
              <span class="trace-step-kicker">{statusLabel}</span>
              <h3>{detailTitle}</h3>
              <p>{detailBody}</p>
            </div>
            <span class={`trace-placeholder-state is-${status}`}>{statusLabel}</span>
          </header>

          <dl class="trace-step-facts">
            <TraceFact
              label={t("evidence.trace.placeholder.projection")}
              value={t("evidence.trace.placeholder.auditProjection")}
            />
            <TraceFact
              label={t("evidence.trace.placeholder.selection")}
              value={correlationId || t("evidence.trace.notSelected")}
            />
            <TraceFact
              label={t("evidence.trace.placeholder.authority")}
              value={t("evidence.common.readOnly")}
            />
            <TraceFact
              label={t("evidence.trace.placeholder.effect")}
              value={t("evidence.trace.placeholder.none")}
            />
          </dl>

          <section class="trace-placeholder-guidance">
            <div>
              <h4>{t("evidence.trace.placeholder.nextTitle")}</h4>
              <p>{t("evidence.trace.placeholder.nextBody")}</p>
            </div>
            <a class="btn" href={auditHref}>{t("evidence.trace.placeholder.openAudit")}</a>
          </section>
        </div>
      </section>
    </div>
  );
}
