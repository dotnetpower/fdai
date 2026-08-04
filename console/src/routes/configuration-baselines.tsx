import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";

import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { AsyncBoundary, KpiCard, KpiGrid, PageHeader, StatusPill, type AsyncState, type PillKind } from "../components/ui";
import { formatConsoleTimestamp } from "../time-format";
import { configurationBaselinesText as t } from "./configuration-baselines.i18n";
import { panelBoolean, panelNonEmptyString, panelNonNegativeInteger, panelNonNegativeNumber, panelRecord, panelStringArray } from "./panel-decode";

interface ConfigurationBaselinesView {
  readonly baseline: { readonly version: string; readonly scope: string; readonly createdAt: string; readonly documentName: string; readonly lifecycle: string; readonly resourceCount: number; readonly topologyCount: number; readonly unknownCount: number };
  readonly drift: { readonly verdict: string; readonly observedAt: string; readonly findingCount: number };
  readonly knowledge: { readonly status: string; readonly citationCount: number; readonly citations: readonly string[] };
  readonly safety: { readonly mutation: number; readonly approval: number; readonly mitigation: number; readonly unsupported: number };
  readonly performance: { readonly totalMs: number; readonly observationMs: number; readonly knowledgeMs: number };
  readonly review: { readonly configured: boolean; readonly state: string; readonly completedRuns: number; readonly requiredRuns: number };
}

export function ConfigurationBaselinesRoute({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<AsyncState<ConfigurationBaselinesView>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    void loadConfigurationBaselines(client).then((next) => { if (active) setState(next); });
    return () => { active = false; };
  }, [client]);
  return <div class="stack configuration-baselines-route"><PageHeader title={t("title")} subtitle={t("subtitle")} /><AsyncBoundary state={state} resourceLabel={t("resourceLabel")}>{(data) => <ConfigurationBaselinesBody data={data} />}</AsyncBoundary></div>;
}

export async function loadConfigurationBaselines(client: OperatorApiClient): Promise<AsyncState<ConfigurationBaselinesView>> {
  try {
    return { status: "ready", data: decodeConfigurationBaselines(await client.panel<unknown>("/configuration-baselines")) };
  } catch (error) {
    return isOptionalOperatorApiUnavailable(error) ? { status: "unavailable", message: t("unavailable") } : { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export function decodeConfigurationBaselines(value: unknown): ConfigurationBaselinesView {
  const root = panelRecord(value, "configuration baselines");
  const baseline = panelRecord(root["baseline"], "configuration baseline");
  const drift = panelRecord(root["drift"], "configuration drift");
  const knowledge = panelRecord(root["knowledge"], "configuration Knowledge");
  const safety = panelRecord(root["safety"], "configuration safety");
  const performance = panelRecord(root["performance"], "configuration performance");
  const review = panelRecord(root["review"], "configuration review");
  return {
    baseline: { version: panelNonEmptyString(baseline, "version", "configuration baseline"), scope: panelNonEmptyString(baseline, "scope", "configuration baseline"), createdAt: panelNonEmptyString(baseline, "created_at", "configuration baseline"), documentName: panelNonEmptyString(baseline, "document_name", "configuration baseline"), lifecycle: panelNonEmptyString(baseline, "lifecycle", "configuration baseline"), resourceCount: panelNonNegativeInteger(baseline, "resource_count", "configuration baseline"), topologyCount: panelNonNegativeInteger(baseline, "topology_count", "configuration baseline"), unknownCount: panelNonNegativeInteger(baseline, "unknown_count", "configuration baseline") },
    drift: { verdict: panelNonEmptyString(drift, "verdict", "configuration drift"), observedAt: panelNonEmptyString(drift, "observed_at", "configuration drift"), findingCount: panelNonNegativeInteger(drift, "finding_count", "configuration drift") },
    knowledge: { status: panelNonEmptyString(knowledge, "status", "configuration Knowledge"), citationCount: panelNonNegativeInteger(knowledge, "citation_count", "configuration Knowledge"), citations: panelStringArray(knowledge["citations"], "configuration citations") },
    safety: { mutation: panelNonNegativeInteger(safety, "mutation_count", "configuration safety"), approval: panelNonNegativeInteger(safety, "approval_request_count", "configuration safety"), mitigation: panelNonNegativeInteger(safety, "mitigation_execution_count", "configuration safety"), unsupported: panelNonNegativeInteger(safety, "unsupported_claim_count", "configuration safety") },
    performance: { totalMs: panelNonNegativeNumber(performance, "total_ms", "configuration performance"), observationMs: panelNonNegativeNumber(performance, "observation_ms", "configuration performance"), knowledgeMs: panelNonNegativeNumber(performance, "knowledge_ms", "configuration performance") },
    review: { configured: panelBoolean(review, "configured", "configuration review"), state: panelNonEmptyString(review, "state", "configuration review"), completedRuns: panelNonNegativeInteger(review, "completed_runs", "configuration review"), requiredRuns: panelNonNegativeInteger(review, "required_runs", "configuration review") },
  };
}

function ConfigurationBaselinesBody({ data }: { readonly data: ConfigurationBaselinesView }) {
  return <div class="stack">
    <div class="governance-readonly-banner"><strong>{t("bannerTitle")}</strong><span>{t("bannerBody")}</span></div>
    <KpiGrid><KpiCard href="#baseline" label={t("version")} value={data.baseline.version} /><KpiCard href="#drift" label={t("decision")} value={data.drift.verdict} /><KpiCard href="#knowledge" label={t("citations")} value={data.knowledge.citationCount} /><KpiCard href="#performance" label={t("totalLatency")} value={`${data.performance.totalMs.toFixed(1)} ms`} /></KpiGrid>
    <EvidenceSection id="baseline" title={t("baseline")} rows={[[t("scope"), data.baseline.scope], [t("created"), formatConsoleTimestamp(data.baseline.createdAt)], [t("document"), data.baseline.documentName], [t("lifecycle"), data.baseline.lifecycle], [t("resources"), data.baseline.resourceCount], [t("topology"), data.baseline.topologyCount], [t("unknown"), data.baseline.unknownCount]]} />
    <EvidenceSection id="drift" title={t("drift")} rows={[[t("decision"), <StatusPill kind={tone(data.drift.verdict)} label={data.drift.verdict} />], [t("findings"), data.drift.findingCount], [t("observed"), formatConsoleTimestamp(data.drift.observedAt)]]} />
    <EvidenceSection id="knowledge" title={t("knowledge")} rows={[[t("decision"), <StatusPill kind={tone(data.knowledge.status)} label={data.knowledge.status} />], [t("citations"), data.knowledge.citationCount]]} />
    <EvidenceSection id="performance" title={t("performance")} rows={[[t("totalLatency"), `${data.performance.totalMs.toFixed(1)} ms`], [t("observationLatency"), `${data.performance.observationMs.toFixed(1)} ms`], [t("knowledgeLatency"), `${data.performance.knowledgeMs.toFixed(1)} ms`]]} />
    <EvidenceSection id="review" title={t("review")} rows={[[t("decision"), data.review.configured ? data.review.state : t("reviewNotConfigured")], [t("findings"), `${data.review.completedRuns}/${data.review.requiredRuns}`]]} />
    <EvidenceSection id="safety" title={t("safety")} rows={[[t("mutation"), data.safety.mutation], [t("approval"), data.safety.approval], [t("mitigation"), data.safety.mitigation], [t("unsupported"), data.safety.unsupported]]} />
  </div>;
}

function EvidenceSection({ id, title, rows }: { readonly id: string; readonly title: string; readonly rows: readonly (readonly [string, ComponentChildren])[] }) {
  return <section id={id} class="stack-section"><h3 class="section-title">{title}</h3><dl class="details-list">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>;
}

function tone(value: string): PillKind {
  if (value === "passed" || value === "cited") return "success";
  if (value === "failed" || value === "blocked") return "danger";
  return "warning";
}
