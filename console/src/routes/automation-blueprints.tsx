import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
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

interface BlueprintCard {
  readonly candidate_id: string;
  readonly state: string;
  readonly normalized_task_intent: string;
  readonly schedule_expression: string;
  readonly resource_scope: string;
  readonly delivery_intent: string;
  readonly required_tools: readonly string[];
  readonly isolation_profile: {
    readonly profile_id: string;
    readonly max_session_seconds: number;
    readonly max_context_chars: number;
    readonly max_tool_calls: number;
    readonly allowed_tool_ids: readonly string[];
  };
  readonly estimated_cost_microusd: number;
  readonly evidence_fingerprints: readonly string[];
  readonly confidence: number;
  readonly expires_at: string;
  readonly enabled: boolean;
  readonly shadow_only: boolean;
  readonly mutation_tool_ids: readonly string[];
}

export interface AutomationBlueprintResponse {
  readonly source: string;
  readonly mutation_controls: boolean;
  readonly count: number;
  readonly candidates: readonly BlueprintCard[];
  readonly metrics: {
    readonly proposed: number;
    readonly accepted: number;
    readonly rejected: number;
    readonly expired: number;
    readonly materialized: number;
    readonly realized_usage: number;
    readonly candidate_precision: number;
    readonly acceptance_rate: number;
  };
}

export function AutomationBlueprintsRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<AutomationBlueprintResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/automation-blueprints")
      .then((value) => { if (!cancelled) setState({ status: "ready", data: decodeAutomationBlueprints(value) }); })
      .catch((error: unknown) => { if (!cancelled) setState({ status: "error", message: error instanceof Error ? error.message : String(error) }); });
    return () => { cancelled = true; };
  }, [client]);
  return <div class="stack"><PageHeader title={t("route.automationBlueprints")} subtitle={t("nav.panelSub.automationBlueprints")} /><AsyncBoundary state={state} resourceLabel="automation blueprints">{(data) => <BlueprintBody data={data} />}</AsyncBoundary></div>;
}

export function decodeAutomationBlueprints(value: unknown): AutomationBlueprintResponse {
  const root = panelRecord(value, "automation blueprints");
  const candidates = panelArray(root["candidates"], "automation blueprints.candidates")
    .map((raw, index) => decodeCard(raw, index));
  const count = panelNonNegativeInteger(root, "count", "automation blueprints");
  if (count !== candidates.length) throw new Error("invalid read API response: automation blueprint count MUST match candidates");
  const metrics = panelRecord(root["metrics"], "automation blueprints.metrics");
  return {
    source: panelNonEmptyString(root, "source", "automation blueprints"),
    mutation_controls: panelBoolean(root, "mutation_controls", "automation blueprints"),
    count,
    candidates,
    metrics: {
      proposed: panelNonNegativeInteger(metrics, "proposed", "automation blueprints.metrics"),
      accepted: panelNonNegativeInteger(metrics, "accepted", "automation blueprints.metrics"),
      rejected: panelNonNegativeInteger(metrics, "rejected", "automation blueprints.metrics"),
      expired: panelNonNegativeInteger(metrics, "expired", "automation blueprints.metrics"),
      materialized: panelNonNegativeInteger(metrics, "materialized", "automation blueprints.metrics"),
      realized_usage: panelNonNegativeInteger(metrics, "realized_usage", "automation blueprints.metrics"),
      candidate_precision: ratio(metrics, "candidate_precision"),
      acceptance_rate: ratio(metrics, "acceptance_rate"),
    },
  };
}

function decodeCard(value: unknown, index: number): BlueprintCard {
  const label = `automation blueprints.candidates[${index}]`;
  const item = panelRecord(value, label);
  const isolation = panelRecord(item["isolation_profile"], `${label}.isolation_profile`);
  return {
    candidate_id: panelNonEmptyString(item, "candidate_id", label),
    state: panelNonEmptyString(item, "state", label),
    normalized_task_intent: panelNonEmptyString(item, "normalized_task_intent", label),
    schedule_expression: panelNonEmptyString(item, "schedule_expression", label),
    resource_scope: panelNonEmptyString(item, "resource_scope", label),
    delivery_intent: panelNonEmptyString(item, "delivery_intent", label),
    required_tools: panelStringArray(item["required_tools"], `${label}.required_tools`),
    isolation_profile: {
      profile_id: panelNonEmptyString(isolation, "profile_id", `${label}.isolation_profile`),
      max_session_seconds: panelNonNegativeInteger(isolation, "max_session_seconds", `${label}.isolation_profile`),
      max_context_chars: panelNonNegativeInteger(isolation, "max_context_chars", `${label}.isolation_profile`),
      max_tool_calls: panelNonNegativeInteger(isolation, "max_tool_calls", `${label}.isolation_profile`),
      allowed_tool_ids: panelStringArray(isolation["allowed_tool_ids"], `${label}.isolation_profile.allowed_tool_ids`),
    },
    estimated_cost_microusd: panelNonNegativeInteger(item, "estimated_cost_microusd", label),
    evidence_fingerprints: panelStringArray(item["evidence_fingerprints"], `${label}.evidence_fingerprints`),
    confidence: ratio(item, "confidence"),
    expires_at: panelNonEmptyString(item, "expires_at", label),
    enabled: panelBoolean(item, "enabled", label),
    shadow_only: panelBoolean(item, "shadow_only", label),
    mutation_tool_ids: panelStringArray(item["mutation_tool_ids"], `${label}.mutation_tool_ids`),
  };
}

function ratio(value: Readonly<Record<string, unknown>>, key: string): number {
  const result = panelNonNegativeNumber(value, key, "automation blueprints");
  if (result > 1) throw new Error(`invalid read API response: ${key} MUST be <= 1`);
  return result;
}

const columns: readonly Column<BlueprintCard>[] = [
  { key: "intent", header: "Suggested automation", render: (item) => <div><strong>{item.normalized_task_intent}</strong><small>{item.schedule_expression}</small></div> },
  { key: "state", header: "Review state", render: (item) => <StatusPill kind={item.state === "draft" ? "shadow" : item.state === "materialized" ? "success" : "warning"} label={item.state} /> },
  { key: "scope", header: "Resource scope", render: (item) => <code>{item.resource_scope}</code> },
  { key: "evidence", header: "Evidence", render: (item) => item.evidence_fingerprints.length },
  { key: "tools", header: "Required tools", render: (item) => item.required_tools.join(", ") || "None" },
  { key: "isolation", header: "Isolation", render: (item) => `${item.isolation_profile.profile_id}; ${item.isolation_profile.max_tool_calls} tool calls` },
  { key: "cost", header: "Estimated cost", render: (item) => `${item.estimated_cost_microusd} micro-USD` },
  { key: "confidence", header: "Confidence", render: (item) => `${(item.confidence * 100).toFixed(1)}%` },
];

function BlueprintBody({ data }: { readonly data: AutomationBlueprintResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "automation-blueprints",
      routeLabel: "Automation blueprints",
      purpose: "Read-only evidence cards for recurring operator work that may become a reviewed scheduled task.",
      glossary: composeGlossary([], [{ term: "automation blueprint", plain: "an inert recurring-work suggestion that requires explicit review", tech: "AutomationBlueprintCandidate" }]),
      headline: `${data.count} candidates; ${data.metrics.materialized} materialized`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "provenance" },
        { key: "candidate_count", value: data.count, group: "quality" },
        { key: "candidate_precision", value: data.metrics.candidate_precision, group: "quality" },
        { key: "realized_usage", value: data.metrics.realized_usage, group: "quality" },
        { key: "mutation_controls", value: data.mutation_controls, group: "safety" },
      ],
      records: { candidates: data.candidates.map((item) => ({ ...item })) },
    }),
    [data],
  );
  return <div class="stack"><div class="governance-readonly-banner"><strong>Review evidence only.</strong><span>Candidates are disabled and shadow-only. Review and materialization happen in authenticated operator channels.</span></div><KpiGrid><KpiCard label="Candidates" value={data.count.toLocaleString()} /><KpiCard label="Accepted" value={data.metrics.accepted.toLocaleString()} /><KpiCard label="Rejected" value={data.metrics.rejected.toLocaleString()} /><KpiCard label="Realized usage" value={data.metrics.realized_usage.toLocaleString()} /></KpiGrid><DataTable rows={data.candidates} columns={columns} keyOf={(item) => item.candidate_id} empty={<EmptyState title="No automation blueprints qualify" />} /></div>;
}
