import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  ErrorState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { currentRoute, navigate, routeHref } from "../router";
import { isRfc3339Timestamp } from "../time-format";
import { presentationLabel, t } from "./i18n/evidence";
import {
  panelArray,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
} from "./panel-decode";

/**
 * Rule-fire trace viewer panel. Given a correlation id, calls
 * ``GET /audit/{correlation_id}/trace`` and renders the ordered
 * pipeline stages so an on-call sees "why did rule X fire?" without
 * hand-grepping the audit log.
 */

interface TraceStep {
  readonly seq: number;
  readonly recorded_at: string;
  readonly stage: string | null;
  readonly decision: string | null;
  readonly reason: string | null;
  readonly action_kind: string;
  readonly mode: string;
  readonly entry_hash: string;
}

interface TraceResponse {
  readonly correlation_id: string;
  readonly step_count: number;
  readonly steps: readonly TraceStep[];
  readonly terminal_stage: string | null;
}

interface Props {
  readonly client: ReadApiClient;
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
      const data = decodeTraceResponse(await client.panel<unknown>(
        `/audit/${encodeURIComponent(id)}/trace`,
      ));
      if (requestGeneration.current === generation) setState({ status: "ready", data });
    } catch (err) {
      if (requestGeneration.current === generation) {
        setState({
          status: "error",
          message: traceLoadErrorMessage(err),
        });
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

  return (
    <div class="stack">
      <PageHeader
        title={t("route.ruleTrace")}
        subtitle={t("evidence.trace.subtitle")}
      />

      <section class="stack-section">
        <h3 class="section-title">{t("evidence.trace.lookupTitle")}</h3>
        <form
          class="form-grid inline"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(traceCorrelationHref(correlationId));
          }}
        >
          <label>
            {t("evidence.trace.correlationId")}
            <input
              type="text"
              value={correlationId}
              onInput={(e) => {
                requestGeneration.current += 1;
                setCorrelationId((e.target as HTMLInputElement).value);
                setState({ status: "idle" });
              }}
              required
            />
          </label>
          <button
            type="submit"
            class="btn primary"
            disabled={state.status === "loading" || !correlationId}
          >
            {t("evidence.trace.fetch")}
          </button>
        </form>
      </section>

      {state.status === "error" ? (
        <div class="stack">
          <ErrorState message={state.message} />
          <TraceEvidenceLinks correlationId={correlationId} />
        </div>
      ) : (
        <AsyncBoundary
          state={state}
          resourceLabel={t("evidence.trace.resource")}
          idle={<p class="muted footnote">{t("evidence.trace.idle")}</p>}
        >
          {(data) => <TraceView data={data} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

function traceLoadErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.startsWith("invalid read API response:")
    ? t("evidence.trace.invalidEvidence")
    : t("evidence.trace.loadError", { message });
}

export function decodeTraceResponse(value: unknown): TraceResponse {
  const root = panelRecord(value, "trace");
  const correlationId = panelNonEmptyString(root, "correlation_id", "trace");
  const steps = panelArray(root["steps"], "trace.steps").map((value, index) => {
    const row = panelRecord(value, `trace.steps[${index}]`);
    const recordedAt = panelNonEmptyString(row, "recorded_at", "trace step");
    if (!isRfc3339Timestamp(recordedAt)) {
      throw new Error("invalid read API response: trace step.recorded_at MUST be RFC 3339");
    }
    const stage = panelNullableString(row, "stage", "trace step");
    if (stage !== null && stage.trim().length === 0) {
      throw new Error("invalid read API response: trace step.stage MUST be null or non-empty");
    }
    return {
      seq: panelNonNegativeInteger(row, "seq", "trace step"),
      recorded_at: recordedAt,
      stage,
      decision: panelNullableString(row, "decision", "trace step"),
      reason: panelNullableString(row, "reason", "trace step"),
      action_kind: panelNonEmptyString(row, "action_kind", "trace step"),
      mode: panelNonEmptyString(row, "mode", "trace step"),
      entry_hash: panelNonEmptyString(row, "entry_hash", "trace step"),
    };
  });
  const stepCount = panelNonNegativeInteger(root, "step_count", "trace");
  if (stepCount !== steps.length) {
    throw new Error("invalid read API response: trace.step_count MUST match steps");
  }
  const sequence = steps.map((step) => step.seq);
  if (new Set(sequence).size !== sequence.length || sequence.some((seq, index) => index > 0 && seq <= sequence[index - 1]!)) {
    throw new Error("invalid read API response: trace steps MUST have unique ascending seq values");
  }
  const terminalStage = panelNullableString(root, "terminal_stage", "trace");
  if (terminalStage !== null && terminalStage.trim().length === 0) {
    throw new Error("invalid read API response: trace.terminal_stage MUST be null or non-empty");
  }
  let lastNamedStage: string | null = null;
  for (const step of steps) {
    if (step.stage !== null) lastNamedStage = step.stage;
  }
  if (terminalStage !== lastNamedStage) {
    throw new Error("invalid read API response: trace.terminal_stage MUST match the last named stage");
  }
  return {
    correlation_id: correlationId,
    step_count: stepCount,
    steps,
    terminal_stage: terminalStage,
  };
}

function decisionPill(decision: string | null): PillKind {
  if (decision === null) return "neutral";
  const v = decision.toLowerCase();
  if (v === "auto") return "auto";
  if (v === "hil") return "hil";
  if (v === "deny") return "danger";
  if (v === "abstain") return "neutral";
  if (v === "done" || v === "ok") return "success";
  if (v === "failed") return "danger";
  return "info";
}

function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
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
    <nav class="trace-evidence-links" aria-label={t("evidence.trace.evidence")}>
      <a href={routeHref("incidents", { params: { status: "all", correlation: correlationId } })}>{t("evidence.trace.incident")}</a>
      <a href={routeHref("audit", { params: { correlation: correlationId } })}>{t("evidence.trace.audit")}</a>
      <a href={routeHref("rca", { params: { correlation: correlationId } })}>{t("evidence.trace.rca")}</a>
    </nav>
  );
}

function TraceView({ data }: { readonly data: TraceResponse }) {

  const columns: readonly Column<TraceStep>[] = [
    {
      key: "n",
      header: "#",
      render: (s) => (
        <a href={routeHref("audit", { params: { correlation: data.correlation_id, entry: s.seq } })}>
          {s.seq}
        </a>
      ),
      cellClass: "num",
      headerClass: "num",
    },
    { key: "at", header: t("evidence.trace.column.recordedAt"), render: (s) => s.recorded_at, cellClass: "mono" },
    { key: "stage", header: t("evidence.trace.column.stage"), render: (s) => s.stage ?? <span class="muted">{t("evidence.trace.unnamed")}</span>, cellClass: "mono" },
    { key: "kind", header: t("evidence.trace.column.actionKind"), render: (s) => s.action_kind, cellClass: "mono" },
    {
      key: "dec",
      header: t("evidence.trace.column.decision"),
      render: (s) =>
        s.decision === null
          ? <span class="muted">-</span>
              : <StatusPill kind={decisionPill(s.decision)} label={presentationLabel("status", s.decision)} />,
    },
            { key: "reason", header: t("evidence.trace.column.reason"), render: (s) => s.reason ?? <span class="muted">-</span> },
    {
      key: "mode",
      header: t("evidence.trace.column.mode"),
      render: (s) => <StatusPill kind={modePill(s.mode)} label={presentationLabel("status", s.mode)} />,
    },
  ];

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard
          href={routeHref("audit", { params: { correlation: data.correlation_id } })}
          label={t("evidence.trace.steps")}
          value={data.step_count}
        />
        <KpiCard
          href={routeHref("audit", { params: { correlation: data.correlation_id } })}
          label={t("evidence.trace.terminalStage")}
          value={<span class="mono">{data.terminal_stage ?? "-"}</span>}
        />
        <KpiCard
          href={routeHref("incidents", { params: { status: "all", correlation: data.correlation_id } })}
          label={t("evidence.trace.correlationId")}
          value={<span class="mono small">{data.correlation_id}</span>}
        />
      </KpiGrid>
      <TraceEvidenceLinks correlationId={data.correlation_id} />
      <section class="stack-section">
        <h3 class="section-title">{t("evidence.trace.timeline")}</h3>
        <DataTable
          columns={columns}
          rows={data.steps}
          keyOf={(s) => s.seq}
          empty={t("evidence.trace.empty")}
        />
      </section>
    </div>
  );
}
