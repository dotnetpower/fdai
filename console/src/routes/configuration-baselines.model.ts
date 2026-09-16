import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

export interface ConfigurationBaselineVersionView {
  readonly version: string;
  readonly status: string;
  readonly createdAt: string;
  readonly resourceCount: number;
  readonly unknownCount: number;
  readonly comparison: {
    readonly baselineVersion: string;
    readonly verdict: string;
    readonly findingCount: number;
  };
}

export interface ConfigurationBaselinesView {
  readonly baseline: {
    readonly version: string;
    readonly scope: string;
    readonly createdAt: string | null;
    readonly documentName: string;
    readonly lifecycle: string;
    readonly resourceCount: number;
    readonly topologyCount: number;
    readonly unknownCount: number;
  };
  readonly versions: readonly ConfigurationBaselineVersionView[];
  readonly drift: {
    readonly verdict: string;
    readonly observedAt: string | null;
    readonly findingCount: number;
  };
  readonly knowledge: {
    readonly status: string;
    readonly citationCount: number;
    readonly citations: readonly string[];
  };
  readonly safety: {
    readonly mutation: number;
    readonly approval: number;
    readonly mitigation: number;
    readonly unsupported: number;
  };
  readonly performance: {
    readonly totalMs: number;
    readonly observationMs: number;
    readonly knowledgeMs: number;
  } | null;
  readonly review: {
    readonly configured: boolean;
    readonly state: string;
    readonly completedRuns: number;
    readonly requiredRuns: number;
    readonly failedAttempts: number;
  };
}

export function decodeConfigurationBaselines(value: unknown): ConfigurationBaselinesView {
  const root = panelRecord(value, "configuration baselines");
  const baseline = panelRecord(root["baseline"], "configuration baseline");
  const drift = panelRecord(root["drift"], "configuration drift");
  const knowledge = panelRecord(root["knowledge"], "configuration Knowledge");
  const safety = panelRecord(root["safety"], "configuration safety");
  const performance = root["performance"] === null
    ? null
    : panelRecord(root["performance"], "configuration performance");
  const review = panelRecord(root["review"], "configuration review");
  const versions = panelArray(root["versions"], "configuration baseline versions").map(
    (item, index) => {
      const version = panelRecord(item, `configuration baseline version ${index}`);
      const comparison = panelRecord(
        version["comparison"],
        `configuration baseline version ${index} comparison`,
      );
      return {
        version: panelNonEmptyString(version, "version", "configuration baseline version"),
        status: panelNonEmptyString(version, "status", "configuration baseline version"),
        createdAt: panelNonEmptyString(
          version,
          "created_at",
          "configuration baseline version",
        ),
        resourceCount: panelNonNegativeInteger(
          version,
          "resource_count",
          "configuration baseline version",
        ),
        unknownCount: panelNonNegativeInteger(
          version,
          "unknown_count",
          "configuration baseline version",
        ),
        comparison: {
          baselineVersion: panelNonEmptyString(
            comparison,
            "baseline_version",
            "configuration baseline comparison",
          ),
          verdict: panelNonEmptyString(
            comparison,
            "verdict",
            "configuration baseline comparison",
          ),
          findingCount: panelNonNegativeInteger(
            comparison,
            "finding_count",
            "configuration baseline comparison",
          ),
        },
      };
    },
  );
  return {
    baseline: {
      version: panelNonEmptyString(baseline, "version", "configuration baseline"),
      scope: panelNonEmptyString(baseline, "scope", "configuration baseline"),
      createdAt: panelNullableString(baseline, "created_at", "configuration baseline"),
      documentName: panelNonEmptyString(
        baseline,
        "document_name",
        "configuration baseline",
      ),
      lifecycle: panelNonEmptyString(baseline, "lifecycle", "configuration baseline"),
      resourceCount: panelNonNegativeInteger(
        baseline,
        "resource_count",
        "configuration baseline",
      ),
      topologyCount: panelNonNegativeInteger(
        baseline,
        "topology_count",
        "configuration baseline",
      ),
      unknownCount: panelNonNegativeInteger(
        baseline,
        "unknown_count",
        "configuration baseline",
      ),
    },
    versions,
    drift: {
      verdict: panelNonEmptyString(drift, "verdict", "configuration drift"),
      observedAt: panelNullableString(drift, "observed_at", "configuration drift"),
      findingCount: panelNonNegativeInteger(
        drift,
        "finding_count",
        "configuration drift",
      ),
    },
    knowledge: {
      status: panelNonEmptyString(knowledge, "status", "configuration Knowledge"),
      citationCount: panelNonNegativeInteger(
        knowledge,
        "citation_count",
        "configuration Knowledge",
      ),
      citations: panelStringArray(knowledge["citations"], "configuration citations"),
    },
    safety: {
      mutation: panelNonNegativeInteger(safety, "mutation_count", "configuration safety"),
      approval: panelNonNegativeInteger(
        safety,
        "approval_request_count",
        "configuration safety",
      ),
      mitigation: panelNonNegativeInteger(
        safety,
        "mitigation_execution_count",
        "configuration safety",
      ),
      unsupported: panelNonNegativeInteger(
        safety,
        "unsupported_claim_count",
        "configuration safety",
      ),
    },
    performance: performance === null
      ? null
      : {
        totalMs: panelNonNegativeNumber(
          performance,
          "total_ms",
          "configuration performance",
        ),
        observationMs: panelNonNegativeNumber(
          performance,
          "observation_ms",
          "configuration performance",
        ),
        knowledgeMs: panelNonNegativeNumber(
          performance,
          "knowledge_ms",
          "configuration performance",
        ),
      },
    review: {
      configured: panelBoolean(review, "configured", "configuration review"),
      state: panelNonEmptyString(review, "state", "configuration review"),
      completedRuns: panelNonNegativeInteger(
        review,
        "completed_runs",
        "configuration review",
      ),
      requiredRuns: panelNonNegativeInteger(
        review,
        "required_runs",
        "configuration review",
      ),
      failedAttempts: panelNonNegativeInteger(
        review,
        "failed_attempts",
        "configuration review",
      ),
    },
  };
}
