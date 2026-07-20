import { useEffect, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, ReadApiError } from "../api";
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
} from "../components/ui";
import { t } from "../i18n";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

interface ComparisonRow {
  readonly evaluation_id: string;
  readonly baseline_policy_ref: string;
  readonly candidate_policy_ref: string;
  readonly baseline_tokens: number;
  readonly candidate_tokens: number | null;
  readonly evidence_overlap: number | null;
  readonly omissions: readonly string[];
  readonly pinned_preserved: boolean;
  readonly latency_ms: number;
  readonly failure_reason: string | null;
  readonly created_at: string;
}

interface ComparisonResponse {
  readonly read_only: boolean;
  readonly count: number;
  readonly invariant_failures: number;
  readonly mutation_controls: boolean;
  readonly comparisons: readonly ComparisonRow[];
}

export function ContextSelectionComparisonsRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<ComparisonResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = decodeContextSelectionComparisons(
          await client.panel<unknown>("/context-selection-comparisons"),
        );
        if (!cancelled) setState({ status: "ready", data });
      } catch (error) {
        if (cancelled) return;
        if (isOptionalReadApiUnavailable(error)) {
          setState({ status: "unavailable", message: "Context policy evidence is not wired." });
        } else {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client]);

  return (
    <div class="stack governance-route">
      <PageHeader
        title={t("route.contextSelectionComparisons")}
        subtitle="Read-only baseline and shadow evidence. Promotion and rollback remain governed server-side."
      />
      <AsyncBoundary state={state} resourceLabel="context policy comparisons">
        {(data) => <ComparisonBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeContextSelectionComparisons(value: unknown): ComparisonResponse {
  const root = panelRecord(value, "context policy comparisons");
  const readOnly = panelBoolean(root, "read_only", "context policy comparisons");
  const mutationControls = panelBoolean(root, "mutation_controls", "context policy comparisons");
  if (!readOnly || mutationControls) {
    throw new ReadApiError(502, "invalid read API response: context policy panel MUST be read-only");
  }
  const comparisons = panelArray(root["comparisons"], "context policy comparisons.comparisons")
    .map((value, index) => decodeRow(value, index));
  const count = panelNonNegativeInteger(root, "count", "context policy comparisons");
  const failures = panelNonNegativeInteger(root, "invariant_failures", "context policy comparisons");
  if (count !== comparisons.length || failures !== comparisons.filter((row) => row.failure_reason !== null).length) {
    throw new ReadApiError(502, "invalid read API response: context policy summary counts MUST match rows");
  }
  return { read_only: readOnly, mutation_controls: mutationControls, count, invariant_failures: failures, comparisons };
}

function decodeRow(value: unknown, index: number): ComparisonRow {
  const row = panelRecord(value, `context policy comparisons[${index}]`);
  return {
    evaluation_id: panelNonEmptyString(row, "evaluation_id", "context policy comparison"),
    baseline_policy_ref: panelNonEmptyString(row, "baseline_policy_ref", "context policy comparison"),
    candidate_policy_ref: panelNonEmptyString(row, "candidate_policy_ref", "context policy comparison"),
    baseline_tokens: panelNonNegativeInteger(row, "baseline_tokens", "context policy comparison"),
    candidate_tokens: nullableNonNegativeInteger(row["candidate_tokens"], "candidate_tokens"),
    evidence_overlap: nullableRatio(row["evidence_overlap"], "evidence_overlap"),
    omissions: panelStringArray(row["omissions"], "context policy comparison.omissions"),
    pinned_preserved: panelBoolean(row, "pinned_preserved", "context policy comparison"),
    latency_ms: panelNonNegativeNumber(row, "latency_ms", "context policy comparison"),
    failure_reason: nullableString(row["failure_reason"], "failure_reason"),
    created_at: panelNonEmptyString(row, "created_at", "context policy comparison"),
  };
}

function nullableNonNegativeInteger(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new ReadApiError(502, `invalid read API response: ${label} MUST be a non-negative integer or null`);
  }
  return value;
}

function nullableRatio(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new ReadApiError(502, `invalid read API response: ${label} MUST be between 0 and 1 or null`);
  }
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string") {
    throw new ReadApiError(502, `invalid read API response: ${label} MUST be a string or null`);
  }
  return value;
}

function ComparisonBody({ data }: { readonly data: ComparisonResponse }) {
  const columns: readonly Column<ComparisonRow>[] = [
    { key: "candidate", header: "Candidate", render: (row) => row.candidate_policy_ref, cellClass: "mono" },
    { key: "tokens", header: "Tokens", render: (row) => `${row.baseline_tokens} / ${row.candidate_tokens ?? "-"}` },
    { key: "overlap", header: "Overlap", render: (row) => row.evidence_overlap === null ? "-" : `${(row.evidence_overlap * 100).toFixed(1)}%` },
    { key: "omissions", header: "Omissions", render: (row) => row.omissions.length ? row.omissions.join(", ") : "-" },
    { key: "pinned", header: "Pinned", render: (row) => <StatusPill kind={row.pinned_preserved ? "success" : "danger"} label={row.pinned_preserved ? "preserved" : "missing"} /> },
    { key: "latency", header: "Latency", render: (row) => `${row.latency_ms.toFixed(1)} ms`, cellClass: "num" },
    { key: "failure", header: "Invariant result", render: (row) => row.failure_reason ? <StatusPill kind="danger" label={row.failure_reason} /> : <StatusPill kind="success" label="passed" /> },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>Comparison only.</strong>
        <span>This view has no install, promotion, demotion, rollback, or kill-switch controls.</span>
      </div>
      <KpiGrid>
        <KpiCard label="Comparisons" value={data.count} />
        <KpiCard label="Invariant failures" value={data.invariant_failures} tone={data.invariant_failures ? "warning" : "positive"} />
      </KpiGrid>
      <DataTable columns={columns} rows={data.comparisons} keyOf={(row) => row.evaluation_id} empty="No shadow comparisons recorded." />
    </div>
  );
}
