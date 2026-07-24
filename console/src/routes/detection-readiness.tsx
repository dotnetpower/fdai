import { useEffect, useState } from "preact/hooks";

import { isOptionalReadApiUnavailable, ReadApiError, type ReadApiClient } from "../api";
import { architectureHref } from "../components/architecture-map.model";
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
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/detection-readiness";
import {
  panelArray,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

const DECISIONS = ["ready", "partial", "blocked", "stale", "unauthorized", "unknown"] as const;
const DIMENSIONS = [
  "discovered",
  "collector_configured",
  "telemetry_observed",
  "detector_bound",
  "pipeline_observed",
  "action_governed",
] as const;
const CEILINGS = ["disabled", "deterministic_fallback", "shadow", "human_approval", "deployment"] as const;

type Decision = typeof DECISIONS[number];
type Dimension = typeof DIMENSIONS[number];
type AuthorityCeiling = typeof CEILINGS[number];

interface DetectionObservationView {
  readonly dimension: Dimension;
  readonly status: string;
}

interface DetectionTargetView {
  readonly resource_ref: string;
  readonly generated_at: string;
  readonly decision: Decision;
  readonly authority_ceiling: AuthorityCeiling;
  readonly observations: readonly DetectionObservationView[];
  readonly missing_dimensions: readonly Dimension[];
  readonly stale_dimensions: readonly Dimension[];
}

interface DetectionReadinessView {
  readonly source: string;
  readonly observed_at: string | null;
  readonly target_count: number;
  readonly counts: Readonly<Record<Decision, number>>;
  readonly targets: readonly DetectionTargetView[];
}

export function DetectionReadinessRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<DetectionReadinessView>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    void client.panel<unknown>("/detection-readiness").then(
      (value) => {
        if (active) setState({ status: "ready", data: decodeDetectionReadiness(value) });
      },
      (error: unknown) => {
        if (!active) return;
        setState(
          isOptionalReadApiUnavailable(error)
            ? { status: "unavailable", message: t("unavailable") }
            : { status: "error", message: error instanceof Error ? error.message : String(error) },
        );
      },
    );
    return () => { active = false; };
  }, [client]);

  return (
    <div class="stack detection-readiness-route">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("resourceLabel")}>
        {(data) => <DetectionReadinessBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeDetectionReadiness(value: unknown): DetectionReadinessView {
  const root = panelRecord(value, "detection readiness");
  const countsRoot = panelRecord(root["counts"], "detection readiness counts");
  const counts = Object.fromEntries(
    DECISIONS.map((decision) => [
      decision,
      panelNonNegativeInteger(countsRoot, decision, "detection readiness counts"),
    ]),
  ) as Record<Decision, number>;
  const targets = panelArray(root["targets"], "detection readiness targets").map(
    (item, index) => decodeTarget(item, index),
  );
  const targetCount = panelNonNegativeInteger(root, "target_count", "detection readiness");
  if (targets.length !== targetCount || Object.values(counts).reduce((sum, count) => sum + count, 0) !== targetCount) {
    throw new ReadApiError(502, "invalid read API response: detection readiness totals do not reconcile");
  }
  return {
    source: panelNonEmptyString(root, "source", "detection readiness"),
    observed_at: panelNullableString(root, "observed_at", "detection readiness"),
    target_count: targetCount,
    counts,
    targets,
  };
}

function decodeTarget(value: unknown, index: number): DetectionTargetView {
  const row = panelRecord(value, `detection readiness targets[${index}]`);
  const decision = member(panelNonEmptyString(row, "decision", "detection target"), DECISIONS, "decision");
  const ceiling = member(panelNonEmptyString(row, "authority_ceiling", "detection target"), CEILINGS, "authority ceiling");
  const observations = panelArray(row["observations"], "detection observations").map((item) => {
    const observation = panelRecord(item, "detection observation");
    return {
      dimension: member(panelNonEmptyString(observation, "dimension", "detection observation"), DIMENSIONS, "dimension"),
      status: panelNonEmptyString(observation, "status", "detection observation"),
    };
  });
  const dimensions = observations.map((item) => item.dimension);
  if (new Set(dimensions).size !== dimensions.length) {
    throw new ReadApiError(502, "invalid read API response: duplicate detection readiness dimension");
  }
  return {
    resource_ref: panelNonEmptyString(row, "resource_ref", "detection target"),
    generated_at: panelNonEmptyString(row, "generated_at", "detection target"),
    decision,
    authority_ceiling: ceiling,
    observations,
    missing_dimensions: dimensionsOf(panelStringArray(row["missing_dimensions"], "missing dimensions")),
    stale_dimensions: dimensionsOf(panelStringArray(row["stale_dimensions"], "stale dimensions")),
  };
}

function member<T extends string>(value: string, values: readonly T[], label: string): T {
  if (!values.includes(value as T)) {
    throw new ReadApiError(502, `invalid read API response: unknown detection readiness ${label}`);
  }
  return value as T;
}

function dimensionsOf(values: readonly string[]): readonly Dimension[] {
  return values.map((value) => member(value, DIMENSIONS, "dimension"));
}

function DetectionReadinessBody({ data }: { readonly data: DetectionReadinessView }) {
  const attention = data.target_count - data.counts.ready;
  const shadowLimited = data.targets.filter((target) =>
    ["disabled", "deterministic_fallback", "shadow"].includes(target.authority_ceiling),
  ).length;
  const anchor = `${routeHref("detection-readiness")}#detection-targets`;
  usePublishViewContext(
    () => ({
      routeId: "detection-readiness",
      routeLabel: t("title"),
      purpose: t("contextPurpose"),
      glossary: composeGlossary([TERMS.detectionReadiness, TERMS.mode]),
      headline: t("contextHeadline", { targets: data.target_count, ready: data.counts.ready }),
      capturedAt: data.observed_at ?? new Date().toISOString(),
      facts: [
        { key: "target_count", value: data.target_count, group: "readiness" },
        { key: "ready_count", value: data.counts.ready, group: "readiness" },
        { key: "attention_count", value: attention, group: "readiness" },
        { key: "source", value: data.source, group: "provenance" },
      ],
      records: { targets: data.targets.map((target) => ({ ...target })) },
    }),
    [attention, data],
  );
  const columns: readonly Column<DetectionTargetView>[] = [
    {
      key: "target",
      header: t("column.target"),
      render: (target) => <a class="mono small" href={architectureHref(target.resource_ref)}>{target.resource_ref}</a>,
    },
    {
      key: "decision",
      header: t("column.decision"),
      render: (target) => <StatusPill kind={decisionKind(target.decision)} label={t(`decision.${target.decision}`)} />,
    },
    {
      key: "evidence",
      header: t("column.evidence"),
      render: (target) => `${target.observations.length}/${DIMENSIONS.length}`,
      cellClass: "num",
    },
    {
      key: "gaps",
      header: t("column.gaps"),
      render: (target) => t("gapSummary", {
        missing: target.missing_dimensions.length,
        stale: target.stale_dimensions.length,
      }),
    },
    {
      key: "ceiling",
      header: t("column.ceiling"),
      render: (target) => <code>{target.authority_ceiling}</code>,
    },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("bannerTitle")}</strong>
        <span>{t("bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={anchor} label={t("targets")} value={data.target_count} />
        <KpiCard href={anchor} label={t("ready")} value={data.counts.ready} tone={data.counts.ready === data.target_count && data.target_count > 0 ? "positive" : "default"} />
        <KpiCard href={anchor} label={t("attention")} value={attention} tone={attention > 0 ? "warning" : "positive"} />
        <KpiCard href={routeHref("promotion-gates")} label={t("shadowLimited")} value={shadowLimited} tone={shadowLimited > 0 ? "warning" : "default"} />
      </KpiGrid>
      <section class="stack-section" aria-labelledby="detection-provenance">
        <h3 id="detection-provenance" class="section-title">{t("provenance")}</h3>
        <dl class="details-list">
          <div><dt>{t("source")}</dt><dd><code>{data.source}</code></dd></div>
          <div><dt>{t("observedAt")}</dt><dd>{data.observed_at ? formatConsoleTimestamp(data.observed_at) : t("notObserved")}</dd></div>
        </dl>
      </section>
      <section id="detection-targets" class="stack-section">
        <h3 class="section-title">{t("targetTitle")}</h3>
        {data.targets.length === 0 ? (
          <EmptyState title={t("emptyTitle")} body={t("emptyBody")} />
        ) : (
          <DataTable columns={columns} rows={data.targets} keyOf={(target) => target.resource_ref} empty={t("emptyTitle")} />
        )}
      </section>
    </div>
  );
}

function decisionKind(decision: Decision): PillKind {
  if (decision === "ready") return "success";
  if (decision === "blocked" || decision === "unauthorized") return "danger";
  if (decision === "partial" || decision === "stale") return "warning";
  return "neutral";
}
