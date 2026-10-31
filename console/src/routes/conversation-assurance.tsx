import { useEffect, useRef, useState } from "preact/hooks";
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
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { putGovernedJson } from "../governed-command";
import { currentRoute, replaceRouteState, ROUTE_STATE_EVENT, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import {
  decodeAssuranceDetail,
  decodeConversationAssurance,
  type AssuranceAssessment,
  type AssuranceDetailPayload,
  type AssuranceVerdict,
  type ConversationAssurancePayload,
  type PantheonAssuranceSummary,
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
const ASSESSMENT_ID = /^conversation-assessment:[0-9a-f]{64}$/;

export function ConversationAssuranceRoute({
  client,
  auth,
}: {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}) {
  const [state, setState] = useState<AsyncState<ConversationAssurancePayload>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [requestedTurn, setRequestedTurn] = useState<string | null>(
    () => currentRoute().search.get("turn"),
  );
  const loadTracker = useRef(createLatestRequestTracker());
  const load = async () => {
    const request = loadTracker.current.begin();
    try {
      const data = decodeConversationAssurance(await client.panel<unknown>("/conversation-assurance"));
      if (!loadTracker.current.isCurrent(request)) return;
      setState({ status: "ready", data });
      const turn = currentRoute().search.get("turn");
      setRequestedTurn(turn);
      setSelectedId((current) => selectedAssessmentId(data, turn, current));
    } catch (error) {
      if (!loadTracker.current.isCurrent(request)) return;
      const unavailable = isOptionalOperatorApiUnavailable(error);
      setState({
        status: unavailable ? "unavailable" : "error",
        message: unavailable
          ? t("assurance.unavailable")
          : error instanceof Error ? error.message : String(error),
      });
    }
  };
  useEffect(() => {
    setState({ status: "loading" });
    void load();
  }, [client]);
  useEffect(() => {
    const sync = () => {
      const turn = currentRoute().search.get("turn");
      setRequestedTurn(turn);
      if (state.status === "ready") {
        setSelectedId((current) => selectedAssessmentId(state.data, turn, current));
      }
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, [state]);
  const selectAssessment = (assessmentId: string) => {
    setSelectedId(assessmentId);
    replaceRouteState(routeHref("conversation-assurance", {
      params: {
        data: currentRoute().search.get("data") === "sample" ? "sample" : null,
        turn: assessmentId,
      },
    }));
  };
  return (
    <div class="stack">
      <PageHeader title={t("assurance.title")} subtitle={t("assurance.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("assurance.resource")}>
        {(data) => (
          <AssuranceBody
            auth={auth}
            client={client}
            data={data}
            requestedAssessment={requestedTurn}
            selectedId={selectedId}
            onSelect={selectAssessment}
            onRefresh={load}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

export function createLatestRequestTracker(): {
  readonly begin: () => number;
  readonly isCurrent: (request: number) => boolean;
} {
  let current = 0;
  return {
    begin: () => {
      current += 1;
      return current;
    },
    isCurrent: (request) => request === current,
  };
}

export function selectedAssessmentId(
  data: ConversationAssurancePayload,
  requestedTurn: string | null,
  current: string | null,
): string | null {
  if (requestedTurn !== null) {
    const listed = data.assessments.find(
      (item) => item.assessment_id === requestedTurn || item.turn_id === requestedTurn,
    )?.assessment_id;
    return listed ?? (ASSESSMENT_ID.test(requestedTurn) ? requestedTurn : null);
  }
  if (current !== null && data.assessments.some((item) => item.assessment_id === current)) {
    return current;
  }
  return data.assessments[0]?.assessment_id ?? null;
}

export function requestedAssessmentUnavailable(
  requestedAssessment: string | null,
  selectedId: string | null,
): boolean {
  return requestedAssessment !== null && selectedId === null;
}

export function assessmentDetailUnavailable(error: unknown): boolean {
  return isOptionalOperatorApiUnavailable(error);
}

function AssuranceBody({
  auth,
  client,
  data,
  requestedAssessment,
  selectedId,
  onSelect,
  onRefresh,
}: {
  readonly auth: AuthContext;
  readonly client: OperatorApiClient;
  readonly data: ConversationAssurancePayload;
  readonly requestedAssessment: string | null;
  readonly selectedId: string | null;
  readonly onSelect: (value: string) => void;
  readonly onRefresh: () => Promise<void>;
}) {
  const evidenceState = data.summary.total === 0 ? "insufficient-sample" : "measured";
  const baseHref = routeHref("conversation-assurance", {
    params: {
      data: currentRoute().search.get("data") === "sample" ? "sample" : null,
      turn: selectedId,
    },
  });
  const href = `${baseHref}#assessments`;
  usePublishViewContext(
    () => ({
      routeId: "conversation-assurance",
      routeLabel: t("assurance.title"),
      purpose: t("assurance.subtitle"),
      glossary: composeGlossary([TERMS.shadowMode]),
      headline: `${data.summary.total} assessments (${data.summary.pass} pass, ${data.summary.fail} fail)`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "total", value: data.summary.total, group: "assurance" },
        { key: "pass", value: data.summary.pass, group: "assurance" },
        { key: "fail", value: data.summary.fail, group: "assurance" },
        { key: "disputes", value: data.summary.disputes, group: "assurance" },
        { key: "selected_assessment", value: selectedId ?? "-", group: "assurance" },
      ],
      records: {
        assessments: data.assessments.slice(0, 25).map((item) => ({
          assessment_id: item.assessment_id,
          turn_id: item.turn_id,
          verdict: item.verdict,
          content_score: item.content_score,
        })),
      },
    }),
    [data, selectedId],
  );
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
        <KpiCard evidenceState={evidenceState} href={`${baseHref}#disputes`} label={t("assurance.disputes")} value={data.summary.total ? data.summary.disputes : kpiEvidenceLabel("insufficient-sample")} />
      </KpiGrid>
      <PantheonSummary summary={data.pantheon} />
      <AssessmentTable assessments={data.assessments} selectedId={selectedId} onSelect={onSelect} />
      <AssessmentDetail
        auth={auth}
        client={client}
        assessmentId={selectedId}
        requestedUnavailable={requestedAssessmentUnavailable(requestedAssessment, selectedId)}
        onRefresh={onRefresh}
      />
      <section id="disputes" class="stack">
        <h2>{t("assurance.disputes")}</h2>
        {data.disputes.length === 0 ? <p>{t("shared.noRows")}</p> : data.disputes.map((item) => (
          <div class="assurance-dispute" key={item.dispute_id}>
            <strong>{t(`assurance.reasonOptions.${item.reason}`)}</strong>
            <span>{item.detail}</span><small>{formatConsoleTimestamp(item.reported_at)}</small>
          </div>
        ))}
      </section>
    </div>
  );
}

function PantheonSummary({ summary }: { readonly summary: PantheonAssuranceSummary }) {
  return (
    <section id="pantheon-diagnostics" class="stack">
      <h2>{t("assurance.pantheon.title")}</h2>
      <p>{t("assurance.pantheon.description")}</p>
      {!summary.available ? <p>{t("assurance.pantheon.unavailable")}</p> : (
        <>
          <KpiGrid>
            <KpiCard evidenceState="measured" href="#pantheon-agents" label={t("assurance.pantheon.turns")} value={summary.turns} />
            <KpiCard evidenceState="measured" href="#pantheon-agents" label={t("assurance.pantheon.average")} value={formatPantheonScore(summary.average_score)} />
            <KpiCard evidenceState="measured" href="#pantheon-agents" label={t("assurance.pantheon.routing")} value={formatRate(summary.routing_accuracy)} />
            <KpiCard evidenceState="measured" href="#pantheon-agents" label={t("assurance.pantheon.missedT2")} value={formatRate(summary.missed_t2_rate)} tone={summary.missed_t2_rate ? "warning" : "positive"} />
            <KpiCard evidenceState="measured" href="#pantheon-agents" label={t("assurance.pantheon.unnecessaryT2")} value={formatRate(summary.unnecessary_t2_rate)} tone={summary.unnecessary_t2_rate ? "warning" : "positive"} />
            <KpiCard evidenceState="measured" href="#pantheon-agents" label={t("assurance.pantheon.hardZero")} value={summary.hard_zero_fail} tone={pantheonSafetyTone(summary.hard_zero_fail)} />
          </KpiGrid>
          <div id="pantheon-agents" class="scroll">
            <table class="data-table">
              <thead><tr><th scope="col">{t("assurance.pantheon.agent")}</th><th scope="col">{t("assurance.pantheon.turns")}</th><th scope="col">{t("assurance.pantheon.average")}</th><th scope="col">{t("assurance.pantheon.minimum")}</th><th scope="col">{t("assurance.pantheon.results")}</th></tr></thead>
              <tbody>{summary.agents.map((item) => (
                <tr key={item.agent}>
                  <td>{item.agent}</td><td>{item.turns}</td>
                  <td>{item.average_score.toFixed(1)}/30</td><td>{item.minimum_score}/30</td>
                  <td>{t("assurance.pantheon.resultCounts", { pass: item.pass, review: item.review, fail: item.fail + item.hard_zero_fail })}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function formatRate(value: number | null): string {
  return value === null ? t("assurance.pantheon.notMeasured") : `${(value * 100).toFixed(1)}%`;
}

export function formatPantheonScore(value: number | null): string {
  return value === null ? t("assurance.pantheon.notMeasured") : `${value.toFixed(1)}/30`;
}

export function pantheonSafetyTone(hardZeroCount: number): "danger" | "positive" {
  return hardZeroCount > 0 ? "danger" : "positive";
}

function AssessmentTable({
  assessments,
  selectedId,
  onSelect,
}: {
  readonly assessments: readonly AssuranceAssessment[];
  readonly selectedId: string | null;
  readonly onSelect: (value: string) => void;
}) {
  return <section id="assessments" class="stack"><h2>{t("assurance.assessments")}</h2>{assessments.length === 0 ? <p>{t("assurance.empty")}</p> : <div class="scroll"><table class="data-table"><thead><tr><th scope="col">{t("assurance.turn")}</th><th scope="col">{t("assurance.state")}</th><th scope="col">{t("assurance.score")}</th><th scope="col">{t("assurance.models")}</th><th scope="col">{t("assurance.cost")}</th><th scope="col">{t("assurance.assessed")}</th></tr></thead><tbody>{assessments.map((item) => <tr key={item.assessment_id}><td><button type="button" class="btn btn-small" aria-pressed={item.assessment_id === selectedId} onClick={() => onSelect(item.assessment_id)}>{item.turn_id}</button><br /><StatusPill kind={verdictKind(item.verdict)} label={t(`assurance.verdict.${item.verdict}`)} /></td><td><StatusPill kind={assessmentStateKind(item.state)} label={t(`assurance.assessmentState.${item.state}`)} /></td><td>{item.content_score.toFixed(1)}/100</td><td>{item.model_calls}</td><td>{formatCost(item.cost_microusd)}</td><td>{formatConsoleTimestamp(item.assessed_at)}</td></tr>)}</tbody></table></div>}</section>;
}

function AssessmentDetail({ auth, client, assessmentId, requestedUnavailable, onRefresh }: { readonly auth: AuthContext; readonly client: OperatorApiClient; readonly assessmentId: string | null; readonly requestedUnavailable: boolean; readonly onRefresh: () => Promise<void> }) {
  const [detail, setDetail] = useState<AsyncState<AssuranceDetailPayload> | null>(null);
  const [detailUnavailable, setDetailUnavailable] = useState(false);
  const [retryGeneration, setRetryGeneration] = useState(0);
  useEffect(() => {
    if (assessmentId === null) { setDetail(null); setDetailUnavailable(false); return; }
    let cancelled = false;
    setDetailUnavailable(false);
    setDetail({ status: "loading" });
    client.panel<unknown>(`/conversation-assurance/${encodeURIComponent(assessmentId)}`)
      .then((value) => { if (!cancelled) setDetail({ status: "ready", data: decodeAssuranceDetail(value) }); })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (assessmentDetailUnavailable(error)) {
          setDetail(null);
          setDetailUnavailable(true);
          return;
        }
        setDetail({ status: "error", message: error instanceof Error ? error.message : String(error) });
      });
    return () => { cancelled = true; };
  }, [assessmentId, client, retryGeneration]);
  const retry = () => {
    setDetailUnavailable(false);
    setRetryGeneration((current) => current + 1);
    void onRefresh();
  };
  if (requestedUnavailable || detailUnavailable) {
    return <section class="stack"><h2>{t("assurance.details")}</h2><p role="status">{t("assurance.requestedAssessmentUnavailable")}</p><button type="button" class="btn btn-small" onClick={retry}>{t("assurance.refreshAssessments")}</button></section>;
  }
  if (assessmentId === null || detail === null) return <p>{t("assurance.selectAssessment")}</p>;
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

export function assessmentStateKind(
  state: AssuranceAssessment["state"],
): "success" | "danger" | "warning" {
  return state === "completed" ? "success" : state === "disputed" ? "danger" : "warning";
}
function formatCost(microusd: number): string { return `$${(microusd / 1_000_000).toFixed(6)}`; }
