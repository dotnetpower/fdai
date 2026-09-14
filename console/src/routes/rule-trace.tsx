import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import {
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { currentRoute, navigate, routeHref } from "../router";
import { isRfc3339Timestamp } from "../time-format";
import { t } from "./i18n/evidence";
import {
  panelArray,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
} from "./panel-decode";
import {
  RuleTraceWorkspace,
} from "./rule-trace-workspace";
import { RuleTracePlaceholder } from "./rule-trace-placeholder";
import { traceStageLabel } from "./rule-trace-supporting-evidence";
import "./rule-trace.css";
import "./rule-trace-lifecycle.css";

/**
 * Rule-fire trace viewer panel. Given a correlation id, calls
 * ``GET /audit/{correlation_id}/trace`` and renders the ordered
 * pipeline stages so an on-call sees "why did rule X fire?" without
 * hand-grepping the audit log.
 */

export interface TraceStep {
  readonly seq: number;
  readonly recorded_at: string;
  readonly stage: string | null;
  readonly decision: string | null;
  readonly reason: string | null;
  readonly action_kind: string;
  readonly mode: string;
  readonly action_id: string | null;
  readonly attempt: number | null;
  readonly execution_path: string | null;
  readonly outcome: string | null;
  readonly entry_hash: string;
}

export interface TraceResponse {
  readonly correlation_id: string;
  readonly step_count: number;
  readonly steps: readonly TraceStep[];
  readonly terminal_stage: string | null;
}

export type TraceLifecycleState =
  | "recorded"
  | "pending"
  | "failed"
  | "not_attempted"
  | "not_recorded";

export interface TraceLifecycleStage {
  readonly id: "proposal" | "decision" | "approval" | "dispatch" | "observation" | "recovery";
  readonly state: TraceLifecycleState;
  readonly evidence: TraceStep | null;
}

export interface TraceActionLifecycle {
  readonly actionId: string;
  readonly attempt: number | null;
  readonly stages: readonly TraceLifecycleStage[];
}

export interface TraceOperationalSummary {
  readonly notificationEscalation: boolean;
  readonly decisionRecorded: boolean;
  readonly rcaRecorded: boolean;
  readonly namedStageCount: number;
}

interface Props {
  readonly client: OperatorApiClient;
}

/**
 * Read a ``?correlation=`` deep-link value from the clean route query.
 * The Agent activity timeline links here (``/trace?correlation=...``)
 * so an operator can jump from one agent's action straight into its
 * full pipeline trace.
 */
function correlationFromRoute(): string {
  return currentRoute().search.get("correlation")?.trim() ?? "";
}

export function traceCorrelationHref(correlationId: string): string {
  return routeHref("trace", { params: { correlation: correlationId.trim() } });
}

export function RuleTraceRoute({ client }: Props) {
  const [correlationId, setCorrelationId] = useState(correlationFromRoute);
  const [state, setState] = useState<AsyncState<TraceResponse>>({ status: "idle" });
  const requestGeneration = useRef(0);

  usePublishViewContext(
    () => buildTraceViewSnapshot(correlationId, state),
    [correlationId, state],
  );

  async function fetchTrace(id: string = correlationId): Promise<void> {
    if (!id) return;
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setState({ status: "loading" });
    try {
      const data = decodeTraceResponse(
        await client.panel<unknown>(`/audit/${encodeURIComponent(id)}/trace`),
        id,
      );
      if (requestGeneration.current === generation) {
        setState(data.steps.length === 0
          ? { status: "unavailable", message: t("evidence.trace.empty") }
          : { status: "ready", data });
      }
    } catch (err) {
      if (requestGeneration.current === generation) {
        setState(traceLoadFailure(err));
      }
    }
  }

  // Auto-fetch when arriving via a deep link (or when the deep-link
  // correlation changes while this panel stays mounted).
  useEffect(() => {
    const sync = () => {
      const deepLinked = correlationFromRoute();
      if (!deepLinked) {
        requestGeneration.current += 1;
        setCorrelationId("");
        setState({ status: "idle" });
        return;
      }
      setCorrelationId(deepLinked);
      void fetchTrace(deepLinked);
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      requestGeneration.current += 1;
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const headerSummary = state.status === "ready"
    ? t("evidence.trace.headerSummary", {
      count: state.data.step_count,
      stage: state.data.terminal_stage === null
        ? t("evidence.trace.noValue")
        : traceStageLabel(state.data.terminal_stage),
    })
    : correlationId
      ? correlationId
      : t("evidence.trace.notSelected");
  const lookup = (
    <TraceLookupForm
      correlationId={correlationId}
      loading={state.status === "loading"}
      onChange={(value) => {
        requestGeneration.current += 1;
        setCorrelationId(value);
        setState({ status: "idle" });
      }}
      onSubmit={() => navigate(traceCorrelationHref(correlationId))}
    />
  );

  return (
    <div class="stack trace-route">
      <PageHeader
        title={t("route.ruleTrace")}
        subtitle={t("evidence.trace.subtitle")}
        actions={(
          <div class="trace-header-meta">
            <span>{t("evidence.trace.summaryLabel")}</span>
            <strong>{headerSummary}</strong>
          </div>
        )}
      />

      <div class="trace-readonly-boundary" role="note">
        <strong>{t("evidence.trace.boundaryTitle")}</strong>
        <span>{t("evidence.trace.boundaryBody")}</span>
      </div>

      {state.status === "ready"
        ? <TraceView data={state.data} toolbar={lookup} />
        : (
            <RuleTracePlaceholder
              correlationId={correlationId}
              status={state.status}
              toolbar={lookup}
              {...(state.status === "error" || state.status === "unavailable"
                ? { message: state.message }
                : {})}
            />
          )}
    </div>
  );
}

function TraceLookupForm({
  correlationId,
  loading,
  onChange,
  onSubmit,
}: {
  readonly correlationId: string;
  readonly loading: boolean;
  readonly onChange: (value: string) => void;
  readonly onSubmit: () => void;
}) {
  return (
    <form
      class="trace-toolbar"
      aria-label={t("evidence.trace.lookupTitle")}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label class="trace-toolbar-field">
        <span>{t("evidence.trace.correlationId")}</span>
        <input
          type="text"
          value={correlationId}
          onInput={(event) => onChange((event.target as HTMLInputElement).value)}
          required
        />
      </label>
      {correlationId.trim()
        ? <TraceEvidenceLinks correlationId={correlationId.trim()} />
        : null}
      <button
        type="submit"
        class="btn primary"
        disabled={loading || !correlationId.trim()}
      >
        {t("evidence.trace.fetch")}
      </button>
    </form>
  );
}

function traceLoadErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.startsWith("invalid Operator API response:")
    ? t("evidence.trace.invalidEvidence")
    : t("evidence.trace.loadError", { message });
}

export function traceLoadFailure(error: unknown): {
  readonly status: "unavailable" | "error";
  readonly message: string;
} {
  if (isOptionalOperatorApiUnavailable(error)) {
    return {
      status: "unavailable",
      message: error.status === 404
        ? t("evidence.trace.empty")
        : traceLoadErrorMessage(error),
    };
  }
  return { status: "error", message: traceLoadErrorMessage(error) };
}

export function decodeTraceResponse(
  value: unknown,
  expectedCorrelationId?: string,
): TraceResponse {
  const root = panelRecord(value, "trace");
  const correlationId = panelNonEmptyString(root, "correlation_id", "trace");
  if (
    expectedCorrelationId !== undefined
    && correlationId !== expectedCorrelationId
  ) {
    throw new Error(
      "invalid Operator API response: trace.correlation_id MUST match the requested correlation",
    );
  }
  const steps = panelArray(root["steps"], "trace.steps").map((value, index) => {
    const row = panelRecord(value, `trace.steps[${index}]`);
    const recordedAt = panelNonEmptyString(row, "recorded_at", "trace step");
    if (!isRfc3339Timestamp(recordedAt)) {
      throw new Error("invalid Operator API response: trace step.recorded_at MUST be RFC 3339");
    }
    const stage = panelNullableString(row, "stage", "trace step");
    if (stage !== null && stage.trim().length === 0) {
      throw new Error("invalid Operator API response: trace step.stage MUST be null or non-empty");
    }
    const sequence = panelNonNegativeInteger(row, "seq", "trace step");
    if (sequence < 1) {
      throw new Error("invalid Operator API response: trace step.seq MUST be positive");
    }
    return {
      seq: sequence,
      recorded_at: recordedAt,
      stage,
      decision: panelNullableString(row, "decision", "trace step"),
      reason: panelNullableString(row, "reason", "trace step"),
      action_kind: panelNonEmptyString(row, "action_kind", "trace step"),
      mode: panelNonEmptyString(row, "mode", "trace step"),
      action_id: optionalNonEmptyString(row, "action_id", "trace step"),
      attempt: optionalPositiveInteger(row, "attempt", "trace step"),
      execution_path: optionalNonEmptyString(row, "execution_path", "trace step"),
      outcome: optionalNonEmptyString(row, "outcome", "trace step"),
      entry_hash: panelNonEmptyString(row, "entry_hash", "trace step"),
    };
  });
  const stepCount = panelNonNegativeInteger(root, "step_count", "trace");
  if (stepCount !== steps.length) {
    throw new Error("invalid Operator API response: trace.step_count MUST match steps");
  }
  const sequence = steps.map((step) => step.seq);
  if (new Set(sequence).size !== sequence.length || sequence.some((seq, index) => index > 0 && seq <= sequence[index - 1]!)) {
    throw new Error("invalid Operator API response: trace steps MUST have unique ascending seq values");
  }
  const terminalStage = panelNullableString(root, "terminal_stage", "trace");
  if (terminalStage !== null && terminalStage.trim().length === 0) {
    throw new Error("invalid Operator API response: trace.terminal_stage MUST be null or non-empty");
  }
  let lastNamedStage: string | null = null;
  for (const step of steps) {
    if (step.stage !== null) lastNamedStage = step.stage;
  }
  if (terminalStage !== lastNamedStage) {
    throw new Error("invalid Operator API response: trace.terminal_stage MUST match the last named stage");
  }
  return {
    correlation_id: correlationId,
    step_count: stepCount,
    steps,
    terminal_stage: terminalStage,
  };
}

function optionalNonEmptyString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  if (value[key] === undefined || value[key] === null) return null;
  return panelNonEmptyString(value, key, label);
}

function optionalPositiveInteger(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  if (value[key] === undefined || value[key] === null) return null;
  const parsed = panelNonNegativeInteger(value, key, label);
  if (parsed < 1) {
    throw new Error(`invalid Operator API response: ${label}.${key} MUST be positive`);
  }
  return parsed;
}

export function buildTraceViewSnapshot(
  correlationId: string,
  state: AsyncState<TraceResponse>,
): ViewSnapshot | null {
  if (!correlationId) return null;
  const base = {
    routeId: "trace",
    routeLabel: t("route.ruleTrace"),
    purpose: t("evidence.trace.viewPurpose"),
    glossary: composeGlossary([
      TERMS.correlationId,
      TERMS.actionKind,
      TERMS.gateDecision,
      TERMS.tier,
      TERMS.mode,
      TERMS.outcome,
    ]),
    capturedAt: new Date().toISOString(),
  } as const;
  if (state.status === "ready") {
    const data = state.data;
    return {
      ...base,
      routeId: "trace",
      headline: t(
        data.terminal_stage ? "evidence.trace.headlineTerminal" : "evidence.trace.headline",
        {
          count: data.step_count,
          correlation: data.correlation_id,
          ...(data.terminal_stage ? { stage: data.terminal_stage } : {}),
        },
      ),
      facts: [
        { key: "load_status", value: "ready", group: "trace" },
        { key: "correlation_id", value: data.correlation_id, group: "trace" },
        { key: "step_count", value: data.step_count, group: "trace" },
        { key: "terminal_stage", value: data.terminal_stage, group: "trace" },
      ],
      records: {
        // Each step carries the `correlation_id` (so the value-chip resolver
        // recognises the id) and its `reason` (so causal questions quote the
        // recorded rationale for this stage).
        steps: data.steps.map((s) => ({
          seq: s.seq,
          recorded_at: s.recorded_at,
          stage: s.stage,
          decision: s.decision,
          reason: s.reason,
          action_kind: s.action_kind,
          mode: s.mode,
          action_id: s.action_id,
          attempt: s.attempt,
          execution_path: s.execution_path,
          outcome: s.outcome,
          entry_hash: s.entry_hash,
          correlation_id: data.correlation_id,
        })),
      },
    };
  }
  const message = state.status === "error" || state.status === "unavailable"
    ? state.message
    : null;
  const headlineKey = state.status === "loading"
    ? "evidence.trace.headlineLoading"
    : state.status === "error" || state.status === "unavailable"
      ? "evidence.trace.headlineError"
      : "evidence.trace.headlineIdle";
  return {
    ...base,
    headline: t(headlineKey, { correlation: correlationId }),
    facts: [
      { key: "load_status", value: state.status, group: "trace" },
      { key: "correlation_id", value: correlationId, group: "trace" },
      ...(message === null ? [] : [{ key: "load_error", value: message, group: "trace" }]),
    ],
    records: {
      status: [{ correlation_id: correlationId, status: state.status, reason: message }],
    },
  };
}

function TraceEvidenceLinks({ correlationId }: { readonly correlationId: string }) {
  return (
    <nav class="trace-evidence-links trace-toolbar-links" aria-label={t("evidence.trace.evidence")}>
      <a href={routeHref("incidents", { params: { status: "all", correlation: correlationId } })}>{t("evidence.trace.incident")}</a>
      <a href={routeHref("audit", { params: { correlation: correlationId } })}>{t("evidence.trace.audit")}</a>
      <a href={routeHref("rca", { params: { correlation: correlationId } })}>{t("evidence.trace.rca")}</a>
    </nav>
  );
}

function TraceView({
  data,
  toolbar,
}: {
  readonly data: TraceResponse;
  readonly toolbar: ComponentChildren;
}) {
  const summary = traceOperationalSummary(data);
  const lifecycles = traceActionLifecycles(data);

  return (
    <RuleTraceWorkspace
      data={data}
      lifecycles={lifecycles}
      summary={summary}
      toolbar={toolbar}
    />
  );
}

/** Derive separate presentation-only lifecycles for exact action attempts. */
export function traceActionLifecycles(data: TraceResponse): readonly TraceActionLifecycle[] {
  const byAction = new Map<string, TraceStep[]>();
  for (const step of data.steps) {
    if (step.action_id === null) continue;
    const steps = byAction.get(step.action_id) ?? [];
    steps.push(step);
    byAction.set(step.action_id, steps);
  }
  const groups: { actionId: string; attempt: number | null; steps: TraceStep[] }[] = [];
  for (const [actionId, steps] of byAction) {
    const attempts = [...new Set(
      steps.flatMap((step) => step.attempt === null ? [] : [step.attempt]),
    )];
    const soleAttempt = attempts.length === 1 ? attempts[0]! : null;
    const byAttempt = new Map<number | null, TraceStep[]>();
    for (const step of steps) {
      const attempt = step.attempt ?? soleAttempt;
      const attemptSteps = byAttempt.get(attempt) ?? [];
      attemptSteps.push(step);
      byAttempt.set(attempt, attemptSteps);
    }
    for (const [attempt, attemptSteps] of byAttempt) {
      groups.push({ actionId, attempt, steps: attemptSteps });
    }
  }
  return groups
    .sort((left, right) => left.steps[0]!.seq - right.steps[0]!.seq)
    .map((group) => ({
      actionId: group.actionId,
      attempt: group.attempt,
      stages: lifecycleStages(group.steps),
    }));
}

function lifecycleStages(steps: readonly TraceStep[]): readonly TraceLifecycleStage[] {
  const stages: TraceLifecycleStage["id"][] = [
    "proposal",
    "decision",
    "approval",
    "dispatch",
    "observation",
    "recovery",
  ];
  return stages.map((id) => {
    const matches = steps.filter((step) => traceStepMatchesLifecycle(step, id));
    const evidence = matches.at(-1) ?? null;
    return {
      id,
      state: evidence === null ? "not_recorded" : traceLifecycleState(id, evidence),
      evidence,
    };
  });
}

function traceStepMatchesLifecycle(
  step: TraceStep,
  stage: TraceLifecycleStage["id"],
): boolean {
  const kind = step.action_kind.toLowerCase();
  const namedStage = step.stage?.toLowerCase() ?? "";
  if (stage === "proposal") {
    return kind.includes("proposal") || namedStage === "plan" || namedStage === "propose";
  }
  if (stage === "decision") {
    return kind.includes("verdict")
      || kind.includes("risk_gate")
      || kind.includes("policy.")
      || (
        step.decision !== null
        && ["decision", "gate", "risk-gate"].includes(namedStage)
      );
  }
  if (stage === "approval") return kind.startsWith("hil.");
  if (stage === "dispatch") {
    return dispatchLifecycleState(step) !== null;
  }
  if (stage === "observation") {
    return kind.startsWith("effect_observation.")
      || kind.startsWith("measurement.action_outcome")
      || kind.includes("effect.observation");
  }
  return kind.includes("rollback") || kind.includes("rolled_back") || kind.includes("recovery");
}

function traceLifecycleState(
  stage: TraceLifecycleStage["id"],
  evidence: TraceStep,
): TraceLifecycleState {
  const kind = evidence.action_kind.toLowerCase();
  const decision = evidence.decision?.toLowerCase() ?? "";
  if (stage === "dispatch") return dispatchLifecycleState(evidence) ?? "not_recorded";
  if (stage === "approval") {
    return kind === "hil.requested" || kind === "hil.approved.claimed"
      ? "pending"
      : "recorded";
  }
  if (
    kind.includes("execution_pending")
    || kind.includes("awaiting_effect_evidence")
    || kind.includes("receipt_timeout")
    || kind.includes("execution_unknown")
    || ["hold", "pending", "unknown", "unavailable"].includes(decision)
  ) {
    return "pending";
  }
  if (
    kind.includes("failed")
    || kind.includes("mismatch")
    || ["failed", "error"].includes(decision)
  ) {
    return "failed";
  }
  return "recorded";
}

const DISPATCH_RECORDED_OUTCOMES = new Set([
  "published",
  "already_existed",
  "dispatched",
  "already_applied",
]);
const DISPATCH_PENDING_OUTCOMES = new Set([
  "publish_outcome_unknown",
  "awaiting_effect_evidence",
  "receipt_timeout",
  "execution_unknown",
]);
const DISPATCH_NOT_ATTEMPTED_OUTCOMES = new Set([
  "dispatch_not_attempted",
  "abstained_blast_radius",
  "abstained_precondition",
  "abstained_render_error",
  "authentication_failed",
  "permission_denied",
  "policy_denied",
  "network_denied",
  "rejected_mode",
  "rejected_invariant",
  "rejected_capability_unavailable",
  "rejected_idempotency_conflict",
  "expired",
]);
const DISPATCH_FAILED_OUTCOMES = new Set(["failed", "stopped"]);

function dispatchLifecycleState(step: TraceStep): TraceLifecycleState | null {
  const kind = step.action_kind.toLowerCase();
  const hilState: Record<string, TraceLifecycleState> = {
    "hil.approved.executed": "recorded",
    "hil.approved.execution_pending": "pending",
    "hil.approved.execution_not_attempted": "not_attempted",
    "hil.approved.execute_failed": "failed",
  };
  if (kind in hilState) return hilState[kind] ?? null;
  if (step.execution_path === null && !kind.startsWith("executor.")) return null;
  const outcome = step.outcome?.toLowerCase()
    ?? (kind.startsWith("executor.") ? kind.split(".").at(-1) ?? "" : "");
  if (DISPATCH_NOT_ATTEMPTED_OUTCOMES.has(outcome)) return "not_attempted";
  if (DISPATCH_PENDING_OUTCOMES.has(outcome)) return "pending";
  if (DISPATCH_FAILED_OUTCOMES.has(outcome)) return "failed";
  if (DISPATCH_RECORDED_OUTCOMES.has(outcome)) return "recorded";
  return null;
}

export function traceOperationalSummary(data: TraceResponse): TraceOperationalSummary {
  return {
    notificationEscalation: data.steps.some((step) =>
      step.action_kind === "notification.escalation"
      || step.action_kind === "hil.request.dispatch_unavailable"
    ),
    decisionRecorded: data.steps.some((step) => step.decision !== null),
    rcaRecorded: data.steps.some((step) => step.action_kind.startsWith("rca.")),
    namedStageCount: data.steps.filter((step) => step.stage !== null).length,
  };
}
