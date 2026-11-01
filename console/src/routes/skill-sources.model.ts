import {
  panelArray,
  panelBoolean,
  panelContractError,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelString,
} from "./panel-decode";

export type SkillSourceLocale = "en" | "ko";
export type SkillSourceDisplayStatus =
  | "disabled_by_default"
  | "not_measured"
  | "ready"
  | "refresh_failed"
  | "revoked";

export interface SkillSourceProjectionItem {
  readonly source_id: string;
  readonly kind: string;
  readonly location: string;
  readonly trust_tier: string;
  readonly owner: string;
  readonly allowed_path: string;
  readonly refresh_policy: "manual" | "scheduled";
  readonly refresh_interval_seconds: number;
  readonly enabled: boolean;
  readonly revision: string;
  readonly last_refresh_at: string | null;
  readonly next_refresh_at: string | null;
  readonly last_etag: string | null;
  readonly last_revision: string | null;
  readonly error_count: number;
  readonly retry_at: string | null;
  readonly last_error_kind: string | null;
}

export interface SkillCandidateProjectionItem {
  readonly candidate_id: string;
  readonly source_id: string;
  readonly quarantine_id: string;
  readonly artifact_digest: string;
  readonly prior_installed_digest: string | null;
  readonly created_at: string;
  readonly verdict: string;
  readonly state: string;
  readonly disabled: true;
}

export interface SkillRevocationProjectionItem {
  readonly revocation_id: string;
  readonly source_id: string;
  readonly artifact_digest: string;
  readonly reason: string;
  readonly revoked_at: string;
}

export interface SkillSourceCatalogProjection {
  readonly read_only: true;
  readonly execution_authority: "none";
  readonly sources: readonly SkillSourceProjectionItem[];
  readonly candidates: readonly SkillCandidateProjectionItem[];
  readonly revocations: readonly SkillRevocationProjectionItem[];
}

export interface SkillSourceCardViewModel {
  readonly sourceId: string;
  readonly location: string;
  readonly owner: string;
  readonly allowedPath: string;
  readonly enabled: boolean;
  readonly status: SkillSourceDisplayStatus;
  readonly statusLabel: string;
  readonly refreshPolicyLabel: string;
  readonly candidateCount: number;
  readonly revocationCount: number;
  readonly lastRefreshAt: string | null;
  readonly lastRevision: string | null;
}

export interface SkillSourcesViewModel {
  readonly locale: SkillSourceLocale;
  readonly readOnly: true;
  readonly executionAuthority: "none";
  readonly canApproveInConsole: false;
  readonly canRevokeInConsole: false;
  readonly title: string;
  readonly subtitle: string;
  readonly governanceNotice: string;
  readonly emptyMessage: string;
  readonly sources: readonly SkillSourceCardViewModel[];
}

const FORBIDDEN_KEYS = new Set([
  "access_token",
  "authentication_token",
  "authorization",
  "bearer_token",
  "credential",
  "credentials",
  "private_key",
  "publisher_signature",
  "raw_token",
  "secret",
  "secrets",
]);

const COPY: Record<
  SkillSourceLocale,
  {
    readonly title: string;
    readonly subtitle: string;
    readonly governanceNotice: string;
    readonly emptyMessage: string;
    readonly policies: Record<"manual" | "scheduled", string>;
    readonly statuses: Record<SkillSourceDisplayStatus, string>;
  }
> = {
  en: {
    title: "External Skill Sources",
    subtitle: "Read-only quarantine, candidate, and revocation posture across approved repositories.",
    governanceNotice:
      "Console view is read-only. Sources and candidates stay disabled by default and grant no execution authority.",
    emptyMessage: "No approved skill sources are registered.",
    policies: {
      manual: "Manual refresh",
      scheduled: "Scheduled refresh",
    },
    statuses: {
      disabled_by_default: "Disabled by default",
      not_measured: "Enabled (refresh not yet measured)",
      ready: "Refresh verified",
      refresh_failed: "Refresh degraded",
      revoked: "Revoked",
    },
  },
  ko: {
    title: "외부 스킬 소스",
    subtitle: "승인된 저장소의 격리, 후보 및 폐기 상태를 읽기 전용으로 표시합니다.",
    governanceNotice:
      "콘솔 화면은 읽기 전용입니다. 소스와 업데이트 후보는 기본적으로 비활성 상태를 유지하며 실행 권한을 부여하지 않습니다.",
    emptyMessage: "등록된 승인 스킬 소스가 없습니다.",
    policies: {
      manual: "수동 새로고침",
      scheduled: "예약 새로고침",
    },
    statuses: {
      disabled_by_default: "기본 비활성화",
      not_measured: "활성화됨 (새로고침 미측정)",
      ready: "새로고침 검증됨",
      refresh_failed: "새로고침 오류",
      revoked: "폐기됨",
    },
  },
};

function rejectForbiddenKeys(record: Readonly<Record<string, unknown>>, label: string): void {
  for (const key of Object.keys(record)) {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) {
      throw panelContractError(`${label} MUST NOT expose secret field ${key}`);
    }
  }
}

export function decodeSkillSourceProjection(value: unknown): SkillSourceCatalogProjection {
  const root = panelRecord(value, "SkillSourceProjection");
  rejectForbiddenKeys(root, "SkillSourceProjection");
  if (panelBoolean(root, "read_only", "SkillSourceProjection") !== true) {
    throw panelContractError("SkillSourceProjection.read_only MUST be true");
  }
  if (panelString(root, "execution_authority", "SkillSourceProjection") !== "none") {
    throw panelContractError("SkillSourceProjection.execution_authority MUST be none");
  }
  const sources = panelArray(root.sources, "SkillSourceProjection.sources").map(
    (entry, idx): SkillSourceProjectionItem => {
      const label = `SkillSourceProjection.sources[${idx}]`;
      const row = panelRecord(entry, label);
      rejectForbiddenKeys(row, label);
      const policy = panelNonEmptyString(row, "refresh_policy", label);
      if (policy !== "manual" && policy !== "scheduled") {
        throw panelContractError(`${label}.refresh_policy is invalid`);
      }
      return {
        source_id: panelNonEmptyString(row, "source_id", label),
        kind: panelNonEmptyString(row, "kind", label),
        location: panelNonEmptyString(row, "location", label),
        trust_tier: panelNonEmptyString(row, "trust_tier", label),
        owner: panelNonEmptyString(row, "owner", label),
        allowed_path: panelNonEmptyString(row, "allowed_path", label),
        refresh_policy: policy,
        refresh_interval_seconds: panelNonNegativeInteger(row, "refresh_interval_seconds", label),
        enabled: panelBoolean(row, "enabled", label),
        revision: panelNonEmptyString(row, "revision", label),
        last_refresh_at: panelNullableString(row, "last_refresh_at", label),
        next_refresh_at: panelNullableString(row, "next_refresh_at", label),
        last_etag: panelNullableString(row, "last_etag", label),
        last_revision: panelNullableString(row, "last_revision", label),
        error_count: panelNonNegativeInteger(row, "error_count", label),
        retry_at: panelNullableString(row, "retry_at", label),
        last_error_kind: panelNullableString(row, "last_error_kind", label),
      };
    },
  );

  const candidates = panelArray(root.candidates, "SkillSourceProjection.candidates").map(
    (entry, idx) => {
      const label = `SkillSourceProjection.candidates[${idx}]`;
      const row = panelRecord(entry, label);
      rejectForbiddenKeys(row, label);
      if (panelBoolean(row, "disabled", label) !== true) {
        throw panelContractError(`${label}.disabled MUST remain true`);
      }
      const digest = panelNonEmptyString(row, "artifact_digest", label);
      if (!/^[0-9a-f]{64}$/.test(digest)) {
        throw panelContractError(`${label}.artifact_digest MUST be lowercase SHA-256`);
      }
      return {
        candidate_id: panelNonEmptyString(row, "candidate_id", label),
        source_id: panelNonEmptyString(row, "source_id", label),
        quarantine_id: panelNonEmptyString(row, "quarantine_id", label),
        artifact_digest: digest,
        prior_installed_digest: panelNullableString(row, "prior_installed_digest", label),
        created_at: panelNonEmptyString(row, "created_at", label),
        verdict: panelNonEmptyString(row, "verdict", label),
        state: panelNonEmptyString(row, "state", label),
        disabled: true as const,
      };
    },
  );

  const revocations = panelArray(root.revocations, "SkillSourceProjection.revocations").map(
    (entry, idx) => {
      const label = `SkillSourceProjection.revocations[${idx}]`;
      const row = panelRecord(entry, label);
      rejectForbiddenKeys(row, label);
      return {
        revocation_id: panelNonEmptyString(row, "revocation_id", label),
        source_id: panelNonEmptyString(row, "source_id", label),
        artifact_digest: panelNonEmptyString(row, "artifact_digest", label),
        reason: panelNonEmptyString(row, "reason", label),
        revoked_at: panelNonEmptyString(row, "revoked_at", label),
      };
    },
  );

  return {
    read_only: true,
    execution_authority: "none",
    sources,
    candidates,
    revocations,
  };
}

function resolveSourceStatus(
  source: SkillSourceProjectionItem,
  revocationCount: number,
): SkillSourceDisplayStatus {
  if (revocationCount > 0) return "revoked";
  if (!source.enabled) return "disabled_by_default";
  if (source.error_count > 0 || source.last_error_kind !== null) return "refresh_failed";
  if (source.last_refresh_at === null) return "not_measured";
  return "ready";
}

export function buildSkillSourcesViewModel(
  projection: SkillSourceCatalogProjection,
  locale: SkillSourceLocale = "en",
): SkillSourcesViewModel {
  const copy = COPY[locale];
  const cards: SkillSourceCardViewModel[] = projection.sources.map((source) => {
    const candidateCount = projection.candidates.filter(
      (item) => item.source_id === source.source_id,
    ).length;
    const revocationCount = projection.revocations.filter(
      (item) => item.source_id === source.source_id,
    ).length;
    const status = resolveSourceStatus(source, revocationCount);
    return {
      sourceId: source.source_id,
      location: source.location,
      owner: source.owner,
      allowedPath: source.allowed_path,
      enabled: source.enabled,
      status,
      statusLabel: copy.statuses[status],
      refreshPolicyLabel: copy.policies[source.refresh_policy],
      candidateCount,
      revocationCount,
      lastRefreshAt: source.last_refresh_at,
      lastRevision: source.last_revision,
    };
  });

  return {
    locale,
    readOnly: true,
    executionAuthority: "none",
    canApproveInConsole: false,
    canRevokeInConsole: false,
    title: copy.title,
    subtitle: copy.subtitle,
    governanceNotice: copy.governanceNotice,
    emptyMessage: copy.emptyMessage,
    sources: cards,
  };
}
