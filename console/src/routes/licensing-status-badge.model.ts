import {
  panelBoolean,
  panelContractError,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelString,
} from "./panel-decode";

export type LicensingLocale = "en" | "ko";
export type LicensingWarningState =
  | "normal"
  | "expiring_soon"
  | "expired"
  | "clock_regression"
  | "read_only_trial";
export type LicensingWatermarkNotice = "none" | "evaluation-ended" | "not-activated";
export type LicensingBadgeTone = "success" | "warning" | "danger" | "neutral";

export interface LicensingWarningProjectionPayload {
  readonly type: "licensing.warning-projection";
  readonly schema_version: "1.0.0";
  readonly read_only: true;
  readonly authority: "none";
  readonly secret_free: true;
  readonly principal_id: string;
  readonly state: LicensingWarningState;
  readonly license_status: string;
  readonly watermark_notice: LicensingWatermarkNotice;
  readonly acting_available: boolean;
  readonly proactive_warning: boolean;
  readonly license_id: string | null;
  readonly expires_at: string | null;
  readonly remaining_seconds: number | null;
  readonly remaining_days: number | null;
  readonly days_remaining?: number | null;
  readonly observed_at: string;
  readonly reason_code: string;
}

export interface LicensingStatusBadgeViewModel {
  readonly locale: LicensingLocale;
  readonly readOnly: true;
  readonly authority: "none";
  readonly secretFree: true;
  readonly state: LicensingWarningState;
  readonly badgeLabel: string;
  readonly tone: LicensingBadgeTone;
  readonly actingAvailable: boolean;
  readonly showProactiveWarning: boolean;
  readonly isUrgentWarning: boolean;
  readonly warningTitle: string | null;
  readonly warningDetail: string | null;
  readonly remainingDaysDisplay: string | null;
  readonly watermarkNotice: LicensingWatermarkNotice;
}

const WARNING_STATES = new Set<LicensingWarningState>([
  "normal",
  "expiring_soon",
  "expired",
  "clock_regression",
  "read_only_trial",
]);
const WATERMARK_NOTICES = new Set<LicensingWatermarkNotice>([
  "none",
  "evaluation-ended",
  "not-activated",
]);
const FORBIDDEN_KEYS = new Set([
  "token",
  "raw_token",
  "license_token",
  "private_key",
  "signing_key",
  "signature",
  "secret",
  "password",
  "document_bytes",
]);
const SECRET_PATTERN =
  /(-----BEGIN|PRIVATE KEY|eyJ[A-Za-z0-9_-]{10,}|[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{24,})/i;

const BADGE_LABELS: Record<LicensingLocale, Record<LicensingWarningState, string>> = {
  en: {
    normal: "Entitlement active",
    expiring_soon: "Renewal required soon",
    expired: "Entitlement expired",
    clock_regression: "Clock regression blocked",
    read_only_trial: "Observation-only mode",
  },
  ko: {
    normal: "사용 권한 활성",
    expiring_soon: "갱신 예정 경고",
    expired: "사용 권한 만료됨",
    clock_regression: "시계 역행 차단됨",
    read_only_trial: "읽기 전용 관찰 모드",
  },
};

const WARNING_COPY: Record<
  LicensingLocale,
  Record<Exclude<LicensingWarningState, "normal">, { readonly title: string; readonly detail: string }>
> = {
  en: {
    expiring_soon: {
      title: "Capability license expires soon",
      detail: "Issue and bind a renewed token before expiry to avoid degrading to read-only mode.",
    },
    expired: {
      title: "Evaluation or capability license has expired",
      detail: "Observation continues, but acting capabilities stay blocked until renewal.",
    },
    clock_regression: {
      title: "Host wall-clock regression detected",
      detail: "Acting capabilities are sticky-denied until trusted time and entitlement are restored.",
    },
    read_only_trial: {
      title: "Acting capabilities are not activated",
      detail: "FDAI is running in read-only observation mode with no acting entitlement.",
    },
  },
  ko: {
    expiring_soon: {
      title: "기능 라이선스 만료 임박",
      detail: "읽기 전용 모드로 전환되지 않도록 만료 전에 갱신된 토큰을 발급하고 바인딩하십시오.",
    },
    expired: {
      title: "평가 기간 또는 기능 라이선스가 만료되었습니다",
      detail: "관찰은 계속되지만 갱신할 때까지 변경 작업은 차단됩니다.",
    },
    clock_regression: {
      title: "호스트 시계 역행이 감지되었습니다",
      detail: "신뢰할 수 있는 시간과 권한이 복구될 때까지 변경 작업이 영구 차단됩니다.",
    },
    read_only_trial: {
      title: "변경 작업 권한이 활성화되지 않았습니다",
      detail: "FDAI가 변경 권한 없이 읽기 전용 관찰 모드로 실행 중입니다.",
    },
  },
};

function scanNestedSecrets(value: unknown): void {
  if (value === null || typeof value !== "object") {
    if (typeof value === "string" && SECRET_PATTERN.test(value)) {
      throw panelContractError("LicensingWarningProjection contains secret-like material");
    }
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      scanNestedSecrets(item);
    }
    return;
  }
  const record = value as Record<string, unknown>;
  for (const [key, child] of Object.entries(record)) {
    if (FORBIDDEN_KEYS.has(key) || FORBIDDEN_KEYS.has(key.toLowerCase())) {
      throw panelContractError(`LicensingWarningProjection MUST NOT expose secret field ${key}`);
    }
    scanNestedSecrets(child);
  }
}

export function decodeLicensingWarningProjection(
  value: unknown,
): LicensingWarningProjectionPayload {
  const root = panelRecord(value, "LicensingWarningProjection");
  scanNestedSecrets(root);
  if (root["days_remaining"] !== undefined && root["days_remaining"] !== null) {
    const rawDays = root["days_remaining"];
    if (typeof rawDays !== "number" || !Number.isFinite(rawDays) || rawDays < 0) {
      throw panelContractError("LicensingWarningProjection.days_remaining MUST NOT be negative");
    }
  }
  if (panelString(root, "type", "LicensingWarningProjection") !== "licensing.warning-projection") {
    throw panelContractError("LicensingWarningProjection.type is invalid");
  }
  if (panelString(root, "schema_version", "LicensingWarningProjection") !== "1.0.0") {
    throw panelContractError("LicensingWarningProjection.schema_version is invalid");
  }
  if (!panelBoolean(root, "read_only", "LicensingWarningProjection")) {
    throw panelContractError("LicensingWarningProjection.read_only MUST be true");
  }
  if (panelString(root, "authority", "LicensingWarningProjection") !== "none") {
    throw panelContractError("LicensingWarningProjection.authority MUST be none");
  }
  if (!panelBoolean(root, "secret_free", "LicensingWarningProjection")) {
    throw panelContractError("LicensingWarningProjection.secret_free MUST be true");
  }
  const state = panelString(root, "state", "LicensingWarningProjection") as LicensingWarningState;
  if (!WARNING_STATES.has(state)) {
    throw panelContractError("LicensingWarningProjection.state is invalid");
  }
  const notice = panelString(
    root,
    "watermark_notice",
    "LicensingWarningProjection",
  ) as LicensingWatermarkNotice;
  if (!WATERMARK_NOTICES.has(notice)) {
    throw panelContractError("LicensingWarningProjection.watermark_notice is invalid");
  }
  const licenseId = panelNullableString(root, "license_id", "LicensingWarningProjection");
  const reasonCode = panelNonEmptyString(root, "reason_code", "LicensingWarningProjection");
  const licenseStatus = panelNonEmptyString(root, "license_status", "LicensingWarningProjection");
  for (const candidate of [licenseId, reasonCode, licenseStatus]) {
    if (candidate !== null && SECRET_PATTERN.test(candidate)) {
      throw panelContractError("LicensingWarningProjection contains secret-like material");
    }
  }
  const remainingDays =
    root["remaining_days"] === null || root["remaining_days"] === undefined
      ? root["days_remaining"] === null || root["days_remaining"] === undefined
        ? null
        : panelNonNegativeInteger(root, "days_remaining", "LicensingWarningProjection")
      : panelNonNegativeInteger(root, "remaining_days", "LicensingWarningProjection");
  const daysRemaining =
    root["days_remaining"] === null || root["days_remaining"] === undefined
      ? remainingDays
      : panelNonNegativeInteger(root, "days_remaining", "LicensingWarningProjection");
  return {
    type: "licensing.warning-projection",
    schema_version: "1.0.0",
    read_only: true,
    authority: "none",
    secret_free: true,
    principal_id: panelNonEmptyString(root, "principal_id", "LicensingWarningProjection"),
    state,
    license_status: licenseStatus,
    watermark_notice: notice,
    acting_available: panelBoolean(root, "acting_available", "LicensingWarningProjection"),
    proactive_warning: panelBoolean(root, "proactive_warning", "LicensingWarningProjection"),
    license_id: licenseId,
    expires_at: panelNullableString(root, "expires_at", "LicensingWarningProjection"),
    remaining_seconds:
      root["remaining_seconds"] === null
        ? null
        : panelNonNegativeInteger(root, "remaining_seconds", "LicensingWarningProjection"),
    remaining_days: remainingDays,
    days_remaining: daysRemaining,
    observed_at: panelNonEmptyString(root, "observed_at", "LicensingWarningProjection"),
    reason_code: reasonCode,
  };
}

export function formatLicensingStatusBadge(
  payload: LicensingWarningProjectionPayload | null | undefined,
  locale: LicensingLocale = "en",
): LicensingStatusBadgeViewModel {
  if (payload === null || payload === undefined) {
    const copy = WARNING_COPY[locale].read_only_trial;
    return {
      locale,
      readOnly: true,
      authority: "none",
      secretFree: true,
      state: "read_only_trial",
      badgeLabel: BADGE_LABELS[locale].read_only_trial,
      tone: "neutral",
      actingAvailable: false,
      showProactiveWarning: true,
      isUrgentWarning: false,
      warningTitle: copy.title,
      warningDetail: copy.detail,
      remainingDaysDisplay: null,
      watermarkNotice: "not-activated",
    };
  }
  const tone: LicensingBadgeTone =
    payload.state === "normal"
      ? "success"
      : payload.state === "expiring_soon"
        ? "warning"
        : payload.state === "read_only_trial"
          ? "neutral"
          : "danger";
  const copy = payload.state === "normal" ? null : WARNING_COPY[locale][payload.state];
  const effectiveDays = payload.days_remaining ?? payload.remaining_days;
  const daysDisplay =
    effectiveDays === null
      ? null
      : locale === "ko"
        ? `${effectiveDays}일 남음`
        : `${effectiveDays}d remaining`;
  const isUrgentWarning =
    payload.state === "expiring_soon" && effectiveDays !== null && effectiveDays <= 7;
  return {
    locale,
    readOnly: true,
    authority: "none",
    secretFree: true,
    state: payload.state,
    badgeLabel: BADGE_LABELS[locale][payload.state],
    tone,
    actingAvailable: payload.acting_available,
    showProactiveWarning: payload.proactive_warning,
    isUrgentWarning,
    warningTitle: copy?.title ?? null,
    warningDetail: copy?.detail ?? null,
    remainingDaysDisplay: daysDisplay,
    watermarkNotice: payload.watermark_notice,
  };
}
