// Plain-language mapping for the Updates page. Pure functions only: every backend code is turned
// into a sentence here, and an unknown code is shown verbatim instead of being hidden.
import type {
  IntegrityResult, IntegrityState, UpdateChange, UpdateCheckRecord, UpdateOutcome, UpdateStatus,
} from "./api";
import { tr, type HubLocale } from "./locale";

export type BadgeVariant = "ok" | "warn" | "fail" | "info" | "mute";

const REASONS: Record<string, string> = {
  adoption_mode_review: "Automatic adoption is off, so every new catalog needs your review.",
  standing_authorization_missing:
    "Automatic adoption has no standing authorization on record, so your review is needed.",
  standing_authorization_expired:
    "The standing authorization for automatic adoption has expired, so your review is needed.",
  signature_not_verified: "The catalog signature could not be verified.",
  release_removed: "The new catalog removes a release that the accepted catalog contains.",
  release_replaced: "The new catalog changes the content of a release that already exists.",
  new_channel: "The new catalog introduces a channel that did not exist before.",
  channel_membership_removed: "The new catalog removes a release from a channel.",
  recall_lifted: "The new catalog lifts a recall that was in force.",
  recall_dropped: "The new catalog no longer lists a recall that was in force.",
  schema_range_widened: "The new catalog widens the tolerated schema range.",
  too_many_new_releases: "The new catalog adds more releases than automatic adoption allows.",
  integrity_not_verified:
    "The vendor's signed catalog roles could not be verified, so your review is needed.",
  timestamp_expired:
    "The vendor's signed timestamp has expired, so only recall changes can be adopted until fresh metadata arrives.",
  root_rotation_requires_review:
    "The vendor changed its offline root keys. A root rotation always needs your review.",
  policy_engine_unavailable: "The adoption policy engine is unavailable, so no automatic decision was made.",
  policy_evaluation_failed: "The adoption policy could not be evaluated, so no automatic decision was made.",
  policy_result_invalid: "The adoption policy returned an unusable result, so no automatic decision was made.",
};

const REASONS_KO: Record<string, string> = {
  adoption_mode_review: "자동 채택이 꺼져 있으므로 새 카탈로그마다 운영자 검토가 필요합니다.",
  standing_authorization_missing:
    "자동 채택에 대한 사전 승인 기록이 없으므로 운영자 검토가 필요합니다.",
  standing_authorization_expired:
    "자동 채택 사전 승인의 유효기간이 만료되었으므로 운영자 검토가 필요합니다.",
  signature_not_verified: "카탈로그 서명을 검증할 수 없습니다.",
  release_removed: "새 카탈로그에서 기존 수락된 카탈로그의 릴리스가 제거되었습니다.",
  release_replaced: "새 카탈로그에서 이미 존재하는 릴리스의 내용이 변경되었습니다.",
  new_channel: "새 카탈로그에 이전에 없던 채널이 추가되었습니다.",
  channel_membership_removed: "새 카탈로그에서 특정 채널의 릴리스가 제외되었습니다.",
  recall_lifted: "새 카탈로그에서 적용 중이던 회수가 해제되었습니다.",
  recall_dropped: "새 카탈로그에 적용 중이던 회수 내역이 누락되었습니다.",
  schema_range_widened: "새 카탈로그에서 허용 스키마 범위가 넓어졌습니다.",
  too_many_new_releases: "새 카탈로그에 자동 채택 한도를 초과하는 수의 릴리스가 추가되었습니다.",
  integrity_not_verified:
    "공급자의 서명된 카탈로그 역할을 검증할 수 없어 운영자 검토가 필요합니다.",
  timestamp_expired:
    "공급자의 서명된 타임스탬프가 만료되었으므로 새 메타데이터가 도착할 때까지 회수 변경만 채택할 수 있습니다.",
  root_rotation_requires_review:
    "공급자가 오프라인 루트 키를 교체했습니다. 루트 키 교체는 항상 운영자 검토가 필요합니다.",
  policy_engine_unavailable: "채택 정책 엔진을 사용할 수 없어 자동 결정을 수행하지 않았습니다.",
  policy_evaluation_failed: "채택 정책을 평가할 수 없어 자동 결정을 수행하지 않았습니다.",
  policy_result_invalid: "채택 정책이 유효하지 않은 결과를 반환하여 자동 결정을 수행하지 않았습니다.",
};

const FAILURES: Record<string, string> = {
  source_unavailable: "The vendor catalog source could not be reached. Try again later.",
  signature_missing: "The vendor catalog has no signature, so it was not accepted.",
  signature_invalid: "The vendor catalog signature is invalid, so it was not accepted.",
  candidate_invalid: "The vendor catalog is malformed or not newer than the accepted one, so it was not accepted.",
  adoption_rejected: "The Hub refused to adopt the catalog. Nothing was changed.",
  integrity_not_verified:
    "The vendor's signed catalog roles could not be verified, so the catalog was not accepted.",
};

const FAILURES_KO: Record<string, string> = {
  source_unavailable: "공급자 카탈로그 원본에 연결할 수 없습니다. 잠시 후 다시 시도하세요.",
  signature_missing: "공급자 카탈로그에 서명이 없어 수락하지 않았습니다.",
  signature_invalid: "공급자 카탈로그 서명이 유효하지 않아 수락하지 않았습니다.",
  candidate_invalid: "공급자 카탈로그 형식이 올바르지 않거나 기존 수락본보다 최신이 아니어서 수락하지 않았습니다.",
  adoption_rejected: "Hub가 카탈로그 채택을 거부했습니다. 변경된 사항이 없습니다.",
  integrity_not_verified:
    "공급자의 서명된 카탈로그 역할을 검증할 수 없어 카탈로그를 수락하지 않았습니다.",
};

const INTEGRITY_REASONS: Record<string, string> = {
  catalog_version_rollback: "A signed record carries an older version than this Hub already verified.",
  catalog_root_signature_invalid: "The root record lacks enough valid offline-key signatures.",
  catalog_root_pin_mismatch: "The first root record does not match the root keys pinned in this Hub.",
  catalog_root_rotation_unsigned_by_previous:
    "A new root record was not signed by enough keys of the previous root.",
  catalog_root_chain_invalid: "The root record chain is incomplete or out of order.",
  catalog_root_expired: "The root record has expired.",
  catalog_root_export_key_missing: "The root record names no key for the catalog export.",
  catalog_root_equivocation: "The vendor served two different root records for one version.",
  catalog_snapshot_equivocation: "The vendor served two different snapshots for one version.",
  catalog_timestamp_equivocation: "The vendor served two different timestamps for one version.",
  catalog_snapshot_signature_invalid: "The snapshot signature is not valid for an authorized key.",
  catalog_timestamp_signature_invalid: "The timestamp signature is not valid for an authorized key.",
  timestamp_snapshot_mismatch: "The timestamp does not name the snapshot that was served.",
  recall_sequence_gap: "The recall sequence has a gap or went backwards, so a recall may be withheld.",
  export_digest_mismatch: "The catalog export does not match the digest the snapshot names.",
  snapshot_export_mismatch: "The snapshot does not describe the catalog that was served.",
  catalog_timestamp_expired: "The signed timestamp has expired.",
  allowed: "All signed records verified.",
};

const INTEGRITY_REASONS_KO: Record<string, string> = {
  catalog_version_rollback: "서명된 레코드의 버전이 이 Hub가 이미 검증한 버전보다 낮습니다.",
  catalog_root_signature_invalid: "루트 레코드에 유효한 오프라인 키 서명 수가 부족합니다.",
  catalog_root_pin_mismatch: "첫 번째 루트 레코드가 이 Hub에 고정된 루트 키와 일치하지 않습니다.",
  catalog_root_rotation_unsigned_by_previous:
    "새 루트 레코드에 이전 루트 키의 충분한 서명이 포함되지 않았습니다.",
  catalog_root_chain_invalid: "루트 레코드 체인이 불완전하거나 순서가 올바르지 않습니다.",
  catalog_root_expired: "루트 레코드의 유효기간이 만료되었습니다.",
  catalog_root_export_key_missing: "루트 레코드에 카탈로그 내보내기용 키가 지정되어 있지 않습니다.",
  catalog_root_equivocation: "공급자가 동일한 버전에 대해 서로 다른 루트 레코드 두 개를 제공했습니다.",
  catalog_snapshot_equivocation: "공급자가 동일한 버전에 대해 서로 다른 스냅샷 두 개를 제공했습니다.",
  catalog_timestamp_equivocation: "공급자가 동일한 버전에 대해 서로 다른 타임스탬프 두 개를 제공했습니다.",
  catalog_snapshot_signature_invalid: "스냅샷 서명이 승인된 키에 대해 유효하지 않습니다.",
  catalog_timestamp_signature_invalid: "타임스탬프 서명이 승인된 키에 대해 유효하지 않습니다.",
  timestamp_snapshot_mismatch: "타임스탬프가 제공된 스냅샷을 가리키지 않습니다.",
  recall_sequence_gap: "회수 시퀀스에 누락이 있거나 역행하여 회수 공지가 누락되었을 수 있습니다.",
  export_digest_mismatch: "카탈로그 내보내기 데이터가 스냅샷에 기록된 다이제스트와 일치하지 않습니다.",
  snapshot_export_mismatch: "스냅샷이 제공된 카탈로그를 설명하지 않습니다.",
  catalog_timestamp_expired: "서명된 타임스탬프의 유효기간이 만료되었습니다.",
  allowed: "모든 서명된 레코드가 검증되었습니다.",
};

/** One sentence for a catalog-role verification code. An unknown code is shown verbatim. */
export function describeIntegrityReason(code: string, locale: HubLocale = "en"): string {
  if (locale === "ko") {
    return INTEGRITY_REASONS_KO[code] ?? `알 수 없는 무결성 코드: ${code}`;
  }
  return INTEGRITY_REASONS[code] ?? `Unrecognized integrity code: ${code}`;
}

export interface IntegrityView {
  badge: { label: string; variant: BadgeVariant };
  lines: string[];
}

/** The state to show for one verification: failed, expired, awaiting a rotation review, or fine. */
export function describeIntegrity(result: IntegrityResult, locale: HubLocale = "en"): IntegrityView {
  if (!result.verified) {
    return {
      badge: { label: tr(locale, "Not verified", "미검증"), variant: "fail" },
      lines: [describeIntegrityReason(result.reason, locale)],
    };
  }
  if (result.root_rotation) {
    const next = result.root ? result.root.version : tr(locale, "a newer version", "새 버전");
    return {
      badge: { label: tr(locale, "Root rotation awaiting review", "루트 키 교체 검토 대기"), variant: "warn" },
      lines: [
        tr(
          locale,
          `The vendor rotated its offline root keys (root version ${result.previous_root_version} to ${next}). A rotation is never adopted automatically.`,
          `공급자가 오프라인 루트 키를 교체했습니다 (루트 버전 ${result.previous_root_version} -> ${next}). 루트 키 교체는 자동으로 채택되지 않습니다.`,
        ),
      ],
    };
  }
  if (result.expired) {
    return {
      badge: { label: tr(locale, "Timestamp expired", "타임스탬프 만료됨"), variant: "warn" },
      lines: [
        tr(
          locale,
          "The signed timestamp has expired. Only recall roll-off Plans are issued until fresh metadata arrives.",
          "서명된 타임스탬프가 만료되었습니다. 새 메타데이터가 도착할 때까지 회수 롤오프 계획만 발급됩니다.",
        ),
        ...(result.demote_operator_overrides_to_shadow
          ? [
              tr(
                locale,
                "Operator-override promotions return to shadow mode until then.",
                "그때까지 운영자 재정의 승격은 shadow 모드로 전환됩니다.",
              ),
            ]
          : []),
      ],
    };
  }
  return {
    badge: { label: tr(locale, "Verified", "검증됨"), variant: "ok" },
    lines: [describeIntegrityReason(result.reason, locale)],
  };
}

/** Whether the persisted timestamp has passed, judged now so an old check cannot look fresh. */
export function isTimestampExpired(state: IntegrityState, now: Date = new Date()): boolean {
  if (state.timestamp_expires_at === null) return true;
  const expiry = Date.parse(state.timestamp_expires_at);
  return Number.isNaN(expiry) || expiry <= now.getTime();
}

export function describeVersions(
  state: Pick<IntegrityState, "root_version" | "snapshot_version" | "timestamp_version">,
  locale: HubLocale = "en",
): string {
  if (locale === "ko") {
    return `루트 v${state.root_version}, 스냅샷 v${state.snapshot_version}, 타임스탬프 v${state.timestamp_version}`;
  }
  return `Root v${state.root_version}, snapshot v${state.snapshot_version}, timestamp v${state.timestamp_version}`;
}

const UNCHANGED: Record<string, string> = {
  source_reports_current: "The vendor reports no newer catalog than the one already accepted.",
  digest_already_accepted: "The vendor catalog is identical to the one already accepted.",
};

const UNCHANGED_KO: Record<string, string> = {
  source_reports_current: "공급자에 이미 수락된 카탈로그보다 더 새로운 카탈로그가 없습니다.",
  digest_already_accepted: "공급자 카탈로그가 이미 수락된 카탈로그와 동일합니다.",
};

export function describeReason(code: string, locale: HubLocale = "en"): string {
  const known = locale === "ko" ? REASONS_KO[code] : REASONS[code];
  if (known) return known;
  const channel = /^channel_not_allowed:(.+)$/.exec(code);
  if (channel) {
    return tr(
      locale,
      `The new catalog publishes releases to channel ${channel[1]}, which automatic adoption does not allow.`,
      `새 카탈로그가 자동 채택이 허용되지 않는 ${channel[1]} 채널에 릴리스를 게시합니다.`,
    );
  }
  return tr(locale, `Unrecognized reason code: ${code}`, `알 수 없는 사유 코드: ${code}`);
}

export function splitReasons(detail: string): string[] {
  return detail.split(",").map(part => part.trim()).filter(part => part.length > 0);
}

/** One human-readable sentence per code carried by a check record. */
export function describeDetail(outcome: UpdateOutcome, detail: string, locale: HubLocale = "en"): string[] {
  switch (outcome) {
    case "unchanged": {
      const map = locale === "ko" ? UNCHANGED_KO : UNCHANGED;
      return [map[detail] ?? tr(locale, `Unrecognized status code: ${detail}`, `알 수 없는 상태 코드: ${detail}`)];
    }
    case "failed": {
      const map = locale === "ko" ? FAILURES_KO : FAILURES;
      return [map[detail] ?? tr(locale, `Unrecognized failure code: ${detail}`, `알 수 없는 실패 코드: ${detail}`)];
    }
    case "review_required": {
      const reasons = splitReasons(detail);
      return reasons.length === 0
        ? [tr(locale, "A new catalog is waiting for your review.", "새 카탈로그가 운영자 검토를 기다리고 있습니다.")]
        : reasons.map(code => describeReason(code, locale));
    }
    case "adopted":
      return [tr(locale, "The new catalog was adopted.", "새 카탈로그가 채택되었습니다.")];
    default:
      return [tr(locale, `Unrecognized status code: ${detail}`, `알 수 없는 상태 코드: ${detail}`)];
  }
}

const OUTCOMES: Record<UpdateOutcome, { label: string; labelKo: string; variant: BadgeVariant }> = {
  unchanged: { label: "Up to date", labelKo: "최신 상태", variant: "ok" },
  adopted: { label: "Adopted", labelKo: "채택됨", variant: "ok" },
  review_required: { label: "Review required", labelKo: "검토 필요", variant: "warn" },
  failed: { label: "Check failed", labelKo: "확인 실패", variant: "fail" },
};

export function outcomeBadge(outcome: string, locale: HubLocale = "en"): { label: string; variant: BadgeVariant } {
  const found = OUTCOMES[outcome as UpdateOutcome];
  if (!found) return { label: outcome, variant: "mute" };
  return { label: tr(locale, found.label, found.labelKo), variant: found.variant };
}

export function shortDigest(sha256: string): string {
  return sha256.slice(0, 12);
}

export function describeSchedule(
  status: Pick<UpdateStatus, "mode" | "check_interval_seconds">,
  locale: HubLocale = "en",
): string {
  if (locale === "ko") {
    const adoptionKo = `자동 채택 ${status.mode === "auto" ? "켜짐" : "꺼짐"}`;
    const seconds = status.check_interval_seconds;
    if (!(seconds > 0)) return `주기적 확인 꺼짐; ${adoptionKo}.`;
    let everyKo: string;
    if (seconds < 60) {
      everyKo = `${seconds}초`;
    } else if (seconds % 3600 === 0) {
      everyKo = `${seconds / 3600}시간`;
    } else {
      everyKo = `${Math.round(seconds / 60)}분`;
    }
    return `${everyKo}마다 공급자 카탈로그를 확인합니다 (${adoptionKo}).`;
  }
  const adoption = `automatic adoption is ${status.mode === "auto" ? "on" : "off"}`;
  const seconds = status.check_interval_seconds;
  if (!(seconds > 0)) return `Periodic checks are off; ${adoption}.`;
  let every: string;
  if (seconds < 60) {
    every = seconds === 1 ? "second" : `${seconds} seconds`;
  } else if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    every = hours === 1 ? "hour" : `${hours} hours`;
  } else {
    const minutes = Math.round(seconds / 60);
    every = minutes === 1 ? "minute" : `${minutes} minutes`;
  }
  return `Checks the vendor catalog every ${every}; ${adoption}.`;
}

export interface ChangeSection {
  label: string;
  items: string[];
}

export function summarizeChange(change: UpdateChange, locale: HubLocale = "en"): ChangeSection[] {
  const noChannel = tr(locale, "no channel", "채널 없음");
  const seqLabel = tr(locale, "sequence", "시퀀스");
  const sections: ChangeSection[] = [
    {
      label: tr(locale, "Added releases", "추가된 릴리스"),
      items: change.added_releases.map(
        r => `${r.release_id} (${r.channels.length > 0 ? r.channels.join(", ") : noChannel})`),
    },
    { label: tr(locale, "Removed releases", "제거된 릴리스"), items: [...change.removed_releases] },
    { label: tr(locale, "Changed releases", "변경된 릴리스"), items: [...change.changed_releases] },
    {
      label: tr(locale, "Added to channels", "채널에 추가됨"),
      items: change.channel_additions.map(c =>
        locale === "ko" ? `${c.channel}: ${c.release_id}` : `${c.release_id} in ${c.channel}`),
    },
    {
      label: tr(locale, "Removed from channels", "채널에서 제외됨"),
      items: change.channel_removals.map(c =>
        locale === "ko" ? `${c.channel}: ${c.release_id}` : `${c.release_id} from ${c.channel}`),
    },
    { label: tr(locale, "New channels", "신규 채널"), items: [...change.new_channels] },
    {
      label: tr(locale, "New recalls", "신규 회수"),
      items: change.new_recalls.map(r => `${r.scope} ${r.target} (${seqLabel} ${r.sequence})`),
    },
    {
      label: tr(locale, "Lifted recalls", "해제된 회수"),
      items: change.lifted_recalls.map(r => `${r.scope} ${r.target} (${seqLabel} ${r.sequence})`),
    },
    {
      label: tr(locale, "Dropped recalls", "제외된 회수"),
      items: (change.removed_recalls ?? []).map(
        r => `${r.scope} ${r.target} (${seqLabel} ${r.sequence})`,
      ),
    },
  ];
  const filled = sections.filter(section => section.items.length > 0);
  if (change.schema_widened) {
    filled.push({
      label: tr(locale, "Schema", "스키마"),
      items: [tr(locale, "The tolerated schema range is widened.", "허용 스키마 범위가 넓어졌습니다.")],
    });
  }
  return filled;
}

export function hasUrgentRecall(change: UpdateChange): boolean {
  return change.new_recalls.length > 0;
}

/** Only a verified-signature candidate that still awaits review may be applied from this page. */
export function canApply(record: UpdateCheckRecord | null): boolean {
  return record !== null && record.outcome === "review_required" &&
    record.candidate !== null && record.candidate.signature_verified &&
    // The Hub refuses everything but recalls while the signed timestamp is expired.
    !record.candidate.decision.reasons.includes("timestamp_expired");
}

const PLAN_OUTCOMES: Record<string, { en: string; ko: string }> = {
  issued: { en: "Plan issued", ko: "계획 발급됨" },
  unchanged: { en: "Plan unchanged", ko: "계획 변경 없음" },
  waiting: { en: "Waiting for a maintenance window", ko: "유지보수 구간 대기 중" },
  "no-eligible-release": { en: "No eligible release", ko: "적격 릴리스 없음" },
  "up-to-date": { en: "Up to date", ko: "최신 상태" },
  "no-managed-entity": { en: "No managed Entity", ko: "관리 대상 엔티티 없음" },
};

export function describePlanOutcome(outcome: string, locale: HubLocale = "en"): string {
  const found = PLAN_OUTCOMES[outcome];
  if (!found) return outcome;
  return tr(locale, found.en, found.ko);
}

export const CANDIDATE_CHANGED_MESSAGE =
  "The vendor catalog changed after you reviewed it. Nothing was applied. The new candidate is shown below; review it before applying.";
export const CANDIDATE_CHANGED_MESSAGE_KO =
  "검토 이후 공급자 카탈로그가 변경되어 적용하지 않았습니다. 아래의 새 후보 카탈로그를 검토한 뒤 적용하세요.";

export function describeActionError(
  error: unknown,
  locale: HubLocale = "en",
): { message: string; candidateChanged: boolean } {
  const e = error as { status?: unknown; reasonCode?: unknown } | null;
  if (e && e.status === 409 && e.reasonCode === "candidate_changed") {
    return {
      message: tr(locale, CANDIDATE_CHANGED_MESSAGE, CANDIDATE_CHANGED_MESSAGE_KO),
      candidateChanged: true,
    };
  }
  if (e && e.status === 422) {
    return {
      message: tr(
        locale,
        "The Hub rejected the request as invalid. Nothing was applied.",
        "Hub가 유효하지 않은 요청으로 거부하여 적용되지 않았습니다.",
      ),
      candidateChanged: false,
    };
  }
  const code = e && typeof e.reasonCode === "string" ? e.reasonCode : null;
  return {
    message: code
      ? tr(
          locale,
          `The request failed (${code}). Nothing was applied.`,
          `요청이 실패했습니다 (${code}). 적용된 사항이 없습니다.`,
        )
      : tr(
          locale,
          "The request failed. Nothing was applied.",
          "요청이 실패했습니다. 적용된 사항이 없습니다.",
        ),
    candidateChanged: false,
  };
}
