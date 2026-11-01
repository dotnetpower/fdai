import { describe, expect, it } from "vitest";
import {
  decodeLicensingWarningProjection,
  formatLicensingStatusBadge,
} from "./licensing-status-badge.model";

const BASE_PAYLOAD = {
  type: "licensing.warning-projection",
  schema_version: "1.0.0",
  read_only: true,
  authority: "none",
  secret_free: true,
  principal_id: "operator-reader-1",
  state: "expiring_soon",
  license_status: "active",
  watermark_notice: "none",
  acting_available: true,
  proactive_warning: true,
  license_id: "lic-2026-11",
  expires_at: "2026-11-05T00:00:00Z",
  remaining_seconds: 345600,
  remaining_days: 4,
  observed_at: "2026-11-01T00:00:00Z",
  reason_code: "renewal_window_approaching",
} as const;

describe("licensing-status-badge.model", () => {
  it("decodes and formats proactive renewal warnings in English and Korean", () => {
    const decoded = decodeLicensingWarningProjection(BASE_PAYLOAD);
    expect(decoded.secret_free).toBe(true);
    expect(decoded.read_only).toBe(true);
    expect(decoded.authority).toBe("none");

    const enBadge = formatLicensingStatusBadge(decoded, "en");
    expect(enBadge.badgeLabel).toBe("Renewal required soon");
    expect(enBadge.tone).toBe("warning");
    expect(enBadge.showProactiveWarning).toBe(true);
    expect(enBadge.remainingDaysDisplay).toBe("4d remaining");
    expect(enBadge.warningTitle).toContain("expires soon");

    const koBadge = formatLicensingStatusBadge(decoded, "ko");
    expect(koBadge.badgeLabel).toBe("갱신 예정 경고");
    expect(koBadge.remainingDaysDisplay).toBe("4일 남음");
    expect(koBadge.warningTitle).toContain("만료 임박");
  });

  it("formats normal, expired, clock_regression, and read_only_trial states accurately", () => {
    const normal = formatLicensingStatusBadge(
      decodeLicensingWarningProjection({
        ...BASE_PAYLOAD,
        state: "normal",
        proactive_warning: false,
        remaining_days: 25,
        reason_code: "entitlement_active",
      }),
      "en",
    );
    expect(normal.tone).toBe("success");
    expect(normal.showProactiveWarning).toBe(false);
    expect(normal.warningTitle).toBeNull();

    const clockReg = formatLicensingStatusBadge(
      decodeLicensingWarningProjection({
        ...BASE_PAYLOAD,
        state: "clock_regression",
        license_status: "clock_regression",
        watermark_notice: "not-activated",
        acting_available: false,
        proactive_warning: true,
        remaining_days: 0,
        remaining_seconds: 0,
        reason_code: "clock_regression_detected",
      }),
      "ko",
    );
    expect(clockReg.tone).toBe("danger");
    expect(clockReg.actingAvailable).toBe(false);
    expect(clockReg.badgeLabel).toBe("시계 역행 차단됨");
    expect(clockReg.warningDetail).toContain("영구 차단");

    const missing = formatLicensingStatusBadge(null, "ko");
    expect(missing.state).toBe("read_only_trial");
    expect(missing.watermarkNotice).toBe("not-activated");
  });

  it("rejects any payload carrying raw token, signature, or private key material", () => {
    expect(() =>
      decodeLicensingWarningProjection({
        ...BASE_PAYLOAD,
        token: "eyJhbGciOiJFZERTQSJ9.c2lnbmF0dXJl",
      }),
    ).toThrow("MUST NOT expose secret field token");

    expect(() =>
      decodeLicensingWarningProjection({
        ...BASE_PAYLOAD,
        license_id: "-----BEGIN PRIVATE KEY-----",
      }),
    ).toThrow("secret-like material");
  });
});
