import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import {
  AsyncBoundary,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  kpiEvidenceLabel,
  type AsyncState,
} from "../components/ui";
import { putGovernedJson } from "../governed-command";
import { currentRoute, routeHref } from "../router";
import {
  decodeAssuranceDetail,
  decodeConversationAssurance,
  type AssuranceAssessment,
  type AssuranceDetailPayload,
  type AssuranceVerdict,
  type ConversationAssurancePayload,
} from "./conversation-assurance.model";
import { t } from "./i18n/conversation-assurance";

const REASONS = [
  "wrong_fact",
  "missing_intent",
  "stale_evidence",
  "wrong_scope",
  "inappropriate_abstention",
  "language_quality",
] as const;

export function ConversationAssuranceRoute({
  client,
  auth,
}: {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}) {
  const [state, setState] = useState<AsyncState<ConversationAssurancePayload>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const load = async () => {
    try {
      const data = decodeConversationAssurance(await client.panel<unknown>("/conversation-assurance"));
      setState({ status: "ready", data });
      const requestedTurn = currentRoute().search.get("turn");
      setSelectedId((current) => selectedAssessmentId(data, requestedTurn, current));
    } catch (error) {
      setState({
        status: isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  };
  useEffect(() => { void load(); }, [client]);
  return (
    <div class="stack">
      <PageHeader title={t("assurance.title")} subtitle={t("assurance.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("assurance.resource")}>
        {(data) => (
          <AssuranceBody
            auth={auth}
            client={client}
            data={data}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onRefresh={load}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

export function selectedAssessmentId(
  data: ConversationAssurancePayload,
  requestedTurn: string | null,
  current: string | null,
): string | null {
  if (requestedTurn !== null) {
    return data.assessments.find((item) => item.turn_id === requestedTurn)?.assessment_id ?? null;
  }
  if (current !== null && data.assessments.some((item) => item.assessment_id === current)) {
    return current;
  }
  return data.assessments[0]?.assessment_id ?? null;
}

function AssuranceBody({
  auth,
  client,
  data,
  selectedId,
  onSelect,
  onRefresh,
}: {
  readonly auth: AuthContext;
  readonly client: OperatorApiClient;
  readonly data: ConversationAssurancePayload;
  readonly selectedId: string | null;
  readonly onSelect: (value: string) => void;
  readonly onRefresh: () => Promise<void>;
}) {
  const evidenceState = data.summary.total === 0 ? "insufficient-sample" : "measured";
  const href = `${routeHref("conversation-assurance")}#assessments`;
  const selected = data.assessments.find((item) => item.assessment_id === selectedId) ?? null;
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("assurance.bannerTitle")}</strong><span>{t("assurance.bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard evidenceState={evidenceState} href={href} label={t("assurance.total")} value={data.summary.total || kpiEvidenceLabel("insufficient-sample")} />
        <KpiCard evidenceState={evidenceState} href={href} label={t("assurance.passing")} value={data.summary.total ? data.summary.pass : kpiEvidenceLabel("insufficient-sample")} tone={data.summary.pass ? "positive" : "default"} />
        <KpiCard evidenceState={evidenceState} href={href} label={t("assurance.failing")} value={data.summary.total ? data.summary.fail : kpiEvidenceLabel("insufficient-sample")} tone={data.summary.fail ? "warning" : "default"} />
        <KpiCard evidenceState={evidenceState} href={href} label={t("assurance.inconclusive")} value={data.summary.total ? data.summary.inconclusive : kpiEvidenceLabel("insufficient-sample")} />
        <KpiCard evidenceState={evidenceState} href={href} label={t("assurance.average")} value={data.summary.average_content_score === null ? kpiEvidenceLabel("insufficient-sample") : `${data.summary.average_content_score.toFixed(1)}/100`} />
        <KpiCard evidenceState={evidenceState} href={`${routeHref("conversation-assurance")}#disputes`} label={t("assurance.disputes")} value={data.summary.total ? data.summary.disputes : kpiEvidenceLabel("insufficient-sample")} />
      </KpiGrid>
      <AssessmentTable assessments={data.assessments} onSelect={onSelect} />
      <AssessmentDetail auth={auth} client={client} assessment={selected} onRefresh={onRefresh} />
      <section id="disputes" class="stack">
        <h2>{t("assurance.disputes")}</h2>
        {data.disputes.length === 0 ? <p>{t("shared.noRows")}</p> : data.disputes.map((item) => (
          <div class="assurance-dispute" key={item.dispute_id}>
            <strong>{t(`assurance.reasonOptions.${item.reason}`)}</strong>
            <span>{item.detail}</span><small>{new Date(item.reported_at).toLocaleString()}</small>
          </div>
        ))}
      </section>
    </div>
  );
}

function AssessmentTable({ assessments, onSelect }: { readonly assessments: readonly AssuranceAssessment[]; readonly onSelect: (value: string) => void }) {
  return <section id="assessments" class="stack"><h2>{t("assurance.assessments")}</h2>{assessments.length === 0 ? <p>{t("assurance.empty")}</p> : <div class="scroll"><table class="data-table"><thead><tr><th scope="col">{t("assurance.turn")}</th><th scope="col">{t("assurance.score")}</th><th scope="col">{t("assurance.models")}</th><th scope="col">{t("assurance.cost")}</th><th scope="col">{t("assurance.assessed")}</th></tr></thead><tbody>{assessments.map((item) => <tr key={item.assessment_id}><td><button type="button" class="btn btn-small" onClick={() => onSelect(item.assessment_id)}>{item.turn_id}</button><br /><StatusPill kind={verdictKind(item.verdict)} label={t(`assurance.verdict.${item.verdict}`)} /></td><td>{item.content_score.toFixed(1)}/100</td><td>{item.model_calls}</td><td>{formatCost(item.cost_microusd)}</td><td>{new Date(item.assessed_at).toLocaleString()}</td></tr>)}</tbody></table></div>}</section>;
}

function AssessmentDetail({ auth, client, assessment, onRefresh }: { readonly auth: AuthContext; readonly client: OperatorApiClient; readonly assessment: AssuranceAssessment | null; readonly onRefresh: () => Promise<void> }) {
  const [detail, setDetail] = useState<AsyncState<AssuranceDetailPayload> | null>(null);
  useEffect(() => {
    if (assessment === null) { setDetail(null); return; }
    let cancelled = false;
    setDetail({ status: "loading" });
    client.panel<unknown>(`/conversation-assurance/${encodeURIComponent(assessment.assessment_id)}`)
      .then((value) => { if (!cancelled) setDetail({ status: "ready", data: decodeAssuranceDetail(value) }); })
      .catch((error: unknown) => { if (!cancelled) setDetail({ status: "error", message: error instanceof Error ? error.message : String(error) }); });
    return () => { cancelled = true; };
  }, [assessment?.assessment_id, client]);
  if (assessment === null || detail === null) return <p>{t("assurance.selectAssessment")}</p>;
  return <section class="stack"><h2>{t("assurance.details")}</h2><AsyncBoundary state={detail} resourceLabel={t("assurance.details")}>{(value) => <DetailBody key={value.assessment.assessment_id} auth={auth} client={client} detail={value} onRefresh={onRefresh} />}</AsyncBoundary></section>;
}

function DetailBody({ auth, client, detail, onRefresh }: { readonly auth: AuthContext; readonly client: OperatorApiClient; readonly detail: AssuranceDetailPayload; readonly onRefresh: () => Promise<void> }) {
  const [reason, setReason] = useState<(typeof REASONS)[number]>("wrong_fact");
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "submitted" | "error">("idle");
  const submit = async (event: Event) => {
    event.preventDefault(); setStatus("submitting");
    try {
      await putGovernedJson(auth, client.operatorApiBaseUrl, `/conversation-assurance/${encodeURIComponent(detail.assessment.assessment_id)}/disputes`, { reason, detail: text.trim(), evidence_refs: [], idempotency_key: crypto.randomUUID() }, "POST");
      setText(""); setStatus("submitted"); await onRefresh();
    } catch { setStatus("error"); }
  };
  return <div class="stack">
    {detail.turn.available ? <><h3>{t("assurance.question")}</h3><p>{detail.turn.question}</p><h3>{t("assurance.answer")}</h3><div class="prose">{detail.turn.answer}</div></> : <p>{t("assurance.turnUnavailable")}</p>}
    <h3>{t("assurance.criteria")}</h3>{detail.assessment.criteria.length === 0 ? <p>{t("assurance.noCriteria")}</p> : <div class="status-list">{detail.assessment.criteria.map((item) => <div key={item.criterion}><strong>{item.criterion}</strong><span>{item.score}/4</span><p>{item.rationale}</p><small>{item.evidence_refs.join(", ") || t("assurance.evidence")}</small></div>)}</div>}
    <form class="stack" onSubmit={(event) => void submit(event)}><h3>{t("assurance.reportTitle")}</h3><p>{t("assurance.reportBody")}</p><label>{t("assurance.reason")}<select value={reason} onChange={(event) => setReason(event.currentTarget.value as (typeof REASONS)[number])}>{REASONS.map((item) => <option value={item} key={item}>{t(`assurance.reasonOptions.${item}`)}</option>)}</select></label><label>{t("assurance.detail")}<textarea required maxLength={1000} value={text} placeholder={t("assurance.detailPlaceholder")} onInput={(event) => setText(event.currentTarget.value)} /></label><button type="submit" class="btn primary" disabled={status === "submitting" || text.trim().length === 0}>{t(status === "submitting" ? "assurance.submitting" : "assurance.submit")}</button>{status === "submitted" ? <p role="status">{t("assurance.submitted")}</p> : null}{status === "error" ? <p role="alert">{t("shared.panelFailed")}</p> : null}</form>
  </div>;
}

function verdictKind(verdict: AssuranceVerdict): "success" | "danger" | "warning" { return verdict === "pass" ? "success" : verdict === "fail" ? "danger" : "warning"; }
function formatCost(microusd: number): string { return `$${(microusd / 1_000_000).toFixed(6)}`; }
