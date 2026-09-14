import type { AuditItem, AuditPage } from "../types";
import type { AsyncState } from "../components/ui";
import { Tooltip } from "../components/tooltip";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { presentationLabel, t } from "./i18n/evidence";
import { traceActorLabel } from "./rule-trace-supporting-evidence";
import { useEffect, useState } from "preact/hooks";

export type TraceDiscoveryKind = "read" | "decision" | "unknown";

export interface TraceDiscoveryItem {
  readonly correlationId: string;
  readonly sampledRecordCount: number;
  readonly latestSequence: number;
  readonly latestRecordedAt: string;
  readonly latestActor: string;
  readonly latestActionKind: string;
  readonly latestDecision: string | null;
  readonly latestMode: string;
  readonly traceKind: TraceDiscoveryKind;
  readonly targetResourceRef: string | null;
  readonly targetCount: number;
  readonly incidentEvidenceRecorded: boolean;
  readonly rcaEvidenceRecorded: boolean;
}

export interface TraceDiscoveryData {
  readonly items: readonly TraceDiscoveryItem[];
  readonly sampledRecordCount: number;
  readonly indexComplete: boolean;
}

export function buildTraceDiscovery(
  page: AuditPage,
  itemLimit = 25,
): TraceDiscoveryData {
  const ordered = [...page.items].sort((left, right) => right.seq - left.seq);
  const correlations: string[] = [];
  for (const item of ordered) {
    const correlationId = normalizedCorrelation(item.correlation_id);
    if (correlationId === null || correlations.includes(correlationId)) continue;
    correlations.push(correlationId);
    if (correlations.length === itemLimit) break;
  }
  return {
    items: correlations.map((correlationId) =>
      discoveryItem(
        correlationId,
        ordered.filter((item) => normalizedCorrelation(item.correlation_id) === correlationId),
      )
    ),
    sampledRecordCount: ordered.length,
    indexComplete: page.next_cursor === null,
  };
}

export function TraceDiscovery({
  selectedCorrelation,
  state,
}: {
  readonly selectedCorrelation: string;
  readonly state: AsyncState<TraceDiscoveryData>;
}) {
  const [expanded, setExpanded] = useState(selectedCorrelation.length === 0);
  const [filter, setFilter] = useState<"all" | TraceDiscoveryKind>("all");

  useEffect(() => {
    setExpanded(selectedCorrelation.length === 0);
  }, [selectedCorrelation]);

  const data = state.status === "ready" ? state.data : null;
  const items = data?.items.filter((item) =>
    filter === "all" || item.traceKind === filter
  ) ?? [];
  return (
    <details
      class="trace-discovery"
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>
        <span>
          <strong>{t("evidence.trace.discovery.title")}</strong>
          <small>{discoverySummary(state)}</small>
        </span>
        <span>{expanded
          ? t("evidence.trace.discovery.hide")
          : t("evidence.trace.discovery.show")}</span>
      </summary>
      <div class="trace-discovery-body">
        {state.status === "loading" ? (
          <p class="trace-discovery-state" role="status">
            {t("evidence.trace.discovery.loading")}
          </p>
        ) : state.status === "error" || state.status === "unavailable" ? (
          <p class="trace-discovery-state" role={state.status === "error" ? "alert" : "status"}>
            {state.message}
          </p>
        ) : data === null || data.items.length === 0 ? (
          <p class="trace-discovery-state" role="status">
            {t("evidence.trace.discovery.empty")}
          </p>
        ) : (
          <>
            <div class="trace-discovery-filters" aria-label={t("evidence.trace.discovery.filter")}>
              {(["all", "read", "decision", "unknown"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                >
                  {t(`evidence.trace.discovery.kind.${value}`)}
                </button>
              ))}
            </div>
            {!data.indexComplete ? (
              <p class="trace-discovery-limit">
                {t("evidence.trace.discovery.incomplete", {
                  count: data.sampledRecordCount,
                })}
              </p>
            ) : null}
            {items.length === 0 ? (
              <p class="trace-discovery-state" role="status">
                {t("evidence.trace.discovery.filterEmpty")}
              </p>
            ) : (
              <ol class="trace-discovery-list">
                {items.map((item) => (
                <li key={item.correlationId}>
                  <Tooltip content={`${item.correlationId} / ${item.latestActionKind}`}>
                    <a
                      class={item.correlationId === selectedCorrelation ? "is-current" : undefined}
                      href={routeHref("trace", {
                        params: { correlation: item.correlationId },
                      })}
                      aria-current={item.correlationId === selectedCorrelation ? "page" : undefined}
                    >
                      <span class="trace-discovery-kind">
                        {t(`evidence.trace.discovery.kind.${item.traceKind}`)}
                      </span>
                      <strong>{item.targetResourceRef
                        ?? (item.targetCount > 1
                          ? t("evidence.trace.targetCount", { count: item.targetCount })
                          : compactId(item.correlationId))}</strong>
                      <small>
                        {traceActorLabel(item.latestActor)}
                        <span aria-hidden="true"> / </span>
                        {formatConsoleTimestamp(item.latestRecordedAt)}
                      </small>
                      <span class="trace-discovery-state-label">
                        <strong>{item.latestDecision === null
                          ? presentationLabel("status", item.latestMode)
                          : presentationLabel("status", item.latestDecision)}</strong>
                        <small>{t(
                          Number(item.incidentEvidenceRecorded)
                            + Number(item.rcaEvidenceRecorded) === 1
                            ? "evidence.trace.discovery.relatedEvidenceOne"
                            : "evidence.trace.discovery.relatedEvidence",
                          {
                            count: Number(item.incidentEvidenceRecorded)
                              + Number(item.rcaEvidenceRecorded),
                          },
                        )}</small>
                      </span>
                    </a>
                  </Tooltip>
                </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>
    </details>
  );
}

function discoveryItem(
  correlationId: string,
  items: readonly AuditItem[],
): TraceDiscoveryItem {
  const latest = items[0]!;
  const targets = new Set(
    items.flatMap((item) => {
      const target = targetRef(item.entry);
      return target === null ? [] : [target];
    }),
  );
  return {
    correlationId,
    sampledRecordCount: items.length,
    latestSequence: latest.seq,
    latestRecordedAt: latest.recorded_at,
    latestActor: latest.actor,
    latestActionKind: latest.action_kind,
    latestDecision: latestDecision(items),
    latestMode: latest.mode,
    traceKind: discoveryKind(items),
    targetResourceRef: targets.size === 1 ? [...targets][0]! : null,
    targetCount: targets.size,
    incidentEvidenceRecorded: items.some((item) =>
      item.action_kind.startsWith("incident.") || nonEmpty(item.entry["incident_id"]) !== null
    ),
    rcaEvidenceRecorded: items.some((item) => item.action_kind.startsWith("rca.")),
  };
}

function latestDecision(items: readonly AuditItem[]): string | null {
  for (const item of items) {
    const decision = nonEmpty(item.entry["decision"]);
    if (decision !== null) return decision;
  }
  return null;
}

function discoveryKind(items: readonly AuditItem[]): TraceDiscoveryKind {
  if (items.some((item) =>
    nonEmpty(item.entry["decision"]) !== null
    || nonEmpty(item.entry["action_id"]) !== null
    || nonEmpty(item.entry["execution_path"]) !== null
    || /^(?:action|effect_observation|executor|hil|policy|risk_gate)\./.test(item.action_kind)
  )) {
    return "decision";
  }
  if (items.every((item) =>
    /^(?:control_loop|inventory|measurement|ontology|read)\./.test(item.action_kind)
  )) {
    return "read";
  }
  return "unknown";
}

function targetRef(entry: Record<string, unknown>): string | null {
  for (const key of ["target_resource_ref", "resource_ref", "resource_id"]) {
    const value = nonEmpty(entry[key]);
    if (value !== null) return value;
  }
  return null;
}

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizedCorrelation(value: string | null): string | null {
  const correlationId = nonEmpty(value);
  return correlationId === null || ["none", "null"].includes(correlationId.toLowerCase())
    ? null
    : correlationId;
}

function compactId(value: string): string {
  return value.length <= 20 ? value : `${value.slice(0, 8)}...${value.slice(-6)}`;
}

function discoverySummary(state: AsyncState<TraceDiscoveryData>): string {
  if (state.status === "loading") return t("evidence.trace.discovery.loading");
  if (state.status === "error" || state.status === "unavailable") return state.message;
  if (state.status !== "ready") return t("evidence.trace.discovery.empty");
  return t(
    state.data.indexComplete
      ? "evidence.trace.discovery.summaryComplete"
      : "evidence.trace.discovery.summaryRecent",
    {
      count: state.data.items.length,
      records: state.data.sampledRecordCount,
    },
  );
}
