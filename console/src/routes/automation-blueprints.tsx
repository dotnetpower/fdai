import { useEffect, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, type ReadApiClient } from "../api";
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
import { routeHref } from "../router";
import { presentationLabel, t } from "./i18n/evidence";
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
      .catch((error: unknown) => { if (!cancelled) setState({ status: isOptionalReadApiUnavailable(error) ? "unavailable" : "error", message: error instanceof Error ? error.message : String(error) }); });
    return () => { cancelled = true; };
  }, [client]);
  return <div class="stack"><PageHeader title={t("route.automationBlueprints")} subtitle={t("nav.panelSub.automationBlueprints")} /><AsyncBoundary state={state} resourceLabel={t("evidence.blueprints.resource")}>{(data) => <BlueprintBody data={data} />}</AsyncBoundary></div>;
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
  { key: "intent", header: t("evidence.blueprints.column.automation"), render: (item) => <div><strong>{item.normalized_task_intent}</strong><small>{item.schedule_expression}</small></div> },
  { key: "state", header: t("evidence.blueprints.column.state"), render: (item) => <StatusPill kind={item.state === "draft" ? "shadow" : item.state === "materialized" ? "success" : "warning"} label={presentationLabel("status", item.state)} /> },
  { key: "scope", header: t("evidence.blueprints.column.scope"), render: (item) => <code>{item.resource_scope}</code> },
  { key: "evidence", header: t("evidence.blueprints.column.evidence"), render: (item) => item.evidence_fingerprints.length },
  { key: "tools", header: t("evidence.blueprints.column.tools"), render: (item) => item.required_tools.join(", ") || t("evidence.common.none") },
  { key: "isolation", header: t("evidence.blueprints.column.isolation"), render: (item) => `${item.isolation_profile.profile_id}; ${t("evidence.blueprints.toolCalls", { count: item.isolation_profile.max_tool_calls })}` },
  { key: "cost", header: t("evidence.blueprints.column.cost"), render: (item) => t("evidence.blueprints.microUsd", { cost: item.estimated_cost_microusd }) },
  { key: "confidence", header: t("evidence.blueprints.column.confidence"), render: (item) => `${(item.confidence * 100).toFixed(1)}%` },
];

function BlueprintBody({ data }: { readonly data: AutomationBlueprintResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "automation-blueprints",
      routeLabel: t("route.automationBlueprints"),
      purpose: t("evidence.blueprints.viewPurpose"),
      glossary: composeGlossary([], [{ term: t("evidence.blueprints.glossaryTerm"), plain: t("evidence.blueprints.glossaryPlain"), tech: "AutomationBlueprintCandidate" }]),
      headline: t("evidence.blueprints.headline", { count: data.count, materialized: data.metrics.materialized }),
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
  const candidatesHref = `${routeHref("automation-blueprints")}#automation-blueprint-candidates`;
  return <div class="stack"><div class="governance-readonly-banner"><strong>{t("evidence.blueprints.bannerTitle")}</strong><span>{t("evidence.blueprints.bannerBody")}</span></div><KpiGrid><KpiCard href={candidatesHref} label={t("evidence.blueprints.candidates")} value={data.count.toLocaleString()} /><KpiCard href={candidatesHref} label={t("evidence.blueprints.accepted")} value={data.metrics.accepted.toLocaleString()} /><KpiCard href={candidatesHref} label={t("evidence.blueprints.rejected")} value={data.metrics.rejected.toLocaleString()} /><KpiCard href={candidatesHref} label={t("evidence.blueprints.realizedUsage")} value={data.metrics.realized_usage.toLocaleString()} /></KpiGrid><div id="automation-blueprint-candidates"><DataTable rows={data.candidates} columns={columns} keyOf={(item) => item.candidate_id} empty={<EmptyState title={t("evidence.blueprints.empty")} />} /></div></div>;
}
