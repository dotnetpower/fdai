/** Request history and exact recorded proposal detail; current approvals/outcomes live in Process. */
import { useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import { AsyncBoundary, EmptyState, type AsyncState } from "../components/ui";
import { routeHref } from "../router";
import type { AlertQualityIdentity } from "./alert-quality.controller";
import type { AlertQualityScopes } from "./alert-quality.scopes";
import { createAlertHistorySession } from "./alert-quality.history.requests";
import type { AlertProposalDetail, AlertRequestHistory, AlertRequestRecord } from "./alert-quality.history.model";
import type { AlertQualityPlan } from "./alert-quality.model";
import { AlertQualityFact as Fact, AlertQualityFacts as Facts, AlertQualityTime as Time, AlertQualityTreatmentView, alertQualityCount, alertQualityReason } from "./alert-quality.presentation";
import { alertQualityText as text } from "./i18n/alert-quality";

export function AlertQualityHistory({ identity, scopes, scope, onReconciled }: {
  readonly identity: AlertQualityIdentity; readonly scopes: AlertQualityScopes; readonly scope: string;
  readonly onReconciled: () => void;
}) {
  const binding = useMemo(() => ({ identity, scopes, scope }), [identity, scopes, scope]);
  const latest = useRef(binding), callback = useRef(onReconciled);
  latest.current = binding; callback.current = onReconciled;
  const [result, setResult] = useState<{ owner: typeof binding; value: AsyncState<AlertRequestHistory> }>({ owner: binding, value: { status: "loading" } });
  const session = useRef<ReturnType<typeof createAlertHistorySession> | null>(null);
  const current = () => latest.current === binding && identity.current() && identity.scopeCurrent(scopes) && scopes.scope_refs.includes(scope);
  useLayoutEffect(() => {
    const owner = createAlertHistorySession(identity.client, scope, identity.memory, current,
      (value) => setResult({ owner: binding, value }), () => callback.current());
    session.current = owner;
    void owner.load();
    return () => { owner.dispose(); if (session.current === owner) session.current = null; };
  }, [binding]);
  const state: AsyncState<AlertRequestHistory> = result.owner === binding && current() ? result.value : { status: "loading" };
  return <section class="alert-quality-section alert-quality-history" aria-labelledby="alert-quality-history-title">
    <h3 id="alert-quality-history-title">{text("history.title")}</h3>
    <p class="muted">{text("history.help")}</p>
    <button class="btn" type="button" style={{ minHeight: 44, alignSelf: "start" }} disabled={state.status === "loading"}
      onClick={() => { if (current()) void session.current?.load(true); }}>{text("history.refresh")}</button>
    <AsyncBoundary state={state} resourceLabel={text("history.title")}>{(data) => <>
      <p class="muted">{text("history.readAt")}: <Time value={data.read_at} /></p>
      {data.truncated ? <p role="status">{text("history.truncated")}</p> : null}
      {data.requests.length === 0 ? <EmptyState title={text("history.empty")} /> : data.requests.map((entry) => <RequestView key={entry.request_ref} entry={entry} />)}
    </>}</AsyncBoundary>
  </section>;
}

export function RequestView({ entry }: { readonly entry: AlertRequestRecord }) {
  return <details>
    <summary style={{ minHeight: 44, cursor: "pointer", overflowWrap: "anywhere" }}>
      {text(`history.status.${entry.status}`)} - {text(entry.operation === "alert_noise.assess" ? "assessmentRequests" : "plans")}
    </summary>
    <section class="stack-section">
      <Facts>
        <Fact label={text("history.accepted")}><Time value={entry.accepted_at} /></Fact>
        <Fact label={text("history.deadline")}><Time value={entry.expires_at} /></Fact>
        <Fact label={text("history.terminal")}>{entry.result_recorded_at === null ? text("unknown") : <Time value={entry.result_recorded_at} />}</Fact>
        <Fact label={text("reason")}>{entry.reason === null ? text("noReasons") : alertQualityReason(entry.reason)}</Fact>
      </Facts>
      <p class="muted">{text("history.ref")}: {entry.request_ref}</p>
      {entry.detail === null || entry.plan === null ? <p class="muted">{text("history.detailMissing")}</p> : <AlertRecordedDetail detail={entry.detail} plan={entry.plan} />}
    </section>
  </details>;
}

export function AlertRecordedDetail({ detail, plan }: { readonly detail: AlertProposalDetail; readonly plan: AlertQualityPlan }) {
  const baseline = detail.baseline.rule, evaluation = baseline.evaluation, processing = detail.baseline.processing_rule;
  const metrics = detail.evaluation;
  return <div class="stack" style={{ minWidth: 0 }}>
    <h4>{text("before")}</h4>
    <Facts>
      <Fact label={text("rule")}>{baseline.ref}</Fact>
      <Fact label={text("history.resource")}>{baseline.resource_ref}</Fact>
      <Fact label={text("service")}>{baseline.service_ref}</Fact>
      <Fact label={text("history.baselineEnabled")}>{text(baseline.enabled ? "history.enabled" : "history.disabled")}</Fact>
      <Fact label={text("history.stateful")}>{text(baseline.stateful ? "history.yes" : "history.no")}</Fact>
      <Fact label={text("history.incident")}>{text(baseline.active_incident ? "history.yes" : "history.no")}</Fact>
      <Fact label={text("history.iacOwner")}>{text(baseline.iac_owned ? "history.yes" : "history.no")}</Fact>
      <Fact label={text("history.serviceOwner")}>{text(baseline.ownership_verified ? "history.yes" : "history.no")}</Fact>
      <Fact label={text("history.baselineGroups")}>{baseline.group_refs.join(", ") || text("history.none")}</Fact>
      <Fact label={text("history.classification")}>{text(`history.classification.${baseline.classification}`)}</Fact>
      <Fact label={text("history.severity")}>{alertQualityCount(baseline.severity)}</Fact>
      <Fact label={text("targetRevision")}>{baseline.revision}</Fact>
      {evaluation === null ? null : <>
        <Fact label={text("metric")}>{evaluation.metric_ref}</Fact>
        <Fact label={text("threshold")}>{String(evaluation.threshold)}</Fact>
        <Fact label={text("window")}>{evaluation.window_seconds}</Fact>
        <Fact label={text("frequency")}>{evaluation.frequency_seconds}</Fact>
        <Fact label={text("operator")}>{text(`operator.${evaluation.operator}`)}</Fact>
        <Fact label={text("aggregation")}>{text(`aggregation.${evaluation.aggregation}`)}</Fact>
      </>}
      {processing === null ? null : <>
        <Fact label={text("processingRule")}>{processing.ref}</Fact>
        <Fact label={text("history.baselineEnabled")}>{text(processing.enabled ? "history.enabled" : "history.disabled")}</Fact>
        <Fact label={text("starts")}>{processing.effective_from === null ? text("unknown") : <Time value={processing.effective_from} />}</Fact>
        <Fact label={text("ends")}>{processing.effective_to === null ? text("unknown") : <Time value={processing.effective_to} />}</Fact>
      </>}
    </Facts>
    <AlertQualityTreatmentView plan={plan} baselineAvailable />
    {metrics === null ? <p class="muted">{text("history.metricsMissing")}</p> : <section class="stack-section">
      <h4>{text("history.guards")}</h4>
      <p class="muted">{text("history.guardHelp")}</p>
      <Facts>
        <Fact label={text("history.truePositive")}>{metrics.baseline_true_positive} / {metrics.treatment_true_positive}</Fact>
        <Fact label={text("history.falsePositive")}>{metrics.baseline_false_positive} / {metrics.treatment_false_positive}</Fact>
        <Fact label={text("history.falseNegative")}>{metrics.baseline_false_negative} / {metrics.treatment_false_negative}</Fact>
        <Fact label={text("history.latency")}>{alertQualityCount(metrics.baseline_max_latency_seconds)} / {alertQualityCount(metrics.treatment_max_latency_seconds)}</Fact>
        <Fact label={text("history.scenarios")}>{metrics.scenario_digest}</Fact>
      </Facts>
    </section>}
    <section class="stack-section">
      <h4>{text("history.process")}</h4><p class="muted">{text("history.processHelp")}</p>
      {detail.process === null ? <p>{text("history.processMissing")}</p> : <>
        <p>{detail.process.workflow_ref} - {text(`history.processStatus.${detail.process.status}`)}</p>
        <p class="muted">{text("history.terminal")}: <Time value={detail.recorded_at} /></p>
        <a style={{ display: "inline-flex", alignItems: "center", minHeight: 44 }} href={routeHref("processes", { segments: [detail.process.process_id] })}>{text("history.openProcess")}</a>
      </>}
    </section>
  </div>;
}
