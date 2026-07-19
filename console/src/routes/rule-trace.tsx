import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { isRfc3339Timestamp } from "../time-format";
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
  readonly stage: string;
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
          message: err instanceof Error ? err.message : String(err),
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
        subtitle='Reconstruct the pipeline path for one correlation id. Read-only projection over the audit log; the trace is never re-executed.'
      />

      <section class="stack-section">
        <h3 class="section-title">Look up a correlation id</h3>
        <form
          class="form-grid inline"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(traceCorrelationHref(correlationId));
          }}
        >
          <label>
            Correlation id
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
            Fetch trace
          </button>
        </form>
      </section>

      <AsyncBoundary
        state={state}
        resourceLabel="trace"
        idle={<p class="muted footnote">Enter a correlation id and click Fetch.</p>}
      >
        {(data) => <TraceView data={data} />}
      </AsyncBoundary>
    </div>
  );
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
    return {
      seq: panelNonNegativeInteger(row, "seq", "trace step"),
      recorded_at: recordedAt,
      stage: panelNonEmptyString(row, "stage", "trace step"),
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
  return {
    correlation_id: correlationId,
    step_count: stepCount,
    steps,
    terminal_stage: panelNullableString(root, "terminal_stage", "trace"),
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

function TraceView({ data }: { readonly data: TraceResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "trace",
      routeLabel: "Trace",
      purpose:
        "Reconstructs one incident end-to-end from the audit log: every " +
        "pipeline stage for a single correlation id, in order, with the " +
        "decision and recorded reason at each step. Answers 'what happened to " +
        "this event and why'. Read-only.",
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.actionKind,
        TERMS.gateDecision,
        TERMS.tier,
        TERMS.mode,
        TERMS.outcome,
      ]),
      headline: `${data.step_count} step(s) for ${data.correlation_id}${data.terminal_stage ? ` - terminal ${data.terminal_stage}` : ""}`,
      capturedAt: new Date().toISOString(),
      facts: [
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
          correlation_id: data.correlation_id,
        })),
      },
    }),
    [data],
  );

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
    { key: "at", header: "Recorded at", render: (s) => s.recorded_at, cellClass: "mono" },
    { key: "stage", header: "Stage", render: (s) => s.stage || <span class="muted">(unnamed)</span>, cellClass: "mono" },
    { key: "kind", header: "Action kind", render: (s) => s.action_kind, cellClass: "mono" },
    {
      key: "dec",
      header: "Decision",
      render: (s) =>
        s.decision === null
          ? <span class="muted">-</span>
          : <StatusPill kind={decisionPill(s.decision)} label={s.decision} />,
    },
    { key: "reason", header: "Reason", render: (s) => s.reason ?? <span class="muted">-</span> },
    {
      key: "mode",
      header: "Mode",
      render: (s) => <StatusPill kind={modePill(s.mode)} label={s.mode} />,
    },
  ];

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard label="Steps" value={data.step_count} />
        <KpiCard
          label="Terminal stage"
          value={<span class="mono">{data.terminal_stage ?? "-"}</span>}
        />
        <KpiCard
          label="Correlation id"
          value={<span class="mono small">{data.correlation_id}</span>}
        />
      </KpiGrid>
      <nav class="trace-evidence-links" aria-label="Correlation evidence">
        <a href={routeHref("incidents", { params: { status: "all", correlation: data.correlation_id } })}>Incident</a>
        <a href={routeHref("audit", { params: { correlation: data.correlation_id } })}>Audit</a>
        <a href={routeHref("rca", { params: { correlation: data.correlation_id } })}>RCA</a>
      </nav>
      <section class="stack-section">
        <h3 class="section-title">Timeline</h3>
        <DataTable
          columns={columns}
          rows={data.steps}
          keyOf={(s) => s.seq}
          empty="No audit steps for this correlation id."
        />
      </section>
    </div>
  );
}
