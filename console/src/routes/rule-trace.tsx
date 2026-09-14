import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { currentRoute, navigate, routeHref } from "../router";
import { formatConsoleTimestamp, isRfc3339Timestamp } from "../time-format";
import { t } from "./i18n/evidence";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
} from "./panel-decode";
import {
  RuleTraceWorkspace,
} from "./rule-trace-workspace";
import { RuleTracePlaceholder } from "./rule-trace-placeholder";
import { TraceCopyButton } from "./rule-trace-copy";
import {
  buildTraceDiscovery,
  TraceDiscovery,
  type TraceDiscoveryData,
} from "./rule-trace-discovery";
import {
  traceActionLabel,
  traceStageLabel,
} from "./rule-trace-supporting-evidence";
import "./rule-trace.css";
import "./rule-trace-lifecycle.css";
import "./rule-trace-experience.css";

/**
 * Rule-fire trace viewer panel. Given a correlation id, calls
 * ``GET /audit/{correlation_id}/trace`` and renders the ordered
 * pipeline stages so an on-call sees "why did rule X fire?" without
 * hand-grepping the audit log.
 */

export interface TraceStep {
  readonly seq: number;
  readonly event_id: string;
  readonly source_correlation_id: string | null;
  readonly recorded_at: string;
  readonly actor: string;
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
  readonly previous_hash: string;
}

export interface TraceResponse {
  readonly correlation_id: string;
  readonly step_count: number;
  readonly steps: readonly TraceStep[];
  readonly terminal_stage: string | null;
  readonly trace_kind: "read" | "decision" | "unknown";
  readonly source_authority: string;
  readonly complete: boolean;
  readonly first_recorded_at: string;
  readonly last_recorded_at: string;
  readonly latest_sequence: number;
  readonly latest_activity_stage: string | null;
  readonly latest_action_kind: string;
  readonly latest_actor: string;
  readonly latest_decision: string | null;
  readonly latest_outcome: string | null;
  readonly latest_mode: string;
  readonly target_resource_ref: string | null;
  readonly target_count: number;
  readonly action_attempt_count: number;
  readonly effect_observation_count: number;
  readonly incident_evidence_recorded: boolean;
  readonly rca_evidence_recorded: boolean;
  readonly metadata_source: "server" | "legacy";
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

const TRACE_STEP_LIMIT = 500;

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
  const [discoveryState, setDiscoveryState] = useState<AsyncState<TraceDiscoveryData>>({
    status: "loading",
  });
  const [loadedAt, setLoadedAt] = useState<string | null>(null);
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
        setLoadedAt(new Date().toISOString());
      }
    } catch (err) {
      if (requestGeneration.current === generation) {
        setState(traceLoadFailure(err));
        setLoadedAt(null);
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
        setLoadedAt(null);
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

  useEffect(() => {
    let active = true;
    setDiscoveryState({ status: "loading" });
    void client.listAudit({ limit: 500 }).then(
      (page) => {
        if (active) {
          setDiscoveryState({
            status: "ready",
            data: buildTraceDiscovery(page),
          });
        }
      },
      (error: unknown) => {
        if (!active) return;
        if (isOptionalOperatorApiUnavailable(error)) {
          setDiscoveryState({
            status: "unavailable",
            message: t("evidence.trace.discovery.unavailableReason", {
              message: error instanceof Error ? error.message : String(error),
            }),
          });
          return;
        }
        setDiscoveryState({
          status: "error",
          message: t("evidence.trace.discovery.loadError", {
            message: error instanceof Error ? error.message : String(error),
          }),
        });
      },
    );
    return () => {
      active = false;
    };
  }, [client]);

  const headerSummary = state.status === "ready"
    ? t("evidence.trace.headerSummaryDetailed", {
      count: state.data.step_count,
      stage: state.data.terminal_stage === null
        ? t("evidence.trace.noValue")
        : traceStageLabel(state.data.terminal_stage),
      latest: state.data.latest_activity_stage === null
        ? traceActionLabel(state.data.latest_action_kind)
        : traceStageLabel(state.data.latest_activity_stage),
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
        setLoadedAt(null);
      }}
      onSubmit={() => navigate(traceCorrelationHref(correlationId))}
      trace={state.status === "ready" ? state.data : null}
      loadedAt={loadedAt}
    />
  );

  return (
    <div class="stack trace-route">
      <PageHeader
        title={t("route.ruleTrace")}
        subtitle={t("evidence.trace.subtitle")}
        actions={(
          <div class="trace-header-meta">
            <span>{t(
              state.status === "ready"
                ? "evidence.trace.summaryLabel"
                : "evidence.trace.selectedCorrelation",
            )}</span>
            <strong>{headerSummary}</strong>
          </div>
        )}
      />

      <details class="trace-readonly-boundary">
        <summary>
          <strong>{t("evidence.trace.boundaryTitle")}</strong>
          <span>{t("evidence.trace.boundaryShort")}</span>
        </summary>
        <p>{t("evidence.trace.boundaryBody")}</p>
      </details>

      <TraceDiscovery
        selectedCorrelation={correlationId}
        state={discoveryState}
      />

      {state.status === "ready"
        ? <TraceView data={state.data} toolbar={lookup} loadedAt={loadedAt} />
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
  loadedAt,
  loading,
  onChange,
  onSubmit,
  trace,
}: {
  readonly correlationId: string;
  readonly loading: boolean;
  readonly loadedAt: string | null;
  readonly onChange: (value: string) => void;
  readonly onSubmit: () => void;
  readonly trace: TraceResponse | null;
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
        ? (
            <>
              <TraceCopyButton
                text={correlationId.trim()}
                label={t("evidence.trace.copyCorrelation")}
              />
              <TraceEvidenceLinks
                correlationId={correlationId.trim()}
                trace={trace}
              />
            </>
          )
        : null}
      <button
        type="submit"
        class="btn primary"
        disabled={loading || !correlationId.trim()}
      >
        {t(trace === null ? "evidence.trace.fetch" : "evidence.trace.refresh")}
      </button>
      {loadedAt !== null ? (
        <span class="trace-toolbar-updated">
          {t("evidence.trace.updated", {
            time: formatConsoleTimestamp(loadedAt),
          })}
        </span>
      ) : null}
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
  const stepValues = panelArray(root["steps"], "trace.steps");
  if (stepValues.length > TRACE_STEP_LIMIT) {
    throw new Error(
      `invalid Operator API response: trace.steps MUST contain at most ${TRACE_STEP_LIMIT} records`,
    );
  }
  const steps = stepValues.map((value, index) => {
    const row = panelRecord(value, `trace.steps[${index}]`);
    const recordedAt = panelNonEmptyString(row, "recorded_at", "trace step");
    if (!isRfc3339Timestamp(recordedAt)) {
      throw new Error("invalid Operator API response: trace step.recorded_at MUST be RFC 3339");
    }
    const stage = nullableNonEmptyString(row, "stage", "trace step");
    const sequence = panelNonNegativeInteger(row, "seq", "trace step");
    if (sequence < 1) {
      throw new Error("invalid Operator API response: trace step.seq MUST be positive");
    }
    return {
      seq: sequence,
      event_id: panelNonEmptyString(row, "event_id", "trace step"),
      source_correlation_id: nullableNonEmptyString(
        row,
        "source_correlation_id",
        "trace step",
      ),
      recorded_at: recordedAt,
      actor: panelNonEmptyString(row, "actor", "trace step"),
      stage,
      decision: nullableNonEmptyString(row, "decision", "trace step"),
      reason: nullableNonEmptyString(row, "reason", "trace step"),
      action_kind: panelNonEmptyString(row, "action_kind", "trace step"),
      mode: panelNonEmptyString(row, "mode", "trace step"),
      action_id: optionalNonEmptyString(row, "action_id", "trace step"),
      attempt: optionalPositiveInteger(row, "attempt", "trace step"),
      execution_path: optionalNonEmptyString(row, "execution_path", "trace step"),
      outcome: optionalNonEmptyString(row, "outcome", "trace step"),
      entry_hash: panelNonEmptyString(row, "entry_hash", "trace step"),
      previous_hash: panelNonEmptyString(row, "previous_hash", "trace step"),
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
  const terminalStage = nullableNonEmptyString(root, "terminal_stage", "trace");
  let lastNamedStage: string | null = null;
  for (const step of steps) {
    if (step.stage !== null) lastNamedStage = step.stage;
  }
  if (terminalStage !== lastNamedStage) {
    throw new Error("invalid Operator API response: trace.terminal_stage MUST match the last named stage");
  }
  const metadata = steps.length === 0
    ? emptyTraceMetadata()
    : decodeTraceMetadata(root, steps, terminalStage);
  return {
    correlation_id: correlationId,
    step_count: stepCount,
    steps,
    terminal_stage: terminalStage,
    ...metadata,
  };
}

function emptyTraceMetadata(): Omit<
  TraceResponse,
  "correlation_id" | "step_count" | "steps" | "terminal_stage"
> {
  return {
    trace_kind: "unknown",
    source_authority: "legacy-audit-trace",
    complete: false,
    first_recorded_at: "",
    last_recorded_at: "",
    latest_sequence: 0,
    latest_activity_stage: null,
    latest_action_kind: "",
    latest_actor: "",
    latest_decision: null,
    latest_outcome: null,
    latest_mode: "",
    target_resource_ref: null,
    target_count: 0,
    action_attempt_count: 0,
    effect_observation_count: 0,
    incident_evidence_recorded: false,
    rca_evidence_recorded: false,
    metadata_source: "legacy",
  };
}

function decodeTraceMetadata(
  root: Readonly<Record<string, unknown>>,
  steps: readonly TraceStep[],
  terminalStage: string | null,
): Omit<TraceResponse, "correlation_id" | "step_count" | "steps" | "terminal_stage"> {
  const first = steps[0];
  const latest = steps.at(-1);
  if (first === undefined || latest === undefined) {
    throw new Error("invalid Operator API response: trace metadata requires at least one step");
  }
  if (root["trace_kind"] === undefined) {
    return legacyTraceMetadata(steps, terminalStage);
  }
  const traceKind = panelNonEmptyString(root, "trace_kind", "trace");
  if (!["read", "decision", "unknown"].includes(traceKind)) {
    throw new Error("invalid Operator API response: trace.trace_kind is unsupported");
  }
  const firstRecordedAt = panelNonEmptyString(root, "first_recorded_at", "trace");
  const lastRecordedAt = panelNonEmptyString(root, "last_recorded_at", "trace");
  if (
    !isRfc3339Timestamp(firstRecordedAt)
    || !isRfc3339Timestamp(lastRecordedAt)
    || firstRecordedAt !== first.recorded_at
    || lastRecordedAt !== latest.recorded_at
  ) {
    throw new Error("invalid Operator API response: trace time bounds MUST match ordered steps");
  }
  const latestSequence = panelNonNegativeInteger(root, "latest_sequence", "trace");
  const latestActivityStage = nullableNonEmptyString(root, "latest_activity_stage", "trace");
  const latestDecision = nullableNonEmptyString(root, "latest_decision", "trace");
  const latestOutcome = nullableNonEmptyString(root, "latest_outcome", "trace");
  const targetResourceRef = optionalNonEmptyString(root, "target_resource_ref", "trace");
  const targetCount = panelNonNegativeInteger(root, "target_count", "trace");
  const actionAttemptCount = panelNonNegativeInteger(root, "action_attempt_count", "trace");
  const effectObservationCount = panelNonNegativeInteger(
    root,
    "effect_observation_count",
    "trace",
  );
  const rcaEvidenceRecorded = panelBoolean(root, "rca_evidence_recorded", "trace");
  if (
    latestSequence !== latest.seq
    || latestActivityStage !== latest.stage
    || panelNonEmptyString(root, "latest_action_kind", "trace") !== latest.action_kind
    || panelNonEmptyString(root, "latest_actor", "trace") !== latest.actor
    || latestOutcome !== latest.outcome
    || panelNonEmptyString(root, "latest_mode", "trace") !== latest.mode
    || latestDecision !== latestRecordedDecision(steps)
  ) {
    throw new Error("invalid Operator API response: trace latest metadata MUST match ordered steps");
  }
  if ((targetCount === 1) !== (targetResourceRef !== null)) {
    throw new Error("invalid Operator API response: trace target summary is inconsistent");
  }
  if (
    traceKind !== traceKindFromSteps(steps)
    || actionAttemptCount !== traceActionAttemptCount(steps)
    || effectObservationCount !== traceEffectObservationCount(steps)
    || rcaEvidenceRecorded !== steps.some((step) => step.action_kind.startsWith("rca."))
  ) {
    throw new Error("invalid Operator API response: trace summary counts MUST match ordered steps");
  }
  const sourceAuthority = panelNonEmptyString(root, "source_authority", "trace");
  if (sourceAuthority !== "operator-audit-log") {
    throw new Error("invalid Operator API response: trace.source_authority is unsupported");
  }
  return {
    trace_kind: traceKind as TraceResponse["trace_kind"],
    source_authority: sourceAuthority,
    complete: panelBoolean(root, "complete", "trace"),
    first_recorded_at: firstRecordedAt,
    last_recorded_at: lastRecordedAt,
    latest_sequence: latestSequence,
    latest_activity_stage: latestActivityStage,
    latest_action_kind: latest.action_kind,
    latest_actor: latest.actor,
    latest_decision: latestDecision,
    latest_outcome: latestOutcome,
    latest_mode: latest.mode,
    target_resource_ref: targetResourceRef,
    target_count: targetCount,
    action_attempt_count: actionAttemptCount,
    effect_observation_count: effectObservationCount,
    incident_evidence_recorded: panelBoolean(root, "incident_evidence_recorded", "trace"),
    rca_evidence_recorded: rcaEvidenceRecorded,
    metadata_source: "server",
  };
}

function legacyTraceMetadata(
  steps: readonly TraceStep[],
  terminalStage: string | null,
): Omit<TraceResponse, "correlation_id" | "step_count" | "steps" | "terminal_stage"> {
  const first = steps[0]!;
  const latest = steps.at(-1)!;
  const attempts = new Set(
    steps.flatMap((step) =>
      step.action_id === null ? [] : [`${step.action_id}:${step.attempt ?? "unknown"}`]
    ),
  );
  return {
    trace_kind: traceKindFromSteps(steps),
    source_authority: "legacy-audit-trace",
    complete: false,
    first_recorded_at: first.recorded_at,
    last_recorded_at: latest.recorded_at,
    latest_sequence: latest.seq,
    latest_activity_stage: latest.stage,
    latest_action_kind: latest.action_kind,
    latest_actor: latest.actor,
    latest_decision: latestRecordedDecision(steps),
    latest_outcome: latest.outcome,
    latest_mode: latest.mode,
    target_resource_ref: null,
    target_count: 0,
    action_attempt_count: attempts.size,
    effect_observation_count: traceEffectObservationCount(steps),
    incident_evidence_recorded: steps.some((step) =>
      step.action_kind.startsWith("incident.")
    ),
    rca_evidence_recorded: steps.some((step) => step.action_kind.startsWith("rca.")),
    metadata_source: "legacy",
  };
}

function traceKindFromSteps(
  steps: readonly TraceStep[],
): TraceResponse["trace_kind"] {
  if (steps.some((step) =>
    step.decision !== null
    || step.action_id !== null
    || step.execution_path !== null
    || /^(?:action|effect_observation|executor|hil|policy|risk_gate)\./.test(step.action_kind)
  )) return "decision";
  if (steps.every((step) =>
    /^(?:control_loop|inventory|measurement|ontology|read)\./.test(step.action_kind)
  )) return "read";
  return "unknown";
}

function traceActionAttemptCount(steps: readonly TraceStep[]): number {
  return new Set(
    steps.flatMap((step) =>
      step.action_id === null ? [] : [`${step.action_id}:${step.attempt ?? "unknown"}`]
    ),
  ).size;
}

function traceEffectObservationCount(steps: readonly TraceStep[]): number {
  return steps.filter((step) =>
    step.action_kind.startsWith("effect_observation.")
    || step.action_kind.startsWith("measurement.action_outcome")
    || step.action_kind.includes("effect.observation")
  ).length;
}

function latestRecordedDecision(steps: readonly TraceStep[]): string | null {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const decision = steps[index]?.decision;
    if (decision !== null && decision !== undefined) return decision;
  }
  return null;
}

function optionalNonEmptyString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  if (value[key] === undefined || value[key] === null) return null;
  return panelNonEmptyString(value, key, label);
}

function nullableNonEmptyString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  const parsed = panelNullableString(value, key, label);
  if (parsed !== null && parsed.trim().length === 0) {
    throw new Error(
      `invalid Operator API response: ${label}.${key} MUST be null or non-empty`,
    );
  }
  return parsed;
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
        { key: "trace_kind", value: data.trace_kind, group: "trace" },
        { key: "complete", value: data.complete, group: "trace" },
        { key: "source_authority", value: data.source_authority, group: "trace" },
        { key: "first_recorded_at", value: data.first_recorded_at, group: "trace" },
        { key: "last_recorded_at", value: data.last_recorded_at, group: "trace" },
        { key: "latest_sequence", value: data.latest_sequence, group: "trace" },
        { key: "latest_actor", value: data.latest_actor, group: "trace" },
        { key: "latest_action_kind", value: data.latest_action_kind, group: "trace" },
        { key: "latest_decision", value: data.latest_decision, group: "trace" },
        { key: "latest_outcome", value: data.latest_outcome, group: "trace" },
        { key: "target_resource_ref", value: data.target_resource_ref, group: "trace" },
        { key: "target_count", value: data.target_count, group: "trace" },
        { key: "action_attempt_count", value: data.action_attempt_count, group: "trace" },
        {
          key: "effect_observation_count",
          value: data.effect_observation_count,
          group: "trace",
        },
      ],
      records: {
        // Each step carries the `correlation_id` (so the value-chip resolver
        // recognises the id) and its `reason` (so causal questions quote the
        // recorded rationale for this stage).
        steps: data.steps.map((s) => ({
          seq: s.seq,
          event_id: s.event_id,
          source_correlation_id: s.source_correlation_id,
          recorded_at: s.recorded_at,
          actor: s.actor,
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
          previous_hash: s.previous_hash,
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

function TraceEvidenceLinks({
  correlationId,
  trace,
}: {
  readonly correlationId: string;
  readonly trace: TraceResponse | null;
}) {
  return (
    <nav class="trace-evidence-links trace-toolbar-links" aria-label={t("evidence.trace.evidence")}>
      <TraceEvidenceLink
        href={routeHref("incidents", { params: { status: "all", correlation: correlationId } })}
        label={t("evidence.trace.incident")}
        recorded={trace?.incident_evidence_recorded ?? null}
      />
      <TraceEvidenceLink
        href={routeHref("audit", { params: { correlation: correlationId } })}
        label={t("evidence.trace.audit")}
        recorded={true}
      />
      <TraceEvidenceLink
        href={routeHref("rca", { params: { correlation: correlationId } })}
        label={t("evidence.trace.rca")}
        recorded={trace?.rca_evidence_recorded ?? null}
      />
    </nav>
  );
}

function TraceEvidenceLink({
  href,
  label,
  recorded,
}: {
  readonly href: string;
  readonly label: string;
  readonly recorded: boolean | null;
}) {
  return (
    <a href={href}>
      <span>{label}</span>
      <small>{recorded === null
        ? t("evidence.trace.evidenceUnknown")
        : recorded
          ? t("evidence.trace.evidenceRecorded")
          : t("evidence.trace.evidenceNotRecorded")}</small>
    </a>
  );
}

function TraceView({
  data,
  loadedAt,
  toolbar,
}: {
  readonly data: TraceResponse;
  readonly loadedAt: string | null;
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
      loadedAt={loadedAt}
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
  if (stage === "approval") {
    return kind === "hil.requested"
      || kind === "hil.rejected"
      || kind === "hil.timeout"
      || kind === "hil.decision.recorded"
      || kind.startsWith("hil.approved.")
      || kind.startsWith("hil.resolve.");
  }
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
    if (kind === "hil.requested") return "pending";
    if (
      kind === "hil.rejected"
      || kind === "hil.timeout"
      || kind.includes("failed")
      || kind.includes("refused")
    ) {
      return "failed";
    }
    return "recorded";
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
