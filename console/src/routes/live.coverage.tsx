import { useEffect, useState } from "preact/hooks";

import {
  isOptionalOperatorApiUnavailable,
  type OperatorApiClient,
} from "../api";
import { OperatorApiError } from "../api-transport";
import type { ConsoleDataMode } from "../console-data-mode";
import { routeHref } from "../router";
import { isRfc3339Timestamp } from "../time-format";
import {
  decodeAnalyzerRun,
  type AnalyzerRunView,
} from "./detection-readiness.analyzer-run";
import { t } from "./i18n/live";

interface CatalogCoverage {
  readonly total: number;
  readonly active: number;
  readonly collected: number;
  readonly resourceTypes: number;
}

interface RuleEvaluationCoverage {
  readonly evaluated: boolean;
  readonly evaluatedRules: number;
}

interface ResourceTotalClient {
  readonly panel: (
    path: string,
    params?: Record<string, string>,
  ) => Promise<unknown>;
}

const RESOURCE_GENERATION_RETRY_DELAYS_MS = [
  250,
  500,
  1_000,
  2_000,
  4_000,
  8_000,
  8_000,
] as const;

type Load<T> =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: T }
  | { readonly status: "unavailable" }
  | { readonly status: "error" };

export interface LiveCoverageState {
  readonly catalog: Load<CatalogCoverage>;
  readonly resources: Load<number>;
  readonly analyzer: Load<AnalyzerRunView | null>;
  readonly ruleEvaluation: Load<RuleEvaluationCoverage>;
}

const UNAVAILABLE_COVERAGE: LiveCoverageState = {
  catalog: { status: "unavailable" },
  resources: { status: "unavailable" },
  analyzer: { status: "unavailable" },
  ruleEvaluation: { status: "unavailable" },
};

export function useLiveCoverage(
  client: OperatorApiClient,
  dataMode: ConsoleDataMode,
): LiveCoverageState {
  const [state, setState] = useState<LiveCoverageState>(
    dataMode === "live"
      ? {
          catalog: { status: "loading" },
          resources: { status: "loading" },
          analyzer: { status: "loading" },
          ruleEvaluation: { status: "loading" },
        }
      : UNAVAILABLE_COVERAGE,
  );

  useEffect(() => {
    if (dataMode !== "live") {
      setState(UNAVAILABLE_COVERAGE);
      return undefined;
    }
    let cancelled = false;
    const update = <K extends keyof LiveCoverageState>(
      key: K,
      value: LiveCoverageState[K],
    ): void => {
      if (!cancelled) setState((current) => ({ ...current, [key]: value }));
    };
    const load = async <K extends keyof LiveCoverageState>(
      key: K,
      read: () => Promise<LiveCoverageState[K]>,
    ): Promise<void> => {
      try {
        update(key, await read());
      } catch (error) {
        update(
          key,
          (
            isOptionalOperatorApiUnavailable(error)
              ? { status: "unavailable" }
              : { status: "error" }
          ) as LiveCoverageState[K],
        );
      }
    };
    void Promise.all([
      load("catalog", async () => ({
        status: "ready",
        data: decodeCatalogCoverage(
          await client.panel<unknown>("/rules", {
            offset: "0",
            limit: "1",
          }),
        ),
      })),
      load("resources", async () => ({
        status: "ready",
        data: await loadLiveResourceTotal(client, () => cancelled),
      })),
      load("analyzer", async () => {
        const raw = record(
          await client.panel<unknown>("/detection-coverage"),
          "detection coverage",
        );
        return {
          status: "ready",
          data: decodeAnalyzerRun(raw.analyzer_run),
        };
      }),
      load("ruleEvaluation", async () => ({
        status: "ready",
        data: decodeRuleEvaluation(
          await client.panel<unknown>("/rules/findings-summary"),
        ),
      })),
    ]);
    return () => {
      cancelled = true;
    };
  }, [client, dataMode]);

  return state;
}

export async function loadLiveResourceTotal(
  client: ResourceTotalClient,
  cancelled: () => boolean = () => false,
  waitForRetry: (delayMs: number) => Promise<void> = wait,
): Promise<number> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return decodeResourceTotal(
        await client.panel("/ontology/instances/states", { summary: "count" }),
      );
    } catch (error) {
      if (
        !(error instanceof OperatorApiError
          && error.status === 409
          && error.message === "inventory_generation_changed")
        || attempt >= RESOURCE_GENERATION_RETRY_DELAYS_MS.length
        || cancelled()
      ) {
        throw error;
      }
      await waitForRetry(RESOURCE_GENERATION_RETRY_DELAYS_MS[attempt]!);
    }
  }
}

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, delayMs));
}

export function LiveCoverage({
  coverage,
  sample,
}: {
  readonly coverage: LiveCoverageState;
  readonly sample: boolean;
}) {
  return (
    <section
      class={`live-coverage${sample ? " is-sample" : ""}`}
      aria-labelledby="live-coverage-title"
    >
      <div class="live-coverage-heading">
        <div>
          <span class="live-eyebrow">{t("live.coverage.eyebrow")}</span>
          <h2 id="live-coverage-title">{t("live.coverage.title")}</h2>
        </div>
        <p>{t("live.coverage.boundary")}</p>
      </div>
      {sample ? (
        <div class="live-coverage-sample" role="note">
          {t("live.coverage.sampleUnavailable")}
        </div>
      ) : (
        <div class="live-coverage-grid">
        <CoverageCard
          href={routeHref("rules")}
          label={t("live.coverage.catalog")}
          load={coverage.catalog}
          value={(data) => data.total.toLocaleString()}
          hint={(data) => t("live.coverage.catalogHint", {
            active: data.active.toLocaleString(),
            collected: data.collected.toLocaleString(),
            types: data.resourceTypes.toLocaleString(),
          })}
        />
        <CoverageCard
          href={routeHref("ontology", { params: { view: "instances" } })}
          label={t("live.coverage.resources")}
          load={coverage.resources}
          value={(data) => data.toLocaleString()}
          hint={() => t("live.coverage.resourceHint")}
        />
        <CoverageCard
          href={routeHref("detection-readiness")}
          label={t("live.coverage.analyzerTargets")}
          load={coverage.analyzer}
          value={(run) =>
            run === null
              ? t("live.coverage.notRecorded")
              : run.targets.toLocaleString()}
          hint={(run) => run === null
            ? t("live.coverage.analyzerUnrecorded")
            : t("live.coverage.analyzerHint", {
                candidates: run.candidate_count === null
                  ? t("live.coverage.notRecorded")
                  : run.candidate_count.toLocaleString(),
                evaluated: run.targets.toLocaleString(),
                held: run.held_count === null
                  ? t("live.coverage.notRecorded")
                  : run.held_count.toLocaleString(),
                holdReason: run.skipped_reasons.length > 0
                  ? ` (${run.skipped_reasons.join(", ")})`
                  : "",
                completeness: t(
                  run.source_complete
                    ? "live.coverage.sourceComplete"
                    : "live.coverage.sourceIncomplete",
                ),
              })}
        />
        <CoverageCard
          href={routeHref("detection-readiness")}
          label={t("live.coverage.analyzerFindings")}
          load={coverage.analyzer}
          value={(run) =>
            run === null
              ? t("live.coverage.notRecorded")
              : run.findings.toLocaleString()}
          hint={(run) => run === null
            ? t("live.coverage.analyzerUnrecorded")
            : t("live.coverage.findingHint", {
                published: run.published.toLocaleString(),
                errors: (
                  run.analyzer_error_count +
                  run.publish_error_count +
                  run.receipt_error_count
                ).toLocaleString(),
              })}
        />
        <CoverageCard
          href={routeHref("rules")}
          label={t("live.coverage.ruleEvaluation")}
          load={coverage.ruleEvaluation}
          evidenceState={(data) => data.evaluated ? "measured" : "not-evaluated"}
          value={(data) => data.evaluated
            ? data.evaluatedRules.toLocaleString()
            : t("live.coverage.notEvaluated")}
          hint={(data) => data.evaluated
            ? t("live.coverage.ruleFindingHint", {
                rules: data.evaluatedRules.toLocaleString(),
              })
            : t("live.coverage.ruleEvaluationMissing")}
        />
        </div>
      )}
    </section>
  );
}

function CoverageCard<T>({
  href,
  label,
  load,
  evidenceState,
  value,
  hint,
}: {
  readonly href: string;
  readonly label: string;
  readonly load: Load<T>;
  readonly evidenceState?: (data: T) => "measured" | "not-evaluated";
  readonly value: (data: T) => string;
  readonly hint: (data: T) => string;
}) {
  if (load.status === "loading") {
    return (
      <a
        class="live-coverage-card skeleton-shimmer"
        href={href}
        aria-label={label}
        aria-busy="true"
      />
    );
  }
  if (load.status !== "ready") {
    return (
      <a class="live-coverage-card" data-state={load.status} href={href}>
        <span>{label}</span>
        <strong>
          {t(
            load.status === "error"
              ? "live.coverage.error"
              : "live.coverage.unavailable",
          )}
        </strong>
      </a>
    );
  }
  return (
    <a
      class="live-coverage-card"
      data-evidence-state={evidenceState?.(load.data) ?? "measured"}
      href={href}
    >
      <span>{label}</span>
      <strong>{value(load.data)}</strong>
      <small>{hint(load.data)}</small>
    </a>
  );
}

export function decodeCatalogCoverage(value: unknown): CatalogCoverage {
  const root = record(value, "rule catalog");
  const total = count(root.total, "rule catalog total");
  const resourceTypes = count(
    root.resource_type_count,
    "rule catalog resource type count",
  );
  const facets = record(root.facets, "rule catalog facets");
  const origins = record(facets.by_origin, "rule catalog origin facets");
  const active = count(origins.active ?? 0, "active rule count");
  const collected = count(origins.collected ?? 0, "collected rule count");
  if (active + collected !== total) {
    throw new Error("rule catalog origin totals do not reconcile");
  }
  return { total, active, collected, resourceTypes };
}

export function decodeResourceTotal(value: unknown): number {
  const root = record(value, "resource page");
  if (
    root.schema_version !== "1.0.0" ||
    root.execution_authority !== false ||
    root.mutation_authority !== false ||
    root.source_kind !== "inventory_snapshot_resource" ||
    typeof root.source_generation !== "string" ||
    !root.source_generation.trim() ||
    root.source_generation.length > 256 ||
    typeof root.source_cutoff !== "string" ||
    !isRfc3339Timestamp(root.source_cutoff)
  ) {
    throw new Error("resource page authority is malformed");
  }
  return count(root.total_count, "resource total");
}

export function decodeRuleEvaluation(value: unknown): RuleEvaluationCoverage {
  const root = record(value, "rule findings summary");
  if (typeof root.evaluated !== "boolean") {
    throw new Error("rule findings evaluated state is malformed");
  }
  if (!root.evaluated) return { evaluated: false, evaluatedRules: 0 };
  const counts = record(root.counts, "rule findings counts");
  return {
    evaluated: true,
    evaluatedRules: Object.keys(counts).length,
  };
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} is malformed`);
  }
  return value as Record<string, unknown>;
}

function count(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new Error(`${label} is malformed`);
  }
  return Number(value);
}
