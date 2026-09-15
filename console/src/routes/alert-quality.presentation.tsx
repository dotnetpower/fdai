/** Evidence and plan presentation; absent projections never become inferred operational facts. */
import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { EmptyState, LoadingState, UnavailableState, type AsyncState } from "../components/ui";
import { getLocale } from "../i18n";
import { navigate, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { ALERT_UNKNOWN_FACET, filterAlertFindings } from "./alert-quality.facets";
import {
  ALERT_FINDINGS_PAGE_SIZE, alertQualityFreshness, alertQualityRequestable,
  type AlertNoiseAssessment, type AlertNoiseFinding, type AlertQualityPayload, type AlertQualityPlan,
} from "./alert-quality.model";
import type { AlertQualityCommandState } from "./alert-quality.requests";
import { alertQualityText as text, type AlertQualityMessage } from "./i18n/alert-quality";

/** Reuse shared form geometry and semantic descriptions rather than decorative cards or rails. */
export function AlertQualityFacts({ children }: { readonly children: ComponentChildren }) {
  return <dl class="form-grid" style={{ margin: 0, gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))" }}>{children}</dl>;
}
export function AlertQualityFact({ label, children }: { readonly label: string; readonly children: ComponentChildren }) {
  return <div style={{ minWidth: 0 }}><dt class="muted">{label}</dt><dd style={{ margin: "8px 0 0", overflowWrap: "anywhere" }}>{children}</dd></div>;
}
export function AlertQualityTime({ value }: { readonly value: string }) {
  return <time dateTime={value}>{formatConsoleTimestamp(value)}</time>;
}
const Facts = AlertQualityFacts;
const Fact = AlertQualityFact;
const Time = AlertQualityTime;

/** Null is unmeasured; zero is formatted only when the server supplied zero. */
export function alertQualityCount(value: number | null): string {
  return value === null ? text("notMeasured") : new Intl.NumberFormat(getLocale()).format(value);
}

/** Stable, content-free explanations; arbitrary dependency prose never reaches the page. */
export function alertQualityReason(reason: string): string {
  const labels: Readonly<Record<string, AlertQualityMessage>> = {
    scope_not_configured: "reason.scope_not_configured", scope_required: "scopeRequired",
    source_unavailable: "loadUnavailable", assessment_missing: "notPublished",
    assessment_not_current: "reason.assessment_not_current", assessment_expired: "reason.assessment_expired",
    assessment_pending: "reason.assessment_pending", proposal_pending: "reason.proposal_pending",
    stale_evidence: "reason.assessment_not_current", evidence_incomplete: "reason.evidenceHeld",
    target_not_observed: "reason.targetHeld", protected_alert: "reason.protectedHeld",
    active_incident_dependency: "reason.incidentHeld", disabled_detector: "reason.targetHeld",
    iac_ownership_missing: "reason.ownershipHeld", service_ownership_missing: "reason.ownershipHeld",
    processing_semantics_unknown: "reason.processingHeld", overlapping_suppression: "reason.processingHeld",
    group_dependencies_incomplete: "reason.dependenciesHeld", dependent_outside_scope: "reason.dependenciesHeld",
    automation_path_protected: "reason.protectedHeld", audience_incomplete: "reason.audienceHeld",
    audience_empty: "reason.audienceHeld", responder_coverage_missing: "reason.audienceHeld",
    no_delivery_path: "reason.audienceHeld", independent_collection_missing: "reason.collectionHeld",
    processing_target_not_inert: "reason.processingHeld", processing_target_scope_mismatch: "reason.processingHeld",
    suppression_window_missing: "reason.windowHeld", suppression_window_exceeds_policy: "reason.windowHeld",
    propagation_budget_insufficient: "reason.propagationHeld", evaluation_kind_unsupported: "reason.evaluationHeld",
    evaluation_requires_single_axis: "reason.evaluationAxisHeld", evaluation_validation_missing: "reason.evaluationEvidenceHeld",
    evaluation_validation_mismatch: "reason.evaluationEvidenceMismatch",
    routing_source_mismatch: "reason.routingHeld", routing_replacement_missing: "reason.routingHeld",
    routing_replacement_already_bound: "reason.routingHeld", suppression_deadline_does_not_fit: "reason.windowHeld",
    delivery_coverage_incomplete: "reason.deliveryCoverage", history_coverage_incomplete: "reason.historyCoverage",
    routing_coverage_incomplete: "reason.audienceHeld",
    candidate_limit_reached: "reason.candidateLimit", evidence_reason_limit_reached: "reason.reasonLimit",
    request_expired: "reason.requestExpired", scope_denied: "reason.scopeDenied",
    evidence_not_retained: "reason.evidenceMissing", evidence_unavailable: "reason.evidenceHeld",
    synthetic_live_evidence: "reason.syntheticHeld",
    preference_store_unavailable: "settings.reason.store", writer_unavailable: "settings.reason.writer",
    producer_not_ready: "settings.reason.producer",
  };
  return text(Object.hasOwn(labels, reason) ? labels[reason]! : "reason.held");
}

/** Pending commands use the shared accessible skeleton from their first waiting frame. */
export function CommandFeedback({ command, onStop }: { readonly command: AlertQualityCommandState; readonly onStop: () => void }) {
  if (command === "idle") return null;
  if (command === "pending") return <section class="stack-section">
    <LoadingState label={text("command.pending")} />
    <button class="btn" style={{ minHeight: 44, alignSelf: "start" }} type="button"
      aria-describedby="alert-quality-stop-help" onClick={onStop}>{text("stop")}</button>
    <p id="alert-quality-stop-help" class="muted">{text("stopHelp")}</p>
  </section>;
  return <p role="status" aria-live="polite">{text(`command.${command}`)}</p>;
}

/** Initial and expired reports do not disable a ready producer; command uncertainty still does. */
export function AlertQualityRequestControls({ state, command, onRefresh, onAssess, onStop, periodSeconds, onPeriodChange, preferenceHeld = false }: {
  readonly state: AsyncState<AlertQualityPayload>; readonly command: AlertQualityCommandState;
  readonly onRefresh: () => void; readonly onAssess: (periodSeconds?: number) => void; readonly onStop: () => void;
  readonly periodSeconds: number; readonly onPeriodChange: (seconds: number) => void;
  readonly preferenceHeld?: boolean;
}) {
  const waiting = command === "pending";
  const held = waiting || command === "unknown" || command === "rejected" || command === "blocked";
  const requestable = !held && !preferenceHeld && state.status === "ready" && alertQualityRequestable(state.data);
  return <section class="stack-section" aria-label={text("assessmentRequests")}>
    <label style={{ minWidth: 0, display: "grid", gap: 8 }}>
      <span>{text("requestedPeriod")}</span>
      <select class="cs-control-select" name="period_seconds" value={periodSeconds} disabled={waiting}
        style={{ minHeight: 44, minWidth: 0, width: "100%" }} aria-describedby="alert-quality-period-help"
        onChange={(event) => onPeriodChange(Number(event.currentTarget.value))}>
        {[3600, 86400, 604800].map((seconds) => <option key={seconds} value={seconds}>{text(`period.${seconds}` as AlertQualityMessage)}</option>)}
      </select>
    </label>
    <p class="muted" id="alert-quality-period-help">{text("requestedPeriodHelp")}</p>
    <div class="toolbar">
      <button class="btn" type="button" style={{ minHeight: 44 }} disabled={waiting || state.status === "loading"}
        onClick={onRefresh}>{text("refresh")}</button>
      <button class="btn" type="button" style={{ minHeight: 44 }} disabled={!requestable}
        aria-describedby="alert-quality-assess-help" onClick={() => { if (requestable) onAssess(periodSeconds); }}>{text("assess")}</button>
    </div>
    <p id="alert-quality-assess-help" class="muted">{text("assessHelp")}</p>
    {preferenceHeld ? <p class="muted">{text("settings.requestHold")}</p> : null}
    <CommandFeedback command={command} onStop={onStop} />
  </section>;
}

/** Show the exact observed window when supplied; retained v1 gaps never use cutoff/validity instead. */
export function AlertQualityEvidence({ report, now }: { readonly report: AlertNoiseAssessment; readonly now: number }) {
  const metrics = [
    ["sourceEpisodes", report.source_episodes], ["attempts", report.notification_attempts],
    ["deliveries", report.confirmed_deliveries], ["acknowledgements", report.acknowledgements],
  ] as const;
  return <section class="stack" id="alert-quality-evidence" aria-labelledby="alert-quality-evidence-title">
    <h3 id="alert-quality-evidence-title">{text("evidence")}</h3>
    <Facts>{metrics.map(([key, value]) => <Fact key={key} label={text(key)}>
      <a href="#alert-quality-findings" style={{ display: "inline-flex", alignItems: "center", minHeight: 44 }}>
        {key === "sourceEpisodes" && value === null ? text("unknown")
          : alertQualityCount(report.coverage === "unavailable" ? null : value)}
      </a>
    </Fact>)}</Facts>
    <p class="muted">{text("denominators")}</p>
    {report.coverage !== "complete" ? <UnavailableState message={text("partialCounts")} /> : null}
    <Facts>
      <Fact label={text("coverage")}>{text(`coverage.${report.coverage}`)}</Fact>
      <Fact label={text("cutoff")}><Time value={report.observed_at} /></Fact>
      <Fact label={text("validUntil")}><Time value={report.valid_until} /></Fact>
      <Fact label={text("freshness")}>{text(`freshness.${alertQualityFreshness(report.observed_at, report.valid_until, now)}`)}</Fact>
      <Fact label={text("period")}>{report.window_start != null && report.window_end != null
        ? <><Time value={report.window_start} /> - <Time value={report.window_end} /><br /><span class="muted">{text("periodHelp")}</span></>
        : text("periodMissing")}</Fact>
    </Facts>
    <details>
      <summary style={{ minHeight: 44, cursor: "pointer" }}>{text("technical")}</summary>
      <div class="stack-section">
        <Facts>
          <Fact label={text("scope")}>{report.scope_ref}</Fact>
          <Fact label={text("source")}>{report.source}</Fact>
          <Fact label={text("evidenceDigest")}>{report.evidence_digest}</Fact>
          <Fact label={text("policyDigest")}>{report.policy_digest}</Fact>
          <Fact label={text("reason")}>{report.reasons.length === 0 ? text("noReasons")
            : [...new Set(report.reasons.map(alertQualityReason))].join(" ")}</Fact>
        </Facts>
        <p class="muted">{text("clockNote")}</p>
      </div>
    </details>
  </section>;
}

/** Facets narrow returned evidence only; missing ownership/routing has its own unknown choice. */
export function AlertQualityFindings({ report, rule, invalidRule }: {
  readonly report: AlertNoiseAssessment; readonly rule: string | null; readonly invalidRule: boolean;
}) {
  const [page, setPage] = useState(0);
  const [service, setService] = useState("");
  const [team, setTeam] = useState("");
  const [audience, setAudience] = useState("");
  const rules = [...new Set(report.findings.map((row) => row.rule_ref))].sort();
  const services = [...new Set(report.findings.map((row) => row.service_ref))].sort();
  const teams = [...new Set(report.findings.flatMap((row) => row.team_refs ?? []))].sort();
  const audiences = [...new Set(report.findings.flatMap((row) => row.audience_kinds ?? []))].sort();
  const rows = invalidRule ? [] : filterAlertFindings(report.findings, { rule, service, team, audience });
  const start = Math.min(page, Math.max(0, Math.ceil(rows.length / ALERT_FINDINGS_PAGE_SIZE) - 1)) * ALERT_FINDINGS_PAGE_SIZE;
  return <section class="stack-section" id="alert-quality-findings" aria-labelledby="alert-quality-findings-title">
    <h3 id="alert-quality-findings-title">{text("findings")}</h3>
    <div class="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))" }}>
      <label style={{ minWidth: 0 }}><span>{text("rule")}</span>
        <select style={{ minHeight: 44, minWidth: 0, width: "100%" }} value={rule ?? ""}
          aria-invalid={invalidRule} onChange={(event) => navigate(routeHref("alert-quality", {
            params: { scope_ref: report.scope_ref, ...(event.currentTarget.value ? { rule_ref: event.currentTarget.value } : {}) },
          }))}>
          <option value="">{text("allRules")}</option>
          {rule !== null && !rules.includes(rule) ? <option value={rule}>{rule}</option> : null}
          {rules.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label style={{ minWidth: 0 }}><span>{text("service")}</span>
        <select style={{ minHeight: 44, minWidth: 0, width: "100%" }} value={service}
          onChange={(event) => { setService(event.currentTarget.value); setPage(0); }}>
          <option value="">{text("allServices")}</option>
          {services.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label style={{ minWidth: 0 }}><span>{text("team")}</span>
        <select name="team_ref" style={{ minHeight: 44, minWidth: 0, width: "100%" }} value={team}
          onChange={(event) => { setTeam(event.currentTarget.value); setPage(0); }}>
          <option value="">{text("allTeams")}</option>
          <option value={ALERT_UNKNOWN_FACET}>{text("unknown")}</option>
          {teams.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label style={{ minWidth: 0 }}><span>{text("audienceKind")}</span>
        <select name="audience_kind" style={{ minHeight: 44, minWidth: 0, width: "100%" }} value={audience}
          onChange={(event) => { setAudience(event.currentTarget.value); setPage(0); }}>
          <option value="">{text("allAudienceKinds")}</option>
          <option value={ALERT_UNKNOWN_FACET}>{text("unknown")}</option>
          {audiences.map((value) => <option key={value} value={value}>{text(`audience.${value}`)}</option>)}
        </select>
      </label>
    </div>
    <p class="muted">{text("filterLimits")}</p>
    {rule !== null || invalidRule ? <a style={{ display: "inline-flex", alignItems: "center", minHeight: 44 }}
      href={routeHref("alert-quality", { params: { scope_ref: report.scope_ref } })}>{text("allRules")}</a> : null}
    {invalidRule ? <UnavailableState message={text("invalidRule")} />
      : rows.length === 0 ? <EmptyState title={text(rule === null && service === "" && team === "" && audience === "" ? "noFindings" : "noMatchedRule")} />
        : <>
          <AlertQualityFindingTable rows={rows.slice(start, start + ALERT_FINDINGS_PAGE_SIZE)} scope={report.scope_ref} coverage={report.coverage} />
          <div class="toolbar">
            <button type="button" class="btn" style={{ minHeight: 44 }} disabled={start === 0} onClick={() => setPage(Math.max(0, start / ALERT_FINDINGS_PAGE_SIZE - 1))}>{text("previous")}</button>
            <span role="status">{text("page", { start: start + 1, end: Math.min(rows.length, start + ALERT_FINDINGS_PAGE_SIZE), total: rows.length })}</span>
            <button type="button" class="btn" style={{ minHeight: 44 }} disabled={start + ALERT_FINDINGS_PAGE_SIZE >= rows.length} onClick={() => setPage(start / ALERT_FINDINGS_PAGE_SIZE + 1)}>{text("next")}</button>
          </div>
        </>}
    <p class="muted">{text("potentialHelp")}</p>
  </section>;
}

/** Native links preserve exact opaque identities; table overflow stays inside a keyboard region. */
export function AlertQualityFindingTable({ rows, scope, coverage }: {
  readonly rows: readonly AlertNoiseFinding[]; readonly scope: string; readonly coverage: AlertNoiseAssessment["coverage"];
}) {
  const headers: readonly AlertQualityMessage[] = ["rule", "reason", "guidance", "sourceEpisodes", "deliveries", "potential", "protection"];
  const count = (value: number | null) => alertQualityCount(coverage === "unavailable" ? null : value);
  const potential = (value: number | null) => coverage === "unavailable" || value === null ? text("unknown") : alertQualityCount(value);
  return <div style={{ maxWidth: "100%", minWidth: 0, overflowX: "auto" }} tabIndex={0} role="region" aria-label={text("findings")}>
    <table class="data-table" style={{ minWidth: 840 }}>
      <caption>{text("findings")}</caption>
      <thead><tr>{headers.map((key) => <th key={key} scope="col" style={{ color: "var(--fg)" }}>{text(key)}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={`${row.rule_ref}:${row.reason}:${index}`}>
        <td><a style={{ display: "inline-flex", alignItems: "center", minHeight: 44 }} href={routeHref("alert-quality", { params: { scope_ref: scope, rule_ref: row.rule_ref } })}>{row.rule_ref}</a><br />{text("service")}: {row.service_ref}
          <br />{text("team")}: {row.team_refs?.join(", ") ?? text("unknown")}
          <br />{text("audienceKind")}: {row.audience_kinds == null ? text("unknown") : row.audience_kinds.length === 0 ? text("noAudience") : row.audience_kinds.map((kind) => text(`audience.${kind}`)).join(", ")}
        </td>
        <td>{text(`reason.${row.reason}`)}</td><td>{text(`guidance.${row.guidance}`)}<br />{text("duplicates")}: {count(row.duplicate_paths)}</td>
        <td class="num">{row.source_episodes === null ? text("unknown") : count(row.source_episodes)}</td>
        <td class="num">{count(row.observed_deliveries)}</td>
        <td class="num">{potential(row.potential_recipients_lower)} / {potential(row.potential_recipients_upper)}</td>
        <td>{text(row.protected ? "protected" : "notProtected")}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}

/** Required approvers, protected paths, recovery and outcome remain independent of plan presence. */
export function AlertQualityPlans({ plans, now }: { readonly plans: readonly AlertQualityPlan[]; readonly now: number }) {
  return <section class="stack" id="alert-quality-plans" aria-labelledby="alert-quality-plans-title">
    <h3 id="alert-quality-plans-title">{text("plans")}</h3>
    <a style={{ alignSelf: "start", display: "inline-flex", alignItems: "center", minHeight: 44 }} href={routeHref("hil-queue")}>{text("approvals")}</a>
    <p class="muted">{text("approvalsHelp")}</p>
    <Facts>
      <Fact label={text("expectedBenefit")}>{text("benefitMissing")}</Fact>
      <Fact label={text("protectedPaths")}>{text("protectedPathsMissing")}</Fact>
      <Fact label={text("outcome")}>{text("outcomeMissing")}</Fact>
    </Facts>
    {plans.length === 0 ? <UnavailableState message={text("noPlans")} /> : plans.map((plan, index) => <details key={`${plan.evidence_digest}:${plan.created_at}:${index}`}>
      <summary style={{ minHeight: 44, overflowWrap: "anywhere", cursor: "pointer" }}>
        {text("planDetails", { number: index + 1, target: plan.treatment.target_ref })} - {text(`kind.${plan.treatment.kind}`)}
      </summary>
      <div class="stack" style={{ padding: "8px 0 16px" }}>
        <strong>{text("shadow")}</strong>
        <Facts>
          <Fact label={text("scope")}>{plan.scope_ref}</Fact>
          <Fact label={text("action")}>{plan.action_type === "ops.restore-alert-configuration" ? text("restore") : text(`kind.${plan.treatment.kind}`)}<br />{plan.action_type}</Fact>
          <Fact label={text("created")}><Time value={plan.created_at} /></Fact>
          <Fact label={text("expires")}><Time value={plan.expires_at} /><br />{text(`freshness.${alertQualityFreshness(plan.created_at, plan.expires_at, now)}`)}</Fact>
        </Facts>
        <AlertQualityTreatmentView plan={plan} />
        <Facts>
          <Fact label={text("requiredQuorum")}>{plan.quorum_required}</Fact>
          <Fact label={text("services")}>{plan.service_refs.join(", ")}</Fact>
          <Fact label={text("targetRevision")}>{plan.target_revision}</Fact>
          <Fact label={text("rollback")}>{plan.rollback_ref}</Fact>
          <Fact label={text("evidenceDigest")}>{plan.evidence_digest}</Fact>
          <Fact label={text("policyDigest")}>{plan.policy_digest}</Fact>
          <Fact label={text("locks")}>{plan.lock_refs.join(", ")}</Fact>
          <Fact label={text("executionBound")}>{plan.max_execution_seconds}</Fact>
          <Fact label={text("observationBound")}>{plan.max_observation_seconds}</Fact>
          <Fact label={text("recoveryBound")}>{plan.max_recovery_seconds}</Fact>
          {plan.treatment.kind === "evaluation" || plan.evaluation_receipt_digest != null
            ? <Fact label={text("evaluationReceipt")}>{plan.evaluation_receipt_digest ?? text("evaluationReceiptMissing")}</Fact> : null}
        </Facts>
        {plan.treatment.kind === "evaluation" ? <p class="muted">{text("evaluationReceiptHelp")}</p> : null}
        <p>{text("quorumHelp")}</p><p class="muted">{text("deliveryPath")}</p>
      </div>
    </details>)}
  </section>;
}

export function AlertQualityTreatmentView({ plan, baselineAvailable = false }: { readonly plan: AlertQualityPlan; readonly baselineAvailable?: boolean }) {
  const treatment = plan.treatment;
  if (treatment.kind === "routing") return <section class="stack-section">
    <h4>{text("treatmentDiff")}</h4>
    <Facts>
      <Fact label={text("rule")}>{treatment.target_ref}</Fact>
      <Fact label={text("removedBinding")}>{treatment.remove_group_ref}</Fact>
      <Fact label={text("addedBinding")}>{treatment.replacement_group_ref}</Fact>
    </Facts>
    {baselineAvailable ? null : <p class="muted">{text("beforeMissing")}</p>}
  </section>;
  return <section class="stack-section">
    <h4>{text("treatmentDiff")}</h4>
    <Facts><Fact label={text("rule")}>{treatment.target_ref}</Fact></Facts>
    {baselineAvailable ? null : <><h4>{text("before")}</h4><p class="muted">{text("beforeMissing")}</p></>}
    <h4>{text("after")}</h4>
    {treatment.kind === "suppression" ? <>
      <Facts>
        <Fact label={text("processingRule")}>{treatment.processing_rule_ref}</Fact>
        <Fact label={text("starts")}><Time value={treatment.starts_at} /></Fact>
        <Fact label={text("ends")}><Time value={treatment.ends_at} /></Fact>
      </Facts><p class="muted">{text("suppressionHelp")}</p>
    </> : <>
      <Facts>
        <Fact label={text("metric")}>{treatment.evaluation.metric_ref}</Fact>
        <Fact label={text("operator")}>{text(`operator.${treatment.evaluation.operator}`)}</Fact>
        <Fact label={text("threshold")}>{String(treatment.evaluation.threshold)}</Fact>
        <Fact label={text("window")}>{treatment.evaluation.window_seconds}</Fact>
        <Fact label={text("frequency")}>{treatment.evaluation.frequency_seconds}</Fact>
        <Fact label={text("aggregation")}>{text(`aggregation.${treatment.evaluation.aggregation}`)}</Fact>
      </Facts><p class="muted">{text("evaluationHelp")}</p>
    </>}
  </section>;
}
